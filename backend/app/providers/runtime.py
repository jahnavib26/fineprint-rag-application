"""Per-request provider selection.

FinePrint runs in two modes, and one process serves both:

* **demo** — the server's own key, so a visitor can ask questions immediately
  with nothing to configure.
* **bring-your-own-key** — the caller picks a provider and model and supplies
  their own key, so their lease is processed under their account rather than
  the host's.

Everything downstream therefore takes an explicit ``Providers`` argument instead
of reaching for a module-level singleton. That is the whole point of this file:
with a process-wide cached client, one visitor's key would be constructed once
and then silently reused to serve the next visitor's request. Passing providers
explicitly makes that class of bug impossible to write rather than something the
next reader has to notice.

Keys live only inside the request that carried them. They are never written to
the database, never included in a trace row, never logged, and never echoed
back — see ``describe()``, which reports the provider and model but not the key.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import EMBEDDING_MODELS, LLM_MODELS, Settings, get_settings
from app.providers.embeddings import (
    Embedder,
    GeminiEmbedder,
    HashingEmbedder,
    OpenAIEmbedder,
    VoyageEmbedder,
)
from app.providers.llm import (
    AnthropicCompleter,
    GeminiCompleter,
    JSONCompleter,
    LLMUnavailable,
    OpenAICompleter,
)

LLM_BUILDERS = {
    "anthropic": AnthropicCompleter,
    "openai": OpenAICompleter,
    "gemini": GeminiCompleter,
}

EMBEDDING_BUILDERS = {
    "voyage": VoyageEmbedder,
    "openai": OpenAIEmbedder,
    "gemini": GeminiEmbedder,
}


class ProviderError(ValueError):
    """A provider/model/key combination the caller asked for isn't usable."""


@dataclass
class Providers:
    """The models one request will use. Built per request, never shared."""

    llm: JSONCompleter | None  # None → offline heuristics
    embedder: Embedder
    cheap_model: str
    smart_model: str
    source: str = "server"  # "server" (demo) | "byok"

    @property
    def llm_available(self) -> bool:
        return self.llm is not None

    def model_for(self, tier: str) -> str:
        return self.cheap_model if tier == "cheap" else self.smart_model

    def require_llm(self) -> JSONCompleter:
        if self.llm is None:
            raise LLMUnavailable("no LLM provider configured for this request")
        return self.llm

    def describe(self) -> dict:
        """Safe to put in a trace row or an API response — no key material."""
        return {
            "llm_provider": self.llm.name if self.llm else "offline",
            "smart": self.smart_model if self.llm else "",
            "cheap": self.cheap_model if self.llm else "",
            "embedding": self.embedder.name,
            "source": self.source,
        }


def build_providers(
    *,
    llm_provider: str | None = None,
    llm_key: str | None = None,
    cheap_model: str | None = None,
    smart_model: str | None = None,
    embedding_provider: str | None = None,
    embedding_key: str | None = None,
    embedding_model: str | None = None,
    source: str = "byok",
) -> Providers:
    """Construct the clients for one request.

    Clients are built fresh rather than cached by key. Caching them would keep
    a visitor's credential resident in the process long after their request
    finished, to save a client construction that costs almost nothing — the
    SDKs create their connection pools lazily.
    """
    llm: JSONCompleter | None = None
    if llm_provider and llm_provider != "offline":
        builder = LLM_BUILDERS.get(llm_provider)
        if builder is None:
            raise ProviderError(f"Unknown LLM provider '{llm_provider}'.")
        if not llm_key:
            raise ProviderError(f"An API key is required to use {llm_provider}.")
        try:
            llm = builder(llm_key)
        except ImportError as exc:  # SDK extra not installed on this deployment
            raise ProviderError(
                f"{llm_provider} isn't installed on this server ({exc})."
            ) from exc

    defaults = LLM_MODELS.get(llm_provider or "", {})
    resolved_cheap = cheap_model or defaults.get("cheap", "")
    resolved_smart = smart_model or defaults.get("smart", "")

    embedder: Embedder = HashingEmbedder()
    if embedding_provider and embedding_provider != "offline":
        embedding_builder = EMBEDDING_BUILDERS.get(embedding_provider)
        if embedding_builder is None:
            raise ProviderError(f"Unknown embedding provider '{embedding_provider}'.")
        if not embedding_key:
            raise ProviderError(
                f"An API key is required to use {embedding_provider} embeddings."
            )
        model = embedding_model or EMBEDDING_MODELS.get(embedding_provider, "")
        try:
            embedder = embedding_builder(embedding_key, model)
        except ImportError as exc:
            raise ProviderError(
                f"{embedding_provider} isn't installed on this server ({exc})."
            ) from exc

    return Providers(
        llm=llm,
        embedder=embedder,
        cheap_model=resolved_cheap,
        smart_model=resolved_smart,
        source=source,
    )


def server_providers(settings: Settings | None = None) -> Providers:
    """Demo mode: whatever the host configured, or offline if it configured nothing."""
    settings = settings or get_settings()
    llm_provider = settings.resolved_llm_provider()
    embedding_provider = settings.resolved_embedding_provider()
    return build_providers(
        llm_provider=llm_provider,
        llm_key=settings.api_key_for(llm_provider),
        cheap_model=settings.model_for("cheap"),
        smart_model=settings.model_for("smart"),
        embedding_provider=embedding_provider,
        embedding_key=settings.api_key_for(embedding_provider),
        embedding_model=settings.resolved_embedding_model(),
        source="server",
    )


def offline_providers() -> Providers:
    """No models at all — used by tests and by the offline eval baseline."""
    return build_providers(source="offline")
