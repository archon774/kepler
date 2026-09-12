"""Tool-layer coverage for plate solving.

BL-7: ``solve_wcs`` was reachable only by importing the algorithm package, and
its astrometry.net index directory was never configured by a public tool.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from astropy.io import fits
from astropy.wcs import WCS

from algorithms.wcs.config import SolverSettings
from algorithms.skylib_lite.astrometry.anet import AstrometryNetError
from algorithms.wcs.results import WcsSolveMetadata, WcsSolveResult
from algorithms.wcs.wcs import build_anet_config
from tools.wcs import solve_astrometry


ROOT = Path(__file__).resolve().parents[1]
OPEN_FRAME = ROOT / "data" / "optical" / "m15_globular_open_000.fits"
SOLVED_FRAME = ROOT / "data" / "optical" / "ngc5128_galaxy_b_001.fits"

solver_available = pytest.mark.skipif(
    shutil.which("solve-field") is None or not os.environ.get("ANET_INDEX_PATH"),
    reason="needs solve-field on PATH and ANET_INDEX_PATH set",
)


def _configure_fake_anet(monkeypatch, tmp_path: Path) -> Path:
    index_path = tmp_path / "indexes"
    index_path.mkdir()
    (index_path / "index-4107.fits").touch()
    monkeypatch.setattr("tools.wcs.find_solve_field", lambda: "/fake/solve-field")
    monkeypatch.setattr(
        "algorithms.wcs.wcs.AstrometryNetBackend.is_available",
        lambda self: True,
    )
    return index_path


def test_a_missing_file_returns_an_error_not_an_exception():
    summary = solve_astrometry(ROOT / "data" / "optical" / "does_not_exist.fits")

    assert summary.has_wcs is False
    assert [error.code for error in summary.errors] == ["file_not_found"]


def test_an_unconfigured_solver_degrades_with_a_named_warning(monkeypatch):
    monkeypatch.delenv("ANET_INDEX_PATH", raising=False)
    monkeypatch.delenv("ATLAS_CATALOG_ROOT", raising=False)

    summary = solve_astrometry(OPEN_FRAME)

    assert summary.has_wcs is False
    assert "solver_unavailable" in [warning.code for warning in summary.warnings]
    assert "ANET_INDEX_PATH" in " ".join(warning.message for warning in summary.warnings)


def test_a_frame_with_wcs_short_circuits_the_solver_by_default(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("the solver should not run for an already-solved frame")

    monkeypatch.setattr("tools.wcs._solve_wcs", fail_if_called)

    summary = solve_astrometry(SOLVED_FRAME)

    assert summary.has_wcs is True
    assert "wcs_from_header" in [warning.code for warning in summary.warnings]


def test_force_resolves_a_frame_that_already_has_wcs(monkeypatch, tmp_path):
    index_path = _configure_fake_anet(monkeypatch, tmp_path)

    def fake_solve(*args, solver_attempts=None, **kwargs):
        solver_attempts.append("astrometry.net")
        return WcsSolveResult(
            wcs=None,
            catalog_sources=(),
            metadata=WcsSolveMetadata(width_px=1056, height_px=1027),
        )

    monkeypatch.setattr("tools.wcs._solve_wcs", fake_solve)

    summary = solve_astrometry(SOLVED_FRAME, index_path=index_path, force=True)

    assert summary.has_wcs is False
    assert summary.attempted_backends == ["astrometry.net"]


def test_per_call_index_and_timeout_reach_the_algorithm(monkeypatch, tmp_path):
    captured = {}
    index_path = _configure_fake_anet(monkeypatch, tmp_path)

    def fake_solve(
        header,
        data,
        tmpdir,
        *,
        file_id=None,
        pixel_scale_hint_arcsec=None,
        solver_settings=None,
        search_bounds=None,
        solver_attempts=None,
        solver_failures=None,
    ):
        captured["file_id"] = file_id
        captured["solver_settings"] = solver_settings
        captured["pixel_scale_hint_arcsec"] = pixel_scale_hint_arcsec
        solver_attempts.append("astrometry.net")
        return WcsSolveResult(
            wcs=None,
            catalog_sources=(),
            metadata=WcsSolveMetadata(width_px=1056, height_px=1027),
        )

    monkeypatch.setattr("tools.wcs._solve_wcs", fake_solve)

    summary = solve_astrometry(
        OPEN_FRAME,
        index_path=index_path,
        timeout_s=12.5,
    )

    settings = captured["solver_settings"]
    assert settings.ANET_INDEX_PATH == [str(index_path)]
    assert settings.ANET_TIMEOUT_S == 12.5
    assert settings.ATLAS_TIMEOUT_S == 12.5
    assert captured["file_id"] is None
    assert captured["pixel_scale_hint_arcsec"] is not None
    assert summary.has_wcs is False
    assert summary.attempted_backends == ["astrometry.net"]
    assert "no_solution" in [warning.code for warning in summary.warnings]


def test_build_anet_config_applies_the_configured_timeout(tmp_path):
    settings = SolverSettings(
        anet_index_path=tmp_path,
        anet_timeout_s=17.0,
    )

    config = build_anet_config(settings)

    assert config is not None
    assert config.index_path == str(tmp_path)
    assert config.timeout_s == 17.0


@pytest.mark.parametrize("timeout_s", [0, 0.5, -1, float("nan")])
def test_timeout_must_be_at_least_one_finite_second(timeout_s):
    summary = solve_astrometry(OPEN_FRAME, timeout_s=timeout_s)

    assert [error.code for error in summary.errors] == ["invalid_timeout"]


def test_invalid_timeout_from_environment_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("ANET_INDEX_PATH", str(tmp_path))
    monkeypatch.setenv("ANET_TIMEOUT_S", "nan")

    summary = solve_astrometry(OPEN_FRAME)

    assert [error.code for error in summary.errors] == ["invalid_timeout"]
    assert "ANET_TIMEOUT_S" in summary.errors[0].message


@pytest.mark.parametrize("missing_binary", [False, True])
def test_an_invalid_astrometry_net_install_is_unavailable(
    monkeypatch,
    tmp_path,
    missing_binary,
):
    monkeypatch.delenv("ATLAS_CATALOG_ROOT", raising=False)
    index_path = tmp_path / "indexes"
    index_path.mkdir()
    executable = None if missing_binary else "/fake/solve-field"
    monkeypatch.setattr("tools.wcs.find_solve_field", lambda: executable)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("an unavailable backend must not be invoked")

    monkeypatch.setattr("tools.wcs._solve_wcs", fail_if_called)

    summary = solve_astrometry(OPEN_FRAME, index_path=index_path)

    assert summary.attempted_backends == []
    assert "solver_unavailable" in [warning.code for warning in summary.warnings]


def test_a_backend_execution_error_is_not_reported_as_a_solve_miss(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("ATLAS_CATALOG_ROOT", raising=False)
    index_path = _configure_fake_anet(monkeypatch, tmp_path)

    def fail_backend(*args, **kwargs):
        raise AstrometryNetError("backend execution failed")

    monkeypatch.setattr("algorithms.wcs.wcs.anet_solve_field_glob", fail_backend)

    summary = solve_astrometry(OPEN_FRAME, index_path=index_path)

    assert summary.attempted_backends == ["astrometry.net"]
    assert [error.code for error in summary.errors] == ["solver_failed"]
    assert "backend execution failed" in summary.errors[0].message
    assert "no_solution" not in [warning.code for warning in summary.warnings]


def test_an_atlas_execution_error_is_not_reported_as_a_solve_miss(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("ANET_INDEX_PATH", raising=False)
    catalog_root = tmp_path / "ucac5"
    (catalog_root / "u5z").mkdir(parents=True)
    (catalog_root / "u5z" / "u5index.asc").touch()
    monkeypatch.setenv("ATLAS_CATALOG_ROOT", str(catalog_root))

    def fail_backend(*args, **kwargs):
        raise OSError("catalog read failed")

    monkeypatch.setattr(
        "algorithms.wcs.wcs.AtlasBackend.solve",
        fail_backend,
    )

    summary = solve_astrometry(OPEN_FRAME)

    assert summary.attempted_backends == ["atlas"]
    assert [error.code for error in summary.errors] == ["solver_failed"]
    assert "catalog read failed" in summary.errors[0].message


def test_write_header_refuses_to_modify_a_bundled_fixture():
    summary = solve_astrometry(SOLVED_FRAME, write_header=True)

    assert [error.code for error in summary.errors] == [
        "refusing_to_modify_fixture"
    ]


def test_the_fixture_guard_exempts_the_archive_download_root():
    """The download root moved inside ``data/`` when the fixture tree was
    renamed. Guarding the whole tree would refuse to write a solved header
    back into a *downloaded* frame -- reporting an archive product as a
    bundled fixture, and closing the archive -> analysis loop BL-11 opened.
    """
    from tools.wcs import _under_fixture_root

    downloads = ROOT / "data" / "fits_downloads"

    assert _under_fixture_root(SOLVED_FRAME)
    assert not _under_fixture_root(
        downloads / "mastDownload" / "HST" / "idxq01010" / "idxq01010_drz.fits"
    )


def test_the_fixture_guard_cannot_be_disabled_by_the_download_root_setting(monkeypatch):
    """Code review of the first draft: exempting whatever FITS_DOWNLOAD_DIR
    named meant KEPLER_FITS_DOWNLOAD_DIR=<repo>/data switched the guard off for
    every fixture. The guard names the fixture subtrees and reads no setting.
    """
    from tools import config
    from tools.wcs import _under_fixture_root

    for misconfigured in (ROOT / "data", ROOT / "data" / "optical", ROOT):
        monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", misconfigured)
        assert _under_fixture_root(SOLVED_FRAME), misconfigured


def test_the_fixture_subtrees_match_the_directories_actually_present():
    """A new fixture subtree under data/ has to be added to the guard, or its
    frames are writable. The only directory allowed to exist there unlisted is
    the archive download root, and no FITS file may sit loose at the top."""
    from tools.wcs import _FIXTURE_ROOT, _FIXTURE_SUBTREES

    present = {
        p.name
        for p in _FIXTURE_ROOT.iterdir()
        if p.is_dir() and p.name != "fits_downloads" and not p.name.startswith(".")
    }

    assert present == set(_FIXTURE_SUBTREES)
    assert list(_FIXTURE_ROOT.glob("*.fits")) == []


def test_the_fixture_guard_does_not_travel_with_the_data_dir_setting(monkeypatch):
    """KEPLER_DATA_DIR points at where downloads land and how far a search may
    walk. Pointing it at an operator's own archive does not make that archive a
    tree of fixtures, nor make this repository's frames writable.
    """
    from tools import config
    from tools.wcs import _under_fixture_root

    monkeypatch.setattr(config, "DATA_DIR", Path("/somewhere/else"))

    assert _under_fixture_root(SOLVED_FRAME)
    assert not _under_fixture_root(Path("/somewhere/else/optical/frame.fits"))


def test_write_header_persists_a_successful_solution(monkeypatch, tmp_path):
    target = tmp_path / "unsolved.fits"
    shutil.copyfile(OPEN_FRAME, target)
    fits.setval(target, "OBSERVER", value="preserve this")
    solved_wcs = WCS(fits.getheader(SOLVED_FRAME), relax=True)
    index_path = _configure_fake_anet(monkeypatch, tmp_path)

    def fake_solve(
        header,
        data,
        tmpdir,
        *,
        file_id=None,
        pixel_scale_hint_arcsec=None,
        solver_settings=None,
        search_bounds=None,
        solver_attempts=None,
        solver_failures=None,
    ):
        header.update(solved_wcs.to_header(relax=True))
        solver_attempts.append("astrometry.net")
        return WcsSolveResult(
            wcs=solved_wcs,
            catalog_sources=(),
            metadata=WcsSolveMetadata(width_px=1056, height_px=1027),
        )

    monkeypatch.setattr("tools.wcs._solve_wcs", fake_solve)

    summary = solve_astrometry(
        target,
        index_path=index_path,
        write_header=True,
    )

    assert summary.has_wcs is True
    assert summary.errors == []
    written = fits.getheader(target)
    assert written["CTYPE1"].startswith("RA---")
    assert written["CTYPE2"].startswith("DEC--")
    assert written["OBSERVER"] == "preserve this"
    assert summary.attempted_backends == ["astrometry.net"]


def test_write_header_refuses_to_overwrite_a_file_changed_during_solve(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "changed-during-solve.fits"
    shutil.copyfile(OPEN_FRAME, target)
    solved_wcs = WCS(fits.getheader(SOLVED_FRAME), relax=True)
    index_path = _configure_fake_anet(monkeypatch, tmp_path)

    def fake_solve(
        header,
        data,
        tmpdir,
        *,
        file_id=None,
        pixel_scale_hint_arcsec=None,
        solver_settings=None,
        search_bounds=None,
        solver_attempts=None,
        solver_failures=None,
    ):
        with fits.open(target, mode="update", memmap=False) as hdul:
            hdul[0].header["OBSERVER"] = "changed concurrently"
            hdul.flush()
        header.update(solved_wcs.to_header(relax=True))
        solver_attempts.append("astrometry.net")
        return WcsSolveResult(
            wcs=solved_wcs,
            catalog_sources=(),
            metadata=WcsSolveMetadata(width_px=1056, height_px=1027),
        )

    monkeypatch.setattr("tools.wcs._solve_wcs", fake_solve)

    summary = solve_astrometry(
        target,
        index_path=index_path,
        write_header=True,
    )

    assert [error.code for error in summary.errors] == ["file_changed"]
    written = fits.getheader(target)
    assert written["OBSERVER"] == "changed concurrently"
    assert "CTYPE1" not in written


def test_solve_astrometry_is_registered():
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    assert TOOL_FUNCTIONS["solve_astrometry"] is solve_astrometry
    schemas = {schema["name"]: schema for schema in TOOL_SCHEMAS}
    properties = schemas["solve_astrometry"]["input_schema"]["properties"]
    assert set(properties) == {
        "path",
        "index_path",
        "write_header",
        "timeout_s",
        "force",
        "search_radius_deg",
        "min_scale_arcsec",
        "max_scale_arcsec",
    }
    assert properties["search_radius_deg"]["exclusiveMinimum"] == 0
    assert properties["search_radius_deg"]["maximum"] == 180
    assert properties["min_scale_arcsec"]["exclusiveMinimum"] == 0
    assert properties["max_scale_arcsec"]["exclusiveMinimum"] == 0


@pytest.mark.solver_data
@solver_available
def test_the_solver_runs_and_reports_its_outcome_either_way():
    """Exercise the real backend without claiming the installed indexes solve M15."""

    summary = solve_astrometry(
        OPEN_FRAME,
        index_path=os.environ["ANET_INDEX_PATH"],
        timeout_s=900,
    )

    assert summary.errors == []
    codes = [warning.code for warning in summary.warnings]
    assert "solver_unavailable" not in codes
    assert "astrometry.net" in summary.attempted_backends
    if summary.has_wcs:
        assert summary.center_ra_deg == pytest.approx(322.49, abs=0.2)
        assert summary.center_dec_deg == pytest.approx(12.167, abs=0.2)
    else:
        assert "no_solution" in codes


# ---------------------------------------------------------------------------
# Explicit search bounds (P6)
# ---------------------------------------------------------------------------

def _fake_solve_recording(captured, metadata=None, *, raises=None):
    """A ``solve_wcs`` stand-in that records its keyword arguments."""

    def fake_solve(header, data, tmpdir, **kwargs):
        captured.update(kwargs)
        if raises is not None:
            raise raises
        kwargs["solver_attempts"].append("astrometry.net")
        return WcsSolveResult(
            wcs=None,
            catalog_sources=(),
            metadata=metadata or WcsSolveMetadata(width_px=1056, height_px=1027),
        )

    return fake_solve


def test_search_bounds_reach_the_algorithm_as_one_bounds_object(monkeypatch, tmp_path):
    from algorithms.wcs.config import WcsSearchBounds

    captured = {}
    index_path = _configure_fake_anet(monkeypatch, tmp_path)
    monkeypatch.setattr("tools.wcs._solve_wcs", _fake_solve_recording(captured))

    solve_astrometry(
        OPEN_FRAME,
        index_path=index_path,
        search_radius_deg=2.0,
        min_scale_arcsec=0.4,
        max_scale_arcsec=0.8,
    )

    assert captured["search_bounds"] == WcsSearchBounds(
        radius_deg=2.0, min_scale_arcsec=0.4, max_scale_arcsec=0.8
    )


def test_a_default_call_sets_no_search_bound(monkeypatch, tmp_path):
    """The parity search: the algorithm sees an override that overrides nothing."""
    captured = {}
    index_path = _configure_fake_anet(monkeypatch, tmp_path)
    monkeypatch.setattr("tools.wcs._solve_wcs", _fake_solve_recording(captured))

    solve_astrometry(OPEN_FRAME, index_path=index_path)

    assert captured["search_bounds"].explicit == ()


@pytest.mark.parametrize(
    "bounds",
    [
        {"search_radius_deg": 0},
        {"search_radius_deg": -1},
        {"search_radius_deg": 180.5},
        {"search_radius_deg": float("nan")},
        {"search_radius_deg": float("inf")},
        {"search_radius_deg": "two"},
        {"min_scale_arcsec": 0},
        {"min_scale_arcsec": float("nan")},
        {"max_scale_arcsec": 0},
        {"max_scale_arcsec": float("inf")},
        {"min_scale_arcsec": 2.0, "max_scale_arcsec": 1.0},
        {"min_scale_arcsec": 1.0, "max_scale_arcsec": 1.0},
        # A single bound is checked against the other side's default (0.1–60).
        {"min_scale_arcsec": 70.0},
        {"max_scale_arcsec": 0.05},
    ],
)
def test_invalid_search_bounds_are_rejected_before_anything_runs(monkeypatch, bounds):
    """Checked at the tool boundary, before backend configuration is even
    looked at -- so an unconfigured solver still reports the input problem."""
    monkeypatch.delenv("ANET_INDEX_PATH", raising=False)
    monkeypatch.delenv("ATLAS_CATALOG_ROOT", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("the solver must not run with invalid bounds")

    monkeypatch.setattr("tools.wcs._solve_wcs", fail_if_called)

    summary = solve_astrometry(OPEN_FRAME, **bounds)

    assert summary.has_wcs is False
    assert [error.code for error in summary.errors] == ["invalid_search_bounds"]
    assert summary.warnings == []
    assert summary.search is None


def test_the_effective_search_is_reported_in_the_summary(monkeypatch, tmp_path):
    captured = {}
    index_path = _configure_fake_anet(monkeypatch, tmp_path)
    metadata = WcsSolveMetadata(
        width_px=1056,
        height_px=1027,
        search_radius_deg=2.0,
        search_min_scale_arcsec=0.4,
        search_max_scale_arcsec=60.0,
        search_center_ra_deg=322.4929,
        search_center_dec_deg=12.1669,
    )
    monkeypatch.setattr("tools.wcs._solve_wcs", _fake_solve_recording(captured, metadata))

    summary = solve_astrometry(
        OPEN_FRAME, index_path=index_path, search_radius_deg=2.0, min_scale_arcsec=0.4
    )

    assert summary.search is not None
    assert summary.search.radius_deg == 2.0
    assert summary.search.all_sky is False
    assert summary.search.min_scale_arcsec == 0.4
    assert summary.search.max_scale_arcsec == 60.0
    assert summary.search.center_ra_deg == pytest.approx(322.4929)
    assert summary.search.center_dec_deg == pytest.approx(12.1669)
    assert summary.search.explicit == ["radius_deg", "min_scale_arcsec"]
    assert "no_solution" in [warning.code for warning in summary.warnings]


def test_a_default_search_is_reported_as_all_sky(monkeypatch, tmp_path):
    captured = {}
    index_path = _configure_fake_anet(monkeypatch, tmp_path)
    metadata = WcsSolveMetadata(
        width_px=1056,
        height_px=1027,
        search_radius_deg=180.0,
        search_min_scale_arcsec=0.1,
        search_max_scale_arcsec=60.0,
        search_center_ra_deg=322.4929,
        search_center_dec_deg=12.1669,
    )
    monkeypatch.setattr("tools.wcs._solve_wcs", _fake_solve_recording(captured, metadata))

    summary = solve_astrometry(OPEN_FRAME, index_path=index_path)

    assert summary.search.all_sky is True
    assert summary.search.radius_deg == 180.0
    assert summary.search.explicit == []


def test_a_bounded_radius_without_a_hint_is_a_named_error(monkeypatch, tmp_path):
    """Not a ``solver_failed``: no backend ran, and the fix is on the input side."""
    from algorithms.wcs.wcs import SearchRadiusWithoutHint

    captured = {}
    index_path = _configure_fake_anet(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "tools.wcs._solve_wcs",
        _fake_solve_recording(
            captured, raises=SearchRadiusWithoutHint("search radius 2 deg needs a pointing hint")
        ),
    )

    summary = solve_astrometry(OPEN_FRAME, index_path=index_path, search_radius_deg=2.0)

    assert summary.has_wcs is False
    assert [error.code for error in summary.errors] == ["search_radius_without_hint"]
    assert "pointing hint" in summary.errors[0].message
    assert summary.attempted_backends == []
    assert summary.search is None


def test_a_header_wcs_short_circuit_reports_no_search(monkeypatch):
    summary = solve_astrometry(SOLVED_FRAME)

    assert "wcs_from_header" in [warning.code for warning in summary.warnings]
    assert summary.search is None


@pytest.mark.solver_data
@solver_available
def test_an_explicit_scale_window_runs_a_bounded_solve():
    """P6's exit criterion, against the real backend: a caller who knows the
    frame's scale and pointing gets a bounded search rather than an all-sky one,
    and the result says which search ran. The M15 frame's header carries
    SECPIX 0.586 and its pointing keywords; whether the installed indexes cover
    a 10-arcmin field decides has_wcs, so both outcomes are accepted.
    """

    summary = solve_astrometry(
        OPEN_FRAME,
        index_path=os.environ["ANET_INDEX_PATH"],
        timeout_s=300,
        search_radius_deg=1.0,
        min_scale_arcsec=0.4,
        max_scale_arcsec=0.8,
    )

    assert summary.errors == []
    assert "astrometry.net" in summary.attempted_backends
    assert summary.search is not None
    assert summary.search.all_sky is False
    assert summary.search.radius_deg == 1.0
    assert summary.search.min_scale_arcsec == 0.4
    assert summary.search.max_scale_arcsec == 0.8
    assert summary.search.center_ra_deg == pytest.approx(322.49, abs=0.01)
    assert summary.search.center_dec_deg == pytest.approx(12.167, abs=0.01)
    assert summary.search.explicit == ["radius_deg", "min_scale_arcsec", "max_scale_arcsec"]
    codes = [warning.code for warning in summary.warnings]
    if summary.has_wcs:
        assert summary.center_ra_deg == pytest.approx(322.49, abs=0.2)
        assert summary.center_dec_deg == pytest.approx(12.167, abs=0.2)
    else:
        assert "no_solution" in codes
