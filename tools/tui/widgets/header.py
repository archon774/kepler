"""The branded console header shown from the moment Kepler launches."""

from __future__ import annotations

from textual.widgets import Static

__all__ = ["KeplerHeader", "WORDMARK", "TAGLINE"]

#: Letter-spaced rather than drawn. A block-capital wordmark needs five rows to
#: stay legible, and this console is a single scrolling conversation where
#: every row the header keeps is a row of transcript nobody can see. Spaced
#: capitals read as a wordmark at one row, in every font a terminal has.
WORDMARK = "K E P L E R"

TAGLINE = "astronomy research console"


class KeplerHeader(Static):
    """The title frame: the Kepler wordmark, the tagline, and the backend spec.

    The backend spec sits in the header, not only in the status bar, because it
    is the one piece of session identity a person must not misread -- a
    transcript looks identical whether Anthropic or a local Ollama model
    produced it. :meth:`set_backend` runs on every ``/backend`` switch, so the
    header is never one switch out of date.

    The frame is a Textual border rather than drawn box characters, so it
    follows the terminal width and the active theme instead of fixing either.
    """

    DEFAULT_CSS = """
    KeplerHeader {
        dock: top;
        height: 3;
        padding: 0 1;
        border: round $accent;
        color: $text-muted;
        background: $panel;
    }
    """

    def __init__(self, backend_spec: str = "", **kwargs) -> None:
        # markup=False: the spec half of this line is whatever `/backend` was
        # given, and a heading is not a place to parse someone's typing.
        super().__init__("", markup=False, **kwargs)
        self._backend_spec = backend_spec

    def on_mount(self) -> None:
        """Draw the banner as soon as the application starts."""

        self.border_title = WORDMARK
        self._refresh_banner()

    def set_backend(self, backend_spec: str) -> None:
        """Point the header at a newly selected backend."""

        self._backend_spec = backend_spec
        self._refresh_banner()

    def banner_text(self) -> str:
        """The header's inner line, as plain text.

        Separate from the widget update so a test can assert what the header
        says without driving a terminal. The wordmark itself is the border
        title and is not part of this string.
        """

        if self._backend_spec:
            return f"{TAGLINE} · {self._backend_spec}"
        return TAGLINE

    def _refresh_banner(self) -> None:
        self.update(self.banner_text())
