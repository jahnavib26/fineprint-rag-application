"""ASGI app: the API, and — when a built frontend is present — the UI too.

Deployed, this is one container serving both from one origin. That removes the
whole class of CORS and API-base-URL configuration that a split deployment
needs, and means the frontend has nothing to configure per environment. In dev
the Vite server proxies `/api` here instead, so the same relative URLs work.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.providers.embeddings import get_embedder

# Populated by the Docker build; absent in local dev, where Vite serves the UI.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="FinePrint",
    description="Ask your lease the questions you never read it for.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_password(request: Request, call_next):
    """Gate everything behind HTTP Basic when APP_PASSWORD is set.

    A hosted instance holds people's leases — private legal documents — and
    has no accounts, so without this anyone with the URL can read and upload
    them. Basic auth is a blunt instrument, but it is the right size for a
    single-tenant demo and costs no UI. Unset, it's a no-op, so local
    development is unaffected.
    """
    settings = get_settings()
    if not settings.app_password or request.url.path == "/api/health":
        return await call_next(request)

    import base64
    import binascii

    header = request.headers.get("authorization", "")
    unauthorized = Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="FinePrint"'},
    )
    if not header.startswith("Basic "):
        return unauthorized
    try:
        decoded = base64.b64decode(header[6:]).decode()
        username, _, password = decoded.partition(":")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return unauthorized

    # compare_digest on both halves: a plain == leaks length and prefix
    # through timing, and the username is as guessable as the password here.
    ok_user = secrets.compare_digest(username, settings.app_username)
    ok_pass = secrets.compare_digest(password, settings.app_password)
    if not (ok_user and ok_pass):
        return unauthorized
    return await call_next(request)


@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    """Reject oversized uploads before anything reads them into memory."""
    settings = get_settings()
    if request.url.path == "/api/documents" and request.method == "POST":
        declared = request.headers.get("content-length")
        limit = settings.max_upload_mb * 1024 * 1024
        if declared and declared.isdigit() and int(declared) > limit:
            return JSONResponse(
                {"detail": f"That file is larger than {settings.max_upload_mb} MB."},
                status_code=413,
            )
    return await call_next(request)


app.include_router(router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    """Reports which providers are live, so a surprising answer can be traced
    to a misconfigured key rather than debugged as a retrieval problem.

    Deliberately exempt from the password gate: platform health checks can't
    authenticate, and it discloses no lease content.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "llm_provider": settings.resolved_llm_provider(),
        "embedding_provider": settings.resolved_embedding_provider(),
        "embedding_model": get_embedder().name,
        "models": {
            "smart": settings.model_for("smart"),
            "cheap": settings.model_for("cheap"),
        },
    }


if STATIC_DIR.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets"
    )

    @app.get("/{path:path}")
    async def spa(path: str) -> Response:
        """Serve the built UI, falling back to index.html.

        Registered after the API router, so /api/* still resolves to real
        endpoints and only genuinely unknown paths reach the SPA.
        """
        candidate = (STATIC_DIR / path).resolve()
        if (
            path
            and STATIC_DIR in candidate.parents  # refuse ../ escapes
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
