"""The Textual application shell, driven through Textual's headless pilot."""

from __future__ import annotations

import asyncio
import sys
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


def test_the_header_names_kepler_and_the_backend_from_launch():
    async def scenario() -> None:
        app = KeplerApp(backend=SimpleNamespace(spec="anthropic/claude-sonnet-5"))
        async with app.run_test() as pilot:
            await pilot.pause()
            header = app.query_one("#banner", KeplerHeader)

            assert str(header.border_title) == WORDMARK
            assert "anthropic/claude-sonnet-5" in header.banner_text()

    _run(scenario())
