from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.providers.embeddings import get_embedder

app = FastAPI(
    title="FinePrint",
    description="Ask your lease the questions you never read it for.",
    version="0.1.0",
)

# Dev only — the Vite frontend runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    """Reports which providers are live, so a surprising answer can be traced
    to a misconfigured key rather than debugged as a retrieval problem."""
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
