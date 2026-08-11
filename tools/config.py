"""Small environment-backed settings helpers for Kepler tools."""

from __future__ import annotations

import os
from pathlib import Path

ARTIFACT_DIR_ENV = "KEPLER_ARTIFACT_DIR"


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


def artifact_directory(directory: str | Path | None = None) -> Path:
    """Resolve the local artifact directory for workspace tools."""

    if directory is not None:
        return Path(directory).expanduser().resolve()
    configured = env_path(ARTIFACT_DIR_ENV, ".")
    if configured is None:
        return Path(".").resolve()
    return configured.resolve()
