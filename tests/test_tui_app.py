"""The Textual application shell, driven through Textual's headless pilot."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from textual.widgets import Static

from tests.llm_fakes import StubBackend
from tools import artifacts, config
from tools.agent.events import TextDelta
from tools.llm.base import BackendUnavailableError
from tools.llm.types import ModelResponse
from tools.tui import __main__ as tui_main
from tools.tui.app import KeplerApp
from tools.tui.render.capability import GraphicsTier
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
    monkeypatch.setattr(tui_app, "describe_session", lambda selected: manifest)
    backend = StubBackend(
        [ModelResponse(stop_reason="end_turn", text="2.5 million ly.")]
    )

    async def scenario() -> None:
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            app.resume_session(tmp_path / "session_manifest.json")
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
        "artifact_directory": str(session_directory),
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
    monkeypatch.setattr(tui_main, "build_backend", lambda spec: backend)
    monkeypatch.setattr(tui_main.KeplerApp, "run", lambda self: created.append(self))
    monkeypatch.setattr(sys, "argv", ["kepler", "--backend", "stub/model"])

    tui_main.main()

    assert len(created) == 1
    assert created[0].backend is backend


def test_main_shows_a_configuration_error_for_an_unavailable_backend(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        tui_main,
        "build_backend",
        lambda spec: (_ for _ in ()).throw(BackendUnavailableError("OPENAI_API_KEY")),
    )
    monkeypatch.setattr(sys, "argv", ["kepler", "--backend", "openai/gpt-4.1"])

    tui_main.main()

    assert "OPENAI_API_KEY" in capsys.readouterr().err
