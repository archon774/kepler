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


def test_only_the_frames_it_draws_are_read(tmp_path, monkeypatch):
    from tools.tui.render.waveform import render_waveform

    """A preview is 120 numbers wide. Decoding a whole file to sample it cost
    0.75 s and ~300 MB on the bundled 10 MB example -- on the UI thread."""

    path = tmp_path / "long.wav"
    frames = 400_000
    with wave.open(str(path), "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(44_100)
        sink.writeframes(struct.pack("<%dh" % frames, *([12_000] * frames)))

    read_sizes: list[int] = []
    real_readframes = wave.Wave_read.readframes

    def counting_readframes(self, count):
        read_sizes.append(count)
        return real_readframes(self, count)

    monkeypatch.setattr(wave.Wave_read, "readframes", counting_readframes)
    rendered = render_waveform(path, width=60)

    assert len(str(rendered)) == 60
    assert read_sizes == [1] * 120, "the preview read more than the frames it drew"


def test_a_header_that_overstates_its_length_draws_silence_not_an_error(tmp_path):
    from tools.tui.render.waveform import render_waveform

    path = tmp_path / "truncated.wav"
    with wave.open(str(path), "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(8_000)
        sink.writeframes(struct.pack("<4h", 0, 1000, -1000, 0))
    raw = bytearray(path.read_bytes())
    path.write_bytes(raw[:-4])  # drop two frames the header still counts

    assert len(str(render_waveform(path, width=4))) == 4
