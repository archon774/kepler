"""Period folding and phase binning — stage 3 of the pipeline.

PORTED from Kepler's retired TypeScript extraction:

* ``git-history:algorithms/lightcurve/pulsar/pulsar-lightcurve.algorithms.ts`` —
  ``getPeriodFoldingChartData`` (astromancer ``pulsar.service.ts`` 273-314)
  and ``binData`` (850-886).
* ``git-history:algorithms/lightcurve/pulsar/pulsar-period-folding.algorithms.ts`` —
  ``foldAndBin``, ``duplicateIfNeeded``, ``differenceAndSum``,
  ``applyCalibration``.
* ``git-history:algorithms/lightcurve/shared/numeric-utils.ts`` — ``floatMod``.

The ordering upstream chose is load-bearing and is preserved: the light curve
is folded into phase, then **binned**, then phase-shifted, then optionally
duplicated across two periods. ``binData`` deliberately does no phase shifting
of its own because ``foldAndBin`` applies it afterwards.

This stage turns a period into a profile. Its output is what the folded
sonification renders, which is why it sits between the periodogram and the
sonifier. See ``docs/pulsar-tool-pipeline.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

__all__ = [
    "FoldedProfile",
    "DEFAULT_BINS",
    "DEFAULT_PHASE",
    "DEFAULT_DISPLAY_PERIOD",
    "float_mod",
    "fold_to_phase",
    "bin_data",
    "fold_and_bin",
    "duplicate_if_needed",
    "apply_calibration",
    "difference_and_sum",
    "fold_lightcurve",
]

#: ``PulsarPeriodFolding`` defaults (``pulsar.service.util.ts`` 623-624 and the
#: period-folding form): 100 bins per period, no phase shift, one period shown.
DEFAULT_BINS = 100
DEFAULT_PHASE = 0.0
DEFAULT_DISPLAY_PERIOD = 1


@dataclass
class FoldedProfile:
    """A folded, binned pulse profile."""

    phase_s: np.ndarray
    """Bin centre, in seconds within the period (upstream's x axis)."""

    source1: np.ndarray
    source2: Optional[np.ndarray] = None
    difference: Optional[np.ndarray] = None
    sum: Optional[np.ndarray] = None

    period_s: float = 0.0
    bins: int = DEFAULT_BINS
    phase: float = DEFAULT_PHASE
    display_period: int = DEFAULT_DISPLAY_PERIOD
    cal: float = 1.0
    samples_folded: int = 0

    @property
    def bin_count(self) -> int:
        return int(self.phase_s.size)

    def pulse_snr(self) -> Optional[float]:
        """Peak significance of the profile against its own off-pulse scatter.

        Not upstream — astromancer shows the profile and lets the eye judge it.
        A tool has no eye, so it needs a number to report, and a caller
        deciding whether a candidate period is real needs it more than a plot.
        Median-absolute-deviation based, so a narrow pulse does not inflate the
        noise estimate it is measured against.
        """
        values = self.sum if self.sum is not None else self.source1
        if values is None or values.size < 4:
            return None
        off = float(np.median(values))
        peak = float(np.max(values))
        if peak == off:
            return None  # genuinely flat: no pulse at this period

        scatter = float(np.median(np.abs(values - off))) * 1.4826
        if scatter <= 0:
            # Every off-pulse bin sits at exactly the median, which happens on
            # noiseless synthetic input and on a profile so sparse that most
            # bins share a value. The MAD is degenerate there but the pulse is
            # real, so fall back to the standard deviation rather than
            # reporting None for what is the cleanest possible detection.
            scatter = float(np.std(values))
        if scatter <= 0:
            return None
        return (peak - off) / scatter


def float_mod(a: np.ndarray, b: float) -> np.ndarray:
    """``floatMod(a, b)`` — repeated subtraction, **not** ``fmod``.

    Upstream is ``while (a > b) a -= b``. Two consequences preserved here:

    * the result lands in ``(0, b]``, not ``[0, b)`` — the loop stops at
      ``a <= b``, so an exact multiple returns ``b`` rather than 0;
    * repeated subtraction accumulates float error differently from a single
      ``fmod``, and with a 56 s baseline over a 0.7 s period that is ~80
      subtractions per sample.

    Vectorized by subtracting from every element still above ``b`` at once,
    which performs the identical sequence of float64 subtractions per element.
    A value already ``<= b`` (including a negative one) is returned untouched,
    exactly as upstream leaves it.
    """
    result = np.array(a, dtype=np.float64, copy=True)
    if b <= 0:
        return result
    while True:
        mask = result > b
        if not mask.any():
            return result
        result[mask] -= b


def fold_to_phase(
    time_s: np.ndarray,
    source1: np.ndarray,
    source2: Optional[np.ndarray],
    period_s: float,
) -> tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """``getPeriodFoldingChartData()`` — map the time axis into one period.

    Returns ``(phase_s, source1, source2)`` with rows ordered as upstream
    leaves them (descending in phase; the sort is upstream's and only matters
    to plotting, since binning is order-independent).

    Note this does **not** apply the phase shift and does not duplicate for a
    two-period display — the pulsar tool does both after binning, unlike its
    variable-star sibling.
    """
    time_s = np.asarray(time_s, dtype=np.float64)
    source1 = np.asarray(source1, dtype=np.float64)

    if time_s.size == 0:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty, (empty if source2 is not None else None)

    # `.sort((a, b) => a[0] - b[0])` — ascending in time before folding.
    order = np.argsort(time_s, kind="stable")
    time_s = time_s[order]
    source1 = source1[order]
    if source2 is not None:
        source2 = np.asarray(source2, dtype=np.float64)[order]

    if period_s == 0 or period_s is None:
        # Upstream produces empty series in this case rather than dividing.
        empty = np.empty(0, dtype=np.float64)
        return empty, empty, (empty if source2 is not None else None)

    min_jd = time_s[0]

    temp_x = period_s + float_mod(time_s - min_jd, period_s)
    # `if (temp_x > period) temp_x -= period`
    over = temp_x > period_s
    temp_x[over] -= period_s

    # `.sort((a, b) => b[0] - a[0])` — descending, upstream's plotting order.
    order = np.argsort(-temp_x, kind="stable")
    return temp_x[order], source1[order], (source2[order] if source2 is not None else None)


def bin_data(x: np.ndarray, y: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    """``binData(data, bins)`` — fixed-width binning with bin averaging.

    Empty bins are dropped, so the result can be shorter than ``bins``.

    PRESERVED: the bin index is ``floor((x - xMin) / binSize)`` guarded by
    ``binIndex < bins``, so the single point at ``x == xMax`` computes an index
    of exactly ``bins`` and is **discarded**. Upstream does the same; the lost
    point is one sample out of thousands.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.size == 0:
        return np.empty(0), np.empty(0)
    if bins <= 0:
        raise ValueError(f"bins must be positive, got {bins!r}")

    x_min = float(np.min(x))
    x_max = float(np.max(x))
    bin_size = (x_max - x_min) / bins

    centres = x_min + np.arange(bins, dtype=np.float64) * bin_size + bin_size / 2

    if bin_size == 0:
        # Degenerate: every point at one x. Upstream divides by zero here and
        # every index becomes NaN -> the guard drops them all, yielding [].
        return np.empty(0), np.empty(0)

    index = np.floor((x - x_min) / bin_size).astype(np.int64)
    keep = (index >= 0) & (index < bins)
    index = index[keep]

    y_sum = np.bincount(index, weights=y[keep], minlength=bins)
    count = np.bincount(index, minlength=bins)

    non_empty = count > 0
    return centres[non_empty], y_sum[non_empty] / count[non_empty]


def fold_and_bin(
    x: np.ndarray,
    y: np.ndarray,
    bins_per_period: int,
    period: float,
    phase: float,
) -> tuple[np.ndarray, np.ndarray]:
    """``foldAndBin(points, binsPerPeriod, period, phase, binData)``.

    Bins **first**, then applies the phase shift and wraps into ``[0, period)``
    with ``((shifted % period) + period) % period``, then sorts ascending.
    That ordering is upstream's and is why :func:`bin_data` does no shifting.
    """
    centres, values = bin_data(x, y, bins_per_period)
    if centres.size == 0:
        return centres, values

    shifted = centres + (phase * period)
    wrapped = np.mod(np.mod(shifted, period) + period, period)

    order = np.argsort(wrapped, kind="stable")
    return wrapped[order], values[order]


def duplicate_if_needed(
    x: np.ndarray, y: np.ndarray, display_period: int, period: float
) -> tuple[np.ndarray, np.ndarray]:
    """``duplicateIfNeeded(arr, displayPeriod, period)``.

    ``displayPeriod == 2`` appends a copy shifted by one period, so the plot
    (and a render built from it) shows two cycles. Any other value is a no-op.
    """
    if display_period != 2:
        return x, y
    return np.concatenate([x, x + period]), np.concatenate([y, y])


def apply_calibration(y: np.ndarray, calibration: float) -> np.ndarray:
    """``applyCalibration(data2, calibration)`` — gain on the 2nd polarization."""
    return np.asarray(y, dtype=np.float64) * calibration


def difference_and_sum(
    y1: np.ndarray, y2: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """``differenceAndSum(finalData1, finalData2)``, pairwise over ``min`` length.

    Upstream pairs by **index**, not by matching x, and re-sorts both outputs
    by x afterwards. Since both inputs arrive already sorted by x from
    ``foldAndBin``, index pairing and x pairing agree — but only because empty
    bins were dropped identically in both channels, which holds when both
    polarizations are sampled together, as they are in a cal file.
    """
    y1 = np.asarray(y1, dtype=np.float64)
    y2 = np.asarray(y2, dtype=np.float64)
    n = min(y1.size, y2.size)
    return y1[:n] - y2[:n], y1[:n] + y2[:n]


def fold_lightcurve(
    time_s: np.ndarray,
    source1: np.ndarray,
    source2: Optional[np.ndarray] = None,
    *,
    period_s: float,
    bins: int = DEFAULT_BINS,
    phase: float = DEFAULT_PHASE,
    display_period: int = DEFAULT_DISPLAY_PERIOD,
    cal: float = 1.0,
) -> FoldedProfile:
    """Run the whole stage-3 chain in upstream's order.

    fold to phase -> calibrate channel 2 -> bin -> phase-shift -> duplicate,
    then derive the difference and sum series.
    """
    if period_s <= 0:
        raise ValueError(f"period_s must be positive, got {period_s!r}")
    if not math.isfinite(period_s):
        raise ValueError(f"period_s must be finite, got {period_s!r}")

    phase_x, folded1, folded2 = fold_to_phase(time_s, source1, source2, period_s)
    samples_folded = int(phase_x.size)

    if folded2 is not None:
        folded2 = apply_calibration(folded2, cal)

    x1, y1 = fold_and_bin(phase_x, folded1, bins, period_s, phase)
    x1, y1 = duplicate_if_needed(x1, y1, display_period, period_s)

    y2 = None
    diff = None
    total = None
    if folded2 is not None:
        x2, y2 = fold_and_bin(phase_x, folded2, bins, period_s, phase)
        _, y2 = duplicate_if_needed(x2, y2, display_period, period_s)
        diff, total = difference_and_sum(y1, y2)

    return FoldedProfile(
        phase_s=x1,
        source1=y1,
        source2=y2,
        difference=diff,
        sum=total,
        period_s=float(period_s),
        bins=int(bins),
        phase=float(phase),
        display_period=int(display_period),
        cal=float(cal),
        samples_folded=samples_folded,
    )
