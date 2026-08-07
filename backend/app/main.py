"""ASGI app: the API, and — when a built frontend is present — the UI too.

Deployed, this is one container serving both from one origin. That removes the
whole class of CORS and API-base-URL configuration that a split deployment
needs, and means the frontend has nothing to configure per environment. In dev
the Vite server proxies `/api` here instead, so the same relative URLs work.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.providers.runtime import server_providers

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
    to a misconfigured key rather than debugged as a retrieval problem."""
    settings = get_settings()
    demo = server_providers(settings)
    return {
        "status": "ok",
        "llm_provider": settings.resolved_llm_provider(),
        "embedding_provider": settings.resolved_embedding_provider(),
        "embedding_model": demo.embedder.name,
        "demo_available": settings.resolved_llm_provider() != "offline",
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
