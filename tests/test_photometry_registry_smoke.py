from __future__ import annotations

import math
from pathlib import Path

from astropy.io import fits

from tools.photometry_pipeline import resolve_fits_path
from tools.photometry import list_photometry_targets, run_photometry_on_target


def test_list_photometry_targets_includes_known_bundled_stem() -> None:
    library = list_photometry_targets()

    assert library.total_count > 0
    assert "ngc1846_cluster_r_000" in library.categories.get("cluster", [])


def test_run_photometry_on_target_reports_missing_target_as_error() -> None:
    result = run_photometry_on_target("does-not-exist-target")

    assert result.file.exists is False
    assert len(result.errors) == 1
    assert result.errors[0].code == "target_not_found"
    assert result.artifacts == []


def test_run_photometry_on_target_no_field_cal_is_fast_and_local(tmp_path: Path) -> None:
    # use_field_cal=False keeps this test offline and deterministic -- the
    # network field-cal path is exercised manually, not in the default
    # no-network test suite.
    result = run_photometry_on_target(
        "ngc1846_cluster_r_000", use_field_cal=False, output_dir=tmp_path
    )

    assert result.source_count > 0
    assert result.zero_point_source == "none"
    assert result.zero_point is None
    assert len(result.artifacts) == 1
    assert Path(result.artifacts[0].path).exists()


def test_run_photometry_on_target_exposes_exposure_seconds_for_flux_mag_check(tmp_path: Path) -> None:
    # Confirmed live: without this field, flux and mag looked mutually
    # inconsistent by several magnitudes to a reader checking the math by
    # hand -- mag = -2.5*log10(flux/exposure_seconds) + zero_point, never the
    # bare -2.5*log10(flux) + zero_point. This is the one field that lets a
    # caller (human or the conversational tool loop) actually verify that.
    target = "ngc1846_cluster_r_000"
    result = run_photometry_on_target(target, use_field_cal=False, output_dir=tmp_path)

    header = fits.getheader(resolve_fits_path(target))
    assert result.exposure_seconds == header["EXPTIME"]

    assert result.brightest is not None
    with_texp_diff = result.brightest.mag - (-2.5 * math.log10(result.brightest.flux / result.exposure_seconds))
    without_texp_diff = result.brightest.mag - (-2.5 * math.log10(result.brightest.flux))
    # Dividing by exposure time first should close almost all of the gap --
    # what's left is the small, separately-documented aperture-correction
    # residual (this path doesn't force apcorr_tol=0; only "field-cal" does),
    # not exposure time. Without the division, the gap is dominated by
    # exposure time instead and is much larger.
    assert abs(with_texp_diff) < 1.0
    assert abs(without_texp_diff) > 1.0


def test_source_summary_reports_sky_position(tmp_path: Path) -> None:
    # The bundled cluster frames are plate-solved, so brightest/faintest should
    # carry a real sky position -- the same one
    # algorithms.hrdiagram_py.observations.extract_photometry_from_fits reports,
    # since both ultimately read it off the same WCS.
    result = run_photometry_on_target(
        "ngc1846_cluster_r_000", use_field_cal=False, output_dir=tmp_path
    )

    assert result.brightest is not None
    assert result.brightest.ra_deg is not None
    assert result.brightest.dec_deg is not None
    assert 0.0 <= result.brightest.ra_deg < 360.0
    assert -90.0 <= result.brightest.dec_deg <= 90.0


def test_write_source_table_produces_an_hr_diagram_compatible_csv(tmp_path: Path) -> None:
    # write_source_table is opt-in (default False) so the artifact count for
    # existing callers doesn't change -- see
    # test_run_photometry_on_target_no_field_cal_is_fast_and_local.
    import pandas as pd

    result = run_photometry_on_target(
        "ngc1846_cluster_r_000",
        use_field_cal=False,
        output_dir=tmp_path,
        write_source_table=True,
    )

    assert len(result.artifacts) == 2
    table_artifact = next(a for a in result.artifacts if a.format == "csv")
    assert Path(table_artifact.path).exists()

    df = pd.read_csv(table_artifact.path)
    # Same column names tools.hr_diagram.crossmatch_gaia's matching.field_footprint
    # reads (ra_deg/dec_deg) -- this CSV should be usable there without renaming.
    assert {"ra_deg", "dec_deg"}.issubset(df.columns)
    assert len(df) > 0
    assert df["ra_deg"].between(0.0, 360.0).all()
    assert df["dec_deg"].between(-90.0, 90.0).all()
