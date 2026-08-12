"""Small environment-backed settings helpers for Kepler tools."""

from __future__ import annotations

import os
from pathlib import Path

ARTIFACT_DIR_ENV = "KEPLER_ARTIFACT_DIR"
FITS_DOWNLOAD_DIR_ENV = "KEPLER_FITS_DOWNLOAD_DIR"


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


# Resolved to an absolute path at import. Artifact paths are handed back to
# callers who may write files, change directory, or pass the path to another
# process, and a bare "artifacts/..." silently means something different in
# each of those. This also keeps ArtifactRef.path consistent with
# FileMetadata.path, which describe_file() has always resolved.
ARTIFACT_DIR = (env_path(ARTIFACT_DIR_ENV, "artifacts") or Path("artifacts")).resolve()
FITS_DOWNLOAD_DIR = env_path(FITS_DOWNLOAD_DIR_ENV, "fits_downloads") or Path(
    "fits_downloads"
)
PREVIEW_ROWS = int(env_value("KEPLER_PREVIEW_ROWS", "10") or "10")
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
