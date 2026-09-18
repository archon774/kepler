"""Presentational WAV thumbnails for the TUI artifact browser.

The sonifier plays samples by index and ignores the observation timestamps.
This waveform is therefore a visual audio preview only; it must never be used
to infer a pulsar period. The folded-profile plot is the scientific artifact.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from rich.text import Text

__all__ = ["render_waveform"]

_BRAILLE_DOTS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))


def render_waveform(path: str | Path, *, width: int = 60) -> Text:
    """Render PCM WAV amplitudes in ``width`` two-by-four braille cells.

    Only the frames it draws are read. The preview picks evenly spaced frames
    and seeks to each one, rather than decoding the file and then sampling
    what it decoded: a preview is 120 numbers wide, and the bundled 10 MB
    example alone cost 0.75 s and ~300 MB of Python floats that way -- on the
    UI thread, where that is a frozen console. The chosen frames are the same
    frames either way.
    """

    if width < 1:
        raise ValueError("width must be positive")

    count = width * 2
    with wave.open(str(path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("WAV preview requires uncompressed PCM audio")
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        frames = source.getnframes()
        if channels < 1:
            raise ValueError("WAV must contain at least one channel")
        if frames < 1:
            return Text("No audio samples.")
        points = [
            _frame_amplitude(source, index * frames // count, channels, sample_width)
            for index in range(count)
        ]

    glyphs = []
    for index in range(0, len(points), 2):
        dots = _BRAILLE_DOTS[0][_amplitude_row(points[index])]
        dots |= _BRAILLE_DOTS[1][_amplitude_row(points[index + 1])]
        glyphs.append(chr(0x2800 + dots))
    return Text("".join(glyphs), style="cyan")


def _decode_pcm(raw: bytes, sample_width: int) -> list[float]:
    """Normalize unsigned 8-bit and signed 16/24/32-bit PCM samples."""

    if sample_width == 1:
        return [(value - 128) / 128 for value in raw]
    if sample_width == 2:
        return [value / 32_768 for (value,) in struct.iter_unpack("<h", raw)]
    if sample_width == 3:
        return [
            int.from_bytes(raw[index : index + 3], "little", signed=True) / 8_388_608
            for index in range(0, len(raw), 3)
        ]
    if sample_width == 4:
        return [value / 2_147_483_648 for (value,) in struct.iter_unpack("<i", raw)]
    raise ValueError(f"Unsupported PCM sample width: {sample_width} bytes")


def _frame_amplitude(
    source: wave.Wave_read, position: int, channels: int, sample_width: int
) -> float:
    """The mean amplitude of one frame, read where it lies in the file.

    A frame past the end -- a header that overstates its own length -- reads
    as silence rather than raising: a truncated file should draw a short
    waveform, not refuse to preview.
    """

    source.setpos(position)
    samples = _decode_pcm(source.readframes(1), sample_width)
    if not samples:
        return 0.0
    return sum(samples) / channels


def _amplitude_row(value: float) -> int:
    """Map a normalized amplitude to one of the four braille dot rows."""

    bounded = min(1.0, max(-1.0, value))
    return int(round((1.0 - bounded) * 1.5))
