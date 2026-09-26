"""What this install actually has, stated in the served instructions (C5).

A model on the other end of the server cannot see the user's disk or
environment. It needs to know, before it calls anything, which data is present
(so a missing bundle is not mistaken for an empty answer), that artifact paths
are local files it can read, and that any credential in play is the user's
own. :func:`install_facts` is that statement, kept short because it shares the
~2,000-character instruction budget with the skill brief
(``tools.skill.BRIEF_LIMIT``).

Reads only the environment and the filesystem; imports ``tools.config`` and so
must run after the roots are pinned. Values of credentials are never read into
the text -- only whether a variable is set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from tools import config

__all__ = ["install_facts"]


def _pulsar_scans_present() -> bool:
    from tools.pulsar import list_pulsar_scans

    listing = list_pulsar_scans()
    return bool(listing.scans) and not listing.errors


def _references_present() -> bool:
    from tools.fieldcal_reference import list_zeropoint_references

    return bool(list_zeropoint_references())


def _frames_present() -> bool:
    from tools.optical import bundled_frame_paths

    return bool(bundled_frame_paths())


def _isochrones_present() -> bool:
    grid = config.ISOCHRONE_DIR
    return grid is not None and grid.is_dir() and next(grid.glob("*.npy"), None) is not None


def _plate_solving_available(environ: Mapping[str, str]) -> bool:
    from algorithms.wcs.config import SolverSettings
    from tools.wcs import _configured_backend_warnings

    settings = SolverSettings(
        anet_index_path=environ.get("ANET_INDEX_PATH") or None,
        atlas_catalog_root=environ.get("ATLAS_CATALOG_ROOT") or None,
        atlas_catalog=environ.get("ATLAS_CATALOG") or None,
    )
    available, _warnings = _configured_backend_warnings(settings)
    return bool(available)


def _mark(present: bool, missing: str) -> str:
    return "present" if present else missing


def install_facts(
    artifact_root: Path | None = None, environ: Mapping[str, str] | None = None
) -> str:
    """A few lines describing this install, for the end of the instructions.

    Every fact is the answer the tools themselves give -- the same listing,
    the same data directory, the same backend check -- never a second guess
    at it. An earlier version looked in its own places (``DATA_DIR``, a
    recursive glob, "is the variable set") and could tell a model the scans
    were missing while ``list_pulsar_scans`` returned five of them, or that
    plate solving was configured when the index directory held no index files.
    """

    environ = os.environ if environ is None else environ
    root = config.ARTIFACT_DIR if artifact_root is None else artifact_root
    ads = bool(environ.get("ADS_DEV_KEY"))
    solver = _plate_solving_available(environ)

    return "\n".join(
        [
            "This install:",
            f"- Artifacts are local files under {root}; read them directly.",
            f"- Pulsar scans {_mark(_pulsar_scans_present(), 'MISSING')}; zero-point "
            f"references {_mark(_references_present(), 'MISSING')}; optical frame library "
            f"{_mark(_frames_present(), 'absent (kepler-mcp fetch-data optical)')}; isochrone grid "
            f"{_mark(_isochrones_present(), 'absent (HR fit unavailable; fetch-data isochrones)')}; plate "
            f"solving {'configured' if solver else 'not configured (solve_astrometry reports unavailable)'}.",
            "- Keys are the user's own, from this server's environment. ADS_DEV_KEY "
            + ("is set." if ads else "is not set: the ADS tools will report it missing."),
        ]
    )
