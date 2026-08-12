"""Chart specifications for the pulsar plots — what Astromancer draws.

PORTED from ``algorithms/lightcurve/pulsar/pulsar-charts.spec.ts``, itself
extracted from Astromancer's three Highcharts components and the
``PulsarChartInfo`` / ``PulsarPeriodogram`` / ``PulsarPeriodFolding`` defaults.

This module is **specification, not rendering**: series identity, axis
semantics, default labels and the folded axis extent. ``tools.pulsar`` turns
that into a PNG with matplotlib. Keeping them apart is what lets the spec stay
faithful to upstream while the renderer is free to be a renderer -- the same
split the extraction already made between chart maths and Highcharts calls.

What was deliberately NOT carried over is the widget plumbing: boost
thresholds, ``turboThreshold``, export buttons, tooltip format strings, and the
RxJS form subscriptions. A plot needs the spec, not the chart object.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "SeriesSpec",
    "ChartSpec",
    "LIGHT_CURVE_CHART",
    "PERIODOGRAM_CHART",
    "PERIODOGRAM_PEAK_SERIES",
    "CONFIDENCE_LINES",
    "FOLDED_CHART",
    "FOLDED_SINGLE_SOURCE_NAME",
    "folded_x_axis_maximum",
]


@dataclass(frozen=True)
class SeriesSpec:
    """One plotted series, as upstream declares it."""

    name: str
    column: str
    type: str = "line"
    visible: bool = True
    """``False`` where upstream adds the series with ``visible: false`` -- it
    is in the legend but hidden until clicked. Preserved because which series
    are *available* is chart meaning, not styling."""

    line_width: Optional[float] = None
    marker: Optional[str] = None
    marker_radius: Optional[float] = None
    color: Optional[str] = None
    dash_style: Optional[str] = None
    z_index: Optional[int] = None


@dataclass(frozen=True)
class ChartSpec:
    """One chart: default labels, axis semantics, and its series."""

    title: str
    x_axis_label: str
    y_axis_label: str
    x_axis_type: str = "linear"
    legend: bool = True
    series: tuple[SeriesSpec, ...] = field(default_factory=tuple)


#: ``PulsarChartInfo.getDefaultChartInfo()`` plus the component's series
#: literal. The label order matches Kepler's ingest: ``source1`` carries the
#: file's XX1 column and is labelled "Polarization XX", so the plot shows XX
#: where the file says XX. Both are transposed the same way -- see
#: ``algorithms/pulsar/ingest.py::CAL_COLUMNS``.
LIGHT_CURVE_CHART = ChartSpec(
    title="Title",
    x_axis_label="Time (s)",
    y_axis_label="Intensity",
    x_axis_type="linear",
    legend=True,
    series=(
        SeriesSpec("Polarization XX", "source1", line_width=0.1, marker=None),
        SeriesSpec("Polarization YY", "source2", line_width=0.1, marker=None),
    ),
)

#: ``PulsarPeriodogram.getDefaultPeriodogram()``. The **logarithmic** x axis is
#: load-bearing, not cosmetic: ``lomb_scargle`` evaluates a logarithmic period
#: grid in period mode, so a linear axis misrepresents where it actually
#: sampled.
PERIODOGRAM_CHART = ChartSpec(
    title="Title",
    x_axis_label="Period (s)",
    y_axis_label="Intensity",
    x_axis_type="logarithmic",
    legend=True,
    series=(
        SeriesSpec("Polarization XX", "power", marker="circle", marker_radius=3),
    ),
)

#: Upstream names the peak marker "Global Maxima" although ``find_global_max``
#: returns one point.
PERIODOGRAM_PEAK_SERIES = SeriesSpec(
    "Global Maxima", "peak", type="scatter", color="red", z_index=10
)

#: ``addConfidenceLines`` -- horizontal dashed lines at the false-alarm
#: thresholds. Colours and dash are the original literals.
#:
#: These assume white noise. A peak above the green line is not thereby a
#: pulsar; four of the five bundled scans clear it on interference. See
#: ``docs/extraction.md``, Pulsar Sonification §8.
CONFIDENCE_LINES = (
    SeriesSpec("67.3% Confidence", "conf-1-sigma", color="red", dash_style="ShortDash"),
    SeriesSpec("95.4% Confidence", "conf-2-sigma", color="orange", dash_style="ShortDash"),
    SeriesSpec("99.73% Confidence", "conf-3-sigma", color="green", dash_style="ShortDash"),
)

#: ``PulsarPeriodFolding`` defaults. Note the x axis is "Time (s)", not
#: "Phase": upstream plots seconds within one period.
FOLDED_CHART = ChartSpec(
    title="Title",
    x_axis_label="Time (s)",
    y_axis_label="Intensity",
    x_axis_type="linear",
    legend=True,
    series=(
        SeriesSpec("Polarization XX", "source1", marker=None),
        SeriesSpec("Polarization YY", "source2", marker=None),
        SeriesSpec("Difference", "difference", visible=False, marker=None),
        SeriesSpec("Sum", "sum", visible=False, marker=None),
    ),
)

#: A single-polarization file labels its one series "Data".
FOLDED_SINGLE_SOURCE_NAME = "Data"


def folded_x_axis_maximum(period: float, display_period: int = 1) -> float:
    """``updateXAxisScale()`` -- the folded plot's x extent. Axis starts at 0.

    Rounds the maximum **up** to the period plus a magnitude-matched ``delta``,
    but only when the period's fractional part is already smaller than that
    delta. So ``P = 0.7145`` is left alone (fraction 0.7145 exceeds delta 0.1)
    while ``P = 1.0001`` becomes 1.1 -- a near-integer period gets a padded
    axis instead of a hairline sliver at the right edge.

    ``parseInt(p.toString())`` truncates toward zero; for a positive period
    that is the integer part, reproduced here with ``math.floor``.
    """
    p = float(period)

    if p > 4.95:
        delta = 0.15
    elif p > 0.5:
        delta = 0.1
    elif p > 0.05:
        delta = 0.01
    elif p > 0.005:
        delta = 0.001
    elif p > 0.0005:
        delta = 0.0001
    elif p > 0.00005:
        delta = 0.00001
    else:
        delta = 0.000001

    truncated = math.floor(p) if p >= 0 else math.ceil(p)
    if p - truncated < delta:
        p = truncated + delta

    # PulsarDisplayPeriod.TWO
    if display_period == 2:
        p = p * 2

    return p
