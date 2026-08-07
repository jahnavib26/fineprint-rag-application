"""Per-request provider construction.

The property under test is isolation: two requests carrying different keys must
never end up sharing a client. That was a real risk before this refactor —
``get_llm()`` memoized into a module global, so the first caller's key would
have been reused for everyone after them.
"""

from __future__ import annotations

import pytest

from app.providers.embeddings import HashingEmbedder
from app.providers.llm import LLMUnavailable
from app.providers.runtime import (
    ProviderError,
    build_providers,
    offline_providers,
)


def test_no_key_means_offline():
    providers = offline_providers()
    assert not providers.llm_available
    assert isinstance(providers.embedder, HashingEmbedder)
    with pytest.raises(LLMUnavailable):
        providers.require_llm()


def test_two_requests_get_independent_clients():
    """The regression this refactor exists to prevent."""
    pytest.importorskip("anthropic")
    a = build_providers(llm_provider="anthropic", llm_key="key-a")
    b = build_providers(llm_provider="anthropic", llm_key="key-b")
    assert a.llm is not b.llm
    assert a.llm._client is not b.llm._client


def test_provider_without_key_is_rejected():
    with pytest.raises(ProviderError, match="API key is required"):
        build_providers(llm_provider="anthropic", llm_key=None)


def test_unknown_provider_is_rejected():
    with pytest.raises(ProviderError, match="Unknown LLM provider"):
        build_providers(llm_provider="not-a-vendor", llm_key="x")


def test_describe_never_leaks_the_key():
    """describe() feeds trace rows and API responses, so it must be safe."""
    pytest.importorskip("anthropic")
    secret = "sk-ant-super-secret-value"
    providers = build_providers(
        llm_provider="anthropic",
        llm_key=secret,
        smart_model="claude-sonnet-5",
        cheap_model="claude-haiku-4-5",
    )
    described = repr(providers.describe())
    assert secret not in described
    assert "claude-sonnet-5" in described  # model names are useful and safe


def test_models_fall_back_to_provider_defaults():
    pytest.importorskip("openai")
    providers = build_providers(llm_provider="openai", llm_key="k")
    assert providers.model_for("smart")
    assert providers.model_for("cheap")
    assert providers.model_for("smart") != providers.model_for("cheap")


def test_caller_can_pin_a_model():
    pytest.importorskip("openai")
    providers = build_providers(
        llm_provider="openai", llm_key="k", smart_model="gpt-5-turbo-imaginary"
    )
    assert providers.model_for("smart") == "gpt-5-turbo-imaginary"


def test_llm_and_embeddings_are_independent_choices():
    """Anthropic has no embeddings endpoint, so this pairing must be legal."""
    pytest.importorskip("anthropic")
    pytest.importorskip("voyageai")
    providers = build_providers(
        llm_provider="anthropic",
        llm_key="a",
        embedding_provider="voyage",
        embedding_key="v",
    )
    assert providers.llm.name == "anthropic"
    assert providers.embedder.name.startswith("voyage")
