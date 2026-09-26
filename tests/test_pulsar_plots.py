"""Pulsar chart rendering.

These do not check that a plot *looks* right — that is not a thing a test can
assert. They check the two things that are assertable and that matter:

1. **The chart spec matches Astromancer.** Axis labels, series names, the
   logarithmic periodogram axis, which series are hidden by default, and the
   folded x-axis ladder are all upstream's, and a "tidy-up" that renames a
   series or linearises an axis should fail here.
2. **The renderer honours the spec** and writes a real PNG.

The spec constants are the port's contract with
`git-history:algorithms/lightcurve/pulsar/pulsar-charts.spec.ts`; the line numbers behind
each value are in that file's comments.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from algorithms.pulsar import charts
from tests.conftest import PULSAR_PERIODS_S
from tools.pulsar import (
    compute_pulsar_periodogram,
    fold_pulsar_lightcurve,
    load_pulsar_lightcurve,
    plot_pulsar,
)


# ---------------------------------------------------------------------------
# The spec, against upstream
# ---------------------------------------------------------------------------

def test_default_labels_match_astromancer() -> None:
    """`PulsarChartInfo` / `PulsarPeriodogram` / `PulsarPeriodFolding` defaults."""
    assert charts.LIGHT_CURVE_CHART.x_axis_label == "Time (s)"
    assert charts.LIGHT_CURVE_CHART.y_axis_label == "Intensity"
    assert charts.PERIODOGRAM_CHART.x_axis_label == "Period (s)"
    assert charts.PERIODOGRAM_CHART.y_axis_label == "Intensity"
    # Upstream plots seconds within one period, so this is "Time (s)", NOT
    # "Phase" — changing it would misdescribe the axis.
    assert charts.FOLDED_CHART.x_axis_label == "Time (s)"
    assert charts.FOLDED_CHART.y_axis_label == "Intensity"


def test_periodogram_x_axis_is_logarithmic() -> None:
    """`xAxis: { type: 'logarithmic' }` — load-bearing, not cosmetic.

    `lomb_scargle` evaluates a logarithmic period grid in period mode, so a
    linear axis would misrepresent where it actually sampled.
    """
    assert charts.PERIODOGRAM_CHART.x_axis_type == "logarithmic"
    assert charts.LIGHT_CURVE_CHART.x_axis_type == "linear"
    assert charts.FOLDED_CHART.x_axis_type == "linear"


def test_series_names_match_astromancer() -> None:
    assert [s.name for s in charts.LIGHT_CURVE_CHART.series] == [
        "Polarization XX",
        "Polarization YY",
    ]
    assert [s.name for s in charts.FOLDED_CHART.series] == [
        "Polarization XX",
        "Polarization YY",
        "Difference",
        "Sum",
    ]
    assert charts.PERIODOGRAM_PEAK_SERIES.name == "Global Maxima"
    assert [line.name for line in charts.CONFIDENCE_LINES] == [
        "67.3% Confidence",
        "95.4% Confidence",
        "99.73% Confidence",
    ]
    assert [line.color for line in charts.CONFIDENCE_LINES] == ["red", "orange", "green"]
    assert charts.FOLDED_SINGLE_SOURCE_NAME == "Data"


def test_difference_and_sum_are_hidden_by_default() -> None:
    """PRESERVED: upstream adds both with `visible: false`.

    They are in the legend but off until the user clicks them. Which series are
    *available* is chart meaning, so they are carried rather than dropped — and
    they must not become visible by default.
    """
    by_name = {s.name: s for s in charts.FOLDED_CHART.series}
    assert by_name["Difference"].visible is False
    assert by_name["Sum"].visible is False
    assert by_name["Polarization XX"].visible is True
    assert by_name["Polarization YY"].visible is True


@pytest.mark.parametrize(
    "period, expected",
    [
        (0.7145, 0.7145),      # frac 0.7145 > delta 0.1 -> untouched
        (1.0001, 1.1),         # frac 0.0001 < delta 0.1 -> padded to 1 + 0.1
        (5.0, 5.15),           # p > 4.95 -> delta 0.15, frac 0 < 0.15
        (0.06, 0.06),          # delta 0.01, frac 0.06 > 0.01
        (0.0001, 0.0001),      # delta 1e-6 branch
    ],
)
def test_folded_axis_ladder_matches_updateXAxisScale(period, expected) -> None:
    """`updateXAxisScale`'s magnitude ladder, verbatim.

    Rounds the axis maximum up to period + a magnitude-matched delta, but only
    when the fractional part is already below that delta — so a near-integer
    period gets a padded axis instead of a hairline sliver at the right edge.
    """
    assert charts.folded_x_axis_maximum(period, 1) == pytest.approx(expected)


def test_folded_axis_doubles_for_two_period_display() -> None:
    """`if (displayPeriod === PulsarDisplayPeriod.TWO) p = p * 2`."""
    single = charts.folded_x_axis_maximum(0.7145, 1)
    double = charts.folded_x_axis_maximum(0.7145, 2)
    assert double == pytest.approx(single * 2)


# ---------------------------------------------------------------------------
# The renderer
# ---------------------------------------------------------------------------

def _png_size(path: Path) -> tuple[int, int]:
    """Width/height straight out of the IHDR chunk — proves it is a real PNG."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


@pytest.fixture
def staged(pulsar_path, artifact_dir):
    """The three artifacts a plot can be asked for."""
    lightcurve = load_pulsar_lightcurve(pulsar_path("b0329"))
    spectrum = compute_pulsar_periodogram(lightcurve.artifact.path)
    profile = fold_pulsar_lightcurve(
        lightcurve.artifact.path, PULSAR_PERIODS_S["b0329"]
    )
    return lightcurve, spectrum, profile


def test_kind_is_inferred_from_the_columns(staged) -> None:
    lightcurve, spectrum, profile = staged

    assert plot_pulsar(lightcurve.artifact.path).kind == "lightcurve"
    assert plot_pulsar(spectrum.artifact.path).kind == "periodogram"
    assert plot_pulsar(profile.artifact.path).kind == "folded"


def test_a_raw_scan_is_ingested_and_drawn_as_a_light_curve(
    pulsar_path, artifact_dir
) -> None:
    result = plot_pulsar(pulsar_path("b0329"))

    assert result.errors == []
    assert result.kind == "lightcurve"
    assert _png_size(Path(result.artifact.path))[0] > 100


def test_each_plot_writes_a_real_png_with_upstream_labels(staged, artifact_dir) -> None:
    lightcurve, spectrum, profile = staged
    expected = {
        "lightcurve": charts.LIGHT_CURVE_CHART,
        "periodogram": charts.PERIODOGRAM_CHART,
        "folded": charts.FOLDED_CHART,
    }

    for source in (lightcurve, spectrum, profile):
        result = plot_pulsar(source.artifact.path)
        assert result.errors == []

        spec = expected[result.kind]
        assert result.x_axis_label == spec.x_axis_label
        assert result.y_axis_label == spec.y_axis_label
        assert result.x_axis_type == spec.x_axis_type

        path = Path(result.artifact.path)
        assert path.is_absolute() and path.suffix == ".png"
        assert path.parent == artifact_dir / "pulsar"
        width, height = _png_size(path)
        assert width > 500 and height > 200


def test_periodogram_plot_draws_the_peak_and_confidence_lines(staged) -> None:
    """The plot that makes a bad period obvious.

    The peak marker and the three false-alarm lines come from the artifact's
    metadata, so the spectrum is not recomputed to draw them.
    """
    _, spectrum, _ = staged

    result = plot_pulsar(spectrum.artifact.path)

    assert "Global Maxima" in result.series
    for line in charts.CONFIDENCE_LINES:
        assert line.name in result.series


def test_folded_plot_hides_difference_and_sum_unless_asked(staged) -> None:
    _, _, profile = staged

    default = plot_pulsar(profile.artifact.path)
    shown = plot_pulsar(profile.artifact.path, show_hidden_series=True)

    assert default.hidden_series == ["Difference", "Sum"]
    assert "Difference" not in default.series
    assert {"Difference", "Sum"} <= set(shown.series)
    assert shown.hidden_series == []


def test_folded_plot_reports_the_period_it_drew(staged) -> None:
    _, _, profile = staged

    result = plot_pulsar(profile.artifact.path)

    assert result.period_s == pytest.approx(PULSAR_PERIODS_S["b0329"])


def test_labels_and_title_can_be_overridden(staged) -> None:
    lightcurve, _, _ = staged

    result = plot_pulsar(
        lightcurve.artifact.path, title="B0329+54", x_label="t", y_label="counts"
    )

    assert (result.title, result.x_axis_label, result.y_axis_label) == (
        "B0329+54",
        "t",
        "counts",
    )


def test_bad_inputs_come_back_as_errors(pulsar_path, artifact_dir, tmp_path) -> None:
    assert [e.code for e in plot_pulsar(tmp_path / "absent.ecsv").errors] == [
        "file_not_found"
    ]
    assert [e.code for e in plot_pulsar(pulsar_path("b0329"), kind="spectrogram").errors] == [
        "invalid_input"
    ]

    from astropy.table import Table

    unknown = tmp_path / "unknown.ecsv"
    Table({"a": np.arange(3), "b": np.arange(3)}).write(unknown, format="ascii.ecsv")
    assert [e.code for e in plot_pulsar(unknown).errors] == ["invalid_input"]


def test_registry_exposes_the_plot_tool() -> None:
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    assert TOOL_FUNCTIONS["plot_pulsar"] is plot_pulsar
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "plot_pulsar")
    assert schema["input_schema"]["required"] == ["path"]
