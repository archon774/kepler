"""Tool-layer coverage for ``tools.astrometry``.

BL-1: this file exists because ``describe_image_wcs`` raised ``TypeError`` on
38 of the 39 bundled frames and no test imported the module. The parametrized
sweep is the point -- a fix that works on one frame and not the rest is not a
fix.

The fix landed on ``dev`` before this test did (``tools/astrometry.py`` now
materializes the ``StrListProxy`` before slicing), so the sweep passes on the
first run here. It is kept because its absence is what let the bug reach a
release branch in the first place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.astrometry import describe_image_wcs

FRAME_PATHS = sorted((Path(__file__).resolve().parents[1] / "data" / "optical").glob("*.fits"))


def test_the_fixture_directory_is_populated():
    assert len(FRAME_PATHS) == 39


@pytest.mark.parametrize("path", FRAME_PATHS, ids=lambda p: p.stem)
def test_describe_image_wcs_never_raises_on_a_bundled_frame(path):
    summary = describe_image_wcs(path)
    assert summary.file.exists is True


def test_frame_with_a_wcs_reports_ctype_and_a_centre():
    summary = describe_image_wcs(
        Path(__file__).resolve().parents[1] / "data" / "optical" / "ngc5128_galaxy_b_001.fits"
    )
    assert summary.has_wcs is True
    assert summary.ctype == ("RA---TAN", "DEC--TAN")
    assert summary.center_ra_deg == pytest.approx(201.36, abs=0.5)
    assert summary.center_dec_deg == pytest.approx(-43.02, abs=0.5)
    assert summary.pixel_scale_arcsec is not None


def test_frame_without_a_wcs_warns_instead_of_erroring():
    """m15_globular_open_000 carries no WCS keywords at all (data/README.md)."""
    summary = describe_image_wcs(
        Path(__file__).resolve().parents[1] / "data" / "optical" / "m15_globular_open_000.fits"
    )
    assert summary.has_wcs is False
    assert [w.code for w in summary.warnings] == ["no_celestial_wcs"]
    assert summary.errors == []


def test_missing_file_returns_an_error_not_an_exception():
    summary = describe_image_wcs("data/optical/does_not_exist.fits")
    assert summary.has_wcs is False
    assert [e.code for e in summary.errors] == ["file_not_found"]
