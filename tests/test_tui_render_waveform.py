"""The braille waveform preview used for WAV artifacts."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest


def _write_stereo_pcm16(path: Path, samples: list[int]) -> Path:
    """Write a tiny two-channel PCM WAV with identical channels."""

    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"".join(struct.pack("<hh", value, value) for value in samples))
    return path


def test_waveform_maps_stereo_pcm16_samples_to_braille_positions(tmp_path):
    """A changed channel mix, amplitude map, or braille dot map must be visible."""

    from tools.tui.render.waveform import render_waveform

    path = _write_stereo_pcm16(
        tmp_path / "pulse.wav", [-32_768, -16_384, 16_384, 32_767]
    )

    assert render_waveform(path, width=2).plain == "⡠⠊"


def test_waveform_rejects_a_nonpositive_width(tmp_path):
    """A zero-cell preview has no meaningful terminal representation."""

    from tools.tui.render.waveform import render_waveform

    path = _write_stereo_pcm16(tmp_path / "pulse.wav", [0])

    with pytest.raises(ValueError, match="width must be positive"):
        render_waveform(path, width=0)
