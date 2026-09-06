"""Stage 0 for optical frames, mirroring tools.pulsar's scan discovery.

BL-3: the only frame resolver lived inside a CLI script, raised
FileNotFoundError instead of returning a ToolError, and reported no header
metadata -- so a caller could not ask "which frames are in B?" without opening
all 39 files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.models import OpticalFrame, OpticalFrameList
from tools.optical import list_optical_frames, resolve_optical_frame

ROOT = Path(__file__).resolve().parents[1]
OPTICAL = ROOT / "test_data" / "optical"


def test_lists_every_bundled_frame():
    listing = list_optical_frames()
    assert listing.count == 39
    assert Path(listing.search_root) == OPTICAL
    assert listing.errors == []


def test_listing_reports_the_filter_spread_recorded_in_the_readme():
    """test_data/README.md: V (25), R (7), B (2), Halpha (2), OIII (1), Lum (1), Open (1)."""
    listing = list_optical_frames()
    counts: dict[str, int] = {}
    for frame in listing.frames:
        counts[frame.image_filter] = counts.get(frame.image_filter, 0) + 1
    assert counts == {
        "V": 25, "R": 7, "B": 2, "Halpha": 2, "OIII": 1, "Lum": 1, "Open": 1,
    }


def test_filter_narrowing():
    listing = list_optical_frames(image_filter="B")
    assert listing.count == 2
    assert {Path(f.path).stem for f in listing.frames} == {
        "ngc5128_galaxy_b_000", "ngc5128_galaxy_b_001",
    }


def test_category_comes_from_the_filename_convention():
    """Frames are named <object>_<category>_<filter>_<seq> (test_data/README.md)."""
    frame = resolve_optical_frame("ngc1846_cluster_r_000")
    assert isinstance(frame, OpticalFrame)
    assert frame.category == "cluster"
    assert frame.image_filter == "R"


def test_resolves_a_bare_stem_a_filename_and_a_full_path():
    for query in (
        "ngc5128_galaxy_b_001",
        "ngc5128_galaxy_b_001.fits",
        str(OPTICAL / "ngc5128_galaxy_b_001.fits"),
    ):
        frame = resolve_optical_frame(query)
        assert isinstance(frame, OpticalFrame), query
        assert Path(frame.path).stem == "ngc5128_galaxy_b_001"


def test_resolves_an_object_name_with_punctuation_variants():
    """'NGC 5128' and 'ngc5128' both name the same field; only B has two frames."""
    result = resolve_optical_frame("NGC 5128")
    assert isinstance(result, OpticalFrameList)
    assert [e.code for e in result.errors] == ["ambiguous"]
    assert result.count == 4  # two B frames, two V frames


def test_the_frame_with_no_wcs_is_reported_not_hidden():
    frame = resolve_optical_frame("m15_globular_open_000")
    assert isinstance(frame, OpticalFrame)
    assert frame.has_wcs is False
    assert frame.center_ra_deg is None
    assert [w.code for w in frame.warnings] == ["no_celestial_wcs"]


def test_a_frame_with_a_wcs_carries_a_centre_and_a_pixel_scale():
    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    assert frame.has_wcs is True
    assert frame.center_ra_deg == pytest.approx(201.36, abs=0.5)
    assert frame.center_dec_deg == pytest.approx(-43.02, abs=0.5)
    assert frame.pixel_scale_arcsec == pytest.approx(1.2, abs=1.0)


def test_an_unknown_name_returns_the_candidates_not_an_exception():
    result = resolve_optical_frame("messier 87")
    assert isinstance(result, OpticalFrameList)
    assert [e.code for e in result.errors] == ["not_found"]
    assert result.count == 39


def test_a_missing_directory_returns_an_error_naming_the_env_override():
    listing = list_optical_frames("/nonexistent/optical")
    assert listing.count == 0
    assert [e.code for e in listing.errors] == ["directory_not_found"]
    assert "KEPLER_OPTICAL_DATA_DIR" in listing.errors[0].message


def test_env_override_redirects_the_search_root(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", str(tmp_path))
    listing = list_optical_frames()
    assert Path(listing.search_root) == tmp_path
    assert listing.count == 0
