"""The recorded ground truth, reachable as a tool result.

BL-4: test_data/fieldcal/ and test_data/afterglow/ carry a complete
cross-implementation parity chain for NGC 5128 B, and before this module
nothing outside tests/ could read any of it.

The chain, all offline (test_data/README.md):

    Kepler calc_solution        21.147659857998637   (bit-exact)
    Skynet recorded local fit   21.147659857998637
    Afterglow API              (21.14747923526837)   = 20.0 + 1.1474792352683736
    Afterglow web table         21.147                (3 dp, recorded by hand)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fieldcal_reference import (
    compare_zeropoint_to_reference,
    list_zeropoint_references,
    load_zeropoint_reference,
    replay_catalog_sources,
    solve_zeropoint_from_reference,
)

#: The upstream diagnostic's own declared agreement threshold, in magnitudes.
PARITY_ZP_TOLERANCE = 0.0005

#: The number every step of the chain has to reproduce.
SKYNET_ZERO_POINT = 21.147659857998637
AFTERGLOW_ZERO_POINT = 21.14747923526837


def test_lists_the_four_recorded_solves():
    fields = {ref.field for ref in list_zeropoint_references()}
    assert fields == {"ngc5128_b_002", "ngc5286_b_000", "ngc5286_b_001", "ngc5286_b_002"}


def test_the_ngc5128_reference_carries_all_three_recorded_numbers():
    ref = load_zeropoint_reference("ngc5128_b_002")
    assert ref.catalog == "APASS"
    assert ref.num_calibration_sources == 35
    assert ref.skynet_zero_point == SKYNET_ZERO_POINT
    assert ref.afterglow_zero_point == pytest.approx(AFTERGLOW_ZERO_POINT, abs=1e-12)
    assert ref.afterglow_base == 20.0
    assert ref.web_table_zero_point == pytest.approx(21.147, abs=5e-4)
    assert ref.parity_tolerance_mag == PARITY_ZP_TOLERANCE


def test_the_afterglow_zero_point_is_base_plus_correction():
    """Kepler computes the absolute value; Afterglow reports 20.0 + a correction."""
    ref = load_zeropoint_reference("ngc5128_b_002")
    assert ref.afterglow_zero_point == pytest.approx(
        ref.afterglow_base + ref.afterglow_correction, abs=1e-12
    )


def test_the_reference_names_the_bundled_frame_it_describes():
    ref = load_zeropoint_reference("ngc5128_b_002")
    assert Path(ref.frame_path).name == "ngc5128_galaxy_b_001.fits"
    assert Path(ref.frame_path).is_file()


@pytest.mark.parametrize(
    "field",
    ["ngc5128_b_002", "ngc5286_b_000", "ngc5286_b_001", "ngc5286_b_002"],
)
def test_solving_from_the_recorded_rows_reproduces_the_recorded_solve(field):
    """PARITY: bit-exact against what Skynet returned for these exact rows."""
    reference = load_zeropoint_reference(field)
    solution = solve_zeropoint_from_reference(field)
    assert solution.errors == []
    assert solution.zero_point == reference.skynet_zero_point


def test_comparison_places_a_zero_point_against_both_implementations():
    comparison = compare_zeropoint_to_reference(SKYNET_ZERO_POINT, "ngc5128_b_002")
    assert comparison.delta_vs_skynet == 0.0
    assert abs(comparison.delta_vs_afterglow) == pytest.approx(1.806e-4, abs=1e-6)
    assert comparison.within_tolerance is True
    assert comparison.tolerance_mag == PARITY_ZP_TOLERANCE


def test_comparison_flags_a_zero_point_outside_the_recorded_tolerance():
    comparison = compare_zeropoint_to_reference(21.2, "ngc5128_b_002")
    assert comparison.within_tolerance is False
    assert comparison.delta_vs_skynet == pytest.approx(0.0523401, abs=1e-6)


def test_the_twenty_magnitude_trap_is_called_out_not_silently_compared():
    """Handing in Afterglow's bare correction must warn, not report a 20 mag error."""
    comparison = compare_zeropoint_to_reference(1.1474792352683736, "ngc5128_b_002")
    assert comparison.within_tolerance is False
    assert "afterglow_base_convention" in [w.code for w in comparison.warnings]


def test_an_unknown_field_returns_the_candidates_not_an_exception():
    reference = load_zeropoint_reference("ngc9999_z_000")
    assert [e.code for e in reference.errors] == ["not_found"]
    assert "ngc5128_b_002" in reference.errors[0].message


def test_a_missing_directory_returns_an_error_naming_the_env_override():
    reference = load_zeropoint_reference("ngc5128_b_002", "/nonexistent/fieldcal")
    assert [e.code for e in reference.errors] == ["directory_not_found"]
    assert "KEPLER_FIELDCAL_DATA_DIR" in reference.errors[0].message


def test_replay_returns_the_recorded_catalog_rows():
    sources = replay_catalog_sources("ngc5128_b_002")
    assert len(sources) == 35
    assert {s.catalog_name for s in sources} == {"APASS"}
    assert all(s.ra_hours is not None and s.dec_degs is not None for s in sources)


@pytest.mark.slow
def test_offline_field_calibration_lands_inside_the_afterglow_tolerance():
    """The full chain on a real frame with no network: extract, measure, match,
    resolve reference magnitudes, solve, compare.

    LIMITATION -- only the 35 *matched* APASS rows were recorded upstream, not
    the full cone-search response. This exercises photometry -> matching ->
    ref-mag resolution -> solve against real catalog values, but it cannot
    reproduce fit_summary.json's num_not_selected_by_field_cal (263): the rows
    that failed to match were never written down.
    """
    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    comparison = calibrate_zeropoint(
        frame.path,
        catalog_sources=replay_catalog_sources("ngc5128_b_002"),
        compare_to="ngc5128_b_002",
    )

    assert comparison.errors == []
    # A loose bound, deliberately: this re-measures photometry from pixels
    # rather than replaying the recorded instrumental magnitudes, so it will
    # not be bit-exact. test_solving_from_the_recorded_rows_reproduces_the_
    # recorded_solve is the bit-exact check.
    assert abs(comparison.delta_vs_afterglow) < 0.1


def test_calibrate_zeropoint_does_not_reach_the_network_when_rows_are_supplied(monkeypatch):
    """A supplied catalog must short-circuit query_catalogs entirely."""
    import algorithms.fieldcal.deps as deps

    def explode(*args, **kwargs):
        raise AssertionError("calibrate_zeropoint queried the network")

    monkeypatch.setattr(deps, "query_catalogs", explode)

    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    comparison = calibrate_zeropoint(
        frame.path,
        catalog_sources=replay_catalog_sources("ngc5128_b_002"),
        compare_to="ngc5128_b_002",
    )
    assert comparison.zero_point is not None


def test_the_bundled_ocl_frames_join_back_to_the_recorded_sweep():
    """BL-6: the rename lost the join key; frame_provenance.json restores it."""
    from tools.fieldcal_reference import load_ocl_reference

    lum = load_ocl_reference("m15_globular_lum_000")
    assert lum["input_file"] == "messier 15_14111493_Lum_005.fits"
    assert lum["best_filter"] == "V"
    assert lum["winning_trial"]["metrics"]["zero_point"] == pytest.approx(
        20.141497332382436, abs=1e-12
    )

    openf = load_ocl_reference("m15_globular_open_000")
    assert openf["input_file"] == "messier 15_14111493_Open_000.fits"
    assert openf["best_filter"] is None
    # Corroborates the mapping independently: this is the one bundled frame
    # with no WCS keywords, and every trial failed for exactly that reason.
    assert all(
        t["pipeline"]["wcs"]["failure_reason"] == "no WCS solution found in FITS header"
        for t in openf["trials"]
    )
