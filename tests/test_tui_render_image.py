"""The deterministic half-block image fallback."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

FIXTURE = Path(__file__).parent / "fixtures" / "tui" / "four_by_four.png"


def _ansi(renderable) -> str:
    """Capture the renderer under a fixed truecolor terminal configuration."""

    output = StringIO()
    Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        width=80,
    ).print(renderable, end="")
    return output.getvalue()


def test_halfblocks_match_the_committed_four_by_four_png_golden():
    """A changed pixel pairing or color channel must break the fallback output."""

    from tools.tui.render.image import render_halfblocks

    assert _ansi(render_halfblocks(FIXTURE, max_width=4)) == (
        "\x1b[38;2;255;0;0;48;2;0;0;0m▀\x1b[0m"
        "\x1b[38;2;0;255;0;48;2;128;128;128m▀\x1b[0m"
        "\x1b[38;2;0;0;255;48;2;255;255;0m▀\x1b[0m"
        "\x1b[38;2;255;255;255;48;2;0;255;255m▀\x1b[0m\n"
        "\x1b[38;2;255;0;255;48;2;32;32;32m▀\x1b[0m"
        "\x1b[38;2;255;128;0;48;2;64;64;64m▀\x1b[0m"
        "\x1b[38;2;0;128;255;48;2;96;96;96m▀\x1b[0m"
        "\x1b[38;2;128;0;255;48;2;128;128;128m▀\x1b[0m"
    )
