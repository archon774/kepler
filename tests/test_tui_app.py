"""The Textual application shell, driven through Textual's headless pilot."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from textual.widgets import Input, OptionList, Static

from tests.llm_fakes import StubBackend
from tools import artifacts, config
from tools.agent.approval import Decision
from tools.agent.events import (
    SessionFinished,
    SessionStarted,
    TextDelta,
    ThinkingDelta,
    ToolCallProposed,
)
from tools.agent.events import UserMessage as UserMessageEvent
from tools.llm.base import BackendUnavailableError
from tools.llm.types import ModelResponse, ToolCallBlock, ToolResultBlock
from tools.tui import __main__ as tui_main
from tools.tui.app import ApprovalModal, KeplerApp
from tools.tui.render.capability import GraphicsTier
from tools.tui.commands import Suggestion
from tools.tui.widgets.header import WORDMARK, KeplerHeader
from tools.tui.widgets.models import ModelBrowser
from tools.tui.widgets.prompt import CommandMenu
from tools.tui.widgets.transcript import ThoughtBlock, Transcript, UserEntry


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


def test_shell_exposes_a_transcript_prompt_and_status_bar():
    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test():
            assert app.query_one("#transcript")
            assert app.query_one("#prompt")
            assert app.query_one("#status")

    _run(scenario())


def test_shell_identifies_the_selected_backend_in_its_title_frame():
    async def scenario() -> None:
        app = KeplerApp(backend=SimpleNamespace(spec="stub/model"))
        async with app.run_test():
            assert app.title == "Kepler"
            assert app.sub_title == "stub/model"

    _run(scenario())


def test_engine_events_append_assistant_text_to_the_transcript():
    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            app.post_message(KeplerApp.EngineEvent(TextDelta(text="hello")))
            await pilot.pause()
            transcript = app.query_one("#transcript", Transcript)
            assert transcript.assistant_text == "hello"

    _run(scenario())


def test_unknown_slash_command_renders_an_error_without_starting_the_engine():
    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            await pilot.press("/", "n", "o", "p", "e", "enter")
            await pilot.pause()
            transcript = app.query_one("#transcript", Transcript)
            assert any(
                "Unknown command: /nope" in str(entry.render())
                for entry in transcript.query(Static)
            )
            assert app.engine_starts == 0

    _run(scenario())


def test_help_command_renders_the_generated_command_list():
    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            await pilot.press("/", "?", "enter")
            await pilot.pause()
            transcript = app.query_one("#transcript", Transcript)
            rendered = "\n".join(
                str(entry.render()) for entry in transcript.query(Static)
            )
            assert "/help" in rendered
            assert "/quit" in rendered
            assert app.engine_starts == 0

    _run(scenario())


def test_artifacts_command_opens_the_browser_without_starting_the_engine():
    async def scenario() -> None:
        from tools.tui.widgets.artifacts import ArtifactBrowser

        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        async with app.run_test() as pilot:
            await pilot.press("/", "a", "enter")
            await pilot.pause()

            assert isinstance(app.screen, ArtifactBrowser)
            assert app.engine_starts == 0

    _run(scenario())


def test_f3_opens_the_artifact_browser_without_starting_the_engine():
    async def scenario() -> None:
        from tools.tui.widgets.artifacts import ArtifactBrowser

        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        async with app.run_test() as pilot:
            await pilot.press("f3")
            await pilot.pause()

            assert isinstance(app.screen, ArtifactBrowser)
            assert app.engine_starts == 0

    _run(scenario())


def test_sessions_command_opens_the_browser_without_starting_the_engine():
    """Session browsing is UI-only and must not become a model prompt."""

    from tools.tui.widgets.sessions import SessionBrowser

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            await pilot.press("/", "s", "enter")
            await pilot.pause()

            assert isinstance(app.screen, SessionBrowser)
            assert app.engine_starts == 0

    _run(scenario())


def test_f4_opens_the_session_browser_without_starting_the_engine():
    """The advertised session keybinding must use the same UI-only route."""

    from tools.tui.widgets.sessions import SessionBrowser

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            await pilot.press("f4")
            await pilot.pause()

            assert isinstance(app.screen, SessionBrowser)
            assert app.engine_starts == 0

    _run(scenario())


def test_resume_session_restores_assistant_text_without_starting_the_engine(
    monkeypatch, tmp_path
):
    """Loading a trace prepares its context; only a later prompt may run it."""

    from tools.tui import app as tui_app

    path = tmp_path / "session_manifest.json"
    manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "user_message": "Find M31.",
        "turns": [
            {"turn": 1, "assistant_text": "I will look it up."},
            {"turn": 2, "assistant_text": "M31 is the Andromeda Galaxy."},
        ],
    }
    monkeypatch.setattr(tui_app, "describe_session", lambda selected: manifest)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            app.resume_session(path)
            await pilot.pause()

            transcript = app.query_one("#transcript", Transcript)
            assert "I will look it up." in transcript.assistant_text
            assert "M31 is the Andromeda Galaxy." in transcript.assistant_text
            assert app.engine_starts == 0

    _run(scenario())


def test_resume_session_with_tool_history_restores_only_assistant_text(
    monkeypatch, tmp_path
):
    """A durable tool trace must load without trying to render non-text blocks."""

    from tools.tui import app as tui_app

    path = tmp_path / "session_manifest.json"
    manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "user_message": "Find M31.",
        "turns": [],
        "history": [
            {
                "role": "user",
                "blocks": [{"type": "text", "text": "Find M31."}],
            },
            {
                "role": "assistant",
                "blocks": [
                    {"type": "text", "text": "I will look it up."},
                    {
                        "type": "tool_call",
                        "call_id": "call-1",
                        "name": "search_simbad",
                        "arguments": {"name": "M31"},
                    },
                ],
            },
            {
                "role": "user",
                "blocks": [
                    {
                        "type": "tool_result",
                        "call_id": "call-1",
                        "name": "search_simbad",
                        "content": '{"status": "ok"}',
                        "is_error": False,
                    }
                ],
            },
            {
                "role": "assistant",
                "blocks": [{"type": "text", "text": "M31 is Andromeda."}],
            },
        ],
    }
    monkeypatch.setattr(tui_app, "describe_session", lambda selected: manifest)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            app.resume_session(path)
            await pilot.pause()

            transcript = app.query_one("#transcript", Transcript)
            assert transcript.assistant_text == "I will look it up.\n\nM31 is Andromeda."
            assert isinstance(app._history[1].blocks[1], ToolCallBlock)
            assert isinstance(app._history[2].blocks[0], ToolResultBlock)

    _run(scenario())


def test_error_session_history_is_ready_for_the_next_prompt(monkeypatch, tmp_path):
    """A worker error after SessionFinished must not discard resume context."""

    from textual.widgets import Input
    from tools.tui import app as tui_app

    manifest_path = tmp_path / "session_manifest.json"
    manifest = {
        "user_message": "Find M31.",
        "turns": [],
        "history": [
            {
                "role": "user",
                "blocks": [{"type": "text", "text": "Find M31."}],
            },
            {
                "role": "assistant",
                "blocks": [{"type": "text", "text": "M31 is Andromeda."}],
            },
        ],
    }
    received: list[tuple] = []

    def fake_run_session(_text, *, history, **_kwargs):
        received.append(tuple(history))
        yield SessionFinished(outcome="error", manifest_path=str(manifest_path))
        if len(received) == 1:
            raise RuntimeError("backend disconnected")

    monkeypatch.setattr(tui_app, "describe_session", lambda path: manifest)
    monkeypatch.setattr(tui_app, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            first = app.run_prompt("failed prompt")
            async with asyncio.timeout(2):
                while not first.is_finished:
                    await pilot.pause()
            prompt = app.query_one("#prompt", Input)
            async with asyncio.timeout(2):
                while prompt.disabled:
                    await pilot.pause()
            async with asyncio.timeout(2):
                while not app._history:
                    await pilot.pause()

            prompt.value = "follow-up"
            await pilot.press("enter")
            async with asyncio.timeout(2):
                while len(received) < 2:
                    await pilot.pause()

    _run(scenario())

    assert [message.role for message in received[1]] == ["user", "assistant"]
    assert [message.blocks[0].text for message in received[1]] == [
        "Find M31.",
        "M31 is Andromeda.",
    ]


def test_unexpected_engine_failure_is_rendered_in_the_transcript(monkeypatch):
    """A failure before SessionFinished must not be silently converted to success."""

    from textual.widgets import Input
    from tools.tui import app as tui_app

    def fake_run_session(*_args, **_kwargs):
        raise RuntimeError("backend disconnected before session start")
        yield

    monkeypatch.setattr(tui_app, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            worker = app.run_prompt("Find M31.")
            async with asyncio.timeout(2):
                while not worker.is_finished:
                    await pilot.pause()
            prompt = app.query_one("#prompt", Input)
            async with asyncio.timeout(2):
                while prompt.disabled:
                    await pilot.pause()

            transcript = app.query_one("#transcript", Transcript)
            rendered = "\n".join(
                str(entry.render()) for entry in transcript.query(Static)
            )
            assert "The engine stopped unexpectedly." in rendered
            assert "backend disconnected before session start" not in rendered

    _run(scenario())


def test_unexpected_engine_failure_does_not_retain_an_unanswered_prompt(
    monkeypatch,
):
    """A follow-up after an early failure must start from valid prior history."""

    from textual.widgets import Input
    from tools.tui import app as tui_app

    received: list[tuple[str, tuple]] = []

    def fake_run_session(text, *, history, **_kwargs):
        received.append((text, tuple(history)))
        if text == "failed prompt":
            raise RuntimeError("backend disconnected before session start")
        yield TextDelta(text="recovered")

    monkeypatch.setattr(tui_app, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            first = app.run_prompt("failed prompt")
            async with asyncio.timeout(2):
                while not first.is_finished:
                    await pilot.pause()

            prompt = app.query_one("#prompt", Input)
            async with asyncio.timeout(2):
                while prompt.disabled:
                    await pilot.pause()
            prompt.value = "follow-up"
            await pilot.press("enter")
            async with asyncio.timeout(2):
                while len(received) < 2:
                    await pilot.pause()

    _run(scenario())

    assert received[1] == ("follow-up", ())


def test_resume_is_rejected_while_an_engine_session_is_running(monkeypatch, tmp_path):
    """A live worker may not be overwritten by selecting another saved trace."""

    from tools.tui import app as tui_app

    started = threading.Event()
    release = threading.Event()
    loaded: list[object] = []

    def fake_run_session(_text, **_kwargs):
        started.set()
        release.wait(timeout=2)
        yield TextDelta(text="done")

    monkeypatch.setattr(tui_app, "run_session", fake_run_session)
    monkeypatch.setattr(
        tui_app, "describe_session", lambda path: loaded.append(path) or {}
    )

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            worker = app.run_prompt("running")
            try:
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await pilot.pause()
                app.resume_session(tmp_path / "other_session_manifest.json")
                await pilot.pause()
                assert loaded == []
            finally:
                release.set()
            await worker.wait()

    _run(scenario())


def test_resume_command_loads_the_session_matching_its_id(monkeypatch, tmp_path):
    """The slash command must select by manifest id, not an opaque file path."""

    from tools.artifacts import describe_artifact_file
    from tools.tui import app as tui_app

    path = tmp_path / "session_manifest.json"
    path.write_text("{}", encoding="utf-8")
    manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "user_message": "Find M31.",
        "turns": [{"turn": 1, "assistant_text": "M31 is Andromeda."}],
    }
    monkeypatch.setattr(
        tui_app, "list_sessions", lambda: [describe_artifact_file(path)]
    )
    monkeypatch.setattr(tui_app, "describe_session", lambda selected: manifest)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            app.resume((manifest["session_id"],))
            await pilot.pause()

            transcript = app.query_one("#transcript", Transcript)
            assert transcript.assistant_text == "M31 is Andromeda."
            assert app.engine_starts == 0

    _run(scenario())


def test_resume_command_reports_an_unknown_session_without_starting_the_engine(
    monkeypatch,
):
    """A mistyped id must remain a local command error, never a model prompt."""

    from tools.tui import app as tui_app

    monkeypatch.setattr(tui_app, "list_sessions", lambda: [])

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            app.resume(("missing",))
            await pilot.pause()

            transcript = app.query_one("#transcript", Transcript)
            assert any(
                "Unknown session: missing" in str(entry.render())
                for entry in transcript.query(Static)
            )
            assert app.engine_starts == 0

    _run(scenario())


def test_next_prompt_after_resume_sends_loaded_history_to_the_engine(
    monkeypatch, tmp_path
):
    """The follow-up must preserve resumed context in the real engine request."""

    from tools.tui import app as tui_app
    from textual.widgets import Input

    root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "user_message": "Find M31.",
        "turns": [{"turn": 1, "assistant_text": "M31 is Andromeda."}],
    }
    from tools.workspace import describe_session as read_manifest

    initial_path = tmp_path / "session_manifest.json"
    monkeypatch.setattr(
        tui_app,
        "describe_session",
        lambda selected: manifest if selected == initial_path else read_manifest(selected),
    )
    backend = StubBackend(
        [ModelResponse(stop_reason="end_turn", text="2.5 million ly.")]
    )

    async def scenario() -> None:
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            app.resume_session(initial_path)
            prompt = app.query_one("#prompt", Input)
            prompt.value = "How far away is it?"
            await pilot.press("enter")
            await asyncio.sleep(0.1)
            await pilot.pause()

            messages = backend.calls[0]["messages"]
            assert [message.role for message in messages] == [
                "user",
                "assistant",
                "user",
            ]
            assert [message.blocks[0].text for message in messages] == [
                "Find M31.",
                "M31 is Andromeda.",
                "How far away is it?",
            ]

    _run(scenario())


def test_second_prompt_after_resume_keeps_the_first_follow_up_context(
    monkeypatch, tmp_path
):
    """Resume history must remain available beyond one follow-up prompt."""

    from tools.tui import app as tui_app
    from textual.widgets import Input

    manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "user_message": "Find M31.",
        "turns": [{"turn": 1, "assistant_text": "M31 is Andromeda."}],
    }
    from tools.workspace import describe_session as read_manifest

    initial_path = tmp_path / "session_manifest.json"
    monkeypatch.setattr(
        tui_app,
        "describe_session",
        lambda selected: manifest if selected == initial_path else read_manifest(selected),
    )
    backend = StubBackend(
        [
            ModelResponse(stop_reason="end_turn", text="2.5 million ly."),
            ModelResponse(stop_reason="end_turn", text="Hubble measured it."),
        ]
    )

    async def scenario() -> None:
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            app.resume_session(initial_path)
            prompt = app.query_one("#prompt", Input)
            prompt.value = "How far away is it?"
            await pilot.press("enter")
            async with asyncio.timeout(2):
                while len(backend.calls) < 1:
                    await pilot.pause()
            await pilot.pause()

            prompt.value = "Who measured it?"
            await pilot.press("enter")
            async with asyncio.timeout(2):
                while len(backend.calls) < 2:
                    await pilot.pause()

            messages = backend.calls[1]["messages"]
            assert [message.role for message in messages] == [
                "user",
                "assistant",
                "user",
                "assistant",
                "user",
            ]
            assert [message.blocks[0].text for message in messages] == [
                "Find M31.",
                "M31 is Andromeda.",
                "How far away is it?",
                "2.5 million ly.",
                "Who measured it?",
            ]

    _run(scenario())


def test_next_prompt_keeps_tool_blocks_from_the_finished_session_manifest(
    monkeypatch, tmp_path
):
    """The TUI must retain tool context when continuing a completed run."""

    from tools.tui import app as tui_app
    from textual.widgets import Input

    manifest_path = tmp_path / "session_manifest.json"
    manifest = {
        "history": [
            {
                "role": "user",
                "blocks": [{"type": "text", "text": "Find M31."}],
            },
            {
                "role": "assistant",
                "blocks": [
                    {
                        "type": "tool_call",
                        "call_id": "call-1",
                        "name": "search_simbad",
                        "arguments": {"name": "M31"},
                    }
                ],
            },
            {
                "role": "user",
                "blocks": [
                    {
                        "type": "tool_result",
                        "call_id": "call-1",
                        "name": "search_simbad",
                        "content": '{"status": "ok"}',
                        "is_error": False,
                    }
                ],
            },
            {"role": "assistant", "blocks": []},
        ],
        "user_message": "Find M31.",
        "turns": [],
    }
    received: list[tuple] = []

    def fake_run_session(_text, *, history, **_kwargs):
        received.append(tuple(history))
        yield SessionFinished(outcome="end_turn", manifest_path=str(manifest_path))

    monkeypatch.setattr(tui_app, "describe_session", lambda path: manifest)
    monkeypatch.setattr(tui_app, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "first follow-up"
            await pilot.press("enter")
            async with asyncio.timeout(2):
                while len(received) < 1:
                    await pilot.pause()
            await pilot.pause()

            prompt.value = "second follow-up"
            await pilot.press("enter")
            async with asyncio.timeout(2):
                while len(received) < 2:
                    await pilot.pause()

    _run(scenario())

    continued_history = received[1]
    assert isinstance(continued_history[1].blocks[0], ToolCallBlock)
    assert isinstance(continued_history[2].blocks[0], ToolResultBlock)
    assert continued_history[1].blocks[0].call_id == "call-1"
    assert continued_history[2].blocks[0].content == '{"status": "ok"}'


def test_artifact_browser_uses_the_resumed_session_directory(monkeypatch, tmp_path):
    """F3 must expose referenced artifacts without replaying them into the transcript."""

    from tools.tui import app as tui_app
    from tools.tui.widgets.artifacts import ArtifactBrowser

    root = tmp_path / "artifacts"
    session_id = "20260914T120000Z_abcdef123456"
    session_directory = root / "sessions" / session_id
    artifact_path = session_directory / "result.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("saved result", encoding="utf-8")
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    manifest = {
        "session_id": session_id,
        "artifact_directory": str(tmp_path / "untrusted-artifact-directory"),
        "user_message": "Find M31.",
        "turns": [{"turn": 1, "assistant_text": "M31 is Andromeda."}],
    }
    monkeypatch.setattr(tui_app, "describe_session", lambda selected: manifest)

    async def scenario() -> None:
        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        async with app.run_test() as pilot:
            app.resume_session(session_directory / "session_manifest.json")
            app.show_artifacts(())
            await pilot.pause()

            browser = app.screen
            assert isinstance(browser, ArtifactBrowser)
            assert [item.file.path for item in browser.artifacts] == [
                str(artifact_path.resolve())
            ]

    _run(scenario())


def test_artifact_browser_uses_the_live_session_directory(monkeypatch, tmp_path):
    """F3 must list artifacts emitted by the session currently on screen."""

    from tools.tui.widgets.artifacts import ArtifactBrowser

    root = tmp_path / "artifacts"
    session_directory = root / "sessions" / "20260914T120000Z_abcdef123456"
    artifact_path = session_directory / "result.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("live result", encoding="utf-8")
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)

    async def scenario() -> None:
        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        async with app.run_test() as pilot:
            app.post_message(
                KeplerApp.EngineEvent(
                    SessionStarted(
                        "20260914T120000Z_abcdef123456",
                        str(session_directory / "session_manifest.json"),
                        "stub/model",
                        "model",
                    )
                )
            )
            await pilot.pause()
            app.show_artifacts(())
            await pilot.pause()

            browser = app.screen
            assert isinstance(browser, ArtifactBrowser)
            assert [item.file.path for item in browser.artifacts] == [
                str(artifact_path.resolve())
            ]

    _run(scenario())


def test_failed_resume_keeps_the_prior_session_artifact_directory(
    monkeypatch, tmp_path
):
    """An invalid selection must not discard a usable resumed artifact source."""

    from tools.tui import app as tui_app
    from tools.tui.widgets.artifacts import ArtifactBrowser

    root = tmp_path / "artifacts"
    session_directory = root / "sessions" / "20260914T120000Z_abcdef123456"
    artifact_path = session_directory / "result.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("saved result", encoding="utf-8")
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    valid_manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "artifact_directory": str(session_directory),
        "user_message": "Find M31.",
        "turns": [{"turn": 1, "assistant_text": "M31 is Andromeda."}],
    }
    manifests: list[object] = [valid_manifest]
    monkeypatch.setattr(tui_app, "describe_session", lambda selected: manifests[0])

    async def scenario() -> None:
        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        async with app.run_test() as pilot:
            app.resume_session(session_directory / "session_manifest.json")
            manifests[0] = ["invalid manifest"]
            app.resume_session(tmp_path / "bad_session_manifest.json")
            app.show_artifacts(())
            await pilot.pause()

            browser = app.screen
            assert isinstance(browser, ArtifactBrowser)
            assert [item.file.path for item in browser.artifacts] == [
                str(artifact_path.resolve())
            ]
            assert app.engine_starts == 0

    _run(scenario())


def test_main_builds_the_requested_backend_and_runs_the_app(monkeypatch):
    backend = object()
    created: list[KeplerApp] = []
    monkeypatch.setattr(tui_main, "open_backend", lambda spec, **_: backend)
    monkeypatch.setattr(tui_main.KeplerApp, "run", lambda self: created.append(self))
    monkeypatch.setattr(sys, "argv", ["kepler", "--backend", "stub/model"])

    assert tui_main.main() == 0
    assert len(created) == 1
    assert created[0].backend is backend


def test_main_shows_a_configuration_error_for_an_unavailable_backend(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        tui_main,
        "open_backend",
        lambda spec, **_: (_ for _ in ()).throw(
            BackendUnavailableError("OPENAI_API_KEY")
        ),
    )
    monkeypatch.setattr(sys, "argv", ["kepler", "--backend", "openai/gpt-4.1"])

    assert tui_main.main() == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def _transcript_text(app) -> str:
    return "\n".join(
        str(entry.render()) for entry in app.query_one("#transcript", Transcript).query(Static)
    )


def test_the_header_names_kepler_and_the_backend_from_launch():
    async def scenario() -> None:
        app = KeplerApp(backend=SimpleNamespace(spec="anthropic/claude-sonnet-5"))
        async with app.run_test() as pilot:
            await pilot.pause()
            header = app.query_one("#banner", KeplerHeader)

            assert str(header.border_title) == WORDMARK
            assert "anthropic/claude-sonnet-5" in header.banner_text()

    _run(scenario())


def test_backend_command_without_arguments_lists_without_switching():
    async def scenario() -> None:
        backend = SimpleNamespace(spec="anthropic/claude-sonnet-5")
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            await pilot.press("/", "b", "enter")
            await pilot.pause()

            rendered = _transcript_text(app)
            assert "/backend anthropic" in rendered
            assert "/backend ollama" in rendered
            assert app.backend is backend
            assert app.engine_starts == 0

    _run(scenario())


def test_backend_command_switches_the_session_and_retitles_the_header(monkeypatch):
    async def scenario() -> None:
        from tools.tui import app as app_module

        replacement = SimpleNamespace(spec="ollama/qwen3:8b")
        monkeypatch.setattr(app_module, "open_backend", lambda spec, **_: replacement)
        # A host with nothing to report is what makes a bare provider name
        # switch to the default rather than opening the picker.
        monkeypatch.setattr(app_module, "offered_models", lambda provider: ())

        app = KeplerApp(backend=SimpleNamespace(spec="anthropic/claude-sonnet-5"))
        async with app.run_test() as pilot:
            for key in ("/", "b", "space", "o", "l", "l", "a", "m", "a", "enter"):
                await pilot.press(key)
            await pilot.pause()

            assert app.backend is replacement
            assert app.sub_title == "ollama/qwen3:8b"
            header = app.query_one("#banner", KeplerHeader)
            assert "ollama/qwen3:8b" in header.banner_text()
            assert "Backend switched to ollama/qwen3:8b." in _transcript_text(app)

    _run(scenario())


def test_a_refused_backend_leaves_the_session_on_the_one_that_answers(monkeypatch):
    async def scenario() -> None:
        from tools.tui import app as app_module

        def refuse(spec: str, **_):
            raise BackendUnavailableError("OLLAMA_BASE_URL")

        monkeypatch.setattr(app_module, "open_backend", refuse)
        monkeypatch.setattr(app_module, "offered_models", lambda provider: ())

        backend = SimpleNamespace(spec="anthropic/claude-sonnet-5")
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            for key in ("/", "b", "space", "o", "l", "l", "a", "m", "a", "enter"):
                await pilot.press(key)
            await pilot.pause()

            rendered = _transcript_text(app)
            assert "ollama serve" in rendered
            assert "Still on anthropic/claude-sonnet-5" in rendered
            assert app.backend is backend
            assert app.sub_title == "anthropic/claude-sonnet-5"

    _run(scenario())


def test_an_unknown_backend_name_is_refused_without_building_anything(monkeypatch):
    async def scenario() -> None:
        from tools.tui import app as app_module

        def explode(spec: str, **_):  # pragma: no cover - must never run
            raise AssertionError("resolution should have refused first")

        monkeypatch.setattr(app_module, "open_backend", explode)

        app = KeplerApp(backend=SimpleNamespace(spec="anthropic/claude-sonnet-5"))
        async with app.run_test() as pilot:
            for key in ("/", "b", "space", "h", "a", "l", "enter"):
                await pilot.press(key)
            await pilot.pause()

            assert "unknown backend 'hal'" in _transcript_text(app)

    _run(scenario())


def test_a_switch_is_refused_while_a_turn_is_still_running(monkeypatch):
    """The guard rides on the session worker the resume path already tracks.

    `_session_running()` is set on the UI thread inside `run_prompt`, before
    the worker starts -- unlike a flag set inside the worker, it is already
    true at the one moment the guard exists to cover. The handler is called
    directly because a running turn disables the prompt, so the command
    cannot be typed while the condition holds.
    """

    async def scenario() -> None:
        from tools.tui import app as app_module

        def explode(spec: str, **_):  # pragma: no cover - must never run
            raise AssertionError("a running turn must not be switched under")

        release = threading.Event()

        def blocking_session(*args, **kwargs):
            release.wait()
            return
            yield  # pragma: no cover - makes this a generator

        monkeypatch.setattr(app_module, "open_backend", explode)
        monkeypatch.setattr(app_module, "run_session", blocking_session)

        backend = SimpleNamespace(spec="anthropic/claude-sonnet-5")
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            app.run_prompt("a question")
            assert app._session_running()

            app.switch_backend(("ollama",))
            await pilot.pause()

            assert "A turn is still running" in _transcript_text(app)
            assert app.backend is backend
            assert app.sub_title == "anthropic/claude-sonnet-5"

            release.set()
            while app._session_running():
                await pilot.pause()

    _run(scenario())


def test_launch_spec_prefers_the_flag_then_the_environment_then_the_default(
    monkeypatch,
):
    monkeypatch.setenv("KEPLER_MODEL_BACKEND", "gemini/gemini-2.5-pro")
    assert tui_main.launch_spec("ollama") == "ollama/qwen3.8:27b-mlx"
    assert tui_main.launch_spec(None) == "gemini/gemini-2.5-pro"

    monkeypatch.delenv("KEPLER_MODEL_BACKEND")
    assert tui_main.launch_spec(None) == "anthropic/claude-sonnet-5"


def test_the_kepler_console_script_launches_this_module():
    """``kepler`` is the console's entry point, and a bare ``kepler`` opens it.

    Pinned because the command is the only documented way in and nothing else
    would notice it going missing: ``argparse`` already prints ``usage: kepler``
    whether or not the script is registered, so a dropped entry produces a
    help text naming a command that does not exist.
    """

    import tomllib

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert pyproject["project"]["scripts"]["kepler"] == "tools.tui:launch"


def test_a_bare_invocation_needs_no_arguments_to_reach_the_app(monkeypatch):
    """No flag, no environment variable, no subcommand: ``kepler`` runs."""

    launched: dict[str, object] = {}

    monkeypatch.delenv("KEPLER_MODEL_BACKEND", raising=False)
    monkeypatch.setattr(sys, "argv", ["kepler"])
    monkeypatch.setattr(tui_main, "load_dotenv", lambda: ())
    monkeypatch.setattr(
        tui_main, "open_backend", lambda spec, **_: launched.setdefault("spec", spec)
    )
    monkeypatch.setattr(
        tui_main, "KeplerApp", lambda **kwargs: type("Stub", (), {"run": lambda self: launched.setdefault("ran", True)})()
    )

    assert tui_main.main() == 0
    assert launched["spec"] == "anthropic/claude-sonnet-5"
    assert launched["ran"] is True


def test_typing_a_slash_offers_the_whole_command_registry():
    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            menu = app.query_one("#completions", CommandMenu)
            assert menu.display is False

            await pilot.press("slash")
            await pilot.pause()

            assert menu.display is True
            assert "/backend" in str(menu.menu_text())

    _run(scenario())


def test_tab_completes_a_partial_command_and_then_its_arguments():
    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            await pilot.press("slash", "b", "a", "c")
            await pilot.pause()
            assert [s.value for s in app.query_one("#completions", CommandMenu).suggestions] == [
                "/backend"
            ]

            await pilot.press("tab")
            await pilot.pause()
            assert prompt.value == "/backend "
            assert prompt.cursor_position == len("/backend ")

            await pilot.press("o", "tab")
            await pilot.pause()
            assert prompt.value == "/backend ollama "

    _run(scenario())


def test_the_menu_closes_and_tab_is_left_alone_for_an_ordinary_message():
    """A console that swallows Tab has made its own footer unreachable."""

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            await pilot.press("M", "3", "1")
            await pilot.pause()

            assert app.query_one("#completions", CommandMenu).display is False

            await pilot.press("tab")
            await pilot.pause()
            assert prompt.value == "M31"
            assert app.focused is not prompt

    _run(scenario())


def test_the_completion_menu_counts_the_offers_it_cannot_show():
    menu = CommandMenu()
    menu.suggestions = tuple(
        Suggestion(f"/c{index}", "help") for index in range(CommandMenu.MAX_ROWS + 3)
    )

    rendered = str(menu.menu_text())

    assert rendered.count("\n") == CommandMenu.MAX_ROWS
    assert "… 3 more" in rendered


def test_what_you_typed_stays_visible_after_you_send_it(monkeypatch):
    """An answer read without the question that produced it is a different
    claim, and the input clears the moment you press enter."""

    from tools.tui import app as app_module

    monkeypatch.setattr(
        app_module, "run_session", lambda text, **_: iter((TextDelta(text="ok"),))
    )

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "resolve M31"
            await pilot.press("enter")
            await pilot.pause()

            entries = app.query_one("#transcript", Transcript).query(UserEntry)
            assert [entry.text for entry in entries] == ["resolve M31"]

    _run(scenario())


def test_a_message_typed_mid_turn_is_queued_and_then_marked_delivered(monkeypatch):
    from tools.tui import app as app_module

    started = threading.Event()
    release = threading.Event()

    def fake_run_session(text, **kwargs):
        started.set()
        release.wait(timeout=2)
        yield TextDelta(text="ok")

    monkeypatch.setattr(app_module, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript", Transcript)
            prompt = app.query_one("#prompt", Input)
            try:
                prompt.value = "first"
                await pilot.press("enter")
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await pilot.pause()

                prompt.value = "also check the 60 Hz line"
                await pilot.press("enter")
                await pilot.pause()

                queued = transcript.query(UserEntry).last()
                assert queued.pending is True
                assert "queued" in str(queued.render())

                transcript.handle_event(
                    UserMessageEvent(text="also check the 60 Hz line", turn=2)
                )
                await pilot.pause()
                assert queued.pending is False
                assert "queued" not in str(queued.render())
            finally:
                release.set()

            worker = app._active_worker
            async with asyncio.timeout(2):
                while worker is not None and not worker.is_finished:
                    await pilot.pause()

    _run(scenario())


def test_escape_asks_the_running_loop_to_stop_and_the_status_bar_says_so(monkeypatch):
    from tools.tui import app as app_module

    started = threading.Event()
    release = threading.Event()
    stopped: list[bool] = []

    def fake_run_session(text, **kwargs):
        started.set()
        release.wait(timeout=2)
        stopped.append(kwargs["should_stop"]())
        yield TextDelta(text="ok")

    monkeypatch.setattr(app_module, "run_session", fake_run_session)

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            try:
                app.query_one("#prompt", Input).value = "first"
                await pilot.press("enter")
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await pilot.pause()

                assert "esc stop" in str(app.query_one("#status").render())
                await pilot.press("escape")
                await pilot.pause()
                assert "stopping" in str(app.query_one("#status").render())
            finally:
                release.set()

            worker = app._active_worker
            async with asyncio.timeout(2):
                while worker is not None and not worker.is_finished:
                    await pilot.pause()

    _run(scenario())

    assert stopped == [True]


def test_a_note_the_session_never_took_comes_back_to_the_prompt():
    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            app._queued_input.append("and the 60 Hz line")
            app.post_message(
                KeplerApp.EngineEvent(
                    SessionFinished(outcome="end_turn", manifest_path="/tmp/m.json")
                )
            )
            await pilot.pause()

            assert app.query_one("#prompt", Input).value == "and the 60 Hz line"
            assert "ended before your note was delivered" in _transcript_text(app)

    _run(scenario())


def test_reasoning_renders_apart_from_the_answer():
    """A discarded hypothesis rendered like a finding is how a transcript
    misleads, so the two are different widgets."""

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript", Transcript)
            transcript.handle_event(ThinkingDelta(text="Weighing two catalogs."))
            transcript.handle_event(TextDelta(text="APASS."))
            await pilot.pause()

            thought = transcript.query_one(ThoughtBlock)
            assert thought.thinking == "Weighing two catalogs."
            assert "thinking" in str(thought.render())
            assert transcript.assistant_text == "APASS."
            assert "Weighing" not in transcript.assistant_text

    _run(scenario())


def test_a_bare_provider_name_opens_the_picker_for_a_host_that_lists_models(
    monkeypatch,
):
    """A host holding eleven models has ten answers a default gets wrong."""

    async def scenario() -> None:
        from tools.tui import app as app_module

        replacement = SimpleNamespace(spec="ollama/gemma4:12b")
        opened: list[str] = []

        def open_backend(spec, **_):
            opened.append(spec)
            return replacement

        monkeypatch.setattr(app_module, "open_backend", open_backend)
        monkeypatch.setattr(
            app_module,
            "offered_models",
            lambda provider: ("qwen3.8:27b-mlx", "gemma4:12b"),
        )

        app = KeplerApp(backend=SimpleNamespace(spec="anthropic/claude-sonnet-5"))
        async with app.run_test() as pilot:
            for key in ("/", "b", "space", "o", "l", "l", "a", "m", "a", "enter"):
                await pilot.press(key)
            await pilot.pause()

            assert isinstance(app.screen, ModelBrowser)
            assert opened == []

            app.screen.query_one("#model-list", OptionList).highlighted = 1
            await pilot.press("enter")
            await pilot.pause()

            assert opened == ["ollama/gemma4:12b"]
            assert app.sub_title == "ollama/gemma4:12b"

    _run(scenario())


def test_closing_the_picker_leaves_the_session_where_it_was(monkeypatch):
    async def scenario() -> None:
        from tools.tui import app as app_module

        def explode(spec, **_):  # pragma: no cover - must never run
            raise AssertionError("a closed picker must not switch anything")

        monkeypatch.setattr(app_module, "open_backend", explode)
        monkeypatch.setattr(
            app_module, "offered_models", lambda provider: ("gemma4:12b",)
        )

        backend = SimpleNamespace(spec="anthropic/claude-sonnet-5")
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            for key in ("/", "b", "space", "o", "l", "l", "a", "m", "a", "enter"):
                await pilot.press(key)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            assert app.backend is backend
            assert app.sub_title == "anthropic/claude-sonnet-5"

    _run(scenario())


def test_naming_the_model_outright_switches_without_a_dialog(monkeypatch):
    """A habit or a keybind should not acquire a dialog it did not have."""

    async def scenario() -> None:
        from tools.tui import app as app_module

        replacement = SimpleNamespace(spec="ollama/gemma4:12b")
        monkeypatch.setattr(app_module, "open_backend", lambda spec, **_: replacement)

        def never(provider):  # pragma: no cover - must never run
            raise AssertionError("an explicit model needs no inventory")

        monkeypatch.setattr(app_module, "offered_models", never)

        app = KeplerApp(backend=SimpleNamespace(spec="anthropic/claude-sonnet-5"))
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "/backend ollama gemma4:12b"
            await pilot.press("enter")
            await pilot.pause()

            assert app.sub_title == "ollama/gemma4:12b"

    _run(scenario())


def test_the_picker_marks_what_is_current_and_what_is_default():
    browser = ModelBrowser(
        "ollama",
        ("gemma4:12b", "qwen3.8:27b-mlx"),
        current="gemma4:12b",
        default="qwen3.8:27b-mlx",
    )

    assert browser.label_for("gemma4:12b") == "gemma4:12b  · current"
    assert browser.label_for("qwen3.8:27b-mlx") == "qwen3.8:27b-mlx  · default"
    assert browser.label_for("qwen3.5:9b") == "qwen3.5:9b"


def test_the_picker_does_not_mark_another_providers_model_as_current():
    """`claude-sonnet-5` is not a model the Ollama picker should call current
    just because the session is on it."""

    from tools.tui.app import _model_of

    assert _model_of("anthropic/claude-sonnet-5", "ollama") == ""
    assert _model_of("ollama/gemma4:12b", "ollama") == "gemma4:12b"
    assert _model_of(None, "ollama") == ""


def test_quitting_with_an_approval_open_releases_the_worker_waiting_on_it():
    """A thread worker blocked on a decision cannot be cancelled: nothing but
    this interface sets that event, and Python joins its executor threads at
    exit. Left unreleased, quitting with a modal open hangs the process."""

    decisions: list[Decision] = []
    finished = threading.Event()

    async def scenario() -> None:
        app = KeplerApp(backend=StubBackend([]))

        def worker() -> None:
            decisions.append(
                app._request_approval(ToolCallProposed("c1", "search_ads", {}))
            )
            finished.set()

        async with app.run_test() as pilot:
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            async with asyncio.timeout(2):
                while not isinstance(app.screen, ApprovalModal):
                    await pilot.pause()
            app.exit()
            await pilot.pause()

        assert finished.wait(timeout=3), "the worker was left blocked forever"
        assert thread.join(timeout=3) is None and not thread.is_alive()

    _run(scenario())

    assert decisions == [Decision.DENY]


def test_the_approval_modal_shows_the_arguments_not_just_the_name():
    """Approving `search_vizier` says nothing about what it would query, and
    the transcript node carrying the arguments is behind the modal."""

    modal = ApprovalModal(
        ToolCallProposed("c1", "search_vizier", {"target": "M31", "radius": 5})
    )

    rendered = str(modal.argument_text())

    assert '"target": "M31"' in rendered
    assert '"radius": 5' in rendered
    assert str(ApprovalModal(ToolCallProposed("c", "n", {})).argument_text()) == (
        "no arguments"
    )


def test_a_huge_argument_is_truncated_rather_than_reshaping_the_dialog():
    modal = ApprovalModal(ToolCallProposed("c1", "search_ads", {"q": "x" * 50_000}))

    rendered = str(modal.argument_text())

    assert len(rendered) < 2_100
    assert rendered.endswith("… truncated")


def test_an_unreadable_manifest_still_leaves_the_answer_in_the_history(monkeypatch):
    """The fallback the review found dead. The manifest is the faithful
    record; when it cannot be read back, a follow-up that remembers the answer
    but not the working beats one that remembers neither."""

    from tools.tui import app as app_module

    def unreadable(path):
        raise OSError("manifest gone")

    monkeypatch.setattr(app_module, "describe_session", unreadable)

    async def scenario() -> None:
        backend = StubBackend(
            [ModelResponse(stop_reason="end_turn", text="M31 is Andromeda.")]
        )
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            worker = app.run_prompt("what is M31?")
            async with asyncio.timeout(2):
                while not worker.is_finished:
                    await pilot.pause()
            await pilot.pause()

            assert [
                (message.role, message.blocks[0].text) for message in app._history
            ] == [
                ("user", "what is M31?"),
                ("assistant", "M31 is Andromeda."),
            ]

    _run(scenario())


def test_the_console_script_loads_dotenv_before_tools_config():
    """Second review, finding 12: `kepler` imported tools.config, which fixes
    its settings at import, before main() loaded .env -- so a setting kept in
    .env was read and then ignored."""
    import subprocess

    probe = (
        "import sys, types\n"
        "import tools.dotenv as d\n"
        "seen = []\n"
        "d.load_dotenv = lambda *a, **k: seen.append('tools.config' in sys.modules) or ()\n"
        "fake = types.ModuleType('tools.tui.__main__'); fake.main = lambda: 0\n"
        "sys.modules['tools.tui.__main__'] = fake\n"
        "import tools.tui\n"
        "assert tools.tui.launch() == 0\n"
        "print(seen)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "[False]"
