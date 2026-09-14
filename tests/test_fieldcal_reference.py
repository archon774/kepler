"""The recorded ground truth, reachable as a tool result.

BL-4: data/fieldcal/ and data/afterglow/ carry a complete
cross-implementation parity chain for NGC 5128 B, and before this module
nothing outside tests/ could read any of it.

The chain, all offline (data/README.md):

    Kepler calc_solution        21.147659857998637   (bit-exact)
    Skynet recorded local fit   21.147659857998637
    Afterglow API              (21.14747923526837)   = 20.0 + 1.1474792352683736
    Afterglow web table         21.147                (3 dp, recorded by hand)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fieldcal_reference import (
    CATALOG_FIXTURES,
    compare_zeropoint_to_reference,
    list_zeropoint_references,
    load_catalog_response,
    load_zeropoint_reference,
    replay_catalog_sources,
    replay_field_calibration,
    replay_variable_sources,
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


def test_the_selected_row_fixture_is_the_default_and_is_named():
    """The two replay inputs are chosen explicitly; the default is the small one."""
    assert CATALOG_FIXTURES == ("selected_rows", "full_response")
    by_default = replay_catalog_sources("ngc5128_b_002")
    named = replay_catalog_sources("ngc5128_b_002", fixture="selected_rows")
    assert [s.ref_mag for s in by_default] == [s.ref_mag for s in named]


def test_an_unknown_fixture_name_is_a_caller_error():
    with pytest.raises(ValueError, match="selected_rows"):
        replay_catalog_sources("ngc5128_b_002", fixture="everything")


# ---------------------------------------------------------------------------
# P7: the full APASS response and the end-to-end selection replay
# ---------------------------------------------------------------------------

#: fit_summary.json's own selection statistics for the recorded run. 304 rows
#: were photometered; 6 had no valid magnitude; 35 matched APASS; 263 did not.
RECORDED_NUM_MATCHED = 35
RECORDED_NUM_NOT_SELECTED = 263

#: The recorded 10-arcmin cone holds 132 APASS rows and 12 VSX rows; the live
#: path clips a response to the detector before the solve sees it, and on
#: this frame that keeps 45 and 5. The selection is identical either way --
#: the replay clips because the live path does, not because it has to.
CONE_APASS_ROWS, FRAME_APASS_ROWS = 132, 45
CONE_VSX_ROWS, FRAME_VSX_ROWS = 12, 5

#: The extracted VizieR mapping (``algorithms/query/vizier.py``) stores each
#: band's uncertainty as the ``np.float32`` astroquery handed it, and pydantic
#: warns every time such a source is ``model_dump()``-ed -- which
#: ``perform_field_calibration`` does for every candidate. The live path
#: behaves identically, and the resolved ``ref_mag_error`` is a Python float,
#: bit-exact (asserted below). Silenced on the replays that go through that
#: mapping so a real failure is not buried under 130 lines of it.
float32_mag_errors = pytest.mark.filterwarnings(
    "ignore:Pydantic serializer warnings:UserWarning"
)


def test_the_recorded_apass_response_documents_its_provenance():
    """Checkbox 1: query coordinates, radius, release, retrieval date, columns,
    licence. The fixture is only as trustworthy as this record."""
    response = load_catalog_response("ngc5128_b_002")
    assert response.errors == []
    assert response.catalog == "APASS"
    assert response.vizier_table == "II/336/apass9"
    assert response.row_count == 132

    query = response.query
    assert query["shape"] == "cone"
    assert query["radius_arcmin"] == 10.0
    assert query["ra_hours"] == pytest.approx(13.42413224816283, abs=1e-12)
    assert query["dec_degs"] == pytest.approx(-43.018409934383605, abs=1e-12)

    provenance = response.provenance
    assert provenance["retrieved_utc"].startswith("2026-09-13T")
    assert "DR9" in provenance["catalog_release"]
    assert "APASS" in provenance["licence"] and "VizieR" in provenance["licence"]
    assert provenance["truncated"] is False
    assert response.columns == [
        "RAJ2000", "DEJ2000", "Bmag", "e_Bmag", "Vmag", "e_Vmag",
        "g'mag", "e_g'mag", "r'mag", "e_r'mag", "i'mag", "e_i'mag",
    ]


def test_the_recorded_vsx_response_is_documented_too():
    response = load_catalog_response("ngc5128_b_002", catalog="VSX")
    assert response.errors == []
    assert response.row_count == 12
    assert response.query["radius_arcmin"] == 10.0
    assert "variable_check_tol" in response.provenance["why_recorded"]


def test_a_field_without_a_recorded_response_says_so():
    response = load_catalog_response("ngc5286_b_000")
    assert [e.code for e in response.errors] == ["fixture_missing"]
    assert "apass_response.json" in response.errors[0].message


@float32_mag_errors
def test_full_response_replay_normalizes_the_whole_recorded_cone():
    """The 132 rows go through the real VizieR column mapping, so this is the
    candidate list the live path would have handed perform_field_calibration."""
    sources = replay_catalog_sources("ngc5128_b_002", fixture="full_response")
    assert len(sources) == 132
    assert {s.catalog_name for s in sources} == {"APASS"}
    # recno was requested but not returned, exactly as live: no ids.
    assert all(s.id is None for s in sources)
    assert all(s.ra_hours is not None and s.dec_degs is not None for s in sources)
    # Six rows have no B magnitude; every row has at least one band.
    assert sum("B" in s.mags for s in sources) == 126
    assert all(s.mags for s in sources)
    # float32 in the response, reproduced exactly: 10.097 as a float32.
    assert sources[0].mags["B"].value == 10.097000122070312


def test_full_response_replay_is_empty_where_nothing_was_recorded():
    assert replay_catalog_sources("ngc5286_b_000", fixture="full_response") == []
    assert replay_variable_sources("ngc5286_b_000") == []


@float32_mag_errors
def test_replay_variable_sources_returns_the_recorded_vsx_rows():
    variables = replay_variable_sources("ngc5128_b_002")
    assert len(variables) == 12
    assert {v.catalog_name for v in variables} == {"VSX"}
    assert all(v.ra_hours is not None and v.dec_degs is not None for v in variables)


def _recorded_used_rows() -> list[dict]:
    import csv

    path = Path(__file__).resolve().parent.parent / "data" / "fieldcal" / "zp_solutions"
    with (path / "ngc5128_b_002" / "fit_data.csv").open(newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["used_for_calibration"] == "True"]


@float32_mag_errors
def test_the_selection_replay_reproduces_the_recorded_run():
    """The end-to-end selection replay -- checkbox 3.

    Recorded Afterglow detections + the full APASS cone + the VSX rows, through
    perform_field_calibration exactly as upstream's diagnostic drove it. Unlike
    the selected-row replay, the 35 are *chosen* here from 132 candidates.
    """
    replay = replay_field_calibration("ngc5128_b_002")
    assert replay.errors == []
    assert replay.fixture == "full_response"
    assert Path(replay.frame_path).name == "ngc5128_galaxy_b_001.fits"

    # Catalog candidate count, selected/rejected counts. The candidates are
    # what the solve was handed -- the cone clipped to the detector, as the
    # live path clips -- and the cone's own size is reported beside them.
    assert (replay.num_catalog_rows, replay.num_catalog_candidates) == (CONE_APASS_ROWS, FRAME_APASS_ROWS)
    assert (replay.num_variable_rows, replay.num_variable_sources) == (CONE_VSX_ROWS, FRAME_VSX_ROWS)
    assert replay.num_detected_sources == 298
    assert replay.num_matched == RECORDED_NUM_MATCHED
    assert replay.num_catalog_not_selected == FRAME_APASS_ROWS - RECORDED_NUM_MATCHED
    assert replay.num_detections_not_selected == RECORDED_NUM_NOT_SELECTED
    assert replay.recorded_num_matched == RECORDED_NUM_MATCHED
    assert replay.recorded_num_not_selected == RECORDED_NUM_NOT_SELECTED
    assert replay.selection_matches_recorded is True

    # Matched source identity and order, and the reference magnitudes.
    used = _recorded_used_rows()
    assert [m.detected_id for m in replay.matches] == [r["id"] for r in used]
    assert [m.ref_mag for m in replay.matches] == [float(r["local_ref_mag"]) for r in used]
    assert [m.ref_mag_error for m in replay.matches] == [
        float(r["local_ref_mag_error"]) if r["local_ref_mag_error"] else None for r in used
    ]
    assert [m.mag for m in replay.matches] == [float(r["mag"]) for r in used]
    assert all(0.0 <= m.separation_arcsec < 3.06 for m in replay.matches)
    assert len({m.catalog_index for m in replay.matches}) == RECORDED_NUM_MATCHED

    # The existing recorded solution, bit for bit.
    reference = load_zeropoint_reference("ngc5128_b_002")
    assert replay.solution.zero_point == reference.skynet_zero_point
    assert replay.solution.source_count == RECORDED_NUM_MATCHED
    assert replay.solution.rej_percent == pytest.approx(25.71428571428571, abs=1e-12)
    assert replay.comparison.delta_vs_skynet == 0.0
    assert replay.comparison.within_tolerance is True


@float32_mag_errors
def test_the_selection_replay_needs_the_recorded_vsx_rows(tmp_path):
    """PINNED: without the VSX filter the replay matches 36 sources, not 35.

    Gaia DR3 6088704247666049024 sits 0.91 arcsec from the APASS row that would
    otherwise match SRC467 (a star Afterglow detected twice: SRC335 is the same
    star, 0.05 arcsec away). The recorded run ran with variable_check_tol=5 and
    dropped that row before matching. This is why the VSX response is part of
    the fixture.
    """
    import shutil

    field_dir = tmp_path / "zp_solutions" / "ngc5128_b_002"
    shutil.copytree(
        Path(__file__).resolve().parent.parent / "data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002",
        field_dir,
    )
    (field_dir / "vsx_response.json").unlink()

    replay = replay_field_calibration("ngc5128_b_002", tmp_path)
    assert replay.errors == []
    assert (replay.num_variable_rows, replay.num_variable_sources) == (0, 0)
    assert [w.code for w in replay.warnings] == ["variable_sources_not_recorded"]
    assert "No recorded VSX response" in replay.warnings[0].message
    assert replay.num_matched == 36
    assert replay.selection_matches_recorded is False
    assert "SRC467" in [m.detected_id for m in replay.matches]
    # The extra star is rejected by the solve, so the zero point barely moves --
    # which is exactly why a count check matters and a tolerance check does not.
    assert abs(replay.comparison.delta_vs_skynet) < 1e-9
    assert replay.solution.zero_point != load_zeropoint_reference("ngc5128_b_002").skynet_zero_point


@float32_mag_errors
def test_the_selection_replay_opens_no_socket(monkeypatch):
    import socket

    def refuse(self, *args, **kwargs):
        raise AssertionError("the offline replay opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(
        "algorithms.query.runner.query_catalogs",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("query_catalogs was called")),
    )
    replay = replay_field_calibration("ngc5128_b_002")
    assert replay.errors == []
    assert replay.num_matched == RECORDED_NUM_MATCHED
    assert len(replay_catalog_sources("ngc5128_b_002", fixture="full_response")) == 132


def test_the_selection_replay_reports_a_field_it_cannot_run():
    replay = replay_field_calibration("ngc5286_b_000")
    assert replay.solution is None
    codes = [e.code for e in replay.errors]
    assert "fixture_missing" in codes
    assert "frame_not_bundled" in codes


@float32_mag_errors
def test_a_malformed_response_fixture_is_reported_not_raised(tmp_path):
    """A hand-made fixture under KEPLER_FIELDCAL_DATA_DIR that does not parse
    must surface as fixture_missing from a registered tool, not as a
    traceback -- nothing guards dispatch in the agent loop."""
    import shutil

    field_dir = tmp_path / "zp_solutions" / "ngc5128_b_002"
    shutil.copytree(
        Path(__file__).resolve().parent.parent / "data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002",
        field_dir,
    )
    (field_dir / "apass_response.json").write_text(
        '{"columns": [{"name": "RAJ2000", "dtype": "not-a-dtype"}], "rows": [[1.0]]}'
    )
    (field_dir / "vsx_response.json").write_text('{"rows": "nope"}')

    assert replay_catalog_sources("ngc5128_b_002", tmp_path, fixture="full_response") == []
    assert replay_variable_sources("ngc5128_b_002", tmp_path) == []
    assert [e.code for e in load_catalog_response("ngc5128_b_002", directory=tmp_path).errors] == [
        "fixture_missing"
    ]
    replay = replay_field_calibration("ngc5128_b_002", tmp_path)
    assert [e.code for e in replay.errors] == ["fixture_missing"]
    assert "not readable" in replay.errors[0].message

    # numpy raises OverflowError for an out-of-range integer cell and
    # numpy.ma.MaskError for a nested-list cell -- neither is a TypeError or
    # a ValueError, and both must land in the same place.
    (field_dir / "vsx_response.json").write_text(
        '{"columns": [{"name": "V", "dtype": "uint8"}], "rows": [[300]]}'
    )
    assert replay_variable_sources("ngc5128_b_002", tmp_path) == []
    (field_dir / "vsx_response.json").write_text(
        '{"columns": [{"name": "V", "dtype": "float64"}], "rows": [[[1.0, 2.0]]]}'
    )
    assert replay_variable_sources("ngc5128_b_002", tmp_path) == []
    assert [e.code for e in load_catalog_response("ngc5128_b_002", "VSX", tmp_path).errors] == [
        "fixture_missing"
    ]

    # Rows that parse but a provenance block that is the wrong shape: the
    # rows are still usable, and the provenance loader must not raise either.
    (field_dir / "apass_response.json").write_text(
        '{"query": [1, 2], "provenance": "none", "vizier_table": 336, '
        '"columns": [{"name": "RAJ2000", "dtype": "float64"}, {"name": "DEJ2000", "dtype": "float64"}, '
        '{"name": "Bmag", "dtype": "float32"}], "rows": [[201.3, -43.0, 12.5]]}'
    )
    response = load_catalog_response("ngc5128_b_002", directory=tmp_path)
    assert response.errors == []
    assert response.row_count == 1
    assert response.query == {} and response.provenance == {}
    assert response.vizier_table == "336"
    assert len(replay_catalog_sources("ngc5128_b_002", tmp_path, fixture="full_response")) == 1


def test_a_recorded_response_with_no_usable_rows_is_reported_as_empty(tmp_path):
    """A file that is present and parses, whose rows the plugin mapping all
    drops, is a different diagnosis from a file that is not there."""
    import json
    import shutil

    field_dir = tmp_path / "zp_solutions" / "ngc5128_b_002"
    shutil.copytree(
        Path(__file__).resolve().parent.parent / "data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002",
        field_dir,
    )
    payload = json.loads((field_dir / "apass_response.json").read_text())
    for row in payload["rows"]:
        row[2:] = [None] * (len(row) - 2)  # no magnitudes at all
    (field_dir / "apass_response.json").write_text(json.dumps(payload))

    assert load_catalog_response("ngc5128_b_002", directory=tmp_path).row_count == CONE_APASS_ROWS
    assert replay_catalog_sources("ngc5128_b_002", tmp_path, fixture="full_response") == []
    replay = replay_field_calibration("ngc5128_b_002", tmp_path)
    assert [e.code for e in replay.errors] == ["fixture_empty"]
    assert "132" in replay.errors[0].message


def test_the_replay_reads_the_response_for_the_recorded_catalog(tmp_path):
    """One name drives the file, the plugin mapping and the settings."""
    import json
    import shutil

    field_dir = tmp_path / "zp_solutions" / "ngc5128_b_002"
    shutil.copytree(
        Path(__file__).resolve().parent.parent / "data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002",
        field_dir,
    )
    summary = json.loads((field_dir / "fit_summary.json").read_text())
    summary["catalog_queried"] = ["PanSTARRS"]
    (field_dir / "fit_summary.json").write_text(json.dumps(summary))

    assert replay_catalog_sources("ngc5128_b_002", tmp_path, fixture="full_response") == []
    assert len(replay_catalog_sources("ngc5128_b_002", tmp_path, fixture="full_response", catalog="APASS")) == CONE_APASS_ROWS
    replay = replay_field_calibration("ngc5128_b_002", tmp_path)
    assert [e.code for e in replay.errors] == ["fixture_missing"]
    assert "panstarrs_response.json" in replay.errors[0].message


def test_matches_are_attributed_to_the_earliest_duplicate_detection():
    """fit_data.csv carries exact-duplicate detection rows (SRC317/SRC319),
    and a kd-tree query on identical points returns the lowest index, so a
    match at a duplicated position belongs to the earlier row. Matches come
    in detection order, which is what makes the attribution unambiguous."""
    from algorithms.fieldcal.schemas import PhotometryData
    from tools.fieldcal_reference import _detection_indices

    detections = [
        PhotometryData(id="A", x=1.0, y=1.0),
        PhotometryData(id="B", x=2.0, y=2.0),
        PhotometryData(id="C", x=2.0, y=2.0),  # exact duplicate of B
        PhotometryData(id="D", x=3.0, y=3.0),
    ]
    assert _detection_indices([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)], detections) == [0, 1, 3]
    # Two matches at the duplicated position take the two rows in order.
    assert _detection_indices([(2.0, 2.0), (2.0, 2.0)], detections) == [1, 2]
    # A position that is not a detection, and an out-of-order match, still resolve.
    assert _detection_indices([(9.0, 9.0), (3.0, 3.0), (1.0, 1.0)], detections) == [None, 3, 0]


def test_the_response_table_keeps_full_strings_and_exact_float32(tmp_path):
    """The recorded dtype fixes the kind (unicode, float32), not a width: a
    string longer than the recorded column width must not be truncated."""
    from tools.fieldcal_reference import _response_table

    table = _response_table(
        {
            "columns": [{"name": "Name", "dtype": "<U2"}, {"name": "Bmag", "dtype": "float32"}],
            "rows": [["a much longer name", 16.590999603271484], ["", None]],
        }
    )
    assert str(table["Name"][0]) == "a much longer name"
    assert table["Bmag"].dtype.name == "float32"
    assert float(table["Bmag"][0]) == 16.590999603271484
    assert bool(table["Bmag"].mask[1]) and not bool(table["Name"].mask[1])


def test_the_selection_replay_reports_an_unknown_field():
    replay = replay_field_calibration("ngc9999_z_000")
    assert [e.code for e in replay.errors] == ["not_found"]


@pytest.mark.slow
def test_offline_field_calibration_lands_inside_the_afterglow_tolerance():
    """The full chain on a real frame with no network: extract, measure, match,
    resolve reference magnitudes, solve, compare.

    This is the selected-row case: the 35 APASS rows Skynet actually matched
    are the only candidates, so photometry -> matching -> ref-mag resolution
    -> solve runs against real catalog values but catalog *selection* is not
    exercised -- every row is known to match. The full-response case below is
    the one that selects.
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


@pytest.mark.slow
@float32_mag_errors
def test_full_response_calibration_from_pixels_selects_its_own_matches():
    """The end-to-end selection replay from pixels: extract, measure, then
    choose matches from all 132 candidates (minus VSX variables) rather than
    from the 35 that are known to match. Same loose bound as the selected-row
    case above, for the same reason -- the photometry is re-measured."""
    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    comparison = calibrate_zeropoint(
        frame.path, catalog_fixture="full_response", compare_to="ngc5128_b_002"
    )
    assert comparison.errors == []
    assert comparison.reference.field == "ngc5128_b_002"
    assert abs(comparison.delta_vs_afterglow) < 0.1


def test_calibrate_zeropoint_rejects_a_fixture_without_a_field():
    from tools.photometry import calibrate_zeropoint

    comparison = calibrate_zeropoint(
        "data/optical/ngc5128_galaxy_b_001.fits", catalog_fixture="full_response"
    )
    assert [e.code for e in comparison.errors] == ["catalog_fixture_requires_compare_to"]


def test_calibrate_zeropoint_rejects_a_fixture_alongside_explicit_rows():
    from tools.photometry import calibrate_zeropoint

    comparison = calibrate_zeropoint(
        "data/optical/ngc5128_galaxy_b_001.fits",
        catalog_sources=replay_catalog_sources("ngc5128_b_002"),
        catalog_fixture="selected_rows",
        compare_to="ngc5128_b_002",
    )
    assert [e.code for e in comparison.errors] == ["conflicting_catalog_inputs"]


def test_calibrate_zeropoint_rejects_an_unknown_fixture_name():
    from tools.photometry import calibrate_zeropoint

    comparison = calibrate_zeropoint(
        "data/optical/ngc5128_galaxy_b_001.fits",
        catalog_fixture="everything",
        compare_to="ngc5128_b_002",
    )
    assert [e.code for e in comparison.errors] == ["unknown_catalog_fixture"]
    assert "full_response" in comparison.errors[0].message


def test_calibrate_zeropoint_reports_a_fixture_that_was_never_recorded():
    """The three NGC 5286 solves have neither a frame nor a full response; the
    error has to name the fixture, not fall through to a network query."""
    from tools.photometry import calibrate_zeropoint

    comparison = calibrate_zeropoint(
        "data/optical/ngc5128_galaxy_b_001.fits",
        catalog_fixture="full_response",
        compare_to="ngc5286_b_000",
    )
    assert [e.code for e in comparison.errors] == ["catalog_fixture_missing"]
    assert "ngc5286_b_000" in comparison.errors[0].message


@pytest.mark.slow
@float32_mag_errors
def test_the_full_response_fixture_applies_the_recorded_vsx_filter_from_pixels(monkeypatch):
    """From pixels, 'full_response' must hand the recorded VSX rows to the
    algorithm with the variable check on, and 'selected_rows' must not --
    the selected rows are already known to match, and one of them could sit
    near a variable."""
    import algorithms.fieldcal.field_cal as field_cal
    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    seen: dict[str, tuple] = {}
    real = field_cal.perform_field_calibration

    def spy(*args, **kwargs):
        seen[kwargs["field_cal_settings"].catalogs[0]] = (
            kwargs["variable_sources"],
            kwargs["field_cal_settings"].variable_check_tol,
            len(kwargs["catalog_sources"]),
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(field_cal, "perform_field_calibration", spy)
    frame = resolve_optical_frame("ngc5128_galaxy_b_001")

    calibrate_zeropoint(frame.path, catalog_fixture="selected_rows", compare_to="ngc5128_b_002")
    variables, tol, candidates = seen.pop("APASS")
    assert (variables, tol, candidates) == (None, 0, 35)

    calibrate_zeropoint(frame.path, catalog_fixture="full_response", compare_to="ngc5128_b_002")
    variables, tol, candidates = seen.pop("APASS")
    # Clipped to the detector first, as the live query path clips.
    assert len(variables) == FRAME_VSX_ROWS and tol == 5 and candidates == FRAME_APASS_ROWS


def test_calibrate_zeropoint_keeps_its_warnings_on_an_error_return(tmp_path, monkeypatch):
    """A skipped variable filter is part of the diagnosis when the solve then
    fails; the warning must ride on the error result, not vanish."""
    import shutil

    from tools.photometry import calibrate_zeropoint

    field_dir = tmp_path / "zp_solutions" / "ngc5128_b_002"
    shutil.copytree(
        Path(__file__).resolve().parent.parent / "data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002",
        field_dir,
    )
    (field_dir / "vsx_response.json").unlink()
    monkeypatch.setenv("KEPLER_FIELDCAL_DATA_DIR", str(tmp_path))

    comparison = calibrate_zeropoint(
        tmp_path / "no_such_frame.fits", catalog_fixture="full_response", compare_to="ngc5128_b_002"
    )
    assert [e.code for e in comparison.errors] == ["file_not_found"]
    assert [w.code for w in comparison.warnings] == ["variable_sources_not_recorded"]


@pytest.mark.slow
@float32_mag_errors
def test_calibrate_zeropoint_does_not_reach_the_network_when_a_fixture_is_named(monkeypatch):
    """Both fixtures short-circuit every query -- APASS and, for the full
    response with variable checks on, VSX too."""
    import socket

    def refuse(self, *args, **kwargs):
        raise AssertionError("calibrate_zeropoint opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)

    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    for fixture in CATALOG_FIXTURES:
        comparison = calibrate_zeropoint(
            frame.path, catalog_fixture=fixture, compare_to="ngc5128_b_002"
        )
        assert comparison.errors == [], fixture
        assert comparison.zero_point is not None, fixture


@float32_mag_errors
def test_the_offline_paths_are_reachable_from_the_agent_registry():
    """A model cannot pass CatalogSource objects, so the fixture names are the
    only way it reaches an offline solve; the selection replay is a tool of
    its own."""
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    schemas = {s["name"]: s for s in TOOL_SCHEMAS}
    fixture = schemas["calibrate_zeropoint"]["input_schema"]["properties"]["catalog_fixture"]
    assert tuple(fixture["enum"]) == CATALOG_FIXTURES
    assert "compare_to" in fixture["description"]

    replay = schemas["replay_field_calibration"]
    assert replay["input_schema"]["required"] == ["field"]
    assert TOOL_FUNCTIONS["replay_field_calibration"] is replay_field_calibration
    assert TOOL_FUNCTIONS["replay_field_calibration"](field="ngc5128_b_002").num_matched == 35


@pytest.mark.slow
def test_calibrate_zeropoint_does_not_reach_the_network_when_rows_are_supplied(monkeypatch):
    """A supplied catalog must short-circuit query_catalogs entirely."""
    def explode(*args, **kwargs):
        raise AssertionError("calibrate_zeropoint queried the network")

    monkeypatch.setattr("algorithms.query.runner.query_catalogs", explode)

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
