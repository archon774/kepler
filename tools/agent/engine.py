"""``run_session()`` -- Kepler's headless agent loop.

Events flow out as an iterator; a :class:`~tools.agent.approval.Decision` flows
in through the ``approver`` callable. Keeping the directions separate leaves the
event stream pure and directly consumable by the ``tools/runner.py`` shim, the
Kepler console, and the benchmark harness. See
``docs/working/model-backends.md`` section 4.7 and
``docs/working/tui-harness.md`` section 4.

Two behaviours from the pre-engine ``run()`` are load-bearing and preserved:

* the repeated-call cache keyed by ``make_cache_key`` -- a model was observed
  re-issuing an identical failing call across turns;
* saving the session after every tool call, so a killed run still leaves a
  readable manifest.

Streaming note: the Anthropic adapter streams text into ``on_text`` during
``complete()``, but a generator cannot yield from a callback, so the engine
buffers the chunks and emits the ``TextDelta`` events immediately after the
call returns -- before any tool-call event, which is the same order the old
loop printed them in.
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
from tools.llm.types import Message, ModelResponse, TextBlock, ToolResultBlock
from tools.llm.validation import index_schemas, validate_tool_call
from tools.sessions import AgentSession, make_cache_key

__all__ = ["run_session"]

_ToolFunctions = Mapping[str, Callable[..., Any]]


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
) -> Iterator[events.Event]:
    """Run a bounded agent loop and yield its events.

    The registry schemas are translated into the backend's declared dialect
    once, before the turn loop; every ``complete()`` call gets that payload.
    ``tool_schemas``/``tool_functions`` default to the live registry, read at
    call time.
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

    messages = list(history)
    messages.append(Message(role="user", blocks=(TextBlock(text=user_message),)))
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
                yield events.TurnStarted(turn=turn_number)

                streamed: list[str] = []
                response = backend.complete(
                    messages=messages,
                    tools=dialect_tools,
                    system=system,
                    max_tokens=max_tokens,
                    on_text=streamed.append,
                )
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
                    )
                    continue

                session.record_turn(
                    turn=turn_number,
                    stop_reason=response.raw_stop_reason or response.stop_reason,
                    assistant_text=response.text,
                    tool_call_sequences=[],
                )
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
) -> Iterator[events.Event]:
    assistant_blocks: list[Any] = []
    if response.text:
        assistant_blocks.append(TextBlock(text=response.text))
    assistant_blocks.extend(response.tool_calls)
    messages.append(Message(role="assistant", blocks=tuple(assistant_blocks)))

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
        denied = fault is None and approver(proposed) is Decision.DENY

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
        elif denied:
            reason = "not permitted by the approval policy"
            result = {
                "status": "error",
                "errors": [{"code": "denied", "message": reason}],
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
                result = functions[call.name](**arguments).model_dump()
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
        session.save(current_turn=turn_number)

        if not denied:
            yield events.ToolCallFinished(
                call_id=call.call_id,
                name=call.name,
                result=result,
                artifacts=_artifact_paths(result),
                duration_ms=duration_ms,
            )

        result_blocks.append(
            ToolResultBlock(
                call_id=call.call_id,
                name=call.name,
                content=json.dumps(result, default=str),
                is_error=result.get("status") == "error",
            )
        )

    session.record_turn(
        turn=turn_number,
        stop_reason=response.raw_stop_reason or response.stop_reason,
        assistant_text=response.text,
        tool_call_sequences=sequences,
    )
    session.save(current_turn=turn_number)
    yield events.TurnFinished(
        turn=turn_number,
        stop_reason=response.stop_reason,
        usage=response.usage,
        latency_ms=response.latency_ms,
    )
    messages.append(Message(role="user", blocks=tuple(result_blocks)))


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
