"""LLM providers behind one method: "return JSON matching this schema".

Every model call in this system wants strict JSON back — a clause type, a list
of atomic claims, a per-claim verdict, a set of override edges. Nothing wants
prose. So the interface is a single ``complete_json``, and each provider uses
its own native structured-output mechanism to *constrain* the response rather
than asking for JSON in the prompt and hoping:

    Claude   output_config.format  → json_schema
    OpenAI   response_format       → json_schema (strict)
    Gemini   response_schema       → response_mime_type application/json

Callers ask for a tier ("cheap" or "smart"), never a model name, so switching
providers is one env var and never a prompt rewrite.
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class LLMUnavailable(RuntimeError):
    """No provider is configured — callers fall back to offline heuristics."""


class ProviderCallError(RuntimeError):
    """A configured provider was called and failed: bad key, quota, outage.

    Deliberately *not* a subclass of LLMUnavailable, because the two need
    opposite handling. "No provider configured" is a known state we degrade
    gracefully from. "Your key was rejected" must reach the user: silently
    falling back would hand them a weaker offline answer while they believe
    their key is working, which is the precise failure this project exists to
    avoid — a system that looks like it works.
    """

    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def _translate(provider: str, exc: Exception) -> ProviderCallError:
    """Turn an SDK exception into something a tenant can act on."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 401 or "api key" in str(exc).lower():
        return ProviderCallError(
            f"{provider} rejected the API key. Check it and try again.", status=401
        )
    if status == 429:
        return ProviderCallError(
            f"{provider} rate-limited or out of quota for this key.", status=429
        )
    return ProviderCallError(f"{provider} request failed: {exc}", status=502)


class JSONCompleter(Protocol):
    name: str

    async def complete_json(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]: ...


class AnthropicCompleter:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)

    async def complete_json(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        try:
                response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:
            raise _translate("Claude", exc) from exc
        # A refusal arrives as a successful response with an empty/partial body;
        # reading content[0] blindly would raise something unhelpful.
        if response.stop_reason == "refusal":
            raise LLMUnavailable("Claude declined this request")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


class OpenAICompleter:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)

    async def complete_json(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        try:
            response = await self._client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "fineprint", "schema": schema, "strict": True},
                },
            )
        except Exception as exc:
            raise _translate("OpenAI", exc) from exc
        message = response.choices[0].message
        if message.refusal:
            raise LLMUnavailable(f"OpenAI declined this request: {message.refusal}")
        return json.loads(message.content or "{}")


class GeminiCompleter:
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)

    async def complete_json(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system,
                    "response_mime_type": "application/json",
                    "response_schema": _gemini_schema(schema),
                    "max_output_tokens": max_tokens,
                },
            )
        except Exception as exc:
            raise _translate("Gemini", exc) from exc
        if not response.text:
            raise LLMUnavailable("Gemini returned no content")
        return json.loads(response.text)


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini takes an OpenAPI subset that rejects ``additionalProperties``.

    Strip it recursively and preserve key order via ``propertyOrdering``, which
    Gemini uses to keep generated fields in a stable sequence.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "properties" and isinstance(value, dict):
            out["properties"] = {k: _gemini_schema(v) for k, v in value.items()}
            out["propertyOrdering"] = list(value)
        elif isinstance(value, dict):
            out[key] = _gemini_schema(value)
        elif isinstance(value, list):
            out[key] = [_gemini_schema(v) for v in value]
        else:
            out[key] = value
    return out


def llm_provider_names() -> list[str]:
    return ["anthropic", "openai", "gemini"]


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """JSON Schema helper — strict modes require ``additionalProperties: false``."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
