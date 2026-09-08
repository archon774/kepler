"""Structural guards for the maintained stateless optical architecture."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_OPTICAL_API = (
    "ProcessingRun",
    "ProcessingRunRef",
    "ensure_wcs_solution",
    "build_wcs_for_processing_run",
    "build_wcs_from_processing_run_solution",
    "wire_fieldcal_deps",
    "fieldcal.deps",
    "batch_wcs_photometry_zeropoint_export",
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
