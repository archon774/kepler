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
from typing import Callable, Mapping

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


def _ads_token_available(environ: Mapping[str, str], home: Path | None = None) -> bool:
    """astroquery's own lookup: ``ADS_DEV_KEY``, then ``~/.ads/dev_key``.

    Reporting only the variable told a user whose token is in the file -- the
    place astroquery documents -- that the ADS tools would fail, when they
    work.
    """

    if environ.get("ADS_DEV_KEY"):
        return True
    try:
        token_file = (Path.home() if home is None else home) / ".ads" / "dev_key"
        return token_file.is_file() and bool(token_file.read_text(encoding="utf-8").strip())
    except (OSError, RuntimeError, KeyError, UnicodeDecodeError):
        return False


def _checked(probe: Callable[[], bool]) -> bool | None:
    """A probe's answer, or ``None`` when the probe itself failed.

    These facts are read at server startup. A probe that raised -- an
    unreadable data directory, a malformed setting -- used to stop the server
    from starting at all, with a traceback on a stderr the user may never see;
    the fact is reported as unknown instead, and the tool concerned reports
    the real error when it is called.
    """

    try:
        return probe()
    except Exception:  # noqa: BLE001 -- a startup fact must never stop the server
        return None


def _mark(present: bool | None, missing: str) -> str:
    if present is None:
        return "unknown (check failed)"
    return "present" if present else missing


def install_facts(
    artifact_root: Path | str | None = None, environ: Mapping[str, str] | None = None
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
    ads = _checked(lambda: _ads_token_available(environ))
    solver = _checked(lambda: _plate_solving_available(environ))
    pulsar = _checked(_pulsar_scans_present)
    references = _checked(_references_present)
    frames = _checked(_frames_present)
    isochrones = _checked(_isochrones_present)
    if solver is None:
        solving = "unknown (check failed)"
    else:
        solving = "configured" if solver else "not configured (solve_astrometry reports unavailable)"

    return "\n".join(
        [
            "This install:",
            f"- Artifacts are local files under {root}; read them directly.",
            f"- Pulsar scans {_mark(pulsar, 'MISSING')}; zero-point "
            f"references {_mark(references, 'MISSING')}; optical frame library "
            f"{_mark(frames, 'absent (kepler-mcp fetch-data optical)')}; isochrone grid "
            f"{_mark(isochrones, 'absent (HR fit unavailable; fetch-data isochrones)')}; plate "
            f"solving {solving}.",
            "- Keys are the user's own, from this server's environment. An ADS token "
            + (
                "is set."
                if ads
                else "is not set (ADS_DEV_KEY or ~/.ads/dev_key): the ADS tools will report it missing."
            ),
        ]
    )
