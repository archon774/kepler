"""Session-browser and resume-history behavior for the Kepler TUI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import OptionList

from tools.artifacts import describe_artifact_file
from tools.llm.types import TextBlock
from tools.tui.widgets.sessions import history_from_manifest


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


def test_history_from_manifest_preserves_user_prompt_and_assistant_turn_order():
    """Resume must preserve recorded text without inventing missing tool results."""

    manifest = {
        "user_message": "Find M31.",
        "turns": [
            {"turn": 1, "assistant_text": "I will look it up."},
            {"turn": 2, "assistant_text": None},
            {"turn": 3, "assistant_text": "M31 is the Andromeda Galaxy."},
        ],
        "tool_calls": [
            {"tool_name": "lookup", "artifacts": [{"path": "/tmp/m31.json"}]}
        ],
    }

    history = history_from_manifest(manifest)

    assert [message.role for message in history] == ["user", "assistant", "assistant"]
    assert [message.blocks for message in history] == [
        (TextBlock(text="Find M31."),),
        (TextBlock(text="I will look it up."),),
        (TextBlock(text="M31 is the Andromeda Galaxy."),),
    ]


def test_history_from_manifest_rejects_a_non_mapping_manifest():
    """A structurally invalid manifest must become a recoverable load failure."""

    with pytest.raises(ValueError, match="not an object"):
        history_from_manifest(["not", "a", "manifest"])


def test_session_browser_lists_manifest_metadata_and_selects_the_session(
    monkeypatch, tmp_path
):
    """The browser must identify a session before returning its manifest path."""

    from tools.tui.app import KeplerApp
    from tools.tui.widgets import sessions as session_widgets

    path = tmp_path / "session_manifest.json"
    path.write_text("{}", encoding="utf-8")
    artifact = describe_artifact_file(path)
    manifest = {
        "session_id": "20260914T120000Z_abcdef123456",
        "created_at": "2026-09-14T12:00:00+00:00",
        "model": "claude-test",
        "outcome": "end_turn",
        "turns": [{"turn": 1}, {"turn": 2}],
    }
    monkeypatch.setattr(session_widgets, "list_sessions", lambda: [artifact])
    monkeypatch.setattr(session_widgets, "describe_session", lambda path: manifest)

    async def scenario() -> None:
        app = KeplerApp(backend=object())
        browser = session_widgets.SessionBrowser()
        selected: list[Path | None] = []
        async with app.run_test() as pilot:
            app.push_screen(browser, selected.append)
            await pilot.pause()

            options = browser.query_one("#session-list", OptionList)
            label = str(options.get_option_at_index(0).prompt)
            for value in (
                manifest["session_id"],
                manifest["created_at"],
                manifest["model"],
                manifest["outcome"],
                "2 turns",
            ):
                assert value in label

            await pilot.press("enter")
            await pilot.pause()
            assert selected == [path]
            assert app.engine_starts == 0

    _run(scenario())
