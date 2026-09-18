"""Detect the terminal graphics protocol before Textual starts reading stdin."""

from __future__ import annotations

import os
import sys
from enum import Enum
from typing import Callable, Mapping

from textual_image._terminal import TerminalError, capture_terminal_response

__all__ = ["GraphicsTier", "detect_tier"]


class GraphicsTier(str, Enum):
    """The most capable graphics presentation available to the TUI."""

    KITTY = "kitty"
    ITERM2 = "iterm2"
    SIXEL = "sixel"
    HALFBLOCK = "halfblock"


def detect_tier(
    environ: Mapping[str, str] | None = None,
    *,
    sixel_probe: Callable[[], bool] | None = None,
) -> GraphicsTier:
    """Return the best known graphics tier, with a colored-text fallback.

    Environment declarations identify Kitty and iTerm2 without writing an
    escape sequence. Other terminals receive a 100 ms Sixel device-attributes
    query before the always-safe half-block fallback is selected.
    """

    values = os.environ if environ is None else environ
    if values.get("KITTY_WINDOW_ID") or values.get("TERM") == "xterm-kitty":
        return GraphicsTier.KITTY
    if values.get("TERM_PROGRAM") == "iTerm.app":
        return GraphicsTier.ITERM2

    probe = _probe_sixel if sixel_probe is None else sixel_probe
    return GraphicsTier.SIXEL if probe() else GraphicsTier.HALFBLOCK


def _probe_sixel() -> bool:
    """Issue a short Sixel device-attributes query without raising to the UI."""

    stdin = sys.__stdin__
    stdout = sys.__stdout__
    if not stdin or not stdout:
        return False
    if not (stdin.isatty() and stdout.isatty()):
        return False

    try:
        with capture_terminal_response("\x1b[?", "c", 0.1) as response:
            stdout.write("\x1b[c")
            stdout.flush()
        sequence = response.sequence[len("\x1b[?") : -len("c")]
    except (OSError, TerminalError, TimeoutError):
        return False

    return "4" in sequence.split(";")
