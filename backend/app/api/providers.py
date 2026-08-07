"""Per-request provider selection from headers, plus the catalogue the UI shows.

Keys arrive in headers rather than the JSON body for one practical reason: the
upload endpoint is multipart, so a body field would have to be duplicated in two
encodings. Headers work identically for both.

A key is read here, used to build clients for this request, and dropped. It is
never written to the database, never put in a trace, never logged, and never
returned. The only thing that outlives the request is the provider and model
*name*, which is what makes a trace row diagnosable.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from app.config import EMBEDDING_MODELS, LLM_MODELS, get_settings
from app.providers.runtime import ProviderError, Providers, build_providers, server_providers

# Headers a caller may send. Absent → demo mode on the server's own key.
LLM_PROVIDER = "x-llm-provider"
LLM_KEY = "x-llm-key"
LLM_CHEAP_MODEL = "x-llm-cheap-model"
LLM_SMART_MODEL = "x-llm-smart-model"
EMBEDDING_PROVIDER = "x-embedding-provider"
EMBEDDING_KEY = "x-embedding-key"
EMBEDDING_MODEL = "x-embedding-model"


def provider_catalogue() -> dict:
    """What the UI offers. Model lists are defaults, not a closed set — the
    caller may send any model name their provider accepts."""
    settings = get_settings()
    return {
        "llm": [
            {
                "id": name,
                "label": label,
                "default_smart": models["smart"],
                "default_cheap": models["cheap"],
            }
            for name, models, label in (
                ("anthropic", LLM_MODELS["anthropic"], "Claude"),
                ("openai", LLM_MODELS["openai"], "OpenAI"),
                ("gemini", LLM_MODELS["gemini"], "Gemini"),
            )
        ],
        "embedding": [
            {"id": name, "label": label, "default_model": EMBEDDING_MODELS[name]}
            for name, label in (
                ("voyage", "Voyage"),
                ("openai", "OpenAI"),
                ("gemini", "Gemini"),
            )
        ],
        # Whether the visitor can try it without a key of their own.
        "demo_available": settings.resolved_llm_provider() != "offline",
        "demo_llm_provider": settings.resolved_llm_provider(),
        "demo_embedding_provider": settings.resolved_embedding_provider(),
    }


async def request_providers(
    request: Request,
    x_llm_provider: str | None = Header(default=None),
    x_llm_key: str | None = Header(default=None),
    x_llm_cheap_model: str | None = Header(default=None),
    x_llm_smart_model: str | None = Header(default=None),
    x_embedding_provider: str | None = Header(default=None),
    x_embedding_key: str | None = Header(default=None),
    x_embedding_model: str | None = Header(default=None),
) -> Providers:
    """Build this request's providers: the caller's keys, or the server's."""
    byok = bool(x_llm_key or x_embedding_key)
    if not byok:
        return server_providers()

    try:
        providers = build_providers(
            llm_provider=x_llm_provider,
            llm_key=x_llm_key,
            cheap_model=x_llm_cheap_model,
            smart_model=x_llm_smart_model,
            embedding_provider=x_embedding_provider,
            embedding_key=x_embedding_key,
            embedding_model=x_embedding_model,
            source="byok",
        )
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Mark the request so the rate limiter can leave it alone: the caller is
    # spending their own money, so there is nothing here for us to ration.
    request.state.byok = True
    return providers


ProvidersDep = Depends(request_providers)
