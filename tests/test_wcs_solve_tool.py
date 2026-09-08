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
OPEN_FRAME = ROOT / "test_data" / "optical" / "m15_globular_open_000.fits"
SOLVED_FRAME = ROOT / "test_data" / "optical" / "ngc5128_galaxy_b_001.fits"

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
    summary = solve_astrometry(ROOT / "test_data" / "optical" / "does_not_exist.fits")

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
    }


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
