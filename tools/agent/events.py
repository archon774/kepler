"""The event union the agent loop emits.

Ten frozen dataclasses, defined here (``docs/working/tui-harness.md`` section
4.1 specifies the shape; this document owns the construction). Events are
ephemeral snapshots for the shim, the TUI, and the benchmark harness to read;
the durable record is the session manifest. ``arguments`` and ``result`` are
stored as plain dict copies so a consumer can serialise or ``repr`` them
without ceremony.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Union

from tools.llm.types import FaultType, Usage

__all__ = [
    "SessionStarted",
    "TurnStarted",
    "TextDelta",
    "ToolCallProposed",
    "ToolCallStarted",
    "ToolCallFinished",
    "ToolCallDenied",
    "ProtocolFault",
    "TurnFinished",
    "SessionFinished",
    "Event",
]


@dataclass(frozen=True)
class SessionStarted:
    session_id: str
    manifest_path: str
    backend_spec: str
    model: str


@dataclass(frozen=True)
class TurnStarted:
    turn: int


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallProposed:
    call_id: str
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", dict(self.arguments))


@dataclass(frozen=True)
class ToolCallStarted:
    call_id: str
    name: str
    arguments: Mapping[str, Any]
    cache_hit: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", dict(self.arguments))


@dataclass(frozen=True)
class ToolCallFinished:
    call_id: str
    name: str
    result: Mapping[str, Any]
    artifacts: tuple[str, ...] = ()
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", dict(self.result))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))


@dataclass(frozen=True)
class ToolCallDenied:
    call_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class ProtocolFault:
    turn: int
    type: FaultType
    detail: str


@dataclass(frozen=True)
class TurnFinished:
    turn: int
    stop_reason: str
    usage: Usage | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class SessionFinished:
    outcome: str
    manifest_path: str


Event = Union[
    SessionStarted,
    TurnStarted,
    TextDelta,
    ToolCallProposed,
    ToolCallStarted,
    ToolCallFinished,
    ToolCallDenied,
    ProtocolFault,
    TurnFinished,
    SessionFinished,
]
