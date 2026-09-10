"""Cross-implementation parity: Kepler's zero point vs the Afterglow web service.

``test_fieldcal_solution.py`` proves Kepler's extracted ``calc_solution``
reproduces *Skynet's* recorded output bit-for-bit. That is a parity check
against one implementation. This file closes the loop against a second,
independent one: the hosted Afterglow field-calibration service, whose results
are in ``data/afterglow/``.

The chain of custody for NGC 5128 B runs:

    Kepler calc_solution
      -> 21.147659857998637   (reproduced exactly, test_fieldcal_solution.py)
    Skynet recorded local fit
      -> 21.147659857998637   (fit_summary.json: local_zero_point)
    Afterglow API response
      -> 21.14747923526837    (zero_point 20.0 + correction 1.1474792352683736)
    Afterglow web values table
      -> 21.147               (afterglow_web_values_master.csv, 3 dp)

Kepler and Afterglow agree to 1.8e-4 mag — inside the 5e-4 tolerance the
upstream diagnostic declares. Every one of those numbers was recorded before
the extraction, and none of this needs a network.

The Afterglow response also settles a question the source comments only assert:
``photometry_settings.apcorr_tol`` is ``0`` in Afterglow's own run, which is why
``field_cal.py`` forces it to zero for calibration photometry.
"""

from __future__ import annotations

import pytest

from algorithms.fieldcal.schemas import PhotometryData, PhotometrySettings
from algorithms.fieldcal.solution import calc_solution

#: The upstream diagnostic's own declared agreement threshold, in magnitudes.
PARITY_ZP_TOLERANCE = 0.0005


def _sources(rows):
    return [
        PhotometryData(
            mag=r["mag"], mag_error=r["mag_error"],
            ref_mag=r["ref_mag"], ref_mag_error=r["ref_mag_error"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# The parity chain
# ---------------------------------------------------------------------------

def test_kepler_zero_point_matches_the_afterglow_service(zp_case):
    """Kepler's solve agrees with Afterglow's within the recorded tolerance.

    This is the cross-implementation claim. The fixture records both the
    Afterglow calibrated zero point and the tolerance the upstream parity
    diagnostic applied, so nothing here is a threshold this test invented.
    """
    rows, summary = zp_case("ngc5128_b_002")
    zero_point, *_ = calc_solution(_sources(rows))

    afterglow = summary["afterglow_calibrated_zero_point"]
    assert summary["parity_zp_tolerance"] == PARITY_ZP_TOLERANCE
    assert summary["zero_point_within_tolerance"] is True

    assert abs(zero_point - afterglow) < PARITY_ZP_TOLERANCE
    assert abs(zero_point - afterglow) == pytest.approx(
        summary["local_minus_afterglow_calibrated_zero_point"], abs=1e-12
    )


def test_afterglow_calibrated_zero_point_is_base_plus_correction(zp_case):
    """Afterglow reports ``zero_point = 20`` plus a correction, never an absolute.

    Kepler computes the absolute zero point directly, so every comparison has to
    add the two Afterglow numbers first. Getting this wrong yields a clean,
    plausible 20-magnitude error.
    """
    _, summary = zp_case("ngc5128_b_002")
    assert summary["afterglow_zero_point"] == 20.0
    assert (
        summary["afterglow_zero_point"] + summary["afterglow_zero_point_correction"]
        == pytest.approx(summary["afterglow_calibrated_zero_point"], abs=1e-12)
    )


def test_recorded_solve_matches_the_afterglow_web_values_table(
    zp_case, afterglow_web_zero_points
):
    """The published web value for this frame rounds from the same number.

    ``afterglow_web_values_master.csv`` is a third recording of this result,
    made by hand from the web UI at three decimal places, independent of the API
    JSON. Reaching it from Kepler's solve closes the chain.
    """
    rows, summary = zp_case("ngc5128_b_002")
    zero_point, zero_point_error, *_ = calc_solution(_sources(rows))

    web_zp, web_err = afterglow_web_zero_points["ngc5128_galaxy_b_001.fits"]
    assert web_zp == pytest.approx(summary["afterglow_calibrated_zero_point"], abs=5e-4)
    assert web_zp == pytest.approx(zero_point, abs=1e-3)
    assert web_err == pytest.approx(zero_point_error, abs=1e-3)


def test_afterglow_photometry_export_agrees_with_its_own_api_response(
    afterglow_photometry_rows, zp_case
):
    """Afterglow's CSV export carries the same zero point as its JSON response.

    Every row repeats the run-level calibration, so this also pins the
    convention documented upstream: ``calibrated = zero_point + correction``.
    """
    _, summary = zp_case("ngc5128_b_002")
    assert len(afterglow_photometry_rows) > 200

    row = afterglow_photometry_rows[0]
    base = float(row["zero_point"])
    correction = float(row["zero_point_correction"])
    calibrated = float(row["calibrated_zero_point"])

    assert base == 20.0
    assert base + correction == pytest.approx(calibrated, abs=1e-12)
    assert calibrated == pytest.approx(
        summary["afterglow_calibrated_zero_point"], abs=1e-9
    )

    # The run-level values are constant down the export.
    assert {r["calibrated_zero_point"] for r in afterglow_photometry_rows} == {
        row["calibrated_zero_point"]
    }


def test_afterglow_calibrated_mag_is_instrumental_mag_plus_correction(
    afterglow_photometry_rows,
):
    """``calibrated_mag = mag + zero_point_correction`` for every exported row.

    This is the relation Kepler's zero point is *for*. Pinning it against real
    exported rows fixes the sign and which of the two zero-point numbers is the
    additive one.
    """
    checked = 0
    for row in afterglow_photometry_rows:
        if not row["mag"] or not row["calibrated_mag"]:
            continue
        expected = float(row["mag"]) + float(row["zero_point_correction"])
        assert float(row["calibrated_mag"]) == pytest.approx(expected, abs=1e-9)
        checked += 1
    assert checked > 200


# ---------------------------------------------------------------------------
# Afterglow's own settings corroborate the parity overrides
# ---------------------------------------------------------------------------

def test_afterglow_ran_with_aperture_correction_disabled(afterglow_fieldcal_response):
    """``apcorr_tol: 0`` in Afterglow's own settings.

    ``field_cal.py`` forces ``apcorr_tol = 0.0`` for calibration photometry
    under a "LEGACY AFTERGLOW PARITY — DO NOT CLEAN UP" comment. This is the
    evidence behind that comment: the reference implementation whose numbers
    Kepler has to reproduce ran with aperture correction off, so Kepler must
    too, regardless of what the caller asked for.
    """
    settings = afterglow_fieldcal_response["photometry_settings"]
    assert settings["apcorr_tol"] == 0
    assert settings["zero_point"] == 20


def test_kepler_photometry_settings_can_express_the_afterglow_run(
    afterglow_fieldcal_response,
):
    """Every setting Afterglow used has a Kepler equivalent with the same value.

    Names differ where the extraction renamed them (``a_in`` -> ``a_in_px``,
    ``theta_out`` -> ``theta_out_deg``, ``zero_point`` -> ``zero_point_mag``);
    the mapping is asserted here so a rename cannot silently drop one.
    """
    afterglow = afterglow_fieldcal_response["photometry_settings"]
    mapping = {
        "mode": "mode", "a": "a", "b": "b", "theta": "theta",
        "a_in": "a_in_px", "a_out": "a_out_px", "b_out": "b_out_px",
        "theta_out": "theta_out_deg", "gain": "gain",
        "centroid_radius": "centroid_radius", "zero_point": "zero_point_mag",
        "fix_aper": "fix_aper", "fix_ell": "fix_ell", "fix_rot": "fix_rot",
        "apcorr_tol": "apcorr_tol", "reject_bkg_outliers": "reject_bkg_outliers",
    }
    assert set(mapping) == set(afterglow), "Afterglow settings block changed shape"

    settings = PhotometrySettings(
        **{kepler: afterglow[their] for their, kepler in mapping.items()}
    )
    for their, kepler in mapping.items():
        assert getattr(settings, kepler) == afterglow[their], kepler


def test_afterglow_field_cal_settings_match_keplers_defaults_where_they_overlap(
    afterglow_fieldcal_response,
):
    """``min_snr``, ``source_match_tol`` and ``variable_check_tol`` line up.

    Kepler's ``PhotometricCalibrationSettings`` defaults were carried over from
    this same configuration; a drift in any of them changes which sources reach
    the solve.
    """
    from algorithms.fieldcal.schemas import PhotometricCalibrationSettings

    afterglow = afterglow_fieldcal_response["field_cal"]
    defaults = PhotometricCalibrationSettings()

    assert afterglow["min_snr"] == defaults.min_snr
    assert afterglow["source_match_tol"] == defaults.source_match_tol
    assert afterglow["variable_check_tol"] == defaults.variable_check_tol
    assert afterglow["catalogs"] == defaults.catalogs


def test_afterglow_limmag5_agrees_with_the_recorded_solve(
    afterglow_fieldcal_response, zp_case
):
    """The 5-sigma limiting magnitude tracks too, to ~0.1 mag.

    ``limmag5`` comes out of a ``polyfit`` over SNR against magnitude, so it is
    the loosest of the five returned values — a tenth of a magnitude between two
    implementations is agreement, not drift.
    """
    _, summary = zp_case("ngc5128_b_002")
    afterglow_limmag = afterglow_fieldcal_response["result"]["data"][0]["limmag5"]

    rows, _ = zp_case("ngc5128_b_002")
    *_, limmag5, _ = calc_solution(_sources(rows))

    assert limmag5 == pytest.approx(summary["limmag5"], abs=1e-9)
    assert limmag5 == pytest.approx(afterglow_limmag, abs=0.1)


# ---------------------------------------------------------------------------
# Ground-truth coverage of the shipped frames
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "frame",
    ["carina_nebula_v_000.fits", "m31_galaxy_v_000.fits", "ngc2070_nebula_v_000.fits",
     "ngc3628_galaxy_v_000.fits", "ngc5286_globular_v_000.fits", "nsv2849_star_v_000.fits"],
)
def test_shipped_frames_have_afterglow_ground_truth(frame, afterglow_web_zero_points):
    """Six of the eight optical frames carry a published zero point.

    These are the reference values the network-gated end-to-end test in
    ``test_query_live.py`` compares against. Asserting they are present keeps
    that test honest: if the table were ever trimmed, the live test would
    silently have nothing to check.

    The two frames deliberately absent are the Open and Lum M15 exposures —
    unfiltered passes have no direct catalog band, which is what makes them the
    OCL substitution fixtures rather than zero-point fixtures.
    """
    zero_point, error = afterglow_web_zero_points[frame]
    assert 15.0 < zero_point < 27.0
    assert error >= 0


def test_ocl_frames_are_absent_from_the_web_table(afterglow_web_zero_points):
    assert "m15_globular_lum_000.fits" not in afterglow_web_zero_points
    assert "m15_globular_open_000.fits" not in afterglow_web_zero_points


def test_web_table_is_the_union_of_the_per_filter_tables(data_dir):
    """``build_master_table.py``'s contract: master == bvr + narrowband + sdss.

    The merge is by ``file`` key with last-write-wins, so a duplicate across two
    category tables would silently drop a row. Recomputing the union here checks
    the shipped master is current with its inputs.
    """
    import csv

    base = data_dir / "afterglow"
    union: dict[str, dict] = {}
    for category in ("bvr", "narrowband", "sdss"):
        with open(base / f"afterglow_web_values_{category}.csv", newline="") as fh:
            for row in csv.DictReader(fh):
                union[row["file"].strip()] = row

    with open(base / "afterglow_web_values_master.csv", newline="") as fh:
        master = {row["file"]: row for row in csv.DictReader(fh)}

    assert set(master) == set(union)
    for name, row in master.items():
        assert row["Afterglow web zero_point"] == union[name]["Afterglow web zero_point"]
