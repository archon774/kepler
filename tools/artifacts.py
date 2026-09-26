"""Local file and table artifact helpers."""

from __future__ import annotations

import os

import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from mimetypes import guess_type
from pathlib import Path
from typing import Iterator
from typing import Optional

from astropy.table import Table

from .config import ARTIFACT_DIR, artifact_directory
from .models import ArtifactMetadata, ArtifactRef, FileMetadata

__all__ = [
    "describe_file",
    "artifact_type_for_path",
    "describe_artifact_file",
    "list_artifact_files",
    "write_table",
    "write_text",
    "reserve_artifact_path",
    "reserve_path_in",
    "describe_artifact",
    "list_artifacts",
    "preview_rows",
    "current_artifact_subdir",
    "scoped_artifacts",
]

_FITS_SUFFIXES = {".fit", ".fits", ".fts"}
_TABLE_SUFFIXES = {".csv", ".ecsv", ".parquet", ".tsv"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
_AUDIO_SUFFIXES = {".aiff", ".flac", ".mp3", ".ogg", ".wav"}
_TEXT_SUFFIXES = {".json", ".log", ".md", ".txt", ".yaml", ".yml"}
_WRITE_SUFFIXES = {"ecsv": ".ecsv", "csv": ".csv", "fits": ".fits"}
_ACTIVE_ARTIFACT_SUBDIR: ContextVar[str | None] = ContextVar(
    "kepler_active_artifact_subdir", default=None
)


def current_artifact_subdir() -> str | None:
    """Return the active artifact subdirectory, if a caller scoped one."""

    return _ACTIVE_ARTIFACT_SUBDIR.get()


@contextmanager
def scoped_artifacts(subdir: str | Path) -> Iterator[None]:
    """Route artifact writes through ``subdir`` for the current context."""

    relative = Path(subdir)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"artifact scope must be a relative subdirectory: {subdir!r}")
    token = _ACTIVE_ARTIFACT_SUBDIR.set(str(relative))
    try:
        yield
    finally:
        _ACTIVE_ARTIFACT_SUBDIR.reset(token)


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
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
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


def _to_native(value):
    """Convert a numpy/masked scalar to a plain Python type where possible."""

    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except Exception:
            return value
    if isinstance(value, float) and value != value:
        return None
    return value


def preview_rows(table: Table, limit: int) -> list[dict]:
    """Return the first ``limit`` rows of ``table`` as JSON-safe dicts."""

    if table is None or len(table) == 0:
        return []
    n = min(limit, len(table))
    colnames = [str(c) for c in table.colnames]
    return [
        {name: _to_native(table[name][i]) for name in colnames} for i in range(n)
    ]


def _safe_stem(label: str) -> str:
    """Turn an arbitrary label into a safe filename stem."""

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    return stem or "artifact"


def _reserve_path(directory: Path, stem: str, suffix: str) -> Path:
    """Claim a path under ``directory`` that no other writer holds, and return it.

    The name is claimed by creating the file exclusively (``O_CREAT | O_EXCL``),
    not by checking that it does not exist. A check-then-write let two
    processes sharing one artifact root -- two MCP servers on the per-user
    root, one per host window -- receive the same path and overwrite each
    other's result. The placeholder is an empty file; every writer overwrites
    it.
    """

    directory.mkdir(parents=True, exist_ok=True)
    counter = 0
    while True:
        name = f"{stem}{suffix}" if counter == 0 else f"{stem}_{counter}{suffix}"
        path = directory / name
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            # Jump past the highest suffix already taken, once, rather than
            # probing _1, _2, ... one open at a time: on a shared root that is
            # never cleaned, that cost grew with every earlier file of this
            # stem. A name claimed meanwhile is still caught by O_EXCL.
            counter = max(counter, _highest_suffix(directory, stem, suffix)) + 1
            continue
        return path


def _highest_suffix(directory: Path, stem: str, suffix: str) -> int:
    """The largest ``n`` of an existing ``<stem>_<n><suffix>`` in ``directory``."""

    pattern = re.compile(re.escape(stem) + r"_(\d+)" + re.escape(suffix) + r"\Z")
    highest = 0
    try:
        for entry in os.scandir(directory):
            match = pattern.match(entry.name)
            if match:
                highest = max(highest, int(match.group(1)))
    except OSError:
        pass
    return highest


def reserve_path_in(directory: str | Path, name: str, ext: str) -> Path:
    """Claim a non-colliding ``<name>.<ext>`` in an explicit ``directory``.

    For writers that choose their own directory (a caller-supplied
    ``output_dir``) rather than an artifact subdirectory; same guarantee as
    :func:`reserve_artifact_path`.
    """
    return _reserve_path(Path(directory), _safe_stem(name), f".{ext.lstrip('.')}")


def discard_placeholder(path: str | Path | None) -> None:
    """Remove a reserved path that was never written, and nothing else.

    A reservation is an empty file (:func:`_reserve_path`). A writer that
    fails -- or, like a plot that finds nothing to draw, decides not to
    write -- would otherwise leave a 0-byte file that ``list_artifacts``
    reports as a result. Only an empty regular file is removed, so a path
    that did receive its content is never touched.
    """

    if path is None:
        return
    path = Path(path)
    try:
        if path.is_file() and not path.is_symlink() and path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass


def _write_directory(subdir: Optional[str]) -> Path:
    """Return the artifact write directory, including an active session scope."""

    directory = ARTIFACT_DIR
    active_subdir = current_artifact_subdir()
    if active_subdir:
        directory = directory / active_subdir
    if subdir:
        directory = directory / subdir
    return directory


def reserve_artifact_path(
    name: str, *, subdir: Optional[str] = None, ext: str = "bin"
) -> Path:
    """Reserve a non-colliding artifact path for a caller that writes its own file.

    ``write_table``/``write_text`` cover the cases where this module can do the
    writing. Binary formats with their own encoder -- WAV, for instance -- need
    the path resolution and collision handling without the write.

    Routed through ``_write_directory`` so a reserved path lands inside an
    active ``scoped_artifacts`` session like every other write does; resolving
    against ``ARTIFACT_DIR`` directly would drop files outside the session.
    """
    return _reserve_path(_write_directory(subdir), _safe_stem(name), f".{ext.lstrip('.')}")


def write_table(
    table: Table, name: str, *, subdir: Optional[str] = None, fmt: str = "ecsv"
) -> ArtifactRef:
    """Write ``table`` to disk in full and return a reference to it."""

    if fmt not in _WRITE_SUFFIXES:
        raise ValueError(f"Unsupported artifact format: {fmt!r}")

    directory = _write_directory(subdir)
    path = _reserve_path(directory, _safe_stem(name), _WRITE_SUFFIXES[fmt])

    # Written beside the reservation, then moved onto it. Writing the reserved
    # path itself with overwrite=True let astropy's FITS writer delete the
    # placeholder first, releasing the claimed name to another writer for the
    # length of the write; os.replace keeps it claimed throughout, and a write
    # that fails leaves no half-written file behind.
    handle, staging = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=directory
    )
    os.close(handle)
    try:
        if fmt == "csv":
            table.write(staging, format="ascii.csv", overwrite=True)
        else:
            table.write(staging, format=fmt, overwrite=True)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        discard_placeholder(path)
        raise

    return ArtifactRef(
        path=str(path),
        format=fmt,
        row_count=len(table),
        columns=[str(c) for c in table.colnames],
    )


def write_text(
    text: str, name: str, *, subdir: Optional[str] = None, ext: str = "md"
) -> ArtifactRef:
    """Write arbitrary text to disk and return a reference to it."""

    directory = _write_directory(subdir)
    path = _reserve_path(directory, _safe_stem(name), f".{ext.lstrip('.')}")
    try:
        path.write_text(text, encoding="utf-8")
    except BaseException:
        discard_placeholder(path)
        raise
    return ArtifactRef(path=str(path), format=ext.lstrip("."), row_count=None)


def describe_artifact(path: str) -> dict:
    """Return basic metadata for a previously written artifact."""

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    stat = p.stat()
    return {"path": str(p), "size_bytes": stat.st_size, "modified": stat.st_mtime}


def list_artifacts(directory: Optional[str] = None) -> list[str]:
    """List files under the artifact directory, or ``directory`` if given."""

    root = Path(directory) if directory else ARTIFACT_DIR
    if not root.exists():
        return []
    return sorted(str(p) for p in root.iterdir() if p.is_file())
