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
``docs/archive/model-backends.md`` section 11 question 2.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Sequence

from tools.llm.base import (
    BackendUnavailableError,
    BaseHTTPBackend,
    OnText,
    OnThinking,
)
from tools.llm.openai_backend import OpenAIBackend, _CAPABILITIES
from tools.llm.types import Message, ModelResponse

__all__ = [
    "OllamaBackend",
    "OLLAMA_DEFAULT_BASE_URL",
    "OLLAMA_MAX_OUTPUT_TOKENS",
    "OLLAMA_DEFAULT_TIMEOUT_S",
    "OLLAMA_PROBE_TIMEOUT_S",
    "OLLAMA_TIMEOUT_ENV",
]

OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MAX_OUTPUT_TOKENS = 8192

#: Per-request timeout, in seconds. ``BaseHTTPBackend``'s 60 s is a sensible
#: default for a hosted API and badly wrong for a local daemon: a turn here is
#: bounded by the host's own hardware, not by a provider's SLA. Measured on the
#: development host, ``qwen3.8:27b-mlx`` takes **~189 s** for one turn of
#: Kepler's real tool surface -- 15,460 prompt tokens, because the 55 registry
#: schemas serialize to a 61 KB payload that is resent every turn -- and that is
#: with the model already resident. A cold load adds ~30 s more.
#:
#: So the default is raised rather than the caller being expected to discover
#: a ``ReadTimeout`` that looks like a daemon fault. It stays an *explicit*
#: timeout (S3: never an unbounded request); ``OLLAMA_TIMEOUT_S`` moves it for
#: a slower host or a larger model.
OLLAMA_DEFAULT_TIMEOUT_S = 600.0
OLLAMA_TIMEOUT_ENV = "OLLAMA_TIMEOUT_S"

#: How long the *questions about the daemon* may take -- is it up, what does
#: it hold. Nothing like the generation timeout above and deliberately so: a
#: daemon answers ``/api/tags`` at once or it is not answering, and these are
#: asked from a console that has a person waiting at it. Inheriting 600 s would
#: mean one Tab against a host that accepts connections and then says nothing
#: freezes the interface for ten minutes.
OLLAMA_PROBE_TIMEOUT_S = 5.0

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
        timeout_s: float | None = None,
    ) -> None:
        resolved_base = (base_url or self._DEFAULT_BASE_URL).rstrip("/")
        self._timeout_s = _resolve_timeout(timeout_s)
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
        than hitting a mid-turn connection error.

        This says the *daemon* is up, and nothing about whether it holds this
        backend's model -- see :meth:`installed_models`.
        """

        import httpx

        try:
            with self._client(timeout_s=OLLAMA_PROBE_TIMEOUT_S) as client:
                return client.get(self._native_tags_url()).status_code == 200
        except httpx.HTTPError:
            return False

    def installed_models(self) -> tuple[str, ...]:
        """The model names the daemon reports, or ``()`` if it cannot be asked.

        A daemon that is running is not a daemon that has your model: Ollama
        answers an unknown one with a 404 from ``/v1/chat/completions``, which
        arrives *mid-turn*, on the user's first question, as an
        ``httpx.HTTPStatusError``. An empty tuple means "could not ask" and is
        deliberately not the same as "has nothing" -- a caller must not turn a
        failed listing into a refusal to run.
        """

        import httpx

        try:
            with self._client(timeout_s=OLLAMA_PROBE_TIMEOUT_S) as client:
                response = client.get(self._native_tags_url())
            if response.status_code != 200:
                return ()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return ()

        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return ()
        return tuple(
            entry["name"]
            for entry in models
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        )

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: object,
        system: str,
        max_tokens: int,
        temperature: float = 0.0,
        on_text: OnText | None = None,
        on_thinking: OnThinking | None = None,
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
                on_thinking=on_thinking,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise BackendUnavailableError(
                "OLLAMA_BASE_URL",
                "start the daemon with `ollama serve` and pull the model",
            ) from exc
        except httpx.ReadTimeout as exc:
            # A read timeout is a different fault from an unreachable daemon:
            # the daemon answered the connection and is still thinking. Naming
            # the variable that bounds it is the whole contract of this error,
            # and it is the difference between "your daemon is down" and "your
            # host needs longer for this model".
            raise BackendUnavailableError(
                OLLAMA_TIMEOUT_ENV,
                f"the daemon accepted the request but did not answer within "
                f"{self._timeout_s:g}s; a larger model or a slower host needs "
                f"a higher {OLLAMA_TIMEOUT_ENV}",
            ) from exc


def _resolve_timeout(explicit: float | None) -> float:
    """An explicit argument beats ``OLLAMA_TIMEOUT_S``, which beats the
    default -- the same resolution order the factory uses for credentials.

    A non-numeric or non-positive environment value is ignored rather than
    raising: a malformed timeout should not make an otherwise-working daemon
    unreachable, and the default it falls back to is a safe one.
    """

    if explicit is not None and explicit > 0:
        return float(explicit)
    raw = os.environ.get(OLLAMA_TIMEOUT_ENV)
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return OLLAMA_DEFAULT_TIMEOUT_S
        if value > 0:
            return value
    return OLLAMA_DEFAULT_TIMEOUT_S
