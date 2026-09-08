"""Kepler: optional agentic loop over the ``tools`` schemas.

This module is now a thin shim over ``tools.agent``: it builds a model
backend, runs :func:`tools.agent.engine.run_session`, and prints each event to
the console exactly as the loop did before the engine was extracted. Its path,
the ``run()`` signature, ``main()``, the ``kepler-astro-query`` console script,
and the module-level ``TOOL_SCHEMAS`` / ``TOOL_FUNCTIONS`` globals (read at call
time) are all preserved -- see ``docs/working/model-backends.md`` section 4.7.
``SYSTEM_PROMPT`` now lives in ``tools.agent.prompt`` and is re-exported here.

Per ``docs/tool-architecture.md`` section 5, serving/agent-loop code is
optional: every tool works from ordinary Python without this module.
"""

from __future__ import annotations

import json
import sys

from tools.agent import events
from tools.agent.engine import run_session
from tools.agent.prompt import SYSTEM_PROMPT
from tools.llm.base import BackendUnavailableError
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS
from tools.sessions import AgentSession

__all__ = ["run", "main", "SYSTEM_PROMPT"]


def run(
    user_message: str,
    *,
    max_turns: int = 20,
    model: str = "claude-sonnet-5",
    system: str = SYSTEM_PROMPT,
    backend: object | None = None,
) -> str | None:
    """Run a bounded agentic loop answering ``user_message``.

    Returns the session manifest path when a session runs. The CLI ignores the
    return value; tests and Python callers use it to inspect the saved
    tool-call trace. With no ``backend`` supplied it constructs the Anthropic
    backend and behaves exactly as before; when one is supplied the ``model``
    argument is informational -- the backend's own model wins -- but the
    session still records it.
    """

    if backend is None:
        from tools.llm.anthropic_backend import AnthropicBackend

        try:
            backend = AnthropicBackend(model=model)
        except BackendUnavailableError:
            print(
                "Set your ANTHROPIC_API_KEY environment variable to execute queries."
            )
            return None

    print(f"User: {user_message}\n" + "=" * 50)

    session = AgentSession(
        user_message=user_message,
        model=model,
        max_turns=max_turns,
        system=system,
    )

    current_turn = 0
    manifest_path: str | None = None
    try:
        for event in run_session(
            user_message,
            backend=backend,
            system=system,
            max_turns=max_turns,
            session=session,
            tool_schemas=TOOL_SCHEMAS,
            tool_functions=TOOL_FUNCTIONS,
        ):
            if isinstance(event, events.TurnStarted):
                current_turn = event.turn
            manifest_path = _print_event(event, current_turn) or manifest_path
    except Exception:
        # The broad handler that saved an error manifest (in the engine) and
        # re-raises; surface the path on stderr, as before.
        path = manifest_path or str(session.manifest_path)
        print(f"\n\n[Session Manifest] {path}", file=sys.stderr)
        raise

    return manifest_path


def _print_event(event: events.Event, current_turn: int) -> str | None:
    """Reproduce the pre-engine console output, event by event."""

    if isinstance(event, events.TextDelta):
        print(event.text, end="", flush=True)
        return None

    if isinstance(event, events.ToolCallStarted):
        print(
            f"\n\n[*] [Turn {current_turn}] Executing {event.name} "
            f"with {dict(event.arguments)}"
        )
        if event.cache_hit:
            print("(repeated call -- returning cached result)")
        return None

    if isinstance(event, events.ToolCallFinished):
        print("Tool Output JSON Preview:")
        print(json.dumps(event.result, indent=2, default=str)[:400] + "...\n")
        return None

    if isinstance(event, events.ToolCallDenied):
        print(
            f"\n\n[*] [Turn {current_turn}] {event.name} denied: {event.reason}"
        )
        return None

    if isinstance(event, events.SessionFinished):
        if event.outcome == "end_turn":
            print("\n\n[Task Complete]")
            print(f"[Session Manifest] {event.manifest_path}")
        elif event.outcome == "max_turns":
            print("\n\n[Max turns reached]")
            print(f"[Session Manifest] {event.manifest_path}")
        return event.manifest_path

    return None


def main() -> None:
    user_message = " ".join(sys.argv[1:])
    run(user_message)


if __name__ == "__main__":
    main()
