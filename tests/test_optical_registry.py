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


def test_the_frame_registry_is_reachable_from_an_agent_loop():
    from tools.registry import TOOL_FUNCTIONS

    assert TOOL_FUNCTIONS["list_optical_frames"] is list_optical_frames
    assert TOOL_FUNCTIONS["resolve_optical_frame"] is resolve_optical_frame


def test_the_cli_resolver_delegates_to_the_registry():
    """One resolution rule, not two. BL-3."""
    from tools.claude_photometry_haiku_tool import resolve_fits_path

    resolved = resolve_fits_path("ngc5128_galaxy_b_001")
    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    assert Path(resolved) == Path(frame.path)


def test_the_cli_resolver_still_raises_for_its_own_callers():
    """The CLI contract is an exception; the tool contract is a ToolError."""
    from tools.claude_photometry_haiku_tool import resolve_fits_path

    with pytest.raises(FileNotFoundError):
        resolve_fits_path("messier 87")


# --- BL-11: the archive-to-analysis loop -------------------------------------
#
# tools.mast/tools.casda download products into tools.config.FITS_DOWNLOAD_DIR
# and nothing could then find them: the registry searched one directory. The
# download root is now a second search root, recursive because astroquery lays
# MAST products out under mastDownload/<mission>/<obs_id>/ rather than flat.


@pytest.fixture(autouse=True)
def download_root(tmp_path, monkeypatch):
    """Point the download root at an empty tmp path for every test here.

    ``fits_downloads/`` is gitignored but real: a developer who has ever run
    ``search_mast(..., download=True)`` has one in the working tree. Now that
    it is a genuine second search root, a stray download would otherwise move
    the bundled-frame counts the assertions above pin.
    """
    from tools import config

    root = tmp_path / "fits_downloads"
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", root)
    return root


def _write_frame(path: Path, *, object_name: str, image_filter: str) -> Path:
    """A minimal well-formed FITS frame; header-only, so no WCS."""
    import numpy as np
    from astropy.io import fits

    path.parent.mkdir(parents=True, exist_ok=True)
    header = fits.Header()
    header["OBJECT"] = object_name
    header["FILTER"] = image_filter
    fits.PrimaryHDU(np.zeros((4, 4), dtype=np.float32), header).writeto(path)
    return path


def test_search_roots_reports_only_the_optical_root_when_nothing_is_downloaded():
    listing = list_optical_frames()
    assert Path(listing.search_root) == OPTICAL
    assert [Path(r) for r in listing.search_roots] == [OPTICAL]


def test_a_downloaded_frame_is_listed_alongside_the_bundled_ones(download_root):
    _write_frame(
        download_root / "mastDownload" / "HST" / "idxq01010" / "idxq01010_drz.fits",
        object_name="NGC 1234",
        image_filter="F606W",
    )
    listing = list_optical_frames()

    assert listing.count == 40
    assert [Path(r) for r in listing.search_roots] == [OPTICAL, download_root]
    # search_root still names the primary root, unchanged.
    assert Path(listing.search_root) == OPTICAL
    assert "idxq01010_drz.fits" in {Path(f.path).name for f in listing.frames}


def test_a_downloaded_frame_resolves_by_object_name(download_root):
    _write_frame(
        download_root / "mastDownload" / "HST" / "idxq01010" / "idxq01010_drz.fits",
        object_name="NGC 1234",
        image_filter="F606W",
    )
    frame = resolve_optical_frame("NGC 1234")

    assert isinstance(frame, OpticalFrame)
    assert Path(frame.path).name == "idxq01010_drz.fits"
    assert frame.object_name == "NGC 1234"


def test_a_downloaded_frame_resolves_by_bare_stem(download_root):
    """The stem probe has to try every root, not just the primary one."""
    _write_frame(
        download_root / "idxq01010_drz.fits", object_name="NGC 1234", image_filter="F606W"
    )
    frame = resolve_optical_frame("idxq01010_drz")

    assert isinstance(frame, OpticalFrame)
    assert Path(frame.path).name == "idxq01010_drz.fits"


def test_only_the_download_root_is_searched_recursively(download_root, tmp_path, monkeypatch):
    """MAST nests; a caller's own archive directory keeps the flat contract."""
    nested_primary = tmp_path / "primary"
    _write_frame(
        nested_primary / "subdir" / "buried.fits", object_name="Buried", image_filter="V"
    )
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", str(nested_primary))
    _write_frame(
        download_root / "deep" / "deeper" / "found.fits", object_name="Found", image_filter="V"
    )

    names = {Path(f.path).name for f in list_optical_frames().frames}
    assert names == {"found.fits"}


def test_an_explicit_directory_argument_still_means_exactly_that_directory(download_root):
    _write_frame(
        download_root / "idxq01010_drz.fits", object_name="NGC 1234", image_filter="F606W"
    )
    listing = list_optical_frames(OPTICAL)

    assert listing.count == 39
    assert [Path(r) for r in listing.search_roots] == [OPTICAL]
    assert "idxq01010_drz.fits" not in {Path(f.path).name for f in listing.frames}


def test_a_frame_reachable_through_two_roots_is_listed_once(monkeypatch, download_root):
    """Nothing stops an operator pointing both env vars at one directory."""
    download_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", str(download_root))
    _write_frame(download_root / "one.fits", object_name="One", image_filter="V")

    listing = list_optical_frames()
    assert listing.count == 1
    assert [Path(r) for r in listing.search_roots] == [download_root, download_root]


def test_a_missing_primary_root_is_not_an_error_when_a_download_root_has_frames(
    monkeypatch, download_root
):
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", "/nonexistent/optical")
    _write_frame(download_root / "one.fits", object_name="One", image_filter="V")

    listing = list_optical_frames()
    assert listing.errors == []
    assert listing.count == 1
    assert [Path(r) for r in listing.search_roots] == [download_root]
    # The primary root is still what search_root names, present or not.
    assert Path(listing.search_root) == Path("/nonexistent/optical")


def test_directory_not_found_names_every_root_it_tried(monkeypatch, download_root):
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", "/nonexistent/optical")
    listing = list_optical_frames()

    assert [e.code for e in listing.errors] == ["directory_not_found"]
    assert listing.search_roots == []
    message = listing.errors[0].message
    assert "/nonexistent/optical" in message
    assert str(download_root) in message
    assert "KEPLER_OPTICAL_DATA_DIR" in message


def test_an_absent_download_root_is_skipped_without_a_warning(download_root):
    assert not download_root.exists()
    listing = list_optical_frames()

    assert listing.warnings == []
    assert listing.errors == []
    assert [Path(r) for r in listing.search_roots] == [OPTICAL]
