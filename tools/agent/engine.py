"""``run_session()`` -- Kepler's headless agent loop.

Events flow out as an iterator; a :class:`~tools.agent.approval.Decision` flows
in through the ``approver`` callable. Keeping the directions separate leaves the
event stream pure and directly consumable by the Kepler console, a plain
Python caller, and the benchmark harness alike. See
``docs/working/model-backends.md`` section 4.7 and
``docs/tool-architecture.md`` section 10.

Two behaviours from the pre-engine ``run()`` are load-bearing and preserved:

* the repeated-call cache keyed by ``make_cache_key`` -- a model was observed
  re-issuing an identical failing call across turns;
* saving the session after every tool call, so a killed run still leaves a
  readable manifest.

Streaming note: the Anthropic adapter streams text and reasoning into
``on_text``/``on_thinking`` during ``complete()``, but a generator cannot yield
from a callback. So by default the engine buffers the chunks and emits the
``TextDelta`` and ``ThinkingDelta`` events immediately after the call returns --
before any tool-call event, which is the same order the old loop printed them
in. A caller that wants them as they arrive passes ``on_delta``: the engine
then hands each delta straight to that callback and does not replay it, so the
events are delivered exactly once either way.

Three optional callables let an interactive caller stay in the loop while it
runs. ``on_delta`` is the live stream above; ``pending_input`` is drained at
the top of every turn and merged into the conversation, so a person can add
information to a run in progress; ``should_stop`` is checked at each turn and
before each tool call, so a person can end one. None of them is required and
the loop is unchanged without them.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

from tools import artifacts
from tools.agent import events
from tools.agent.approval import Approver, Decision, auto_approve
from tools.agent.prompt import SYSTEM_PROMPT
from tools.llm.base import ModelBackend
from tools.llm.schema import for_dialect
from tools.llm.types import (
    Message,
    ModelResponse,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from tools.llm.validation import index_schemas, validate_tool_call
from tools.sessions import AgentSession, backend_record, make_cache_key

__all__ = ["run_session"]

_ToolFunctions = Mapping[str, Callable[..., Any]]

#: Receives ``TextDelta`` and ``ThinkingDelta`` events as they stream, from
#: inside the backend call. It runs on whatever thread ``complete()`` runs on.
OnDelta = Callable[[events.Event], object]


def run_session(
    user_message: str,
    *,
    backend: ModelBackend,
    system: str = SYSTEM_PROMPT,
    max_turns: int = 20,
    approver: Approver = auto_approve,
    history: Sequence[Message] = (),
    session: AgentSession | None = None,
    tool_schemas: Sequence[dict[str, Any]] | None = None,
    tool_functions: _ToolFunctions | None = None,
    on_delta: OnDelta | None = None,
    pending_input: Callable[[], Sequence[str]] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[events.Event]:
    """Run a bounded agent loop and yield its events.

    The registry schemas are translated into the backend's declared dialect
    once, before the turn loop; every ``complete()`` call gets that payload.
    ``tool_schemas``/``tool_functions`` default to the live registry, read at
    call time.

    ``on_delta``, ``pending_input`` and ``should_stop`` are the interactive
    hooks described in the module docstring.
    """

    schemas, functions = _resolve_registry(tool_schemas, tool_functions)
    dialect_tools = for_dialect(backend.capabilities.schema_dialect, list(schemas))
    schema_index = index_schemas(schemas)
    if session is None:
        session = AgentSession(
            user_message=user_message,
            model=str(getattr(backend, "spec", "unknown")).split("/", 1)[-1],
            max_turns=max_turns,
            system=system,
        )
    session.backend = backend_record(backend)

    messages = list(history)
    messages.append(Message(role="user", blocks=(TextBlock(text=user_message),)))
    session.history = _recorded_history(messages)
    call_cache: dict[str, dict[str, Any]] = {}
    max_tokens = backend.capabilities.max_output_tokens

    try:
        with artifacts.scoped_artifacts(session.artifact_subdir):
            session.save()
            yield events.SessionStarted(
                session_id=session.session_id,
                manifest_path=str(session.manifest_path),
                backend_spec=str(getattr(backend, "spec", "")),
                model=session.model,
            )

            for turn in range(max_turns):
                turn_number = turn + 1
                if _stopped(should_stop):
                    manifest_path = session.save(
                        outcome="interrupted", current_turn=turn
                    )
                    yield events.SessionFinished(
                        outcome="interrupted", manifest_path=str(manifest_path)
                    )
                    return

                for note in _drain(pending_input):
                    _add_user_text(messages, note)
                    session.history = _recorded_history(messages)
                    yield events.UserMessage(text=note, turn=turn_number)

                yield events.TurnStarted(turn=turn_number)

                streamed: list[str] = []
                reasoned: list[str] = []
                response = backend.complete(
                    messages=messages,
                    tools=dialect_tools,
                    system=system,
                    max_tokens=max_tokens,
                    on_text=_collector(streamed, on_delta, events.TextDelta),
                    on_thinking=_collector(reasoned, on_delta, events.ThinkingDelta),
                )
                if on_delta is None:
                    # Reasoning before the answer: that is the order it was
                    # produced in, and the order a reader needs it in.
                    for chunk in reasoned:
                        yield events.ThinkingDelta(text=chunk)
                    for chunk in streamed:
                        yield events.TextDelta(text=chunk)
                for fault in response.faults:
                    session.record_fault(turn=turn_number, fault=fault)
                    yield events.ProtocolFault(
                        turn=turn_number, type=fault.type, detail=fault.detail
                    )

                if response.stop_reason == "tool_use":
                    yield from _run_tool_turn(
                        response=response,
                        turn_number=turn_number,
                        messages=messages,
                        call_cache=call_cache,
                        functions=functions,
                        approver=approver,
                        session=session,
                        schema_index=schema_index,
                        should_stop=should_stop,
                    )
                    continue

                session.record_turn(
                    turn=turn_number,
                    stop_reason=response.stop_reason,
                    raw_stop_reason=response.raw_stop_reason,
                    assistant_text=response.text,
                    tool_call_sequences=[],
                    usage=response.usage,
                    latency_ms=response.latency_ms,
                )
                messages.append(
                    Message(
                        role="assistant",
                        blocks=_assistant_blocks(response, with_tool_calls=False),
                    )
                )
                session.history = _recorded_history(messages)
                yield events.TurnFinished(
                    turn=turn_number,
                    stop_reason=response.stop_reason,
                    usage=response.usage,
                    latency_ms=response.latency_ms,
                )
                if response.stop_reason == "end_turn":
                    manifest_path = session.save(
                        outcome="end_turn", current_turn=turn_number
                    )
                    yield events.SessionFinished(
                        outcome="end_turn", manifest_path=str(manifest_path)
                    )
                    return
                session.save(current_turn=turn_number)

            manifest_path = session.save(outcome="max_turns", current_turn=max_turns)
            yield events.SessionFinished(
                outcome="max_turns", manifest_path=str(manifest_path)
            )
    except Exception as exc:
        # GeneratorExit (a consumer calling .close()) is a BaseException and is
        # not caught here: that is a clean shutdown, not an error outcome.
        manifest_path = session.save(outcome="error")
        yield events.SessionFinished(
            outcome="error", manifest_path=str(manifest_path)
        )
        raise exc


def _assistant_blocks(
    response: ModelResponse, *, with_tool_calls: bool
) -> tuple[Any, ...]:
    """The assistant turn as neutral blocks, reasoning first.

    Reasoning leads because that is where the provider requires it and where
    it happened. It is carried in the conversation, not only reported, because
    a provider that signed its reasoning refuses the next request of the same
    turn without it.
    """

    blocks: list[Any] = list(response.thinking)
    if response.text:
        blocks.append(TextBlock(text=response.text))
    if with_tool_calls:
        blocks.extend(response.tool_calls)
    return tuple(blocks)


def _collector(
    sink: list[str], on_delta: OnDelta | None, event_type: Callable[..., events.Event]
) -> Callable[[str], None]:
    """Build one streaming hook: buffer the chunk, and pass it on if asked."""

    def receive(chunk: str) -> None:
        if on_delta is None:
            sink.append(chunk)
            return
        on_delta(event_type(text=chunk))

    return receive


def _stopped(should_stop: Callable[[], bool] | None) -> bool:
    """Whether the caller has asked the loop to end.

    A hook that raises is treated as "keep going": a broken stop button must
    not be able to end a session, and the caller can always ask again.
    """

    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception:
        return False


def _drain(pending_input: Callable[[], Sequence[str]] | None) -> tuple[str, ...]:
    """Take whatever the caller has queued since the last turn."""

    if pending_input is None:
        return ()
    try:
        notes = pending_input()
    except Exception:
        return ()
    return tuple(note for note in notes if isinstance(note, str) and note.strip())


def _add_user_text(messages: list[Message], text: str) -> None:
    """Merge one mid-run note into the conversation.

    It joins the trailing user message when there is one -- which is the
    message carrying the tool results, so the note arrives with them, after
    them. Two consecutive user messages are not a shape every provider
    accepts, and a note is an addition to what the user last said rather than
    a turn of its own.
    """

    if messages and messages[-1].role == "user":
        last = messages[-1]
        messages[-1] = Message(
            role="user", blocks=(*last.blocks, TextBlock(text=text))
        )
        return
    messages.append(Message(role="user", blocks=(TextBlock(text=text),)))


def _recorded_history(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Serialize the complete neutral conversation for later TUI resume."""

    records: list[dict[str, Any]] = []
    for message in messages:
        blocks: list[dict[str, Any]] = []
        for block in message.blocks:
            if isinstance(block, TextBlock):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ThinkingBlock):
                blocks.append(
                    {
                        "type": "thinking",
                        "text": block.text,
                        "signature": block.signature,
                    }
                )
            elif isinstance(block, ToolCallBlock):
                blocks.append(
                    {
                        "type": "tool_call",
                        "call_id": block.call_id,
                        "name": block.name,
                        "arguments": json.loads(
                            json.dumps(dict(block.arguments), default=str)
                        ),
                    }
                )
            elif isinstance(block, ToolResultBlock):
                blocks.append(
                    {
                        "type": "tool_result",
                        "call_id": block.call_id,
                        "name": block.name,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                )
        records.append({"role": message.role, "blocks": blocks})
    return records


def _run_tool_turn(
    *,
    response: ModelResponse,
    turn_number: int,
    messages: list[Message],
    call_cache: dict[str, dict[str, Any]],
    functions: _ToolFunctions,
    approver: Approver,
    session: AgentSession,
    schema_index: Mapping[str, Mapping[str, Any]],
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[events.Event]:
    messages.append(
        Message(role="assistant", blocks=_assistant_blocks(response, with_tool_calls=True))
    )
    session.history = _recorded_history(messages)
    session.resumable = False
    session.save(current_turn=turn_number)

    result_blocks: list[ToolResultBlock] = []
    sequences: list[int] = []

    for call in response.tool_calls:
        arguments = dict(call.arguments)
        cache_key = make_cache_key(call.name, arguments)
        cache_hit = False
        duration_ms: float | None = None
        proposed = events.ToolCallProposed(
            call_id=call.call_id, name=call.name, arguments=arguments
        )
        yield proposed

        # S8: validate against the tool's own schema BEFORE dispatch. A fault
        # is recorded, an error result goes back to the model, and the loop
        # continues -- the tool function is never called, nothing raises. The
        # callable is passed too, so an empty-properties schema still faults on
        # junk arguments (via the signature) rather than raising at dispatch.
        fault = validate_tool_call(
            call.name,
            arguments,
            schema_index,
            call_id=call.call_id,
            func=functions.get(call.name),
        )
        stopped = fault is None and _stopped(should_stop)
        denied = fault is None and not stopped and approver(proposed) is Decision.DENY

        if fault is not None:
            session.record_fault(turn=turn_number, fault=fault)
            yield events.ProtocolFault(
                turn=turn_number, type=fault.type, detail=fault.detail
            )
            result: dict[str, Any] = {
                "status": "error",
                "errors": [{"code": fault.type, "message": fault.detail}],
            }
            cache_hit = cache_key in call_cache
            if not cache_hit:
                call_cache[cache_key] = result
        elif stopped or denied:
            # An interrupted call is refused the same way a denied one is, and
            # for the same reason: every ``tool_use`` needs a ``tool_result``
            # or the conversation cannot be sent again. Stopping mid-turn
            # leaves a usable record, not a broken one.
            reason = (
                "stopped by the user"
                if stopped
                else "not permitted by the approval policy"
            )
            result = {
                "status": "error",
                "errors": [
                    {"code": "interrupted" if stopped else "denied", "message": reason}
                ],
            }
            yield events.ToolCallDenied(
                call_id=call.call_id, name=call.name, reason=reason
            )
        else:
            cache_hit = cache_key in call_cache
            yield events.ToolCallStarted(
                call_id=call.call_id,
                name=call.name,
                arguments=arguments,
                cache_hit=cache_hit,
            )
            started = time.monotonic()
            if cache_hit:
                result = call_cache[cache_key]
            else:
                result = _normalize_result(
                    call.name, functions[call.name](**arguments)
                )
                call_cache[cache_key] = result
            duration_ms = (time.monotonic() - started) * 1000.0

        sequences.append(
            session.record_tool_call(
                turn=turn_number,
                tool_use_id=call.call_id,
                tool_name=call.name,
                arguments=arguments,
                cache_key=cache_key,
                cache_hit=cache_hit,
                result=result,
            )
        )
        result_blocks.append(
            ToolResultBlock(
                call_id=call.call_id,
                name=call.name,
                content=json.dumps(result, default=str),
                is_error=result.get("status") == "error",
            )
        )
        checkpoint = [
            *messages,
            Message(role="user", blocks=tuple(result_blocks)),
        ]
        session.history = _recorded_history(checkpoint)
        session.save(current_turn=turn_number)

        if not (denied or stopped):
            yield events.ToolCallFinished(
                call_id=call.call_id,
                name=call.name,
                result=result,
                artifacts=_artifact_paths(result),
                duration_ms=duration_ms,
            )

    messages.append(Message(role="user", blocks=tuple(result_blocks)))
    session.history = _recorded_history(messages)
    session.resumable = True
    session.record_turn(
        turn=turn_number,
        stop_reason=response.stop_reason,
        raw_stop_reason=response.raw_stop_reason,
        assistant_text=response.text,
        tool_call_sequences=sequences,
        usage=response.usage,
        latency_ms=response.latency_ms,
    )
    session.save(current_turn=turn_number)
    yield events.TurnFinished(
        turn=turn_number,
        stop_reason=response.stop_reason,
        usage=response.usage,
        latency_ms=response.latency_ms,
    )


def _normalize_result(name: str, value: Any) -> dict[str, Any]:
    """Serialize one tool's return value into the result dict the loop records.

    Almost every registered tool returns a single Kepler model. Three return a
    plain ``list`` of them -- ``list_photometric_catalogs``, ``list_artifacts``
    and ``list_zeropoint_references`` -- and a list has no ``model_dump()``, so
    dispatching any of the three raised ``AttributeError`` mid-turn and ended
    the session with outcome ``error``. A model asking what catalogs exist got
    a dead session and no way to tell why.

    A list is wrapped into the ``{status, count, results}`` shape the rest of
    the surface already uses, so the recorded call carries a status and a count
    like every other one and the model sees a result rather than a crash.
    Anything else is a registry defect and says so, rather than reaching
    ``json.dumps`` and being handed to the model as a stringified repr.
    """

    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if isinstance(value, (list, tuple)):
        items = [
            item.model_dump() if callable(getattr(item, "model_dump", None)) else item
            for item in value
        ]
        return {"status": "ok", "count": len(items), "results": items}
    raise TypeError(
        f"tool {name!r} returned {type(value).__name__}; a registered tool must "
        "return a Kepler model or a list of them"
    )


def _resolve_registry(
    tool_schemas: Sequence[dict[str, Any]] | None,
    tool_functions: _ToolFunctions | None,
) -> tuple[Sequence[dict[str, Any]], _ToolFunctions]:
    if tool_schemas is not None and tool_functions is not None:
        return tool_schemas, tool_functions
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    return (
        TOOL_SCHEMAS if tool_schemas is None else tool_schemas,
        TOOL_FUNCTIONS if tool_functions is None else tool_functions,
    )


def _artifact_paths(result: Mapping[str, Any]) -> tuple[str, ...]:
    paths: list[str] = []
    for value in (result.get("artifact"), *(result.get("artifacts") or ())):
        if isinstance(value, Mapping) and value.get("path"):
            paths.append(str(value["path"]))
        elif isinstance(value, str) and value:
            paths.append(value)
    return tuple(paths)
