"""Modal artifact browser and previews for the Kepler console."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

import struct
import wave

from PIL import UnidentifiedImageError
from PIL.Image import DecompressionBombError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList, Static

from tools.models import ArtifactMetadata
from tools.tui.render.capability import GraphicsTier
from tools.tui.render.image import render_halfblocks
from tools.tui.render.waveform import render_waveform
from tools.workspace import list_artifacts

__all__ = ["ArtifactBrowser", "open_externally"]


def open_externally(path: Path) -> bool:
    """Ask the host desktop to open an artifact selected by the user."""

    return webbrowser.open(path.expanduser().resolve().as_uri())


class ArtifactBrowser(ModalScreen[None]):
    """Browse local artifacts while preserving a usable path at every tier."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("o", "open_externally", "Open externally"),
    ]

    CSS = """
    ArtifactBrowser {
        align: center middle;
    }

    #artifact-browser {
        width: 90%;
        height: 90%;
        border: round $accent;
        padding: 1 2;
    }

    #artifact-list {
        height: 8;
    }

    #artifact-path {
        height: auto;
        padding: 1 0;
    }

    #artifact-preview {
        height: 1fr;
        overflow: auto auto;
    }
    """

    def __init__(
        self,
        artifacts: Sequence[ArtifactMetadata] | None = None,
        *,
        tier: GraphicsTier,
        open_path: Callable[[Path], bool] = open_externally,
    ) -> None:
        super().__init__()
        self.artifacts = tuple(list_artifacts() if artifacts is None else artifacts)
        self.tier = tier
        self._open_path = open_path
        self._selected_index = 0 if self.artifacts else None

    def compose(self) -> ComposeResult:
        """Build a compact browser with a full-width preview area."""

        with Vertical(id="artifact-browser"):
            if not self.artifacts:
                yield Static("No artifacts found.")
                return
            yield OptionList(
                *(_artifact_label(artifact) for artifact in self.artifacts),
                id="artifact-list",
                markup=False,
            )
            yield Static(id="artifact-path", markup=False)
            yield Vertical(id="artifact-preview")

    def on_mount(self) -> None:
        """Title the dialog and display the first artifact once it is built."""

        # In the border, as the console header does it: a heading inside the
        # frame spends a row saying what the frame already is.
        self.query_one("#artifact-browser").border_title = "Artifacts"
        if self._selected_index is not None:
            self._show_artifact(self._selected_index)
            self.query_one("#artifact-list", OptionList).focus()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Keep the path and preview synchronized with list navigation."""

        self._show_artifact(event.option_index)

    def action_open_externally(self) -> None:
        """Open only the artifact the user expressly selected."""

        artifact = self._selected_artifact()
        if artifact is None or not artifact.file.exists:
            self.notify("The selected artifact is no longer available.", severity="error")
            return
        if not self._open_path(Path(artifact.file.path).resolve()):
            self.notify("Unable to open the selected artifact.", severity="error")

    def _show_artifact(self, index: int) -> None:
        """Replace the preview and show the filesystem path for one artifact."""

        self._selected_index = index
        artifact = self.artifacts[index]
        self.query_one("#artifact-path", Static).update(artifact.file.path)
        preview = self.query_one("#artifact-preview", Vertical)
        preview.remove_children()
        preview.mount(_preview_widget(artifact, self.tier))

    def _selected_artifact(self) -> ArtifactMetadata | None:
        if self._selected_index is None:
            return None
        return self.artifacts[self._selected_index]


def _artifact_label(artifact: ArtifactMetadata) -> str:
    """Return one plain-text option label from workspace metadata."""

    size = ""
    if artifact.file.size_bytes is not None:
        size = f" · {artifact.file.size_bytes} bytes"
    return f"{Path(artifact.file.path).name} · {artifact.artifact_type}{size}"


#: What a preview is allowed to fail with. Neither library raises what it
#: looks like it raises: Pillow's ``DecompressionBombError`` is a bare
#: ``Exception`` rather than an ``OSError``, and so are ``wave.Error`` and
#: ``struct.error``. A preview that only caught the obvious ones let a large
#: PNG, or any non-WAV file named ``.wav``, raise out of an event handler and
#: take the console with it.
_IMAGE_FAULTS = (OSError, UnidentifiedImageError, DecompressionBombError)
_AUDIO_FAULTS = (OSError, ValueError, wave.Error, struct.error)


def _native_image(path: Path) -> Widget:
    """Build a native-protocol image widget, importing the library on first use.

    The import is deferred because ``textual_image.widget`` probes the terminal
    for its cell size at import time, and that probe divides by the column
    count ``TIOCGWINSZ`` reports. A tty that reports no size at all -- a pty
    opened by a wrapper that never set one -- makes the division raise
    ``ZeroDivisionError`` from inside a third-party import, killing the console
    before it has drawn anything. Nothing needs the probe until a native image
    is actually rendered, which only happens above the half-block tier, so
    deferring it keeps an unsized terminal launchable.
    """

    from textual_image.widget import Image

    return Image(path)


def _preview_widget(artifact: ArtifactMetadata, tier: GraphicsTier) -> Widget:
    """Select a native or text preview without ever removing the path handle."""

    if not artifact.file.exists:
        return Static("Artifact file is no longer available.")

    # Every `Static` below that carries a path or a library's error message
    # sets markup=False: both can contain square brackets, which Textual would
    # read as content markup and silently remove from the screen.

    path = Path(artifact.file.path)
    if artifact.artifact_type == "image":
        try:
            if tier is not GraphicsTier.HALFBLOCK:
                try:
                    return _native_image(path)
                except (ArithmeticError, ImportError):
                    # The native protocol is an improvement on half-blocks,
                    # never a requirement: a terminal the library cannot probe
                    # still gets a picture rather than an error.
                    pass
            return Static(render_halfblocks(path))
        except _IMAGE_FAULTS as error:
            return Static(f"Unable to render image: {error}", markup=False)
    if artifact.file.suffix and artifact.file.suffix.lower() == ".wav":
        try:
            return Static(render_waveform(path))
        except _AUDIO_FAULTS as error:
            return Static(f"Unable to render waveform: {error}", markup=False)
    return Static(f"{artifact.artifact_type.capitalize()} artifact", markup=False)
