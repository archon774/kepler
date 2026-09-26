"""Structural guards for the maintained stateless optical architecture."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_OPTICAL_API = (
    "ProcessingRun",
    "ProcessingRunRef",
    "ensure_wcs_solution",
    "_clear_wcs_solution_fields",
    "build_wcs_for_processing_run",
    "build_wcs_from_processing_run_solution",
    "wire_fieldcal_deps",
    "fieldcal.deps",
    "batch_wcs_photometry_zeropoint_export",
)

RETIRED_TYPESCRIPT_PATHS = (
    "algorithms/hrdiagram",
    "algorithms/lightcurve",
    "algorithms/periodogram",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
)


def test_current_python_has_no_optical_run_or_batch_api():
    """A tool call, not a persisted run, is Kepler's optical execution unit."""
    matches = []
    for directory in (ROOT / "algorithms", ROOT / "tools"):
        for path in directory.rglob("*.py"):
            text = path.read_text()
            for forbidden in FORBIDDEN_OPTICAL_API:
                if forbidden in text:
                    matches.append(f"{path.relative_to(ROOT)}: {forbidden}")

    assert matches == []


def test_gitignore_does_not_ignore_the_data_fixture_tree():
    """``data/`` was ``test_data/`` until the data-directory refactor, and a
    bare ``data/`` pattern was already in ``.gitignore`` for local scratch.
    Renaming into it would have made git ignore the whole ~175 MB fixture tree
    -- silently, since files already tracked stay tracked, so the breakage
    would surface only when someone added a fixture that never got committed.
    """
    patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert not patterns & {"data", "data/", "/data", "/data/"}


def test_retired_typescript_surface_stays_absent():
    """Kepler executes the Python ports and has no Node/TypeScript toolchain."""
    present = [path for path in RETIRED_TYPESCRIPT_PATHS if (ROOT / path).exists()]

    assert present == []
