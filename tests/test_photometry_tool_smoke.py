from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tools.claude_photometry_haiku_tool import (
    list_bundled_targets,
    magnitude_label_for,
    resolve_fits_path,
    resolve_zero_point_mag,
    summarize_results,
)


class DummyHeader(dict):
    pass


def test_resolve_zero_point_mag_from_header() -> None:
    header = DummyHeader({"PHOT_M0": 17.2})
    assert resolve_zero_point_mag(Path("dummy.fits"), header) == 17.2


def test_resolve_zero_point_mag_returns_none_when_missing() -> None:
    header = DummyHeader({"FILTER": "R"})
    assert resolve_zero_point_mag(Path("dummy.fits"), header) is None


def test_summarize_results_uses_supplied_magnitude_label() -> None:
    results = [
        SimpleNamespace(mag=12.5, flux=100.0),
        SimpleNamespace(mag=13.0, flux=200.0),
    ]

    summary = summarize_results(results, "calibrated magnitude")

    assert "median calibrated magnitude" in summary


def test_resolve_fits_path_accepts_repo_test_subject_name() -> None:
    resolved = resolve_fits_path("ngc1846_cluster_r_000")

    assert resolved.is_file()
    assert resolved.name == "ngc1846_cluster_r_000.fits"


def test_list_bundled_targets_groups_repo_test_subjects() -> None:
    targets = list_bundled_targets()

    assert "cluster" in targets
    assert "ngc1846_cluster_r_000" in targets["cluster"]


def test_magnitude_label_distinguishes_unverified_zero_points() -> None:
    zero_point = SimpleNamespace(value=17.2, verified=False)

    assert magnitude_label_for(zero_point) == "magnitude (unverified zero point applied)"


def test_check_only_cli_resolves_bundled_subject() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tool_path = repo_root / "tools" / "claude_photometry_haiku_tool.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "ngc1846_cluster_r_000",
            "--check-only",
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FOUND " in completed.stdout
    assert "ngc1846_cluster_r_000.fits" in completed.stdout
