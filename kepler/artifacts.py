"""Kepler: local artifact path handling.

An artifact is a local file plus basic metadata -- see
``docs/tool-architecture.md`` section 2 ("simple local artifact path
handling"). Every ``kepler.tools`` function that can return more rows than fit
inline writes its full result here and returns a path, never the full table
in the response.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from astropy.table import Table

from .config import ARTIFACT_DIR
from .models import ArtifactRef

__all__ = [
    "write_table",
    "write_text",
    "describe_artifact",
    "list_artifacts",
    "preview_rows",
]

_SUFFIXES = {"ecsv": ".ecsv", "csv": ".csv", "fits": ".fits"}


def _to_native(value):
    """Convert a numpy/masked scalar to a plain Python type where possible.

    Every ``kepler.tools`` module builds ``ToolResult.preview`` from astropy
    table rows; leaving numpy scalar types in place works until a caller
    calls ``.model_dump_json()``, which doesn't know how to encode them.
    """
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
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def preview_rows(table: Table, limit: int) -> list[dict]:
    """Return the first ``limit`` rows of ``table`` as JSON-safe dicts.

    For a bounded ``ToolResult.preview`` only -- never the mechanism for
    returning a full result, which goes through ``write_table`` instead.
    """
    if table is None or len(table) == 0:
        return []
    n = min(limit, len(table))
    colnames = [str(c) for c in table.colnames]
    return [
        {name: _to_native(table[name][i]) for name in colnames} for i in range(n)
    ]


def _safe_stem(label: str) -> str:
    """Turn an arbitrary label into a safe filename stem.

    Catalog identifiers like VizieR's ``"VIII/65"`` or ``"J/ApJ/788/39"``
    contain characters that aren't safe path segments; this collapses anything
    outside ``[A-Za-z0-9_.-]`` to an underscore.
    """
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    return stem or "artifact"


def _reserve_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return a path under ``directory`` that doesn't already exist.

    Adds a numeric suffix on collision rather than overwriting a prior
    result from an earlier query in the same run.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}{suffix}"
    counter = 1
    while path.exists():
        path = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return path


def write_table(
    table: Table, name: str, *, subdir: Optional[str] = None, fmt: str = "ecsv"
) -> ArtifactRef:
    """Write ``table`` to disk in full and return a reference to it.

    ``fmt`` defaults to ECSV, which round-trips astropy units and dtypes
    losslessly -- worth having once a table mixes mJy and Jy columns across
    catalogs. ``csv``/``fits`` are available for callers who want something
    else at the cost of that metadata.

    If the target path already exists (a second query for the same name in
    the same run), a numeric suffix is added rather than silently overwriting
    a prior result.
    """
    if fmt not in _SUFFIXES:
        raise ValueError(f"Unsupported artifact format: {fmt!r}")

    directory = ARTIFACT_DIR / subdir if subdir else ARTIFACT_DIR
    path = _reserve_path(directory, _safe_stem(name), _SUFFIXES[fmt])

    if fmt == "csv":
        table.write(path, format="ascii.csv", overwrite=True)
    else:
        table.write(path, format=fmt, overwrite=True)

    return ArtifactRef(
        path=str(path),
        format=fmt,
        row_count=len(table),
        columns=[str(c) for c in table.colnames],
    )


def write_text(
    text: str, name: str, *, subdir: Optional[str] = None, ext: str = "md"
) -> ArtifactRef:
    """Write arbitrary text (e.g. a formatted literature review) to disk.

    Unlike ``write_table``, this isn't tabular data -- ``row_count`` is left
    ``None`` and ``columns`` empty; the artifact is meant to be read, not
    reloaded into a table.
    """
    directory = ARTIFACT_DIR / subdir if subdir else ARTIFACT_DIR
    path = _reserve_path(directory, _safe_stem(name), f".{ext.lstrip('.')}")
    path.write_text(text, encoding="utf-8")
    return ArtifactRef(path=str(path), format=ext.lstrip("."), row_count=None, columns=[])


def describe_artifact(path: str) -> dict:
    """Return basic metadata for a previously written artifact."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    stat = p.stat()
    return {"path": str(p), "size_bytes": stat.st_size, "modified": stat.st_mtime}


def list_artifacts(directory: Optional[str] = None) -> list[str]:
    """List files under the artifact directory (or ``directory`` if given)."""
    root = Path(directory) if directory else ARTIFACT_DIR
    if not root.exists():
        return []
    return sorted(str(p) for p in root.iterdir() if p.is_file())
