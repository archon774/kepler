"""``tools.calibration.solve_zeropoint_from_measurements`` -- the tools-layer wrapper.

``algorithms.fieldcal.solution.calc_solution`` itself is pinned against real
recorded Skynet solves in ``test_fieldcal_solution.py``. This file covers the
thin wrapper around it: field normalization/aliasing, and the requirement
that the tool never raises -- it must return an ``errors``-populated
``ZeropointSolution`` even when the solver itself does (confirmed live:
``calc_solution`` can raise ``ValueError: math domain error`` on near-zero-
scatter input; see
``test_fieldcal_solution.py::test_zero_scatter_input_is_a_known_failure_mode``).

BL-5: the result field was named ``zero_point_corr`` while holding an
*absolute* zero point. Afterglow fixes ``zero_point = 20`` and reports a
correction; Kepler computes the absolute value. ``test_data/README.md`` warns
that confusing the two "lands 20 magnitudes off in a way that looks entirely
plausible", so the public name has to be unambiguous -- it is now
``zero_point``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.calibration import solve_zeropoint_from_measurements

ROOT = Path(__file__).resolve().parents[1]
SOLVE = ROOT / "test_data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002"

# Real scatter around a zero point near 2.1 (not an exact constant offset) --
# a constant offset reproduces the zero-scatter domain-error edge case this
# test is deliberately *not* about; see the dedicated test below for that.
MEASUREMENTS = [
    {"id": "s1", "mag": 15.0, "mag_error": 0.02},
    {"id": "s2", "mag": 14.5, "mag_error": 0.02},
    {"id": "s3", "mag": 16.2, "mag_error": 0.03},
    {"id": "s4", "mag": 13.8, "mag_error": 0.02},
    {"id": "s5", "mag": 17.0, "mag_error": 0.05},
]
CATALOG_SOURCES = [
    {"id": "s1", "ref_mag": 17.08, "ref_mag_error": 0.02},
    {"id": "s2", "ref_mag": 16.65, "ref_mag_error": 0.02},
    {"id": "s3", "ref_mag": 18.25, "ref_mag_error": 0.03},
    {"id": "s4", "ref_mag": 15.93, "ref_mag_error": 0.02},
    {"id": "s5", "ref_mag": 19.15, "ref_mag_error": 0.05},
]


def _float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calibration_rows() -> list[dict[str, float | None]]:
    with (SOLVE / "fit_data.csv").open() as handle:
        rows = [r for r in csv.DictReader(handle)
                if r["used_for_calibration"].strip().lower() in ("true", "1")]
    return [
        {
            "mag": _float(r["mag"]),
            "mag_error": _float(r["mag_error"]),
            "ref_mag": _float(r["ref_mag"]),
            "ref_mag_error": _float(r["ref_mag_error"]),
        }
        for r in rows
    ]


def test_a_normal_solve_reports_a_zero_point_and_its_error():
    result = solve_zeropoint_from_measurements(MEASUREMENTS, CATALOG_SOURCES)

    assert not result.errors
    assert result.source_count == 5
    assert result.zero_point is not None
    assert result.zero_point_error_mag is not None


def test_a_calc_solution_domain_error_returns_an_error_not_a_crash():
    with patch(
        "tools.calibration.calc_solution",
        side_effect=ValueError("math domain error"),
    ):
        result = solve_zeropoint_from_measurements(MEASUREMENTS, CATALOG_SOURCES)

    assert result.zero_point is None
    assert result.source_count == 5
    assert any(e.code == "numerical_error" for e in result.errors)


def test_result_reports_an_absolute_zero_point_under_an_unambiguous_name():
    solution = solve_zeropoint_from_measurements(_calibration_rows(), [])

    assert solution.source_count == 35
    assert solution.errors == []
    # The absolute zero point Skynet recorded, bit for bit.
    assert solution.zero_point == 21.147659857998637
    # The old name held this same absolute value and must not survive.
    assert not hasattr(solution, "zero_point_corr")


def test_the_absolute_zero_point_is_afterglows_base_plus_correction():
    """Afterglow reports 20.0 + correction; Kepler reports the sum directly."""
    summary = json.loads((SOLVE / "fit_summary.json").read_text())
    solution = solve_zeropoint_from_measurements(_calibration_rows(), [])

    assert summary["field_cal_zero_point_corr"] == pytest.approx(
        solution.zero_point - 20.0, abs=1e-12
    )
