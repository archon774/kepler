"""Small environment-backed settings helpers for Kepler tools."""

from __future__ import annotations

import os
from pathlib import Path

ARTIFACT_DIR_ENV = "KEPLER_ARTIFACT_DIR"
DATA_DIR_ENV = "KEPLER_DATA_DIR"
FITS_DOWNLOAD_DIR_ENV = "KEPLER_FITS_DOWNLOAD_DIR"
ISOCHRONE_DIR_ENV = "KEPLER_ISOCHRONE_DIR"
MAX_FRAMES_ENV = "KEPLER_MAX_FRAMES"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def env_value(name: str, default: str | None = None) -> str | None:
    """Return a non-empty environment variable, or ``default``."""

    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def env_path(name: str, default: str | Path | None = None) -> Path | None:
    """Return an expanded path from the environment, or ``default``."""

    value = env_value(name)
    if value is None:
        value = str(default) if default is not None else None
    if value is None:
        return None
    return Path(value).expanduser()


def env_positive_int(name: str, default: int) -> int:
    """An integer setting that must be at least 1, or ``default``.

    Zero and negatives are rejected at load rather than clamped: a cap of 0
    would return empty listings, and a negative one would slice from the end
    while the truncation warning still claimed "the first N".
    """

    raw = env_value(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer >= 1, got {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    return value


def safe_resolve(path: Path) -> Path:
    """``path.resolve()``, falling back to ``path`` when the filesystem refuses.

    A symlink loop raises ``RuntimeError`` on Python 3.12 -- the floor in
    ``pyproject.toml`` -- and ``OSError`` for other filesystem refusals;
    non-strict resolution on 3.13+ raises nothing for the loop. One helper so
    every containment check in ``tools`` handles all three the same way.
    """

    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def within(path: Path, root: Path) -> bool:
    """Whether ``path`` resolves inside ``root``.

    Both sides are resolved before comparing, so a symlink whose name sits
    under ``root`` but whose target does not is outside it. A path that cannot
    be resolved is treated as outside: both callers use this to decide whether
    something is *safe* (to walk, to write), and an unresolvable path is not.
    """

    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


# Resolved to an absolute path at import. Artifact paths are handed back to
# callers who may write files, change directory, or pass the path to another
# process, and a bare "artifacts/..." silently means something different in
# each of those. This also keeps ArtifactRef.path consistent with
# FileMetadata.path, which describe_file() has always resolved.
ARTIFACT_DIR = (env_path(ARTIFACT_DIR_ENV, "artifacts") or Path("artifacts")).resolve()
# The repository's data root: where general data for this repo lives -- the
# bundled fixture frames and recorded reference solves, and now the archive
# download root too.
#
# It is also a *boundary*. tools.optical walks the download root recursively,
# because astroquery nests MAST products under mastDownload/<mission>/<obs_id>/,
# and a recursive walk is only safe while it is confined to a directory that
# holds astronomy data and nothing else. A download root pointed outside this
# tree is searched flat instead of walked -- see tools.optical._optical_data_roots.
#
# Overriding this moves the download root and the recursion boundary. It does
# *not* move the frame library, which has its own override
# (KEPLER_OPTICAL_DATA_DIR); by default both live under this directory.
DATA_DIR = env_path(DATA_DIR_ENV, _REPO_ROOT / "data").resolve()

# Defaults inside DATA_DIR rather than beside the working directory. A bare
# relative "fits_downloads" meant the download root moved with whatever
# directory the process happened to start in, so the same configuration
# resolved to a different place per caller. Resolved for the same reason
# ARTIFACT_DIR is: a frame's reported path is handed back to a caller who will
# pass it to another tool.
#
# Derived from DATA_DIR at import. Reassigning DATA_DIR at runtime does *not*
# move this; a caller that reassigns one must reassign both, as
# tests/conftest.py does. Setting the environment variables is the supported
# way to move them together.
FITS_DOWNLOAD_DIR = env_path(FITS_DOWNLOAD_DIR_ENV, DATA_DIR / "fits_downloads").resolve()
# The legacy Girardi model is a substantial operator dependency, not Kepler
# data.  Deliberately no default: silently looking in a repository-relative
# directory would make a missing model look bundled and conceal setup errors.
ISOCHRONE_DIR = env_path(ISOCHRONE_DIR_ENV)
PREVIEW_ROWS = int(env_value("KEPLER_PREVIEW_ROWS", "10") or "10")
# How many frames one list_optical_frames call reads headers for and returns.
# Not a tool parameter: the cap exists so a bulk archive download cannot make a
# single listing read thousands of FITS headers and serialise them all into a
# model's context (search_mast records 121,515 products for Cas A alone).
# Callers that genuinely want more raise it here; the listing says when it
# truncated rather than dropping frames silently.
DEFAULT_MAX_FRAMES = env_positive_int(MAX_FRAMES_ENV, 200)
DEFAULT_MAX_CATALOGS = int(env_value("KEPLER_MAX_CATALOGS", "20") or "20")
DEFAULT_MAX_OBSERVATIONS = int(
    env_value("KEPLER_MAX_OBSERVATIONS", "25") or "25"
)
CASDA_OPAL_USERNAME = env_value("CASDA_OPAL_USERNAME")


def artifact_directory(directory: str | Path | None = None) -> Path:
    """Resolve the local artifact directory for workspace tools."""

    if directory is not None:
        return Path(directory).expanduser().resolve()
    return ARTIFACT_DIR.expanduser().resolve()
