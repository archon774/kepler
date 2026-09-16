"""The Textual application shell, driven through Textual's headless pilot."""

from __future__ import annotations

import asyncio
import sys
import threading
from types import SimpleNamespace

from textual.widgets import Static

from tools.agent.events import TextDelta
from tools.llm.base import BackendUnavailableError
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
    """The guard is asked of a real worker in the engine's group, not a flag."""

    async def scenario() -> None:
        from tools.tui import app as app_module

        def explode(spec: str):  # pragma: no cover - must never run
            raise AssertionError("a running turn must not be switched under")

        monkeypatch.setattr(app_module, "open_backend", explode)

        release = threading.Event()
        backend = SimpleNamespace(spec="anthropic/claude-sonnet-5")
        app = KeplerApp(backend=backend)
        async with app.run_test() as pilot:
            app.run_worker(
                release.wait,
                thread=True,
                group=app_module.ENGINE_WORKER_GROUP,
            )
            while not app.engine_running():
                await pilot.pause()

            for key in ("/", "b", "space", "o", "l", "l", "a", "m", "a", "enter"):
                await pilot.press(key)
            await pilot.pause()

            assert "A turn is still running" in _transcript_text(app)
            assert app.backend is backend

            release.set()
            while app.engine_running():
                await pilot.pause()

    _run(scenario())


def test_launch_spec_prefers_the_flag_then_the_environment_then_the_default(
    monkeypatch,
):
    monkeypatch.setenv("KEPLER_MODEL_BACKEND", "gemini/gemini-2.5-pro")
    assert tui_main.launch_spec("ollama") == "ollama/qwen3:8b"
    assert tui_main.launch_spec(None) == "gemini/gemini-2.5-pro"

    monkeypatch.delenv("KEPLER_MODEL_BACKEND")
    assert tui_main.launch_spec(None) == "anthropic/claude-sonnet-5"
