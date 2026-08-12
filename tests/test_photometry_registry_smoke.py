from __future__ import annotations

import math
from pathlib import Path

from astropy.io import fits

from tools.claude_photometry_haiku_tool import resolve_fits_path
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
