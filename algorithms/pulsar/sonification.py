"""Pulsar light-curve sonification: amplitude-modulated noise to 16-bit PCM.

PORTED from ``algorithms/lightcurve/pulsar/pulsar-sonification.algorithms.ts``
-- itself extracted from astromancer's ``PulsarService.sonification``
(``pulsar.service.ts`` 889-1054). This module targets the **saved-WAV path**;
the live-playback twin (``sonificationBrowser``) differs in three documented
ways and is not ported, since it exists to drive an ``AudioContext``.

What the algorithm does: normalize the light curve to [0,1] across both
polarizations, upsample it so one pass spans at least ``sampleRate * period``
points, and use it as the amplitude envelope on white noise. The result is the
"TV static that pulses" rendering.

The synthesis fits nothing; it loops its input over ``pass_seconds``. What the
caller passes is what decides the rendering, and upstream has two modes:

* **Folded** (upstream's primary path, from the period-folding form) --
  ``pass_seconds`` is the *pulsar's period* and the input is the folded,
  phase-binned profile, so the pulse repeats at its true rate. Reaching it
  requires a period, which is what the periodogram is for.
* **Light curve** (upstream's secondary path, from the light-curve sonifier)
  -- ``pass_seconds`` is the windowed observation *duration* and the input is
  the raw background-subtracted scan, so one pass plays the scan through once.

**Only the light-curve mode is wired up today.** ``tools.pulsar`` has no way to
obtain a period yet; folded rendering lands with the periodogram tool. The
caveat below applies to the light-curve mode specifically -- a binned phase
profile is uniform in phase by construction, so it does not suffer from it.

**The synthesis never sees the time axis.** Upstream's first parameter is
``_xValues`` and is unused; samples are played back at a uniform rate in
*index*, not in time. Two consequences, both upstream, both preserved:

* dropped samples are compressed away rather than played as silence, so audio
  time runs slow by the ratio of the mean sample spacing to the instrument
  cadence -- 2.5% on the B0329+54 fixture, which has 1.44 s of gaps in 56 s;
* ``samplesPerPoint`` is floored to a whole number of output samples, adding
  up to a further factor of two at low interpolation factors.

So a period measured off the rendered audio is not the pulsar's period.
:attr:`SonificationResult.pass_audio_seconds` is what lets a caller quantify
the drift; ``tools.pulsar`` reports it as a stretch factor and warns when it
matters.

Only one behaviour deliberately diverges from upstream, and it is the noise
carrier: upstream calls ``Math.random()``, which is unseedable. Kepler's
default checks have to be deterministic (``CLAUDE.md``), so the carrier comes
from a seeded ``numpy`` generator. Same distribution, reproducible draw.
Everything else is arithmetic-for-arithmetic, including the ``Math.floor``
(not round, not truncate) in the PCM conversion.
"""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

__all__ = [
    "SonificationResult",
    "SAMPLE_RATE",
    "DURATION_SECONDS",
    "BURST_MODE_MAX_FREQUENCY_HZ",
    "DEFAULT_CAL",
    "DEFAULT_SPEED",
    "DEFAULT_NOISE_SEED",
    "interpolate_linear",
    "window_sonification_input",
    "folded_sonification_input",
    "sonify",
    "write_wav",
]

#: ``const sampleRate = 44100``.
SAMPLE_RATE = 44100

#: ``const durationSeconds = 60`` -- the rendered length, independent of how
#: long the observation is. Shorter data loops; longer data is windowed.
DURATION_SECONDS = 60.0

#: ``if (frequency < 4000)``. The upstream comment reads "Set to 4000 to
#: deprecate burst mode": the threshold was raised until burst mode always
#: wins. Waveform mode needs a pass shorter than 0.25 ms and is unreachable
#: from any real call; it is ported because it is upstream code.
BURST_MODE_MAX_FREQUENCY_HZ = 4000.0

#: ``PulsarPeriodFolding`` defaults, pulsar.service.util.ts:623-624.
DEFAULT_CAL = 1.0
DEFAULT_SPEED = 1.0

#: PORTED: upstream's carrier is ``Math.random()``. See the module docstring.
DEFAULT_NOISE_SEED = 0

#: The component's input window: ``if (duration > 60) ... x - start > 60``.
MAX_INPUT_SECONDS = 60.0

_PEAK = 0.95
_INT16_SCALE = 32767


@dataclass
class SonificationResult:
    """Rendered audio plus the intermediate values worth reporting."""

    pcm: np.ndarray
    """Interleaved ``int16`` samples, shape ``(frames * channels,)``."""

    sample_rate: int
    channels: int
    mode: str
    """``"burst"`` or ``"waveform"`` -- which upstream branch ran."""

    frames: int
    pass_seconds: float
    """Seconds for one pass through the data, after the ``speed`` divide."""

    interp_factor: int
    samples_per_point: int
    points_per_pass: int
    """Interpolated points in one pass -- ``points_per_pass * samples_per_point
    / sample_rate`` is how many seconds of audio one pass through the data
    occupies, which is not ``pass_seconds``. See ``pass_audio_seconds``."""
    data_min: float
    data_max: float
    peak_scale: float
    """``0.95 / max|audio|``, or 1.0 when the rendered audio is silent."""

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate

    @property
    def pass_audio_seconds(self) -> float:
        """Seconds of audio one pass through the data occupies.

        This is *not* ``pass_seconds``, and the gap between them is the reason
        a period measured off the audio will not match the pulsar's. Upstream
        advances one interpolated point per ``samples_per_point`` output
        samples and floors that count, so the rendered pass is quantized to a
        whole number of samples per point rather than fitted to the elapsed
        time -- which the synthesis never sees at all.
        """
        return self.points_per_pass * self.samples_per_point / self.sample_rate


def interpolate_linear(data: np.ndarray, factor: int) -> np.ndarray:
    """``interpolateLinear(data, factor)``, vectorized.

    Inserts ``factor`` linearly interpolated points between each adjacent
    pair, so the result has ``(n - 1) * (factor + 1) + 1`` points. The
    interpolation weights are ``j / (factor + 1)`` for ``j`` in
    ``1..factor``, computed in float64 exactly as upstream does, so the values
    match bit for bit.
    """
    data = np.asarray(data, dtype=np.float64)
    n = data.size
    if n == 0:
        return np.empty(0, dtype=np.float64)
    if n == 1:
        # Upstream's loop body never runs; it pushes data[n-1] and returns.
        return data.copy()

    factor = int(factor)
    if factor <= 0:
        # ceil() upstream cannot produce this, but a direct caller can.
        return data.copy()

    t = np.arange(1, factor + 1, dtype=np.float64) / (factor + 1)
    start = data[:-1]
    end = data[1:]
    # start * (1 - t) + end * t, term order preserved.
    block = start[:, None] * (1.0 - t)[None, :] + end[:, None] * t[None, :]

    result = np.empty((n - 1) * (factor + 1) + 1, dtype=np.float64)
    body = result[:-1].reshape(n - 1, factor + 1)
    body[:, 0] = start
    body[:, 1:] = block
    result[-1] = data[-1]
    return result


def window_sonification_input(
    time_s: np.ndarray,
    source1: np.ndarray,
    source2: Optional[np.ndarray] = None,
    max_seconds: float = MAX_INPUT_SECONDS,
) -> tuple[np.ndarray, np.ndarray, Optional[np.ndarray], float]:
    """``windowSonificationInput`` -- drop NaN rows, then keep the first 60 s.

    Returns ``(time_s, source1, source2, duration)``. ``duration`` is the span
    of what survived the window and is what upstream passes as the synthesis
    ``period``.
    """
    time_s = np.asarray(time_s, dtype=np.float64)
    source1 = np.asarray(source1, dtype=np.float64)

    good = ~(np.isnan(time_s) | np.isnan(source1))
    if source2 is not None:
        source2 = np.asarray(source2, dtype=np.float64)
        good &= ~np.isnan(source2)

    time_s = time_s[good]
    source1 = source1[good]
    if source2 is not None:
        source2 = source2[good]

    if time_s.size == 0:
        return time_s, source1, source2, 0.0

    start = time_s[0]
    duration = float(time_s[-1] - start)

    if duration > max_seconds:
        # findIndex(x => x - start > 60); -1 (no match) means keep everything.
        over = np.flatnonzero(time_s - start > max_seconds)
        end = int(over[0]) if over.size else time_s.size
        time_s = time_s[:end]
        source1 = source1[:end]
        if source2 is not None:
            source2 = source2[:end]
        duration = float(time_s[-1] - start) if time_s.size else 0.0

    return time_s, source1, source2, duration


def folded_sonification_input(
    profile,
) -> tuple[np.ndarray, Optional[np.ndarray], float]:
    """``foldedSonificationInput`` — stage 3's output, ready for the synthesis.

    Takes an :class:`algorithms.pulsar.folding.FoldedProfile` and returns
    ``(source1, source2, pass_seconds)`` for :func:`sonify`. ``pass_seconds``
    is the profile's **period**, so one pass is one rotation of the pulsar and
    the loop repeats it at the true rate.

    Upstream reads the binned profile straight off the folding chart and hands
    it to ``sonification()`` with ``getPeriodFoldingPeriod()``; the calibration
    is already applied by the folding stage, so ``sonify(cal=...)`` must be
    left at 1.0 here or it would be applied twice.
    """
    if profile.source1 is None or profile.source1.size == 0:
        raise ValueError("folded profile is empty; nothing to sonify")

    pass_seconds = profile.period_s
    if profile.display_period == 2:
        # The profile carries two cycles, so one pass through it is two
        # rotations. Without this the audio would play at half the true rate.
        pass_seconds = profile.period_s * 2

    return profile.source1, profile.source2, float(pass_seconds)


def sonify(
    source1: np.ndarray,
    source2: Optional[np.ndarray] = None,
    *,
    pass_seconds: float,
    speed: float = DEFAULT_SPEED,
    cal: float = DEFAULT_CAL,
    sample_rate: int = SAMPLE_RATE,
    output_seconds: float = DURATION_SECONDS,
    seed: Optional[int] = DEFAULT_NOISE_SEED,
) -> SonificationResult:
    """Render a light curve to interleaved 16-bit PCM.

    ``pass_seconds`` is upstream's ``period`` argument: seconds for one pass
    through ``source1``. The caller gets it from
    :func:`window_sonification_input`. ``speed`` divides it, so ``speed=2``
    plays the data twice as fast and therefore twice over in the same output.

    ``source2`` is the second polarization; supplying it makes the render
    stereo, with ``cal`` applied to that channel before normalization.

    ``seed`` seeds the noise carrier. ``None`` draws from fresh entropy, which
    is what upstream does -- pass it only when reproducibility does not matter.
    """
    source1 = np.asarray(source1, dtype=np.float64)
    if source1.size == 0:
        raise ValueError("no data to sonify")
    if pass_seconds <= 0:
        raise ValueError(f"pass_seconds must be positive, got {pass_seconds!r}")
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed!r}")
    if output_seconds <= 0:
        raise ValueError(f"output_seconds must be positive, got {output_seconds!r}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate!r}")

    channels = 2 if source2 is not None else 1

    # period *= 1 / speed
    period = pass_seconds * (1.0 / speed)

    # Calibration on a copy, so a repeated render cannot compound it.
    source2_cal = None
    if source2 is not None:
        source2_cal = np.asarray(source2, dtype=np.float64) * cal
        if source2_cal.size != source1.size:
            raise ValueError(
                "source1 and source2 must be the same length, got "
                f"{source1.size} and {source2_cal.size}"
            )

    # Global min/max across both channels, then normalize to [0, 1].
    all_values = (
        np.concatenate((source1, source2_cal)) if source2_cal is not None else source1
    )
    global_min = float(np.min(all_values))
    global_max = float(np.max(all_values))
    # `(globalMax - globalMin || 1)`: a flat light curve divides by 1, not 0.
    spread = (global_max - global_min) or 1.0

    norm1 = (source1 - global_min) / spread
    norm2 = (source2_cal - global_min) / spread if source2_cal is not None else None

    # Adaptive interpolation: enough points that one pass carries at least one
    # interpolated sample per output sample. `sampleRate / (1 / period)` is
    # written that way upstream; it is sampleRate * period.
    min_samples_per_cycle = max(64, math.floor(sample_rate / (1.0 / period)))
    interp_factor = math.ceil(min_samples_per_cycle / norm1.size)

    interp1 = interpolate_linear(norm1, interp_factor)
    interp2 = interpolate_linear(norm2, interp_factor) if norm2 is not None else None
    num_points = interp1.size

    total_samples = int(output_seconds * sample_rate)
    rng = np.random.default_rng(seed)

    frequency = 1.0 / period
    if frequency < BURST_MODE_MAX_FREQUENCY_HZ:
        mode = "burst"
        duration_per_point = period / num_points
        samples_per_point = max(1, math.floor(sample_rate * duration_per_point))

        i = np.arange(total_samples, dtype=np.int64)
        point_index = (i % (num_points * samples_per_point)) // samples_per_point
        index = np.minimum(point_index, num_points - 1)

        amp1 = interp1[index]
        # PORTED: Math.random() * 2 - 1, one independent draw per channel.
        audio1 = (rng.random(total_samples) * 2.0 - 1.0) * amp1
        if interp2 is not None:
            amp2 = interp2[index]
            audio2 = (rng.random(total_samples) * 2.0 - 1.0) * amp2
        else:
            audio2 = None
    else:
        mode = "waveform"
        samples_per_point = 1
        t = np.arange(total_samples, dtype=np.float64) / sample_rate
        phase = np.fmod(t, period) / period
        index = np.minimum(
            np.floor(phase * num_points).astype(np.int64), num_points - 1
        )
        audio1 = interp1[index] * 2.0 - 1.0
        audio2 = interp2[index] * 2.0 - 1.0 if interp2 is not None else None

    # Peak-normalize both channels together to 0.95.
    global_max_abs = float(np.max(np.abs(audio1)))
    if audio2 is not None:
        global_max_abs = max(global_max_abs, float(np.max(np.abs(audio2))))
    peak_scale = 1.0
    if global_max_abs > 0:
        peak_scale = _PEAK / global_max_abs
        audio1 = audio1 * peak_scale
        if audio2 is not None:
            audio2 = audio2 * peak_scale

    # Interleave as int16. Math.floor, not rounding -- upstream truncates
    # toward negative infinity, which biases every sample by up to one LSB.
    if audio2 is not None:
        pcm = np.empty(total_samples * 2, dtype=np.int16)
        pcm[0::2] = np.floor(audio1 * _INT16_SCALE).astype(np.int16)
        pcm[1::2] = np.floor(audio2 * _INT16_SCALE).astype(np.int16)
    else:
        pcm = np.floor(audio1 * _INT16_SCALE).astype(np.int16)

    return SonificationResult(
        pcm=pcm,
        sample_rate=int(sample_rate),
        channels=channels,
        mode=mode,
        frames=total_samples,
        pass_seconds=float(period),
        interp_factor=int(interp_factor),
        samples_per_point=int(samples_per_point),
        points_per_pass=int(num_points),
        data_min=global_min,
        data_max=global_max,
        peak_scale=float(peak_scale),
    )


def write_wav(path: str | Path, result: SonificationResult) -> Path:
    """Write ``result`` as a 16-bit PCM WAV file.

    Upstream hand-assembles the 44-byte RIFF header; :mod:`wave` writes the
    identical canonical header for 16-bit PCM, so the bytes match without
    carrying a hand-rolled encoder.
    """
    resolved = Path(path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(resolved), "wb") as handle:
        handle.setnchannels(result.channels)
        handle.setsampwidth(2)
        handle.setframerate(result.sample_rate)
        handle.writeframes(result.pcm.astype("<i2").tobytes())

    return resolved
