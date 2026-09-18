"""Event rendering and worker handoff for the Textual transcript."""

from __future__ import annotations

import asyncio
import threading

from tools.agent.approval import Decision
from tools.agent.events import (
    TextDelta,
    ToolCallDenied,
    ToolCallFinished,
    ToolCallProposed,
    ToolCallStarted,
)
from tools.llm.types import ModelResponse
from tools.tui.app import ApprovalModal, KeplerApp
from tools.tui.widgets.transcript import Transcript
from textual.widgets import Static
from textual.worker import Worker

from tests.llm_fakes import StubBackend


def _run(coroutine):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        executor = loop._default_executor
        if executor is not None:
            executor.shutdown(wait=True)
        loop.close()


def test_transcript_aggregates_assistant_text_deltas():
    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test():
            transcript = app.query_one("#transcript", Transcript)
            transcript.handle_event(TextDelta(text="A"))
            transcript.handle_event(TextDelta(text="B"))

            assert transcript.assistant_text == "AB"

    _run(scenario())


def test_transcript_tracks_a_tool_call_through_finished_state():
    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript", Transcript)
            transcript.handle_event(
                ToolCallProposed("call-1", "search_simbad", {"name": "M31"})
            )
            transcript.handle_event(
                ToolCallStarted(
                    "call-1", "search_simbad", {"name": "M31"}, cache_hit=True
                )
            )
            transcript.handle_event(
                ToolCallFinished(
                    "call-1",
                    "search_simbad",
                    {"status": "ok"},
                    artifacts=("/tmp/m31.ecsv",),
                    duration_ms=12.0,
                )
            )
            await pilot.pause()

            node = transcript.tool_nodes["call-1"]
            assert node.state == "finished"
            assert node.cache_hit is True
            assert node.artifacts == ("/tmp/m31.ecsv",)
            assert node.duration_ms == 12.0

            await pilot.click(node)
            await pilot.pause()
            assert node.expanded is True

    _run(scenario())


def test_transcript_marks_a_denied_tool_call_distinctly():
    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript", Transcript)
            transcript.handle_event(ToolCallProposed("call-1", "search_ads", {}))
            transcript.handle_event(
                ToolCallDenied("call-1", "search_ads", "approval required")
            )
            await pilot.pause()

            node = transcript.tool_nodes["call-1"]
            assert node.state == "denied"
            assert node.reason == "approval required"

    _run(scenario())


def test_thread_worker_delivers_engine_events_to_the_transcript_and_status():
    async def scenario() -> None:
        backend = StubBackend([ModelResponse(stop_reason="end_turn", text="done")])
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            worker = app.run_prompt("summarize M31")
            assert isinstance(worker, Worker)
            async with asyncio.timeout(2):
                while not worker.is_finished:
                    await pilot.pause()
            await pilot.pause()

            transcript = app.query_one("#transcript", Transcript)
            assert transcript.assistant_text == "done"
            assert "1/20 turns" in str(app.query_one("#status").render())

    _run(scenario())


def test_allow_always_is_requested_again_for_a_new_prompt_session(monkeypatch):
    """A fresh prompt must not inherit a prior session's approval decision."""

    from tools.tui import app as tui_app

    asked: list[str] = []
    decisions: list[Decision] = []

    def approve_once_per_session(_app, proposed):
        asked.append(proposed.call_id)
        return Decision.ALLOW_ALWAYS

    def fake_run_session(text, *, approver, **_kwargs):
        decisions.append(
            approver(ToolCallProposed(text, "search_ads", {"query": "M31"}))
        )
        yield TextDelta(text=text)

    monkeypatch.setattr(KeplerApp, "_request_approval", approve_once_per_session)
    monkeypatch.setattr(tui_app, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            for prompt in ("first", "second"):
                worker = app.run_prompt(prompt)
                async with asyncio.timeout(2):
                    while not worker.is_finished:
                        await pilot.pause()

    _run(scenario())

    assert decisions == [Decision.ALLOW, Decision.ALLOW]
    assert asked == ["first", "second"]


def test_a_second_submission_is_queued_rather_than_starting_a_second_session(
    monkeypatch,
):
    """The prompt stays open mid-turn, and what is typed into it waits.

    A person watching a tool chain is the one best placed to correct it, so
    the input is never locked; but only one synchronous engine session may
    run at a time, so the second message is handed to the loop already
    running instead of starting a competing one.
    """

    from textual.widgets import Input
    from tools.tui import app as tui_app

    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    drained: list[tuple[str, ...]] = []

    def fake_run_session(text, **kwargs):
        calls.append(text)
        if text == "first":
            started.set()
            release.wait(timeout=2)
            drained.append(tuple(kwargs["pending_input"]()))
        yield TextDelta(text=text)

    monkeypatch.setattr(tui_app, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            try:
                prompt.value = "first"
                await pilot.press("enter")
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await pilot.pause()

                assert prompt.disabled is False
                prompt.value = "second"
                await pilot.press("enter")
                await pilot.pause()
                assert calls == ["first"]
            finally:
                release.set()

            worker = app._active_worker
            async with asyncio.timeout(2):
                while worker is not None and not worker.is_finished:
                    await pilot.pause()

    _run(scenario())

    assert drained == [("second",)]


def test_approval_request_opens_a_modal_and_releases_the_waiting_worker():
    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        proposed = ToolCallProposed("call-1", "search_ads", {})
        request = KeplerApp.ApprovalRequest(proposed)
        async with app.run_test() as pilot:
            app.post_message(request)
            await pilot.pause()
            assert isinstance(app.screen, ApprovalModal)

            await pilot.click("#allow")
            await pilot.pause()

            assert request.ready.is_set()
            assert request.decision is Decision.ALLOW

    _run(scenario())


def test_a_finished_tool_call_actually_paints_its_line():
    """Guards the transcript against a silently blank tool node.

    Every other test here reads the node's state, which stayed perfectly
    correct while `_render_content` shadowed Textual's private repaint hook
    and each call painted an empty row. What a person sees is the thing worth
    asserting: the name has to reach the screen.
    """

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript", Transcript)
            transcript.handle_event(
                ToolCallProposed("call-1", "search_simbad", {"name": "M31"})
            )
            transcript.handle_event(
                ToolCallFinished("call-1", "search_simbad", {"status": "ok"})
            )
            await pilot.pause()

            node = transcript.tool_nodes["call-1"]
            assert "search_simbad" in node.render_line(0).text

    _run(scenario())


def test_model_text_is_never_read_as_console_markup():
    """Textual parses content markup in a `Static` by default, so a plain
    string from the model could mint a clickable action link -- and would eat
    ordinary astronomy text on the way, since `[OIII]` is markup-shaped."""

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript", Transcript)
            transcript.handle_event(
                TextDelta(text="The [OIII] line, [@click=app.quit]click[/], done.")
            )
            transcript.append_notice("Denied [bold red]tool[/] call")
            await pilot.pause()

            painted = "\n".join(
                widget.render_line(0).text for widget in transcript.query(Static)
            )
            assert "[OIII]" in painted
            assert "[@click=app.quit]" in painted
            assert "[bold red]" in painted

    _run(scenario())
