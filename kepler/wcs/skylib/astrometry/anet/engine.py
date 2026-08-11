"""Discovery helpers for the system astrometry.net engine.

v2 note: replaces the old in-process SWIG ``AstrometryNetSolver``. There is no
compiled engine to load any more — we just locate the ``solve-field`` binary and
parse the bundled NGC catalog for the globular-cluster masking refinement used
by :func:`skylib.astrometry.anet.backend.solve_field_glob`.

Resolution order
----------------
Binary (:func:`find_solve_field`): explicit project config → environment
variable (``SKYLIB_ASTROMETRYNET_SOLVE_FIELD`` / ``SKYLIB_ANET_SOLVE_FIELD``)
→ ``PATH`` lookup of ``solve-field`` (the usual case after a package-manager
install) → ``None`` (caller raises a clear error).

Index directories (:func:`resolve_index_dirs`): explicit project config →
environment variable (``SKYLIB_ASTROMETRYNET_INDEX_PATH`` /
``SKYLIB_ANET_INDEX_ROOT``, ``os.pathsep``-separated). :func:`validate_index_dirs`
then drops any that don't exist or hold no recognizable index files (the standard
``index-*.fits``, vendor-prefixed ``*-index-*.fits`` such as UCAC5, or suffixless
``index-NNN`` such as TYCHO2 — see :data:`INDEX_FILE_CONVENTIONS`).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple, Union

#: Environment variables consulted (in order) for index directories when a
#: config doesn't specify them. The first is the name the test suite uses.
_INDEX_ENV_VARS = ("SKYLIB_ASTROMETRYNET_INDEX_PATH", "SKYLIB_ANET_INDEX_ROOT")

#: Environment variables consulted (in order) for the solve-field binary when a
#: config doesn't specify it.
_SOLVE_FIELD_ENV_VARS = ("SKYLIB_ASTROMETRYNET_SOLVE_FIELD", "SKYLIB_ANET_SOLVE_FIELD")

#: Standard astrometry.net index filename glob. Retained as a module constant for
#: back-compat; the full set of recognized conventions is ``INDEX_FILE_CONVENTIONS``.
INDEX_FITS_GLOB = "index-*.fits"

#: Recognized astrometry.net index-file naming conventions, as ``(label, compiled
#: filename regex)`` pairs. ``solve-field``'s ``add_path`` + ``autoindex`` opens
#: and validates *every* file in a directory regardless of its name (it doesn't
#: filter by extension), so these patterns only gate which directories we pass on
#: — broad enough to cover the collections in production use (2MASS, UCAC5,
#: TYCHO2), narrow enough not to sweep in unrelated files (``.DS_Store``,
#: READMEs, …) and report a directory of junk as usable.
INDEX_FILE_CONVENTIONS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    # Standard astrometry.net build: index-4200-00.fits (optionally .fz/.gz).
    ("standard", re.compile(r"^index-.+\.fits(\.[fg]z)?$", re.IGNORECASE)),
    # Vendor-prefixed FITS index: UCAC5 ucac5-index-00-00.fits.
    ("vendor-prefixed", re.compile(r"^.+-index-.+\.fits(\.[fg]z)?$", re.IGNORECASE)),
    # Suffixless series: TYCHO2 index-205, index-206 (valid FITS, no extension).
    ("suffixless", re.compile(r"^index-\d+(?:-\d+)*$")),
)

#: Human-readable description of the supported conventions, for error/log text.
SUPPORTED_INDEX_DESC = (
    "index-*.fits, <prefix>-index-*.fits (e.g. ucac5-index-*.fits), "
    "or suffixless index-NNN (e.g. TYCHO2 index-205)"
)


def _index_convention(name: str) -> Optional[str]:
    """Return the convention label for an index filename, or None if unrecognized."""
    for label, pattern in INDEX_FILE_CONVENTIONS:
        if pattern.match(name):
            return label
    return None


def detect_index_conventions(path: Union[str, Path]) -> List[str]:
    """Return the sorted set of index-file convention labels present in ``path``.

    Empty when the directory holds no recognizable astrometry.net index files.
    Used both to decide whether a directory is usable (:func:`validate_index_dirs`)
    and to report which naming convention(s) were detected for diagnostics —
    without logging every individual index file.
    """
    labels: Set[str] = set()
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                label = _index_convention(entry.name)
                if label is not None:
                    labels.add(label)
    except OSError:
        return []
    return sorted(labels)


def _resolve_executable(name: str) -> Optional[str]:
    """Resolve a binary given as a path (must exist + be executable) or a bare
    name (looked up on ``PATH``). Returns the resolved path or ``None``."""

    if os.path.sep in name or (os.altsep and os.altsep in name):
        candidate = Path(name)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which(name)


def find_solve_field(explicit: Optional[str] = None) -> Optional[str]:
    """Return a usable ``solve-field`` executable path, or None if unavailable.

    Order: explicit project config → ``SKYLIB_ASTROMETRYNET_SOLVE_FIELD`` /
    ``SKYLIB_ANET_SOLVE_FIELD`` env var → ``PATH`` lookup. On Windows (where
    astrometry.net is generally not installed) and on any host without the
    binary this returns None, which callers use to skip the anet backend.
    """

    if explicit:
        return _resolve_executable(explicit)

    for var in _SOLVE_FIELD_ENV_VARS:
        value = os.getenv(var)
        if value:
            return _resolve_executable(value)

    return shutil.which("solve-field")


def solve_field_candidates(explicit: Optional[str] = None) -> List[str]:
    """Return the binary names/paths :func:`find_solve_field` would try, in
    order. Used to build an actionable error when none resolve."""

    if explicit:
        return [explicit]
    env = [os.getenv(var) for var in _SOLVE_FIELD_ENV_VARS]
    return [v for v in env if v] + ["solve-field"]


def resolve_index_dirs(
    index_path: Optional[Union[str, Sequence[str]]] = None,
) -> List[str]:
    """Normalize the configured/env index path(s) into a list of directories."""

    if index_path is None:
        for var in _INDEX_ENV_VARS:
            value = os.getenv(var)
            if value:
                index_path = value
                break
    if index_path is None:
        return []
    if isinstance(index_path, str):
        return [p for p in index_path.split(os.pathsep) if p]
    return [str(p) for p in index_path if p]


def validate_index_dirs(dirs: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split configured index directories into (usable, problems).

    A directory is usable if it exists, is a directory, and contains at least one
    file matching a recognized astrometry.net index naming convention (see
    :data:`INDEX_FILE_CONVENTIONS`): the standard ``index-*.fits``, vendor-prefixed
    ``*-index-*.fits`` (UCAC5), or suffixless ``index-NNN`` (TYCHO2). ``problems``
    holds one human-readable string per rejected directory, suitable for an error
    message.
    """

    usable: List[str] = []
    problems: List[str] = []
    for raw in dirs:
        path = Path(raw)
        if not path.exists():
            problems.append(f"{raw}: does not exist")
            continue
        if not path.is_dir():
            problems.append(f"{raw}: not a directory")
            continue
        if not detect_index_conventions(path):
            problems.append(f"{raw}: no astrometry.net index files ({SUPPORTED_INDEX_DESC})")
            continue
        usable.append(str(path))
    return usable, problems


def load_ngc_globular_clusters() -> List[List[float]]:
    """Parse ``ngc2000.dat`` for globular clusters.

    Returns a list of ``[ra_hours, dec_degs, radius_degs]`` entries (type ``Gb``),
    used to mask cluster cores before re-solving crowded fields.
    """

    globs: List[List[float]] = []
    ngc_path = Path(__file__).with_name("ngc2000.dat")
    if not ngc_path.exists():
        return globs
    with ngc_path.open() as handle:
        for line in handle.read().splitlines():
            try:
                typ = line[6:9].strip()
                if typ != "Gb":
                    continue
                ra_h, ra_m = line[10:12], line[13:17]
                dec_s, dec_d, dec_m = line[19], line[20:22], line[23:25]
                ra = int(ra_h) + float(ra_m) / 60
                dec = (1 - 2 * (dec_s == "-")) * (int(dec_d) + int(dec_m) / 60.0)
                r = float(line[33:38]) / 2
                globs.append([ra, dec, r / 60])
            except Exception:
                pass
    return globs


__all__ = [
    "find_solve_field",
    "solve_field_candidates",
    "resolve_index_dirs",
    "validate_index_dirs",
    "detect_index_conventions",
    "load_ngc_globular_clusters",
    "INDEX_FITS_GLOB",
    "INDEX_FILE_CONVENTIONS",
    "SUPPORTED_INDEX_DESC",
]
