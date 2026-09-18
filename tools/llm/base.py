"""The ``ModelBackend`` protocol, its capability record, the port's one
construction-time failure, and the shared HTTP transport.

See ``docs/working/model-backends.md`` section 4.2. ``BaseHTTPBackend`` owns the
transport rules (S3/S4) so the OpenAI, Ollama, and Gemini adapters cannot each
get them subtly wrong. It imports ``httpx`` only inside a method, so
``import tools.llm`` still costs no HTTP stack.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, Sequence, runtime_checkable

from tools.llm.types import (
    Message,
    ModelResponse,
    ProtocolFault,
    StopReason,
    ToolCallBlock,
)

__all__ = [
    "SchemaDialect",
    "SCHEMA_DIALECTS",
    "Capabilities",
    "BackendUnavailableError",
    "OnText",
    "OnThinking",
    "ModelBackend",
    "BaseHTTPBackend",
    "truncation_fault",
]

#: Hosts to which an ``Authorization`` header may travel over plaintext HTTP.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

#: The three tool-schema dialects the port translates into. A backend declares
#: exactly one through :class:`Capabilities`.
SCHEMA_DIALECTS: tuple[str, ...] = (
    "json_schema",
    "openai_function",
    "gemini_openapi",
)
SchemaDialect = Literal["json_schema", "openai_function", "gemini_openapi"]

#: Called with assistant text as it becomes available. The Anthropic adapter
#: streams into it; every other adapter calls it once with the finished text.
OnText = Callable[[str], object]

#: Called with reasoning text as it becomes available, on the same terms. A
#: backend that declares no ``thinking`` capability never calls it; one that
#: reveals reasoning only when the turn is over calls it once at the end.
OnThinking = Callable[[str], object]


@dataclass(frozen=True)
class Capabilities:
    """What a backend can and cannot do, as this port uses it."""

    streaming: bool
    parallel_tool_calls: bool
    native_tool_call_ids: bool
    schema_dialect: SchemaDialect
    supports_union_types: bool
    max_output_tokens: int
    #: Whether this backend can reveal the model's reasoning. Declared
    #: ``False`` by a provider that hides it *and* by one this port has not
    #: taught to read it -- the flag describes the adapter, not the model.
    thinking: bool = False


class BackendUnavailableError(RuntimeError):
    """A backend could not be constructed: a missing credential, or an
    unreachable local daemon.

    It always names the environment variable at fault. It is never raised at
    import time, and never raised when a credential is passed explicitly.
    """

    def __init__(self, variable: str, hint: str | None = None) -> None:
        self.variable = variable
        self.hint = hint
        message = f"{variable} is not set or the backend it configures is unreachable"
        if hint:
            message = f"{message} ({hint})"
        super().__init__(message)


def truncation_fault(
    stop_reason: StopReason,
    tool_calls: Sequence[ToolCallBlock],
) -> ProtocolFault | None:
    """The ``truncated_output`` rule of section 4.6, implemented once and shared
    by every adapter rather than four times.

    A ``max_tokens`` stop that arrived with at least one tool call means the
    arguments may be incomplete and the trajectory is not trustworthy. A
    ``max_tokens`` stop with no tool calls is ordinary truncated prose and
    records nothing. The check is on the *normalized* stop reason, so every
    provider's own ceiling value (``length``, ``MAX_TOKENS``, ...) is covered.
    """

    if stop_reason == "max_tokens" and tool_calls:
        return ProtocolFault(
            type="truncated_output",
            detail=(
                f"stopped at the token ceiling with {len(tool_calls)} tool "
                "call(s) present; their arguments may be truncated"
            ),
        )
    return None


class BaseHTTPBackend:
    """Shared HTTP transport for the OpenAI, Ollama, and Gemini adapters.

    We own TLS correctness (section 2.2), so the transport rules are enforced
    here rather than trusted to each adapter: an explicit timeout always, no
    redirect following ever, certificate verification never disabled, and no
    ``Authorization`` header over plaintext HTTP except to loopback (S3). No
    credential is ever placed in a URL (S4).
    """

    #: Per-provider request timeout, in seconds. Subclasses may override.
    _timeout_s: float = 60.0

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        transport: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        #: Tests pass an ``httpx.MockTransport`` here; production never does.
        self._transport = transport

    def _client(self) -> Any:
        import httpx

        return httpx.Client(
            # S3: an explicit timeout, always -- never an unbounded request.
            timeout=httpx.Timeout(self._timeout_s),
            # S3: never follow redirects. This is also httpx's default; it is
            # set explicitly so a future reader cannot delete it as
            # "redundant" -- a redirect must never carry an auth header to
            # another host.
            follow_redirects=False,
            transport=self._transport,
            # `verify` stays at its secure default. Never verify=False. (S3)
        )

    def _auth_allowed_for(self, url: str) -> bool:
        """S3: an ``Authorization`` header may go over HTTPS to anywhere, or
        over plaintext HTTP only to loopback."""

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https":
            return True
        return (parsed.hostname or "").lower() in _LOOPBACK_HOSTS

    def _auth_headers(self) -> dict[str, str]:
        """The provider's auth header(s). Subclasses that authenticate override
        this; it is applied only when :meth:`_auth_allowed_for` says so."""

        return {}

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {"content-type": "application/json"}
        if self._api_key and self._auth_allowed_for(url):
            headers.update(self._auth_headers())
        with self._client() as client:
            response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()


@runtime_checkable
class ModelBackend(Protocol):
    """A provider adapter. ``complete()`` is the only required method, and it
    is non-streaming; streaming is a capability with a one-shot fallback."""

    spec: str
    capabilities: Capabilities

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
    ) -> ModelResponse: ...
