"""``tools.calibration.solve_zeropoint_from_measurements`` -- the tools-layer wrapper.

``algorithms.fieldcal.solution.calc_solution`` itself is pinned against real
recorded Skynet solves in ``test_fieldcal_solution.py``. This file covers the
thin wrapper around it: field normalization/aliasing, and the requirement
that the tool never raises -- it must return an ``errors``-populated
``ZeropointSolution`` even when the solver itself does (confirmed live:
``calc_solution`` can raise ``ValueError: math domain error`` on near-zero-
scatter input; see
``test_fieldcal_solution.py::test_zero_scatter_input_is_a_known_failure_mode``).
"""

from __future__ import annotations

from unittest.mock import patch

from tools.calibration import solve_zeropoint_from_measurements

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


def test_a_normal_solve_reports_a_zero_point_and_its_error():
    result = solve_zeropoint_from_measurements(MEASUREMENTS, CATALOG_SOURCES)

    assert not result.errors
    assert result.source_count == 5
    assert result.zero_point_corr is not None
    assert result.zero_point_error_mag is not None


def test_a_calc_solution_domain_error_returns_an_error_not_a_crash():
    with patch(
        "tools.calibration.calc_solution",
        side_effect=ValueError("math domain error"),
    ):
        result = solve_zeropoint_from_measurements(MEASUREMENTS, CATALOG_SOURCES)

    assert result.zero_point_corr is None
    assert result.source_count == 5
    assert any(e.code == "numerical_error" for e in result.errors)
