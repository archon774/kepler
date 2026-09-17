"""The Textual application shell, driven through Textual's headless pilot."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from textual.widgets import Static

from tests.llm_fakes import StubBackend
from tools import artifacts, config
from tools.agent.events import SessionFinished, SessionStarted, TextDelta
from tools.llm.base import BackendUnavailableError
from tools.llm.types import ModelResponse, ToolCallBlock, ToolResultBlock
from tools.tui import __main__ as tui_main
from tools.tui.app import KeplerApp
from tools.tui.render.capability import GraphicsTier
from tools.tui.widgets.header import WORDMARK, KeplerHeader
from tools.tui.widgets.transcript import Transcript


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
    monkeypatch.setattr(tui_main, "open_backend", lambda spec: backend)
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
        lambda spec: (_ for _ in ()).throw(BackendUnavailableError("OPENAI_API_KEY")),
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
        monkeypatch.setattr(app_module, "open_backend", lambda spec: replacement)

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

        def refuse(spec: str):
            raise BackendUnavailableError("OLLAMA_BASE_URL")

        monkeypatch.setattr(app_module, "open_backend", refuse)

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

        def explode(spec: str):  # pragma: no cover - must never run
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

        def explode(spec: str):  # pragma: no cover - must never run
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

    assert pyproject["project"]["scripts"]["kepler"] == "tools.tui.__main__:main"


def test_a_bare_invocation_needs_no_arguments_to_reach_the_app(monkeypatch):
    """No flag, no environment variable, no subcommand: ``kepler`` runs."""

    launched: dict[str, object] = {}

    monkeypatch.delenv("KEPLER_MODEL_BACKEND", raising=False)
    monkeypatch.setattr(sys, "argv", ["kepler"])
    monkeypatch.setattr(tui_main, "load_dotenv", lambda: ())
    monkeypatch.setattr(tui_main, "open_backend", lambda spec: launched.setdefault("spec", spec))
    monkeypatch.setattr(
        tui_main, "KeplerApp", lambda **kwargs: type("Stub", (), {"run": lambda self: launched.setdefault("ran", True)})()
    )

    assert tui_main.main() == 0
    assert launched["spec"] == "anthropic/claude-sonnet-5"
    assert launched["ran"] is True
