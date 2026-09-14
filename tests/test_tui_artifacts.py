"""Artifact-browser behaviour for the Kepler Textual application."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import OptionList, Static

from tools.artifacts import describe_artifact_file
from tools.tui.app import KeplerApp
from tools.tui.render.capability import GraphicsTier

FIXTURE = Path(__file__).parent / "fixtures" / "tui" / "four_by_four.png"


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


def test_artifact_browser_lists_workspace_metadata_and_keeps_path_visible(monkeypatch, tmp_path):
    """Selecting an artifact must never hide the only universally usable handle."""

    from tools.tui.widgets import artifacts as artifact_widgets

    path = tmp_path / "result.txt"
    path.write_text("result", encoding="utf-8")
    artifact = describe_artifact_file(path)
    monkeypatch.setattr(artifact_widgets, "list_artifacts", lambda: [artifact])

    async def scenario() -> None:
        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        browser = artifact_widgets.ArtifactBrowser(tier=GraphicsTier.HALFBLOCK)
        async with app.run_test() as pilot:
            app.push_screen(browser)
            await pilot.pause()

            assert browser.query_one("#artifact-list", OptionList).option_count == 1
            assert str(path) in str(browser.query_one("#artifact-path", Static).render())

    _run(scenario())


@pytest.mark.parametrize(
    "tier", [GraphicsTier.KITTY, GraphicsTier.ITERM2, GraphicsTier.SIXEL]
)
def test_artifact_browser_uses_textual_image_for_native_image_tiers(tier):
    """A native-capable terminal must receive the dependency-backed image widget."""

    from textual_image.widget import Image as NativeImage

    from tools.tui.widgets.artifacts import ArtifactBrowser

    async def scenario() -> None:
        app = KeplerApp(backend=object(), graphics_tier=tier)
        browser = ArtifactBrowser([describe_artifact_file(FIXTURE)], tier=tier)
        async with app.run_test() as pilot:
            app.push_screen(browser)
            await pilot.pause()

            preview = browser.query_one("#artifact-preview")
            assert isinstance(preview.query_one(NativeImage), NativeImage)

    _run(scenario())


def test_artifact_browser_opens_selected_path_only_after_user_action():
    """The browser may hand a path to the OS, but never opens it on mount."""

    from tools.tui.widgets.artifacts import ArtifactBrowser

    opened: list[Path] = []

    async def scenario() -> None:
        app = KeplerApp(backend=object(), graphics_tier=GraphicsTier.HALFBLOCK)
        browser = ArtifactBrowser(
            [describe_artifact_file(FIXTURE)],
            tier=GraphicsTier.HALFBLOCK,
            open_path=lambda path: opened.append(path) or True,
        )
        async with app.run_test() as pilot:
            app.push_screen(browser)
            await pilot.pause()
            assert opened == []

            await pilot.press("o")
            await pilot.pause()
            assert opened == [FIXTURE.resolve()]

    _run(scenario())
