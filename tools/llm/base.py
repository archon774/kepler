"""The ``ModelBackend`` protocol, its capability record, and the port's one
construction-time failure.

See ``docs/working/model-backends.md`` section 4.2. A shared HTTP base class is
deliberately *not* added here -- it arrives in Phase 2a when there are two HTTP
adapters to share it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol, Sequence, runtime_checkable

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
    "ModelBackend",
    "truncation_fault",
]

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


@dataclass(frozen=True)
class Capabilities:
    """What a backend can and cannot do, as this port uses it."""

    streaming: bool
    parallel_tool_calls: bool
    native_tool_call_ids: bool
    schema_dialect: SchemaDialect
    supports_union_types: bool
    max_output_tokens: int


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
    ) -> ModelResponse: ...
