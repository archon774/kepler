"""``ReplayBackend`` -- replays a recorded model transcript. Test-only.

``docs/working/benchmark.md`` section 5.4. The benchmark harness replays remote
*tools* against live models; this replays the *model* instead, so the harness
itself can be exercised end to end with both sides recorded. A run with a
replayed model and replayed tools is bit-deterministic, opens no socket, costs
nothing, and finishes in under a second, which is what lets the smoke suite run
inside a plain ``uv run pytest``.

It lives here rather than under ``tools/bench/`` because it is a
:class:`~tools.llm.base.ModelBackend` and nothing else, and because the port's
layout table already reserves this path. It is deliberately **not reachable
from** :func:`tools.llm.factory.build_backend`: ``replay`` is not a recognized
provider, and a transcript is a test asset, not a thing an operator points a
real run at.

Running past the end of a transcript raises :class:`TranscriptExhausted`,
loudly. A silent wrap-around would let a harness test pass against a loop that
never terminates -- the failure mode most worth catching here, since the whole
point of the smoke suite is to prove the loop reaches ``end_turn``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.llm.base import Capabilities, OnText
from tools.llm.types import (
    FAULT_TYPES,
    STOP_REASONS,
    Message,
    ModelResponse,
    ProtocolFault,
    ToolCallBlock,
    Usage,
)

__all__ = [
    "ReplayBackend",
    "TranscriptExhausted",
    "TranscriptError",
    "load_transcript",
    "REPLAY_CAPABILITIES",
]

#: Streaming is ``False``: a transcript holds finished turns, so ``on_text`` is
#: called once with the whole text, the way every non-Anthropic adapter does.
#: The dialect is ``json_schema`` because replay does not exercise translation
#: -- a run that wants to see a dialect's effect needs the real adapter.
REPLAY_CAPABILITIES = Capabilities(
    streaming=False,
    parallel_tool_calls=True,
    native_tool_call_ids=True,
    schema_dialect="json_schema",
    supports_union_types=True,
    max_output_tokens=4096,
)

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)


class TranscriptError(ValueError):
    """A transcript file is malformed. Raised at load, before any run."""


class TranscriptExhausted(RuntimeError):
    """The loop asked for a turn the transcript does not have.

    Always an error, never a wrap-around: a transcript that silently repeated
    its last turn would drive an agent loop forever, and a harness test that
    passed against it would be asserting nothing.
    """

    def __init__(self, name: str, length: int) -> None:
        self.name = name
        self.length = length
        super().__init__(
            f"transcript {name!r} has {length} turn(s) and the loop asked for "
            f"turn {length + 1}; it never reached a terminal stop reason"
        )


def load_transcript(path: str | Path) -> tuple[ModelResponse, ...]:
    """Read a transcript file into the responses it records.

    A transcript is a JSON list of ``ModelResponse`` payloads::

        [
          {
            "stop_reason": "tool_use",
            "text": "Let me see what scans are here.",
            "tool_calls": [
              {"call_id": "c1", "name": "list_pulsar_scans", "arguments": {}}
            ],
            "usage": {"input_tokens": 1200, "output_tokens": 24},
            "raw_stop_reason": "tool_use",
            "faults": []
          },
          {"stop_reason": "end_turn", "text": "Five scans are bundled."}
        ]

    ``json.load`` and nothing else -- there is no code path here that
    constructs a Python object from the file. Every field except
    ``stop_reason`` is optional; unknown keys are an error rather than
    ignored, so a typo in ``tool_calls`` fails at load instead of producing a
    turn that quietly calls nothing.
    """

    file = Path(path)
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"{file} is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise TranscriptError(
            f"{file} must hold a JSON list of model responses, got "
            f"{type(payload).__name__}"
        )
    return tuple(
        _to_response(entry, file, index) for index, entry in enumerate(payload)
    )


def _to_response(entry: Any, file: Path, index: int) -> ModelResponse:
    where = f"{file}[{index}]"
    if not isinstance(entry, Mapping):
        raise TranscriptError(f"{where} must be an object, got {type(entry).__name__}")

    unknown = set(entry) - {
        "stop_reason",
        "text",
        "tool_calls",
        "usage",
        "latency_ms",
        "raw_stop_reason",
        "faults",
    }
    if unknown:
        raise TranscriptError(f"{where} has unknown key(s) {sorted(unknown)}")

    stop_reason = entry.get("stop_reason")
    if stop_reason not in STOP_REASONS:
        raise TranscriptError(
            f"{where} stop_reason must be one of {list(STOP_REASONS)}, got "
            f"{stop_reason!r}"
        )

    return ModelResponse(
        stop_reason=stop_reason,
        text=str(entry.get("text") or ""),
        tool_calls=tuple(
            _to_tool_call(call, where, n)
            for n, call in enumerate(entry.get("tool_calls") or ())
        ),
        usage=_to_usage(entry.get("usage"), where),
        latency_ms=entry.get("latency_ms"),
        raw_stop_reason=entry.get("raw_stop_reason"),
        faults=tuple(
            _to_fault(fault, where, n)
            for n, fault in enumerate(entry.get("faults") or ())
        ),
    )


def _to_tool_call(call: Any, where: str, index: int) -> ToolCallBlock:
    if not isinstance(call, Mapping):
        raise TranscriptError(f"{where} tool_calls[{index}] must be an object")
    missing = {"call_id", "name"} - set(call)
    if missing:
        raise TranscriptError(
            f"{where} tool_calls[{index}] is missing {sorted(missing)}"
        )
    arguments = call.get("arguments", {})
    if not isinstance(arguments, Mapping):
        # The adapters parse a provider's JSON-string arguments and record a
        # `malformed_arguments_json` fault when they cannot. A transcript is
        # already-parsed, so a non-object here is an authoring mistake; a test
        # that wants that fault records it in `faults` explicitly.
        raise TranscriptError(
            f"{where} tool_calls[{index}] arguments must be an object; record a "
            "malformed_arguments_json fault instead to replay a parse failure"
        )
    return ToolCallBlock(
        call_id=str(call["call_id"]), name=str(call["name"]), arguments=dict(arguments)
    )


def _to_usage(usage: Any, where: str) -> Usage | None:
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        raise TranscriptError(f"{where} usage must be an object or absent")
    unknown = set(usage) - set(_USAGE_FIELDS)
    if unknown:
        raise TranscriptError(f"{where} usage has unknown key(s) {sorted(unknown)}")
    return Usage(**{name: usage.get(name) for name in _USAGE_FIELDS})


def _to_fault(fault: Any, where: str, index: int) -> ProtocolFault:
    if not isinstance(fault, Mapping):
        raise TranscriptError(f"{where} faults[{index}] must be an object")
    kind = fault.get("type")
    if kind not in FAULT_TYPES:
        raise TranscriptError(
            f"{where} faults[{index}] type must be one of {list(FAULT_TYPES)}, "
            f"got {kind!r}"
        )
    return ProtocolFault(
        type=kind,
        detail=str(fault.get("detail") or ""),
        tool_name=fault.get("tool_name"),
        call_id=fault.get("call_id"),
    )


class ReplayBackend:
    """A :class:`~tools.llm.base.ModelBackend` that replays recorded turns.

    ``spec`` is ``replay/<name>``, where the name is the transcript's stem when
    one was loaded from a file. Every ``complete()`` call consumes one recorded
    response, in order, and ignores its arguments -- a transcript is a fixed
    trajectory, not a function of the conversation. The calls are still
    recorded on :attr:`calls`, so a test can assert what the loop sent.
    """

    def __init__(
        self,
        responses: Iterable[ModelResponse],
        *,
        name: str = "transcript",
        capabilities: Capabilities | None = None,
    ) -> None:
        self._responses = tuple(responses)
        self._index = 0
        self.name = name
        self.spec = f"replay/{name}"
        self.capabilities = capabilities or REPLAY_CAPABILITIES
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_file(
        cls, path: str | Path, *, capabilities: Capabilities | None = None
    ) -> "ReplayBackend":
        """Build a backend from a transcript file, named after its stem."""

        file = Path(path)
        return cls(
            load_transcript(file), name=file.stem, capabilities=capabilities
        )

    def __len__(self) -> int:
        return len(self._responses)

    @property
    def remaining(self) -> int:
        """Recorded turns not yet consumed."""

        return len(self._responses) - self._index

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
        if self._index >= len(self._responses):
            raise TranscriptExhausted(self.name, len(self._responses))

        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        response = self._responses[self._index]
        self._index += 1
        if on_text is not None and response.text:
            on_text(response.text)
        return response
