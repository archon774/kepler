"""Neutral message, content, response, and fault types for the model port.

Every adapter under ``tools.llm`` translates between one provider's wire
dialect and the types defined here. Nothing in this module does I/O or imports
a provider SDK -- that is a testable property and it is tested. See
``docs/working/model-backends.md`` sections 4.1 and 4.6.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

__all__ = [
    "TextBlock",
    "ToolCallBlock",
    "ToolResultBlock",
    "Block",
    "Role",
    "Message",
    "Usage",
    "StopReason",
    "STOP_REASONS",
    "FaultType",
    "FAULT_TYPES",
    "ProtocolFault",
    "ModelResponse",
]

#: The closed set of normalized stop reasons. ``raw_stop_reason`` on a
#: :class:`ModelResponse` keeps the provider's own string verbatim.
STOP_REASONS: tuple[str, ...] = (
    "end_turn",
    "tool_use",
    "max_tokens",
    "refusal",
    "other",
)
StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]

#: The seven protocol faults the protocol grader counts (section 4.6). A fault
#: is a recorded observation, not an exception, unless the loop cannot continue.
FAULT_TYPES: tuple[str, ...] = (
    "malformed_arguments_json",
    "schema_violation",
    "unknown_tool",
    "stringified_null",
    "call_id_mismatch",
    "empty_tool_call",
    "truncated_output",
)
FaultType = Literal[
    "malformed_arguments_json",
    "schema_violation",
    "unknown_tool",
    "stringified_null",
    "call_id_mismatch",
    "empty_tool_call",
    "truncated_output",
]

#: There is deliberately no ``"system"`` role: the system prompt is a separate
#: argument everywhere, because each provider carries it differently.
Role = Literal["user", "assistant"]
_ROLES: tuple[str, ...] = ("user", "assistant")


@dataclass(frozen=True)
class TextBlock:
    """A run of assistant or user text."""

    text: str


@dataclass(frozen=True)
class ToolCallBlock:
    """A model's request to call one tool.

    ``arguments`` is always a parsed mapping, never a JSON string; adapters
    that receive a string parse it (or record ``malformed_arguments_json``).
    """

    call_id: str
    name: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        # A plain dict on a frozen dataclass is silently mutable; store a
        # read-only view, the same reason collection fields are tuples.
        object.__setattr__(
            self, "arguments", MappingProxyType(dict(self.arguments))
        )


@dataclass(frozen=True)
class ToolResultBlock:
    """The result of running one tool, addressed back to its call."""

    call_id: str
    name: str
    content: str
    is_error: bool = False


Block = TextBlock | ToolCallBlock | ToolResultBlock


@dataclass(frozen=True)
class Message:
    """One turn of neutral conversation history."""

    role: Role
    blocks: tuple[Block, ...]

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise ValueError(
                f"Message.role must be one of {_ROLES}, not {self.role!r}. "
                "The system prompt is a separate argument, never a message."
            )
        object.__setattr__(self, "blocks", tuple(self.blocks))


@dataclass(frozen=True)
class Usage:
    """Token accounting for one model call.

    Every field is optional: an absent field is ``None``, never ``0`` -- a
    provider that does not report cache tokens is not a provider that reported
    zero of them.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class ProtocolFault:
    """A typed, recorded observation about how a model misused the protocol."""

    type: FaultType
    detail: str
    tool_name: str | None = None
    call_id: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    """One completed model turn, normalized across providers."""

    stop_reason: StopReason
    text: str = ""
    tool_calls: tuple[ToolCallBlock, ...] = ()
    usage: Usage | None = None
    latency_ms: float | None = None
    raw_stop_reason: str | None = None
    faults: tuple[ProtocolFault, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "faults", tuple(self.faults))
