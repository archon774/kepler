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
OPTICAL = ROOT / "data" / "optical"


def test_lists_every_bundled_frame():
    listing = list_optical_frames()
    assert listing.count == 39
    assert Path(listing.search_root) == OPTICAL
    assert listing.errors == []


def test_listing_reports_the_filter_spread_recorded_in_the_readme():
    """data/README.md: V (25), R (7), B (2), Halpha (2), OIII (1), Lum (1), Open (1)."""
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
    """Frames are named <object>_<category>_<filter>_<seq> (data/README.md)."""
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
    # Reported once, not twice: the same directory named by both env vars is
    # one root, and duplicating it in search_roots reads as a bug.
    assert [Path(r) for r in listing.search_roots] == [download_root]


def test_collapsing_two_roots_into_one_keeps_the_recursive_search(
    monkeypatch, download_root
):
    """The collapse must not inherit the primary root's flat search.

    Taking the first entry's recursion flag would silently stop finding nested
    downloads the moment an operator pointed both env vars at one directory.
    """
    download_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", str(download_root))
    _write_frame(
        download_root / "mastDownload" / "HST" / "obs" / "nested.fits",
        object_name="Nested",
        image_filter="V",
    )

    listing = list_optical_frames()
    assert [Path(f.path).name for f in listing.frames] == ["nested.fits"]


def test_a_downloaded_frame_resolves_by_its_filename(download_root):
    """A filename is what a caller copies out of an archive manifest.

    The flat root/name probe cannot reach a nested download, so this falls
    through to normalized matching -- where _normalize("x.fits") is "xfits",
    not a substring of the stem "x". The full filename is matched too.
    """
    _write_frame(
        download_root / "mastDownload" / "HST" / "idxq01010" / "idxq01010_drz.fits",
        object_name="NGC 1234",
        image_filter="F606W",
    )
    frame = resolve_optical_frame("idxq01010_drz.fits")

    assert isinstance(frame, OpticalFrame)
    assert Path(frame.path).name == "idxq01010_drz.fits"


def test_the_download_root_is_reported_as_an_absolute_path(download_root):
    """A frame path is handed to the next tool, which may have another cwd."""
    _write_frame(download_root / "one.fits", object_name="One", image_filter="V")
    listing = list_optical_frames()

    assert all(Path(r).is_absolute() for r in listing.search_roots)
    assert all(Path(f.path).is_absolute() for f in listing.frames)


def test_photometry_targets_exclude_the_archive_download_root(download_root):
    """list_photometry_targets advertises a fixed bundled set, so it stays one.

    A downloaded product has no <object>_<category>_<filter>_<seq> token to
    parse, and a CASDA radio cube is not an optical photometry target.
    """
    from tools.claude_photometry_haiku_tool import list_bundled_targets

    _write_frame(
        download_root / "idxq01010_drz.fits", object_name="NGC 1234", image_filter="F606W"
    )
    stems = {stem for stems in list_bundled_targets().values() for stem in stems}

    assert "idxq01010_drz" not in stems
    assert "ngc5128_galaxy_b_001" in stems
    # Still reachable through the frame registry, just not as a "target".
    assert isinstance(resolve_optical_frame("idxq01010_drz"), OpticalFrame)


def test_the_archive_tools_and_the_registry_agree_on_the_download_root(download_root):
    """A late reassignment has to move both, or BL-11 comes straight back.

    tools.optical reads config.FITS_DOWNLOAD_DIR through the module; a
    from-import in tools.mast/tools.casda would bind it at import and send
    downloads somewhere the registry never looks.
    """
    from tools import casda, config, mast

    assert mast.__dict__.get("FITS_DOWNLOAD_DIR") is None
    assert casda.__dict__.get("FITS_DOWNLOAD_DIR") is None
    assert mast.config.FITS_DOWNLOAD_DIR == download_root
    assert casda.config.FITS_DOWNLOAD_DIR == config.FITS_DOWNLOAD_DIR


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


def test_an_empty_directory_string_falls_back_to_the_default_roots():
    """Path("") is Path("."), so `is not None` would search the CWD instead.

    An optional string parameter arriving as "" rather than omitted is an
    ordinary thing for a model to do, and the failure is silent: an empty
    listing rather than the bundled frames.
    """
    listing = list_optical_frames("")
    assert listing.count == 39
    assert Path(listing.search_root) == OPTICAL


# --- The recursive walk is bounded ------------------------------------------
#
# Two bounds, added after P2 recorded the unbounded rglob as an open finding.
# KEPLER_FITS_DOWNLOAD_DIR can name anywhere -- a home directory, a mount
# point, "/" -- so recursion is confined to the data directory; and a bulk
# search_mast(download=True) can leave thousands of products under it
# (121,515 for Cas A), so one listing reads a bounded number of headers.


def test_a_download_root_inside_the_data_dir_is_walked(tmp_path, monkeypatch):
    from tools import config

    data_dir = tmp_path / "data"
    inside = data_dir / "fits_downloads"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", inside)
    _write_frame(
        inside / "mastDownload" / "HST" / "idxq01010" / "nested.fits",
        object_name="NGC 1234",
        image_filter="F606W",
    )

    listing = list_optical_frames()

    assert "nested.fits" in {Path(f.path).name for f in listing.frames}
    assert listing.warnings == []


def test_a_download_root_outside_the_data_dir_is_searched_flat(tmp_path, monkeypatch):
    """Still searched -- just not walked. CASDA's download_files writes flat,
    so refusing the root outright would lose those frames too."""
    from tools import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    outside = tmp_path / "elsewhere"
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", outside)
    _write_frame(outside / "flat.fits", object_name="NGC 1234", image_filter="V")
    _write_frame(
        outside / "mastDownload" / "HST" / "idxq01010" / "nested.fits",
        object_name="NGC 5678",
        image_filter="V",
    )

    listing = list_optical_frames()
    names = {Path(f.path).name for f in listing.frames}

    assert "flat.fits" in names
    assert "nested.fits" not in names
    assert [w.code for w in listing.warnings] == ["download_root_outside_data_dir"]
    assert str(outside) in listing.warnings[0].message


def test_containment_is_decided_on_the_resolved_path(tmp_path, monkeypatch):
    """A symlink named inside the data directory but pointing out of it does
    not buy a recursive walk of wherever it lands."""
    from tools import config

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = data_dir / "fits_downloads"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", link)
    _write_frame(
        real / "mastDownload" / "HST" / "idxq01010" / "nested.fits",
        object_name="NGC 5678",
        image_filter="V",
    )

    listing = list_optical_frames()

    assert "nested.fits" not in {Path(f.path).name for f in listing.frames}
    assert [w.code for w in listing.warnings] == ["download_root_outside_data_dir"]


def test_the_shipped_defaults_put_the_download_root_inside_the_data_dir(monkeypatch):
    """The default configuration has to satisfy its own containment rule, or
    the archive-to-analysis loop is flat-searched out of the box (BL-11).

    Loaded as a pristine copy: the autouse ``download_root`` fixture has
    already reassigned both values on the live ``tools.config``.
    """
    import importlib.util

    from tools import config

    monkeypatch.delenv("KEPLER_DATA_DIR", raising=False)
    monkeypatch.delenv("KEPLER_FITS_DOWNLOAD_DIR", raising=False)
    spec = importlib.util.spec_from_file_location("_config_pristine", config.__file__)
    pristine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pristine)

    assert pristine.DATA_DIR == ROOT / "data"
    assert pristine.FITS_DOWNLOAD_DIR.is_relative_to(pristine.DATA_DIR)


def test_a_listing_is_capped_and_says_how_many_it_left_out(monkeypatch):
    from tools import config

    monkeypatch.setattr(config, "DEFAULT_MAX_FRAMES", 5)
    listing = list_optical_frames()

    assert listing.count == 5
    assert [w.code for w in listing.warnings] == ["listing_truncated"]
    assert "39 frames found" in listing.warnings[0].message
    assert "KEPLER_MAX_FRAMES" in listing.warnings[0].message


def test_an_uncapped_listing_carries_no_truncation_warning():
    listing = list_optical_frames()

    assert listing.count == 39
    assert listing.warnings == []


def test_the_cap_bounds_header_reads_not_just_the_returned_list(monkeypatch):
    """The cap exists to stop a bulk download costing thousands of FITS header
    reads, so it has to apply before _summary rather than trimming after."""
    from tools import config, optical

    monkeypatch.setattr(config, "DEFAULT_MAX_FRAMES", 3)
    read: list[Path] = []
    real_summary = optical._summary
    monkeypatch.setattr(
        optical, "_summary", lambda path: (read.append(path), real_summary(path))[1]
    )

    optical.list_optical_frames()

    assert len(read) == 3


def test_a_truncated_listing_warns_on_the_frame_it_resolves(monkeypatch):
    """A lone match in a capped listing was found among the frames that were
    read, not among the frames that exist -- so the caveat rides on the frame
    rather than being dropped with the list it came from."""
    from tools import config

    monkeypatch.setattr(config, "DEFAULT_MAX_FRAMES", 5)
    frame = resolve_optical_frame("carina")

    assert isinstance(frame, OpticalFrame)
    assert "listing_truncated" in [w.code for w in frame.warnings]


def test_a_miss_in_a_truncated_listing_says_the_search_was_partial(monkeypatch):
    """"39 frames are available" would be a lie when only 5 were read, and it
    reads as "it is not here" -- the wrong conclusion in exactly the case the
    cap creates."""
    from tools import config

    monkeypatch.setattr(config, "DEFAULT_MAX_FRAMES", 5)
    result = resolve_optical_frame("ngc7293")

    assert isinstance(result, OpticalFrameList)
    message = result.errors[0].message
    assert "Only the first 5 frames were read" in message
    assert "KEPLER_MAX_FRAMES" in message
    assert "listing_truncated" in [w.code for w in result.warnings]
