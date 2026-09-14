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
    """Render PCM WAV amplitudes in ``width`` two-by-four braille cells."""

    if width < 1:
        raise ValueError("width must be positive")

    with wave.open(str(path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("WAV preview requires uncompressed PCM audio")
        channels = source.getnchannels()
        samples = _decode_pcm(source.readframes(source.getnframes()), source.getsampwidth())

    if not samples:
        return Text("No audio samples.")

    amplitudes = _downmix(samples, channels)
    points = _sample_points(amplitudes, width * 2)
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


def _downmix(samples: list[float], channels: int) -> list[float]:
    """Average interleaved channels into one display-only amplitude stream."""

    if channels < 1:
        raise ValueError("WAV must contain at least one channel")
    return [
        sum(samples[index : index + channels]) / channels
        for index in range(0, len(samples), channels)
    ]


def _sample_points(amplitudes: list[float], count: int) -> list[float]:
    """Choose evenly spaced source samples for the available braille columns."""

    return [
        amplitudes[min(index * len(amplitudes) // count, len(amplitudes) - 1)]
        for index in range(count)
    ]


def _amplitude_row(value: float) -> int:
    """Map a normalized amplitude to one of the four braille dot rows."""

    bounded = min(1.0, max(-1.0, value))
    return int(round((1.0 - bounded) * 1.5))
