"""Pillow-based image rendering that composes with every Textual terminal."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from rich.color import Color
from rich.style import Style
from rich.text import Text

__all__ = ["render_halfblocks"]


def render_halfblocks(path: str | Path, *, max_width: int = 80) -> Text:
    """Render an image as truecolor upper-half block characters.

    Each character carries the upper source pixel as its foreground color and
    the lower source pixel as its background color. The result is ordinary
    styled text, so it remains visible on terminals with no image protocol.
    """

    if max_width < 1:
        raise ValueError("max_width must be positive")

    with Image.open(path) as source:
        image = _composite_on_black(source.convert("RGBA"))

    if image.width > max_width:
        height = max(1, round(image.height * max_width / image.width))
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    if image.height % 2:
        image = _pad_lower_row(image)

    rendered = Text()
    for row in range(0, image.height, 2):
        for column in range(image.width):
            upper = image.getpixel((column, row))
            lower = image.getpixel((column, row + 1))
            rendered.append(
                "▀",
                style=Style(
                    color=Color.from_rgb(*upper),
                    bgcolor=Color.from_rgb(*lower),
                ),
            )
        if row + 2 < image.height:
            rendered.append("\n")
    return rendered


def _composite_on_black(image: Image.Image) -> Image.Image:
    """Flatten transparency predictably before terminal color conversion."""

    background = Image.new("RGB", image.size, "black")
    background.paste(image, mask=image.getchannel("A"))
    return background


def _pad_lower_row(image: Image.Image) -> Image.Image:
    """Supply a black lower pixel for an image with an odd source height."""

    padded = Image.new("RGB", (image.width, image.height + 1), "black")
    padded.paste(image)
    return padded
