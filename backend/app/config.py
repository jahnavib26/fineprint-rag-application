"""Settings, read from the environment / a local .env.

Two independent provider axes:

* **LLM** — classification, synthesis, the grounding gate, amendment detection.
  Claude, GPT, or Gemini; each exposes the same "return JSON matching this
  schema" call, so the pipeline code never learns which one is configured.
* **Embeddings** — Voyage, OpenAI, or Gemini. Anthropic has no embeddings
  endpoint, which is why this is a separate choice rather than one vendor knob.

Every key is optional on purpose: with none set the system runs on deterministic
offline providers, so ingestion, retrieval, and the eval harness stay runnable —
and testable in CI — without spending money or sending a lease to a third party.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

LLMProvider = Literal["anthropic", "openai", "gemini", "offline"]
EmbeddingProvider = Literal["voyage", "openai", "gemini", "offline"]

# Per-provider model pairs. "cheap" runs at ingestion scale (one call per ~20
# clauses) and per claim in the grounding gate; "smart" writes the answer and
# reads addenda for override language.
LLM_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {"cheap": "claude-haiku-4-5", "smart": "claude-sonnet-5"},
    "openai": {"cheap": "gpt-4.1-mini", "smart": "gpt-4.1"},
    "gemini": {"cheap": "gemini-2.5-flash", "smart": "gemini-2.5-pro"},
}

EMBEDDING_MODELS: dict[str, str] = {
    "voyage": "voyage-3.5",
    "openai": "text-embedding-3-large",
    "gemini": "gemini-embedding-001",
}

# One fixed width keeps the pgvector column stable across providers. All three
# support requesting a specific output dimensionality, so switching providers
# needs a re-embed but never a migration.
EMBEDDING_DIMENSIONS = 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    voyage_api_key: str | None = None

    # Leave unset to auto-select from whichever keys are present.
    llm_provider: LLMProvider | None = None
    embedding_provider: EmbeddingProvider | None = None

    # Override the per-provider defaults above if you want to pin a model.
    cheap_model: str | None = None
    smart_model: str | None = None
    embedding_model: str | None = None

    database_url: str = "postgresql+asyncpg://fineprint:fineprint@localhost:5433/fineprint"

    # --- Hosting ---------------------------------------------------------
    # Set to gate the whole app behind HTTP Basic. Unset (the default) leaves
    # it open, which is fine on localhost and is not fine on a public URL:
    # a lease is a private legal document, and every upload here is readable
    # by anyone who can reach the origin.
    app_password: str | None = None
    app_username: str = "tenant"

    # Extra browser origins allowed to call the API. Only needed when the
    # frontend is deployed separately; the single-container deployment serves
    # both from one origin and needs none.
    cors_origins: str = ""

    # A lease is tens of KB of text. Anything vastly larger is a mistake or an
    # attempt to exhaust the dyno's memory during parsing.
    max_upload_mb: int = 25

    top_k: int = 8
    # Below this cosine similarity a clause isn't relevant at all; if nothing
    # clears it the answer is a refusal before a model is even asked. Leave
    # unset to use the configured embedder's own floor — the right threshold is
    # a property of the embedding space, not of the application.
    min_similarity: float | None = None

    def database_connect_args(self) -> tuple[str, dict]:
        """Normalise the URL a managed Postgres hands you into one asyncpg takes.

        Neon, Render, Supabase, and Heroku all emit ``postgres://…?sslmode=require``.
        SQLAlchemy needs an explicit ``+asyncpg`` driver, and asyncpg rejects
        ``sslmode`` outright — it spells the same thing ``ssl``. Left alone,
        both produce startup crashes that read like configuration typos.
        """
        url = self.database_url
        for prefix, replacement in (
            ("postgres://", "postgresql+asyncpg://"),
            ("postgresql://", "postgresql+asyncpg://"),
        ):
            if url.startswith(prefix):
                url = replacement + url[len(prefix) :]
                break

        connect_args: dict = {}
        if "sslmode=" in url:
            parsed = urlsplit(url)
            query = parse_qsl(parsed.query, keep_blank_values=True)
            remaining = [(k, v) for k, v in query if k != "sslmode"]
            sslmode = next((v for k, v in query if k == "sslmode"), "require")
            if sslmode != "disable":
                connect_args["ssl"] = sslmode
            url = urlunsplit(parsed._replace(query=urlencode(remaining)))

        return url, connect_args

    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        # Vite's dev server is a different origin from the API; in the deployed
        # single-container setup they share one and this is unused.
        return origins + ["http://localhost:5173", "http://127.0.0.1:5173"]

    def resolved_llm_provider(self) -> LLMProvider:
        if self.llm_provider:
            return self.llm_provider
        for provider, key in (
            ("anthropic", self.anthropic_api_key),
            ("openai", self.openai_api_key),
            ("gemini", self.gemini_api_key),
        ):
            if key:
                return provider  # type: ignore[return-value]
        return "offline"

    def resolved_embedding_provider(self) -> EmbeddingProvider:
        if self.embedding_provider:
            return self.embedding_provider
        for provider, key in (
            ("voyage", self.voyage_api_key),
            ("openai", self.openai_api_key),
            ("gemini", self.gemini_api_key),
        ):
            if key:
                return provider  # type: ignore[return-value]
        return "offline"

    def api_key_for(self, provider: str) -> str | None:
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "voyage": self.voyage_api_key,
        }.get(provider)

    def model_for(self, tier: str) -> str:
        provider = self.resolved_llm_provider()
        override = self.cheap_model if tier == "cheap" else self.smart_model
        if override:
            return override
        return LLM_MODELS.get(provider, {}).get(tier, "")

    def resolved_embedding_model(self) -> str:
        if self.embedding_model:
            return self.embedding_model
        return EMBEDDING_MODELS.get(self.resolved_embedding_provider(), "hashing-offline")


@lru_cache
def get_settings() -> Settings:
    return Settings()
