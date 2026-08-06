"""Embedding providers behind one interface.

Per this project's own lesson — metadata filters on clause type moved retrieval
quality more than embedding-model choice did — this is deliberately a thin,
swappable seam: ``embed_documents`` / ``embed_query``, one implementation per
provider. Voyage, OpenAI, and Gemini all support requesting a specific output
dimensionality, so every provider emits the same width and switching needs a
re-embed but never a migration.

The offline provider is not a toy. Hashed bag-of-words with sublinear term
frequency is a serviceable lexical retriever, which means ingestion, search, and
the eval harness all run end-to-end with no API key — so a pipeline change can
be gated in CI without spending money.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from app.config import EMBEDDING_DIMENSIONS, get_settings

DIMENSIONS = EMBEDDING_DIMENSIONS


class Embedder(Protocol):
    name: str
    # Cosine similarity below which a clause isn't relevant at all. This is a
    # property of the embedding space, not of the application: dense models put
    # unrelated text around 0.2-0.4, while a sparse lexical vector scores near
    # zero unless words literally overlap. A single global floor would either
    # reject everything on one provider or nothing on the other.
    relevance_floor: float

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


DENSE_RELEVANCE_FLOOR = 0.35
LEXICAL_RELEVANCE_FLOOR = 0.05


class VoyageEmbedder:
    """Voyage AI. Distinct input types for documents vs queries."""

    def __init__(self, api_key: str, model: str) -> None:
        import voyageai

        self._client = voyageai.AsyncClient(api_key=api_key)
        self._model = model
        self.name = f"voyage:{model}"
        self.relevance_floor = DENSE_RELEVANCE_FLOOR

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for batch in _batched(texts, 96):  # Voyage caps documents per request
            result = await self._client.embed(
                batch, model=self._model, input_type="document", output_dimension=DIMENSIONS
            )
            out.extend(result.embeddings)
        return out

    async def embed_query(self, text: str) -> list[float]:
        result = await self._client.embed(
            [text], model=self._model, input_type="query", output_dimension=DIMENSIONS
        )
        return result.embeddings[0]


class OpenAIEmbedder:
    """OpenAI embeddings, truncated to DIMENSIONS via the `dimensions` param."""

    def __init__(self, api_key: str, model: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self.name = f"openai:{model}"
        self.relevance_floor = DENSE_RELEVANCE_FLOOR

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for batch in _batched(texts, 128):
            result = await self._client.embeddings.create(
                model=self._model, input=batch, dimensions=DIMENSIONS
            )
            out.extend(item.embedding for item in result.data)
        return out

    async def embed_query(self, text: str) -> list[float]:
        result = await self._client.embeddings.create(
            model=self._model, input=[text], dimensions=DIMENSIONS
        )
        return result.data[0].embedding


class GeminiEmbedder:
    """Gemini embeddings. Task type matters as much as it does for Voyage."""

    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self.name = f"gemini:{model}"
        self.relevance_floor = DENSE_RELEVANCE_FLOOR

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, "RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "RETRIEVAL_QUERY"))[0]

    async def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for batch in _batched(texts, 100):
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=batch,
                config={"task_type": task_type, "output_dimensionality": DIMENSIONS},
            )
            out.extend(e.values for e in result.embeddings)
        return out


class HashingEmbedder:
    """Deterministic offline embedder: hashed bag-of-words, L2-normalised.

    Lexical, not semantic — it will miss "can I have a cat" → "no animal shall
    be kept" unless the words overlap. That is exactly why the eval suite
    reports retrieval metrics separately: an offline run is a regression check
    on the pipeline's plumbing, not a measurement of retrieval quality.
    """

    name = "hashing-offline"
    relevance_floor = LEXICAL_RELEVANCE_FLOOR

    _TOKEN = re.compile(r"[a-z0-9]+")
    _STOPWORDS = frozenset(
        "the a an and or of to in for on at by with shall be is are as any such "
        "this that it not no from will may".split()
    )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        counts: dict[int, float] = {}
        for token in self._TOKEN.findall(text.lower()):
            if token in self._STOPWORDS or len(token) < 3:
                continue
            index = self._bucket(token)
            counts[index] = counts.get(index, 0.0) + 1.0

        vector = [0.0] * DIMENSIONS
        for index, count in counts.items():
            vector[index] = 1.0 + math.log(count)  # sublinear tf damps repetition

        norm = math.sqrt(sum(v * v for v in vector))
        if norm:
            vector = [v / norm for v in vector]
        return vector

    @staticmethod
    def _bucket(token: str) -> int:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big") % DIMENSIONS


def _batched(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is not None:
        return _embedder

    settings = get_settings()
    provider = settings.resolved_embedding_provider()
    key = settings.api_key_for(provider)
    model = settings.resolved_embedding_model()

    if provider == "offline" or not key:
        _embedder = HashingEmbedder()
    else:
        _embedder = {
            "voyage": VoyageEmbedder,
            "openai": OpenAIEmbedder,
            "gemini": GeminiEmbedder,
        }[provider](key, model)
    return _embedder
