"""The headless agent loop: ``tools.agent.engine.run_session``.

Phase 0c of docs/working/model-backends.md. The engine emits events; a
Decision flows back through the approver. These tests drive it with a
hand-written stub backend, no SDK and no network.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from tests.llm_fakes import StubBackend
from tools import artifacts, config
from tools.agent import events
from tools.agent.approval import Decision
from tools.agent.engine import run_session
from tools.agent.prompt import SYSTEM_PROMPT
from tools.llm.types import (
    Message,
    ModelResponse,
    ProtocolFault,
    TextBlock,
    ToolCallBlock,
)
from tools.models import ToolResult
from tools.sessions import AgentSession


@pytest.fixture(autouse=True)
def _artifact_root(monkeypatch, tmp_path):
    root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    return root


def _session() -> AgentSession:
    return AgentSession(
        user_message="hi", model="test-model", max_turns=5, system=SYSTEM_PROMPT
    )


def _tool_call(name="lookup", call_id="call_0", **arguments):
    return ToolCallBlock(call_id=call_id, name=name, arguments=arguments)


def _drain(backend, *, session=None, approver=None, **kwargs):
    session = session or _session()
    extra = {"approver": approver} if approver is not None else {}
    return list(
        run_session(
            "hi",
            backend=backend,
            session=session,
            tool_schemas=[{"name": "lookup", "input_schema": {"type": "object", "properties": {}}}],
            tool_functions=kwargs.get("tool_functions", {}),
            max_turns=kwargs.get("max_turns", 5),
            **extra,
        )
    ), session


def test_a_plain_answer_yields_start_turn_text_and_finish(monkeypatch):
    backend = StubBackend([ModelResponse(stop_reason="end_turn", text="M31 is Andromeda.")])
    stream, session = _drain(backend)
    kinds = [type(e).__name__ for e in stream]
    assert kinds == [
        "SessionStarted",
        "TurnStarted",
        "TextDelta",
        "TurnFinished",
        "SessionFinished",
    ]
    assert stream[0].backend_spec == "stub/model"
    assert stream[0].model == "test-model"
    assert stream[2].text == "M31 is Andromeda."
    assert stream[-1].outcome == "end_turn"
    assert session.outcome == "end_turn"


def test_the_system_prompt_defaults_to_the_moved_constant(monkeypatch):
    backend = StubBackend([ModelResponse(stop_reason="end_turn", text="done")])
    session = _session()
    list(run_session("hi", backend=backend, session=session, tool_functions={}))
    assert backend.calls[0]["system"] == SYSTEM_PROMPT


def test_history_precedes_the_follow_up_user_message():
    """A resumed prompt must retain recorded context in its first model request."""

    history = (
        Message(role="user", blocks=(TextBlock(text="Find M31."),)),
        Message(role="assistant", blocks=(TextBlock(text="M31 is Andromeda."),)),
    )
    backend = StubBackend([ModelResponse(stop_reason="end_turn", text="What next?")])

    list(
        run_session(
            "How far away is it?",
            backend=backend,
            session=_session(),
            history=history,
            tool_schemas=[],
            tool_functions={},
        )
    )

    messages = backend.calls[0]["messages"]
    assert [message.role for message in messages] == ["user", "assistant", "user"]
    assert [message.blocks for message in messages] == [
        (TextBlock(text="Find M31."),),
        (TextBlock(text="M31 is Andromeda."),),
        (TextBlock(text="How far away is it?"),),
    ]


def test_follow_up_session_manifest_records_prior_text_history():
    """A new follow-up manifest must preserve context needed for later resume."""

    history = (
        Message(role="user", blocks=(TextBlock(text="Find M31."),)),
        Message(role="assistant", blocks=(TextBlock(text="M31 is Andromeda."),)),
    )
    backend = StubBackend([ModelResponse(stop_reason="end_turn", text="2.5 million ly.")])

    stream = list(
        run_session(
            "How far away is it?",
            backend=backend,
            history=history,
            tool_schemas=[],
            tool_functions={},
        )
    )

    manifest_path = next(
        event.manifest_path for event in stream if isinstance(event, events.SessionFinished)
    )
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert manifest["history"] == [
        {"role": "user", "blocks": [{"type": "text", "text": "Find M31."}]},
        {
            "role": "assistant",
            "blocks": [{"type": "text", "text": "M31 is Andromeda."}],
        },
        {
            "role": "user",
            "blocks": [{"type": "text", "text": "How far away is it?"}],
        },
        {
            "role": "assistant",
            "blocks": [{"type": "text", "text": "2.5 million ly."}],
        },
    ]


def test_session_manifest_retains_tool_call_and_result_blocks_for_resume():
    """Durable history must preserve the exact neutral tool exchange."""

    def lookup(target):
        assert target == "M31"
        return ToolResult(status="ok", count=1)

    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(_tool_call(name="lookup", target="M31"),),
            ),
            ModelResponse(stop_reason="end_turn", text="M31 is Andromeda."),
        ]
    )
    stream = list(
        run_session(
            "Find M31.",
            backend=backend,
            tool_schemas=[
                {
                    "name": "lookup",
                    "input_schema": {
                        "type": "object",
                        "properties": {"target": {"type": "string"}},
                        "required": ["target"],
                    },
                }
            ],
            tool_functions={"lookup": lookup},
        )
    )

    manifest_path = next(
        event.manifest_path for event in stream if isinstance(event, events.SessionFinished)
    )
    history = json.loads(Path(manifest_path).read_text(encoding="utf-8"))["history"]
    assert history[1]["blocks"] == [
        {
            "type": "tool_call",
            "call_id": "call_0",
            "name": "lookup",
            "arguments": {"target": "M31"},
        }
    ]
    result = history[2]["blocks"][0]
    assert result["type"] == "tool_result"
    assert result["call_id"] == "call_0"
    assert result["name"] == "lookup"
    assert result["is_error"] is False
    assert json.loads(result["content"])["status"] == "ok"


def test_session_manifest_and_directory_are_owner_only():
    """Persisted prompts and tool payloads must not be world-readable."""

    session = _session()
    manifest_path = session.save()

    assert stat.S_IMODE(session.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600


def test_tool_checkpoint_is_non_resumable_before_approval_or_dispatch():
    """A stopped run cannot advertise a pending tool call as resumable."""

    session = _session()
    backend = StubBackend(
        [
            ModelResponse(stop_reason="tool_use", tool_calls=(_tool_call(),)),
            ModelResponse(stop_reason="end_turn", text="done"),
        ]
    )
    stream = run_session(
        "hi",
        backend=backend,
        session=session,
        tool_schemas=[{"name": "lookup", "input_schema": {"type": "object"}}],
        tool_functions={},
        approver=lambda _proposed: Decision.DENY,
    )

    assert isinstance(next(stream), events.SessionStarted)
    assert isinstance(next(stream), events.TurnStarted)
    assert isinstance(next(stream), events.ToolCallProposed)

    manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
    assert manifest["resumable"] is False
    assert manifest["history"][1]["blocks"][0]["type"] == "tool_call"
    list(stream)


def test_partial_tool_turn_checkpoint_retains_completed_tool_results():
    """A crashed later call must not erase earlier tool context from resume."""

    def first():
        return ToolResult(status="ok", count=1)

    def explode():
        raise RuntimeError("tool exploded")

    session = _session()
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(
                    _tool_call(name="first", call_id="call-1"),
                    _tool_call(name="explode", call_id="call-2"),
                ),
            )
        ]
    )

    with pytest.raises(RuntimeError, match="tool exploded"):
        list(
            run_session(
                "hi",
                backend=backend,
                session=session,
                tool_schemas=[
                    {"name": "first", "input_schema": {"type": "object"}},
                    {"name": "explode", "input_schema": {"type": "object"}},
                ],
                tool_functions={"first": first, "explode": explode},
            )
        )

    manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
    assert manifest["resumable"] is False
    history = manifest["history"]
    assert [block["name"] for block in history[1]["blocks"]] == [
        "first",
        "explode",
    ]
    result = history[2]["blocks"][0]
    assert result["type"] == "tool_result"
    assert result["call_id"] == "call-1"
    assert result["name"] == "first"
    assert result["is_error"] is False
    assert json.loads(result["content"])["status"] == "ok"


def test_max_tokens_comes_from_the_backend_capability(monkeypatch):
    backend = StubBackend(
        [ModelResponse(stop_reason="end_turn", text="done")], max_output_tokens=9999
    )
    _drain(backend)
    assert backend.calls[0]["max_tokens"] == 9999


def test_a_tool_call_is_proposed_started_and_finished(monkeypatch):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(kwargs)
        return ToolResult(status="ok", count=1)

    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                text="looking",
                tool_calls=(_tool_call(target="M31"),),
            ),
            ModelResponse(stop_reason="end_turn", text="Found it."),
        ]
    )
    stream, _ = _drain(backend, tool_functions={"lookup": lookup})
    kinds = [type(e).__name__ for e in stream]
    assert kinds == [
        "SessionStarted",
        "TurnStarted",
        "TextDelta",
        "ToolCallProposed",
        "ToolCallStarted",
        "ToolCallFinished",
        "TurnFinished",
        "TurnStarted",
        "TextDelta",
        "TurnFinished",
        "SessionFinished",
    ]
    assert calls == [{"target": "M31"}]
    started = next(e for e in stream if isinstance(e, events.ToolCallStarted))
    assert started.cache_hit is False
    assert started.arguments == {"target": "M31"}
    finished = next(e for e in stream if isinstance(e, events.ToolCallFinished))
    assert finished.result["status"] == "ok"


def test_an_identical_repeated_call_hits_the_cache_and_runs_the_tool_once(monkeypatch):
    calls: list[dict] = []

    def lookup(**kwargs):
        calls.append(kwargs)
        return ToolResult(status="ok", count=1)

    backend = StubBackend(
        [
            ModelResponse(stop_reason="tool_use", text="", tool_calls=(_tool_call(target="M31"),)),
            ModelResponse(
                stop_reason="tool_use", text="", tool_calls=(_tool_call(call_id="call_1", target="M31"),)
            ),
            ModelResponse(stop_reason="end_turn", text="done"),
        ]
    )
    stream, _ = _drain(backend, tool_functions={"lookup": lookup})
    starts = [e for e in stream if isinstance(e, events.ToolCallStarted)]
    assert [e.cache_hit for e in starts] == [False, True]
    assert calls == [{"target": "M31"}]


def test_max_turns_is_a_terminal_outcome(monkeypatch):
    backend = StubBackend(
        [ModelResponse(stop_reason="tool_use", tool_calls=(_tool_call(),)) for _ in range(10)]
    )

    def lookup(**kwargs):
        return ToolResult(status="ok")

    stream, session = _drain(
        backend, tool_functions={"lookup": lookup}, max_turns=3
    )
    assert stream[-1].outcome == "max_turns"
    assert session.outcome == "max_turns"
    assert sum(isinstance(e, events.TurnStarted) for e in stream) == 3


def test_an_error_tool_result_is_flagged_is_error_in_the_neutral_history(monkeypatch):
    def failing(**kwargs):
        return ToolResult(status="error")

    backend = StubBackend(
        [
            ModelResponse(stop_reason="tool_use", tool_calls=(_tool_call(),)),
            ModelResponse(stop_reason="end_turn", text="ok"),
        ]
    )
    session = _session()
    list(
        run_session(
            "hi",
            backend=backend,
            session=session,
            tool_schemas=[{"name": "lookup", "input_schema": {"type": "object", "properties": {}}}],
            tool_functions={"lookup": failing},
        )
    )
    # the assistant message is history[1]; the tool-result user message is [2]
    result_msg = backend.calls[1]["messages"][2]
    assert result_msg.role == "user"
    assert result_msg.blocks[0].is_error is True


def test_an_unknown_tool_is_caught_by_validation_not_dispatched(monkeypatch):
    backend = StubBackend(
        [
            ModelResponse(stop_reason="tool_use", tool_calls=(_tool_call(name="nonesuch"),)),
            ModelResponse(stop_reason="end_turn", text="ok"),
        ]
    )
    stream, session = _drain(backend, tool_functions={})
    fault = next(e for e in stream if isinstance(e, events.ProtocolFault))
    assert fault.type == "unknown_tool"
    finished = next(e for e in stream if isinstance(e, events.ToolCallFinished))
    assert finished.result["status"] == "error"
    assert finished.result["errors"][0]["code"] == "unknown_tool"
    assert not any(isinstance(e, events.ToolCallStarted) for e in stream)
    assert session.protocol_faults[0]["type"] == "unknown_tool"
    assert stream[-1].outcome == "end_turn"


def test_a_denied_call_never_reaches_the_tool_function(monkeypatch):
    invoked: list = []

    def lookup(**kwargs):
        invoked.append(kwargs)
        return ToolResult(status="ok")

    backend = StubBackend(
        [
            ModelResponse(stop_reason="tool_use", tool_calls=(_tool_call(target="M31"),)),
            ModelResponse(stop_reason="end_turn", text="ok"),
        ]
    )
    stream, _ = _drain(
        backend,
        tool_functions={"lookup": lookup},
        approver=lambda proposed: Decision.DENY,
    )
    assert invoked == []
    denied = next(e for e in stream if isinstance(e, events.ToolCallDenied))
    assert denied.name == "lookup"
    assert not any(isinstance(e, events.ToolCallStarted) for e in stream)
    assert not any(isinstance(e, events.ToolCallFinished) for e in stream)


def test_junk_args_to_a_no_arg_tool_are_a_fault_not_a_crash(monkeypatch):
    invoked: list = []

    def no_args():
        invoked.append(True)
        return ToolResult(status="ok")

    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(ToolCallBlock(call_id="c0", name="no_args", arguments={"junk": 1}),),
            ),
            ModelResponse(stop_reason="end_turn", text="ok"),
        ]
    )
    session = _session()
    stream = list(
        run_session(
            "hi",
            backend=backend,
            session=session,
            tool_schemas=[{"name": "no_args", "input_schema": {"type": "object", "properties": {}}}],
            tool_functions={"no_args": no_args},
        )
    )
    assert invoked == []
    fault = next(e for e in stream if isinstance(e, events.ProtocolFault))
    assert fault.type == "schema_violation"
    assert stream[-1].outcome == "end_turn"  # the run did not crash


def test_a_stringified_null_argument_is_a_fault_and_the_tool_is_not_dispatched(monkeypatch):
    invoked: list = []

    def vizier(**kwargs):
        invoked.append(kwargs)
        return ToolResult(status="ok")

    schema = {
        "name": "vizier",
        "input_schema": {
            "type": "object",
            "properties": {"max_catalogs": {"type": ["integer", "null"]}},
        },
    }
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(ToolCallBlock(call_id="c0", name="vizier", arguments={"max_catalogs": "None"}),),
            ),
            ModelResponse(stop_reason="end_turn", text="ok"),
        ]
    )
    session = _session()
    stream = list(
        run_session(
            "hi",
            backend=backend,
            session=session,
            tool_schemas=[schema],
            tool_functions={"vizier": vizier},
        )
    )
    assert invoked == []
    fault = next(e for e in stream if isinstance(e, events.ProtocolFault))
    assert fault.type == "stringified_null"
    assert session.protocol_faults[0]["type"] == "stringified_null"
    assert session.protocol_faults[0]["tool_name"] == "vizier"
    # the trace records the real arguments the model sent
    assert session.tool_calls[0]["arguments"] == {"max_catalogs": "None"}


def test_adapter_faults_are_recorded_to_the_manifest_too(monkeypatch):
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="end_turn",
                text="done",
                faults=(ProtocolFault(type="truncated_output", detail="ceiling"),),
            )
        ]
    )
    _, session = _drain(backend)
    assert [f["type"] for f in session.protocol_faults] == ["truncated_output"]
    assert session.protocol_faults[0]["turn"] == 1


def test_a_backend_reported_fault_becomes_a_turn_stamped_fault_event(monkeypatch):
    backend = StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(_tool_call(),),
                faults=(ProtocolFault(type="truncated_output", detail="ceiling hit"),),
            ),
            ModelResponse(stop_reason="end_turn", text="ok"),
        ]
    )

    def lookup(**kwargs):
        return ToolResult(status="ok")

    stream, _ = _drain(backend, tool_functions={"lookup": lookup})
    fault = next(e for e in stream if isinstance(e, events.ProtocolFault))
    assert fault.turn == 1
    assert fault.type == "truncated_output"
    assert fault.detail == "ceiling hit"


def test_a_tool_that_raises_saves_an_error_manifest_and_re_raises(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("tool exploded")

    backend = StubBackend(
        [ModelResponse(stop_reason="tool_use", tool_calls=(_tool_call(name="boom"),))]
    )
    session = _session()
    produced: list = []
    with pytest.raises(RuntimeError, match="tool exploded"):
        for event in run_session(
            "hi",
            backend=backend,
            session=session,
            tool_functions={"boom": boom},
            tool_schemas=[
                {"name": "boom", "input_schema": {"type": "object", "properties": {}}}
            ],
        ):
            produced.append(event)
    assert session.outcome == "error"
    assert isinstance(produced[-1], events.SessionFinished)
    assert produced[-1].outcome == "error"


def test_the_artifact_scope_is_reset_after_the_run(monkeypatch):
    backend = StubBackend([ModelResponse(stop_reason="end_turn", text="done")])
    _drain(backend)
    assert artifacts.current_artifact_subdir() is None


def test_events_are_frozen(monkeypatch):
    import dataclasses

    started = events.TurnStarted(turn=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        started.turn = 2


def test_the_engine_imports_no_ui_toolkit():
    import ast
    from pathlib import Path

    pkg = Path(events.__file__).resolve().parent
    for module in pkg.glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        assert names.isdisjoint({"textual", "rich"}), f"{module.name} imports a UI toolkit"
