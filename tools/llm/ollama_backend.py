"""``OllamaBackend`` -- a thin ``OpenAIBackend`` subclass for a local Ollama
daemon.

Ollama serves an OpenAI-compatible endpoint, so this overrides only what
differs (section 4.5): the loopback default base URL, the absence of any auth
header, its ``spec`` and output ceiling, and an ``is_available()`` probe. The
probe hits Ollama's *native* tags path, not the compatibility prefix.

Phase 2b measured the compatibility layer against ``qwen3.8:27b-mlx`` and
found it faithful -- the integer-or-null union reaches the model, tool
arguments arrive as a JSON string, and parallel calls return in one message --
so the native chat endpoint fallback was not taken. See
``docs/working/model-backends.md`` section 11 question 2.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from tools.llm.base import BackendUnavailableError, BaseHTTPBackend, OnText
from tools.llm.openai_backend import OpenAIBackend, _CAPABILITIES
from tools.llm.types import Message, ModelResponse

__all__ = ["OllamaBackend", "OLLAMA_DEFAULT_BASE_URL", "OLLAMA_MAX_OUTPUT_TOKENS"]

OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MAX_OUTPUT_TOKENS = 8192

_OLLAMA_CAPABILITIES = dataclasses.replace(
    _CAPABILITIES, streaming=False, max_output_tokens=OLLAMA_MAX_OUTPUT_TOKENS
)


class OllamaBackend(OpenAIBackend):
    """Adapter over a local Ollama daemon's ``/v1/chat/completions``."""

    _DEFAULT_BASE_URL = OLLAMA_DEFAULT_BASE_URL

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        transport: Any = None,
    ) -> None:
        resolved_base = (base_url or self._DEFAULT_BASE_URL).rstrip("/")
        # Skip OpenAIBackend.__init__: there is no key and a missing one must
        # never raise. Ollama authenticates with nothing.
        BaseHTTPBackend.__init__(
            self, base_url=resolved_base, api_key=None, transport=transport
        )
        self._model = model
        self.spec = f"ollama/{model}"
        self.capabilities = _OLLAMA_CAPABILITIES

    def _provider(self) -> str:
        return "ollama"

    def _auth_headers(self) -> dict[str, str]:
        # No Authorization header, ever -- even if OPENAI_API_KEY is set in the
        # environment. (BaseHTTPBackend already skips auth when _api_key is
        # falsy; this makes the intent explicit and subclass-proof.)
        return {}

    def _native_tags_url(self) -> str:
        root = (
            self._base_url[:-3]
            if self._base_url.endswith("/v1")
            else self._base_url
        )
        return f"{root}/api/tags"

    def is_available(self) -> bool:
        """True when the daemon answers its native tags endpoint. A caller can
        probe this before a run and offer another backend on failure, rather
        than hitting a mid-turn connection error."""

        import httpx

        try:
            with self._client() as client:
                return client.get(self._native_tags_url()).status_code == 200
        except httpx.HTTPError:
            return False

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: object,
        system: str,
        max_tokens: int,
        temperature: float = 0.0,
        on_text: OnText | None = None,
    ) -> ModelResponse:
        import httpx

        try:
            return super().complete(
                messages=messages,
                tools=tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                on_text=on_text,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise BackendUnavailableError(
                "OLLAMA_BASE_URL",
                "start the daemon with `ollama serve` and pull the model",
            ) from exc
