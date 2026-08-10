"""Local file artifact helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from mimetypes import guess_type
from pathlib import Path

from .config import artifact_directory
from .models import ArtifactMetadata, FileMetadata

_FITS_SUFFIXES = {".fit", ".fits", ".fts"}
_TABLE_SUFFIXES = {".csv", ".ecsv", ".parquet", ".tsv"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
_TEXT_SUFFIXES = {".json", ".log", ".md", ".txt", ".yaml", ".yml"}


def describe_file(path: str | Path) -> FileMetadata:
    """Return basic local file metadata without reading file contents."""

    resolved = Path(path).expanduser().resolve(strict=False)
    exists = resolved.exists()
    if not exists:
        return FileMetadata(
            path=str(resolved),
            exists=False,
            suffix=resolved.suffix or None,
        )

    stat = resolved.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    is_file = resolved.is_file()
    return FileMetadata(
        path=str(resolved),
        exists=True,
        is_file=is_file,
        size_bytes=stat.st_size if is_file else None,
        modified_time=modified,
        suffix=resolved.suffix or None,
    )


def artifact_type_for_path(path: str | Path) -> str:
    """Infer a coarse artifact type from the filename suffix."""

    suffix = Path(path).suffix.lower()
    if suffix in _FITS_SUFFIXES:
        return "fits"
    if suffix in _TABLE_SUFFIXES:
        return "table"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _TEXT_SUFFIXES:
        return "text"
    return "file"


def describe_artifact_file(path: str | Path) -> ArtifactMetadata:
    """Describe a single local artifact file."""

    file = describe_file(path)
    media_type, _encoding = guess_type(file.path)
    return ArtifactMetadata(
        file=file,
        artifact_type=artifact_type_for_path(file.path),
        media_type=media_type,
    )


def list_artifact_files(directory: str | Path | None = None) -> list[ArtifactMetadata]:
    """List direct child files in the artifact directory."""

    root = artifact_directory(directory)
    if not root.exists():
        return []
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    return [
        describe_artifact_file(path)
        for path in sorted(root.iterdir())
        if path.is_file()
    ]
