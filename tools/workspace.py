"""Workspace artifact tool wrappers."""

from __future__ import annotations

from pathlib import Path

from tools.artifacts import describe_artifact_file, list_artifact_files
from tools.models import ArtifactMetadata
from tools.sessions import list_session_manifests, read_session_manifest


def list_artifacts(directory: str | Path | None = None) -> list[ArtifactMetadata]:
    """List direct child artifact files in a local directory."""

    return list_artifact_files(directory)


def describe_artifact(path: str | Path) -> ArtifactMetadata:
    """Describe a single local artifact path."""

    return describe_artifact_file(path)


def list_sessions(directory: str | Path | None = None) -> list[ArtifactMetadata]:
    """List saved agent-session manifests under the artifact directory."""

    return [describe_artifact_file(path) for path in list_session_manifests(directory)]


def describe_session(path: str | Path) -> dict:
    """Read a saved agent-session manifest file or session directory."""

    return read_session_manifest(path)
