"""Artifact-browser behaviour for the Kepler Textual application."""

from __future__ import annotations

import asyncio
import struct
import wave
from pathlib import Path

import pytest
from PIL import UnidentifiedImageError
from PIL.Image import DecompressionBombError
from textual.widgets import OptionList, Static

from tools.artifacts import describe_artifact_file
from tools.tui.app import KeplerApp
from tools.tui.render.capability import GraphicsTier
from tools.tui.render.image import render_halfblocks

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


def test_the_image_library_is_not_imported_when_the_module_is():
    """``textual_image.widget`` probes the terminal for its cell size at import
    time, and that probe divides by the column count ``TIOCGWINSZ`` reports. A
    tty that reports no size -- a pty a wrapper opened without setting one --
    therefore raised ``ZeroDivisionError`` from inside the import, before the
    console drew anything. Importing it at module scope makes every launch pay
    that probe; nothing needs it until a native image is rendered.
    """

    import ast

    from tools.tui.widgets import artifacts

    tree = ast.parse(Path(artifacts.__file__).read_text(encoding="utf-8"))
    module_level = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not {name for name in module_level if name.startswith("textual_image")}


@pytest.mark.parametrize("failure", [ZeroDivisionError("no columns"), ImportError("x")])
def test_an_unprobeable_terminal_still_gets_a_picture(monkeypatch, failure):
    """The native protocol is an improvement on half-blocks, not a
    requirement -- a library that cannot measure the terminal must cost the
    user resolution, never the preview."""

    from tools.tui.widgets import artifacts

    def explode(path):
        raise failure

    monkeypatch.setattr(artifacts, "_native_image", explode)

    preview = artifacts._preview_widget(
        describe_artifact_file(FIXTURE), GraphicsTier.KITTY
    )

    assert isinstance(preview, Static)
    assert str(preview.content) == str(render_halfblocks(FIXTURE))


def test_a_preview_catches_what_the_libraries_actually_raise():
    """Neither library raises what it looks like it raises: Pillow's bomb
    guard, `wave.Error` and `struct.error` are all bare `Exception`s, so a
    catch list of `OSError` lets them out of a Textual event handler."""

    from PIL.Image import DecompressionBombError

    from tools.tui.widgets import artifacts

    assert DecompressionBombError in artifacts._IMAGE_FAULTS
    assert wave.Error in artifacts._AUDIO_FAULTS
    assert struct.error in artifacts._AUDIO_FAULTS


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(lambda path: _raise(DecompressionBombError("too big")), id="bomb"),
        pytest.param(lambda path: _raise(UnidentifiedImageError("what")), id="unknown"),
    ],
)
def test_an_unrenderable_image_becomes_a_message_not_a_crash(monkeypatch, failure):
    from tools.tui.widgets import artifacts

    monkeypatch.setattr(artifacts, "render_halfblocks", failure)

    preview = artifacts._preview_widget(
        describe_artifact_file(FIXTURE), GraphicsTier.HALFBLOCK
    )

    assert isinstance(preview, Static)
    assert "Unable to render image" in str(preview.content)


def test_a_file_named_wav_that_is_not_one_becomes_a_message(tmp_path):
    from tools.tui.widgets import artifacts

    impostor = tmp_path / "not-audio.wav"
    impostor.write_bytes(b"this is not a RIFF file")

    preview = artifacts._preview_widget(
        describe_artifact_file(impostor), GraphicsTier.HALFBLOCK
    )

    assert isinstance(preview, Static)
    assert "Unable to render waveform" in str(preview.content)


def _raise(error: Exception):
    raise error
