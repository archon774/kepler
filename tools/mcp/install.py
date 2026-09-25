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
from tools.optical import primary_optical_data_dir

__all__ = ["install_facts"]


def _has_files(directory: Path | None, pattern: str) -> bool:
    if directory is None or not directory.is_dir():
        return False
    return next(directory.rglob(pattern), None) is not None


def _mark(present: bool, missing: str) -> str:
    return "present" if present else missing


def install_facts(
    artifact_root: Path | None = None, environ: Mapping[str, str] | None = None
) -> str:
    """A few lines describing this install, for the end of the instructions."""

    environ = os.environ if environ is None else environ
    root = config.ARTIFACT_DIR if artifact_root is None else artifact_root
    data = config.DATA_DIR

    pulsar = _has_files(data / "pulsar", "*.txt")
    references = _has_files(data / "fieldcal", "*.json")
    optical = _has_files(primary_optical_data_dir(), "*.fits")
    isochrones = _has_files(config.ISOCHRONE_DIR, "*.npy")
    solver = bool(environ.get("ANET_INDEX_PATH") or environ.get("ATLAS_CATALOG_ROOT"))
    ads = bool(environ.get("ADS_DEV_KEY"))

    return "\n".join(
        [
            "This install:",
            f"- Artifacts are local files under {root}; read them directly.",
            f"- Pulsar scans {_mark(pulsar, 'MISSING')}; zero-point references "
            f"{_mark(references, 'MISSING')}; optical frame library "
            f"{_mark(optical, 'absent (kepler-mcp fetch-data optical)')}; isochrone grid "
            f"{_mark(isochrones, 'absent (HR fit unavailable; fetch-data isochrones)')}; plate "
            f"solving {'configured' if solver else 'not configured (solve_astrometry reports unavailable)'}.",
            "- Keys are the user's own, from this server's environment. ADS_DEV_KEY "
            + ("is set." if ads else "is not set: the ADS tools will report it missing."),
        ]
    )
