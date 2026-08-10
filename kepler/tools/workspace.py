"""Workspace artifact tool wrappers."""

from __future__ import annotations

from pathlib import Path

from kepler.artifacts import describe_artifact_file, list_artifact_files
from kepler.models import ArtifactMetadata


def list_artifacts(directory: str | Path | None = None) -> list[ArtifactMetadata]:
    """List direct child artifact files in a local directory."""

    return list_artifact_files(directory)


def describe_artifact(path: str | Path) -> ArtifactMetadata:
    """Describe a single local artifact path."""

    return describe_artifact_file(path)
