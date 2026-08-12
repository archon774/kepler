"""Pulsar sonification: turn an ATNF rotation period into audio.

Real pulsar periods (P0, looked up via psrqpy/ATNF -- the same source
tools.atnf.search_atnf uses) span roughly 1.4 ms (millisecond pulsars) to
~10s (slow rotators), i.e. a raw rotation frequency of ~0.1-700 Hz -- mostly
below or at the edge of audible pitch, and even an audible one doesn't read
as "a pulsar" the way a click train does. mode="click" (the default) plays a
short percussive click once per rotation, recognizable as a pulse train (like
a metronome or geiger counter) at any period; mode="tone" instead plays a
continuous sine wave at the rotation frequency, which needs speed_factor > 1
to be audible at all for most pulsars (see MIN_AUDIBLE_HZ below).

Uses scipy.io.wavfile (already a transitive scipy dependency) rather than
adding a new audio package.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import psrqpy
from scipy.io import wavfile

from tools.artifacts import describe_artifact_file
from tools.config import artifact_directory
from tools.models import PulsarSonificationResult, ToolError, ToolWarning

__all__ = ["sonify_pulsar"]

MIN_AUDIBLE_HZ = 20.0


def _lookup_period_s(name: str) -> float | None:
    query = psrqpy.QueryATNF(psrs=[name], params=["P0"])
    table = query.table
    if table is None or len(table) == 0 or "P0" not in table.colnames:
        return None
    value = float(table["P0"][0])
    return value if np.isfinite(value) and value > 0 else None


def _fade_envelope(t: np.ndarray, duration_s: float, fade_s: float = 0.02) -> np.ndarray:
    """Linear fade-in/out so the waveform starts/ends at zero, avoiding a
    click at playback start/end distinct from the pulse clicks themselves."""
    fade_s = min(fade_s, duration_s / 2) if duration_s > 0 else 0.0
    if fade_s <= 0:
        return np.ones_like(t)
    envelope = np.minimum(t / fade_s, (duration_s - t) / fade_s)
    return np.clip(envelope, 0.0, 1.0)


def _click_waveform(frequency_hz: float, duration_s: float, sample_rate: int) -> np.ndarray:
    t = np.arange(int(duration_s * sample_rate)) / sample_rate
    period_s = 1.0 / frequency_hz
    phase = np.mod(t, period_s)
    # A short (~3ms), exponentially decaying tone burst at each pulse onset --
    # not a single-sample impulse, which would be inaudible at typical
    # playback -- so it's audible as a distinct "tick" rather than a click.
    click_len_s = min(0.003, period_s * 0.5)
    envelope = np.where(phase < click_len_s, np.exp(-phase / (click_len_s / 4.0)), 0.0)
    tone = np.sin(2 * np.pi * 1200.0 * t)
    return envelope * tone


def _tone_waveform(frequency_hz: float, duration_s: float, sample_rate: int) -> np.ndarray:
    t = np.arange(int(duration_s * sample_rate)) / sample_rate
    return np.sin(2 * np.pi * frequency_hz * t) * _fade_envelope(t, duration_s)


def sonify_pulsar(
    name: str,
    mode: str = "click",
    duration_s: float = 5.0,
    sample_rate: int = 44100,
    speed_factor: float = 1.0,
    directory: str | Path | None = None,
) -> PulsarSonificationResult:
    """Render one pulsar's rotation as a .wav file, from its ATNF period (P0).

    `speed_factor` time-compresses the rotation (effective frequency =
    speed_factor / P0) -- leave at 1.0 for the pulsar's real rotation rate,
    or raise it to make a slow pulsar's mode="tone" audible as a pitch rather
    than a sub-audible rumble (mode="click" is audible as a rhythm at any
    speed_factor, including 1.0, since it's a discrete event train rather
    than a continuous waveform).
    """
    if mode not in ("click", "tone"):
        return PulsarSonificationResult(
            name=name, mode=mode,
            errors=[ToolError(code="invalid_input", message="mode must be 'click' or 'tone'.")],
        )
    if speed_factor <= 0:
        return PulsarSonificationResult(
            name=name, mode=mode,
            errors=[ToolError(code="invalid_input", message="speed_factor must be positive.")],
        )
    if duration_s <= 0:
        return PulsarSonificationResult(
            name=name, mode=mode,
            errors=[ToolError(code="invalid_input", message="duration_s must be positive.")],
        )

    try:
        period_s = _lookup_period_s(name)
    except Exception as exc:
        return PulsarSonificationResult(
            name=name, mode=mode, errors=[ToolError(code="provider_unavailable", message=str(exc))],
        )
    if period_s is None:
        return PulsarSonificationResult(
            name=name, mode=mode,
            errors=[ToolError(code="not_found", message=f"No ATNF P0 (rotation period) found for {name!r}.")],
        )

    frequency_hz = speed_factor / period_s
    warnings: list[ToolWarning] = []
    if mode == "tone" and frequency_hz < MIN_AUDIBLE_HZ:
        warnings.append(
            ToolWarning(
                code="below_audible_range",
                message=(
                    f"{frequency_hz:.3g} Hz is below typical audible pitch (~{MIN_AUDIBLE_HZ:.0f} Hz) "
                    f"at speed_factor={speed_factor:g} -- raise speed_factor to hear this as a tone, "
                    "or use mode='click' instead (audible as a rhythm at any speed)."
                ),
            )
        )
    if frequency_hz > sample_rate / 2.0:
        warnings.append(
            ToolWarning(
                code="above_nyquist",
                message=(
                    f"{frequency_hz:.3g} Hz exceeds the Nyquist frequency for sample_rate={sample_rate} -- "
                    "lower speed_factor or raise sample_rate."
                ),
            )
        )

    waveform = (
        _click_waveform(frequency_hz, duration_s, sample_rate)
        if mode == "click"
        else _tone_waveform(frequency_hz, duration_s, sample_rate)
    )
    peak = float(np.max(np.abs(waveform))) or 1.0
    pcm = np.int16(np.clip(waveform / peak, -1.0, 1.0) * 32767)

    out_dir = artifact_directory(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    out_path = out_dir / f"_pulsar_{slug}_{mode}.wav"
    wavfile.write(out_path, sample_rate, pcm)

    return PulsarSonificationResult(
        name=name,
        period_s=period_s,
        frequency_hz=frequency_hz,
        mode=mode,
        speed_factor=speed_factor,
        duration_s=duration_s,
        n_pulses=int(duration_s * frequency_hz),
        audio=describe_artifact_file(out_path),
        warnings=warnings,
    )
