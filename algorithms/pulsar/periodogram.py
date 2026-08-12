"""Lomb-Scargle periodogram for pulsar light curves — stage 2 of the pipeline.

PORTED from the Kepler TypeScript extraction:

* ``algorithms/periodogram/core/lomb-scargle.ts`` — ``lombScargle`` and the
  ``ArrMath`` helpers it computes through (astromancer
  ``shared/data/utils.ts``).
* ``algorithms/periodogram/core/peak-detection.ts`` — ``findLocalMax``,
  ``confidenceThreshold``, ``CONFIDENCE_LEVELS``.
* ``algorithms/periodogram/pulsar/pulsar-periodogram-range.ts`` —
  ``nyquistPeriodogramRange``.

The pulsar tool uses the **unweighted** ``lombScargle``; pulsar rows carry no
per-point error, which is why ``lombScargleWithError`` is not ported.

This is the stage that produces a period. Everything downstream — folding, and
the folded sonification — needs one, so nothing downstream can run until this
does. See ``docs/pulsar-tool-pipeline.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

__all__ = [
    "Periodogram",
    "CONFIDENCE_LEVELS",
    "DEFAULT_STEPS",
    "lomb_scargle",
    "find_global_max",
    "confidence_threshold",
    "nyquist_periodogram_range",
]

#: ``PulsarPeriodogram.points`` default — the periodogram grid step count.
DEFAULT_STEPS = 1000

#: Verbatim from ``peak-detection.ts``. ``color`` is a rendering concern and is
#: carried because it is part of the original literal.
CONFIDENCE_LEVELS: tuple[dict, ...] = (
    {"id": "conf-1-sigma", "name": "67.3% Confidence", "alpha": 1 - 0.673, "color": "red"},
    {"id": "conf-2-sigma", "name": "95.4% Confidence", "alpha": 1 - 0.954, "color": "orange"},
    {"id": "conf-3-sigma", "name": "99.73% Confidence", "alpha": 1 - 0.9973, "color": "green"},
)


@dataclass
class Periodogram:
    """A computed spectrum plus the peak the folding stage consumes."""

    x: np.ndarray
    """Period (seconds) in period mode, frequency (Hz) in frequency mode."""

    power: np.ndarray
    """Normalized Lomb-Scargle spectral power."""

    freq_mode: bool
    start: float
    stop: float
    steps: int

    peak_x: Optional[float] = None
    peak_power: Optional[float] = None

    confidence: dict[str, float] = field(default_factory=dict)
    """False-alarm thresholds by level id, from :func:`confidence_threshold`."""

    @property
    def peak_period_s(self) -> Optional[float]:
        """The peak as a period in seconds, whichever mode was computed."""
        if self.peak_x is None or self.peak_x == 0:
            return None
        return 1.0 / self.peak_x if self.freq_mode else float(self.peak_x)

    @property
    def peak_confidence_level(self) -> Optional[str]:
        """Highest confidence level the peak clears, or ``None``."""
        if self.peak_power is None:
            return None
        best = None
        for level in CONFIDENCE_LEVELS:
            if self.peak_power >= self.confidence.get(level["id"], math.inf):
                best = level["name"]
        return best


def lomb_scargle(
    ts: np.ndarray,
    ys: np.ndarray,
    start: float,
    stop: float,
    steps: int = DEFAULT_STEPS,
    freq_mode: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """``lombScargle(ts, ys, start, stop, steps, freqMode)``.

    Returns ``(x, power)``. In period mode ``x`` is period in seconds; in
    frequency mode it is frequency in Hz.

    Two upstream behaviours are reproduced rather than cleaned up, because they
    decide which trial periods are actually evaluated:

    * **Period mode evaluates a logarithmic grid driven by a linear loop.**
      The loop variable steps linearly from ``start`` to ``stop`` and is
      discarded; the evaluated point is
      ``exp(log(start) + (log(stop) - log(start)) * i / steps)``. So the loop
      only supplies the iteration count. Frequency mode overwrites both with
      the linear loop variable and really is linear.
    * **The grid never reaches ``stop``.** The exponent is ``i / steps`` with
      ``i`` ending at ``steps - 1``, so the last evaluated point falls one step
      short of the upper bound.

    The power is the standard normalized Lomb-Scargle periodogram; upstream
    reaches it through ``ArrMath.dot(v)``, which is ``dot(v, v)``.
    """
    ts = np.asarray(ts, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if ts.size != ys.size:
        # Upstream calls alert() and returns []; a library cannot do that.
        raise ValueError(
            f"Dimension mismatch between time array and value array: "
            f"{ts.size} != {ys.size}"
        )
    if ts.size == 0:
        return np.empty(0), np.empty(0)
    if start <= 0 or stop <= 0:
        raise ValueError(
            f"start and stop must be positive (the grid is logarithmic in "
            f"period mode), got start={start!r}, stop={stop!r}"
        )
    if stop <= start:
        raise ValueError(f"stop must exceed start, got {start!r} -> {stop!r}")
    if steps <= 0:
        raise ValueError(f"steps must be positive, got {steps!r}")

    step = (stop - start) / steps

    h_residue = ys - ys.mean()
    # ArrMath.var is the population variance (divides by N).
    two_var_of_y = 2 * float(np.var(ys))

    log_start = math.log(start)
    log_stop = math.log(stop)

    xs: list[float] = []
    powers: list[float] = []

    # Reproduce upstream's float accumulation: `for (xVal = start;
    # xVal < stop; xVal += step)`. Accumulating is not the same as
    # start + i * step, and it decides the final iteration count.
    x_val = start
    i = 0
    while x_val < stop:
        log_x_val = math.exp(log_start + (log_stop - log_start) * i / steps)
        frequency = log_x_val if freq_mode else 1.0 / log_x_val
        if freq_mode:
            frequency = x_val
            log_x_val = x_val

        omega = 2.0 * math.pi * frequency
        two_omega_t = 2 * omega * ts
        tau = math.atan2(
            float(np.sum(np.sin(two_omega_t))),
            float(np.sum(np.cos(two_omega_t))),
        ) / (2.0 * omega)
        omega_t_minus_tau = omega * (ts - tau)

        cos_term = np.cos(omega_t_minus_tau)
        sin_term = np.sin(omega_t_minus_tau)

        power = (
            float(np.dot(h_residue, cos_term)) ** 2.0 / float(np.dot(cos_term, cos_term))
            + float(np.dot(h_residue, sin_term)) ** 2.0 / float(np.dot(sin_term, sin_term))
        ) / two_var_of_y

        xs.append(log_x_val)
        powers.append(power)

        x_val += step
        i += 1

    return np.asarray(xs, dtype=np.float64), np.asarray(powers, dtype=np.float64)


def find_global_max(x: np.ndarray, power: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    """``findLocalMax(points)`` — despite the name, the **global** maximum.

    Upstream returns it as a single-element array and labels the resulting
    chart series "Global Maxima"; the name is original. Its x value is the
    peak period that the period-folding tab consumes, which makes this the
    handoff between stage 2 and stage 3.
    """
    if x.size == 0:
        return None, None
    # `points[i][1] > globalMax[1]` — strictly greater, so ties keep the
    # earliest, which in period mode is the shortest period.
    index = int(np.argmax(power))
    return float(x[index]), float(power[index])


def confidence_threshold(alpha: float, points: int) -> float:
    """``-Math.log(1 - (1 - alpha) ** (1 / points))``, verbatim.

    Spectral-power threshold a peak must clear to beat the false-alarm
    probability ``alpha`` over ``points`` independent trial frequencies.
    """
    return -math.log(1 - (1 - alpha) ** (1 / points))


def nyquist_periodogram_range(
    ts: np.ndarray, freq_mode: bool = False
) -> Optional[dict[str, float]]:
    """``nyquistPeriodogramRange(ts, method)`` — the default search bounds.

    Returns ``None`` for fewer than two samples rather than emitting garbage,
    as upstream does. Keys are upstream's: ``startPeriod``, ``endPeriod``,
    ``periodFoldingPeriodMin``, ``periodFoldingPeriodMax``.

    Note ``avgDiff`` is **twice** the mean sample interval — upstream's
    Nyquist limit, the shortest period the data can resolve — and is rounded
    to 5 decimals, which is a real quantization of the lower bound.
    """
    ts = np.asarray(ts, dtype=np.float64)
    if ts.size < 2:
        return None

    total_diff = float(np.sum(np.diff(ts)))
    avg_diff = round(total_diff / (ts.size - 1) * 2 * 100000) / 100000

    if freq_mode:
        start_period = 0.1
        end_period = round((1 / avg_diff) * 100000) / 100000
    else:
        start_period = avg_diff
        end_period = 3.0

    return {
        "startPeriod": start_period,
        "endPeriod": end_period,
        "periodFoldingPeriodMin": avg_diff,
        "periodFoldingPeriodMax": 3.0,
    }


def compute_periodogram(
    ts: np.ndarray,
    ys: np.ndarray,
    *,
    start: Optional[float] = None,
    stop: Optional[float] = None,
    steps: int = DEFAULT_STEPS,
    freq_mode: bool = False,
) -> Periodogram:
    """Run the spectrum, locate the peak, and attach confidence thresholds.

    ``start``/``stop`` default to :func:`nyquist_periodogram_range` for the
    given mode — the same defaults the astromancer form seeds from the file.
    """
    ts = np.asarray(ts, dtype=np.float64)
    if start is None or stop is None:
        bounds = nyquist_periodogram_range(ts, freq_mode)
        if bounds is None:
            raise ValueError("need at least two samples to choose search bounds")
        start = bounds["startPeriod"] if start is None else start
        stop = bounds["endPeriod"] if stop is None else stop

    x, power = lomb_scargle(ts, ys, start, stop, steps, freq_mode)
    peak_x, peak_power = find_global_max(x, power)

    return Periodogram(
        x=x,
        power=power,
        freq_mode=freq_mode,
        start=float(start),
        stop=float(stop),
        steps=int(steps),
        peak_x=peak_x,
        peak_power=peak_power,
        confidence={
            level["id"]: confidence_threshold(level["alpha"], steps)
            for level in CONFIDENCE_LEVELS
        },
    )
