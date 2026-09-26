"""Offline variable-star light-curve, periodogram, and folding pipeline."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Sequence

from astropy.table import Table

from algorithms.variable_star.folding import fold_with_error
from algorithms.variable_star.lightcurve import VariableDataRow, merge_sources_by_mjd, with_error_mse
from algorithms.variable_star.periodogram import variable_periodogram
from tools import artifacts
from tools.config import PREVIEW_ROWS
from tools.models import (
    FileMetadata,
    ToolError,
    VariableStarFixture,
    VariableStarFixtureList,
    VariableStarFoldedLightCurve,
    VariableStarLightCurve,
    VariableStarPeriodogram,
)

__all__ = [
    "list_variable_star_fixtures",
    "resolve_variable_star_fixture",
    "load_variable_star_lightcurve",
    "compute_variable_star_periodogram",
    "fold_variable_star_lightcurve",
]

_REQUIRED_COLUMNS = {"id", "mjd", "mag", "mag_error"}
_MAX_INPUT_BYTES = 5 * 1024 * 1024
_MAX_ROWS = 2_000
_MAX_FIXTURES = 100
_MAX_SOURCE_ID_LENGTH = 128
_MAX_FOLD_OPERATIONS = 10_000_000


def _fixture_dir() -> Path:
    # Through the bundled data root, like every other bundled fixture, so an
    # installed wheel finds it: the old ``parents[1] / "test_data"`` path was in
    # no distribution, and an install listed nothing.
    from tools.config import BUNDLED_DATA_DIR

    return BUNDLED_DATA_DIR / "variable_star"


def _describe(path: str | Path) -> FileMetadata:
    return artifacts.describe_file(path)


def _checked_file_size(path: Path) -> None:
    if path.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"Input exceeds the {_MAX_INPUT_BYTES}-byte limit.")


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric.") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "a finite positive" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier} number.")
    return number


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError("CSV path is not a regular file.")
    _checked_file_size(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not _REQUIRED_COLUMNS.issubset(reader.fieldnames):
            missing = ", ".join(sorted(_REQUIRED_COLUMNS - set(reader.fieldnames or [])))
            raise ValueError(f"CSV is missing required columns: {missing}")
        rows: list[dict[str, str]] = []
        for row in reader:
            if len(rows) >= _MAX_ROWS:
                raise ValueError(f"CSV exceeds the {_MAX_ROWS}-row limit.")
            rows.append(row)
    for row in rows:
        if not row.get("id"):
            raise ValueError("id must not be blank.")
        if len(row["id"]) > _MAX_SOURCE_ID_LENGTH:
            raise ValueError(f"id exceeds the {_MAX_SOURCE_ID_LENGTH}-character limit.")
        _finite(row.get("mjd"), "mjd")
        _finite(row.get("mag"), "mag")
        _finite(row.get("mag_error"), "mag_error", positive=True)
    return rows


def _validated_subdir(subdir: str) -> str:
    path = Path(subdir)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact subdirectory must be relative and cannot contain '..'.")
    root = artifacts.ARTIFACT_DIR.resolve()
    if not (root / path).resolve().is_relative_to(root):
        raise ValueError("artifact subdirectory must resolve beneath the artifact root.")
    return str(path)


def _validate_periodogram_range(start: float, stop: float) -> tuple[float, float]:
    start_value = _finite(start, "start_period", positive=True)
    stop_value = _finite(stop, "end_period", positive=True)
    if stop_value <= start_value:
        raise ValueError("end_period must exceed start_period.")
    step = (stop_value - start_value) / 2000
    if step <= 0:
        raise ValueError("period range must have a representable positive step.")
    if start_value + step <= start_value:
        raise ValueError("period range step must advance start_period.")
    value = start_value
    for _ in range(2001):
        next_value = value + step
        if next_value <= value:
            raise ValueError("period range step must advance every grid point.")
        value = next_value
        if value >= stop_value:
            break
    else:
        raise ValueError("period range exceeds the bounded grid iteration count.")
    return start_value, stop_value


def _validate_fold_period(period: float, times: Sequence[float]) -> float:
    period_value = _finite(period, "period", positive=True)
    if not times:
        raise ValueError("light-curve artifact contains no rows.")
    baseline = max(times) - min(times)
    if baseline:
        cycles = baseline / period_value
        if not math.isfinite(cycles):
            raise ValueError("period is too small to fold representably over this observation.")
        if cycles * len(times) > _MAX_FOLD_OPERATIONS:
            raise ValueError("period exceeds the fold work limit for this observation.")
    return period_value


def _fixture(path: Path) -> VariableStarFixture:
    try:
        rows = _read_csv(path)
    except (OSError, ValueError):
        rows = []
    source_ids = list(dict.fromkeys(row["id"] for row in rows))
    return VariableStarFixture(
        path=str(path.resolve()),
        name=path.stem,
        source_ids=source_ids[:2],
        source_count=len(source_ids),
        row_count=len(rows),
    )


def list_variable_star_fixtures(directory: str | Path | None = None) -> VariableStarFixtureList:
    """Stage 0. List compact paired-source CSV fixtures available offline."""
    root = Path(directory).expanduser() if directory else _fixture_dir()
    if not root.is_dir():
        return VariableStarFixtureList(
            search_root=str(root),
            errors=[ToolError(code="directory_not_found", message=f"No variable-star data directory at {root}.")],
        )
    paths: list[Path] = []
    for path in root.glob("*.csv"):
        if len(paths) >= _MAX_FIXTURES:
            return VariableStarFixtureList(
                search_root=str(root),
                errors=[ToolError(code="too_many_fixtures", message=f"Fixture listing exceeds the {_MAX_FIXTURES}-file limit.")],
            )
        paths.append(path)
    fixtures = [_fixture(path) for path in sorted(paths)]
    return VariableStarFixtureList(fixtures=fixtures, search_root=str(root), count=len(fixtures))


def resolve_variable_star_fixture(
    name: str, directory: str | Path | None = None
) -> VariableStarFixture | VariableStarFixtureList:
    """Stage 0. Resolve a bundled fixture by its stem or an explicit CSV path."""
    direct = Path(name).expanduser()
    if direct.is_file():
        return _fixture(direct)
    listing = list_variable_star_fixtures(directory)
    matches = [fixture for fixture in listing.fixtures if fixture.name == name]
    if len(matches) == 1:
        return matches[0]
    listing.errors.append(
        ToolError(code="not_found", message=f"No variable-star fixture matches {name!r}.")
    )
    return listing


def _rows_from_artifact(file: FileMetadata) -> list[VariableDataRow]:
    if not file.exists:
        raise FileNotFoundError("Variable-star file does not exist.")
    if not file.is_file:
        raise ValueError("Path is not a regular file.")
    if (file.suffix or "").lower() != ".ecsv":
        raise ValueError("Pass an ECSV artifact from load_variable_star_lightcurve.")
    artifact_root = artifacts.ARTIFACT_DIR.resolve()
    if not Path(file.path).resolve().is_relative_to(artifact_root):
        raise ValueError("Pass an artifact written by load_variable_star_lightcurve.")
    _checked_file_size(Path(file.path))
    table = Table.read(file.path, format="ascii.ecsv")
    columns = {"mjd", "source1", "source2", "error1", "error2", "error_mse"}
    if not columns.issubset(table.colnames):
        raise ValueError("Artifact is not a variable-star light-curve artifact.")
    if len(table) > _MAX_ROWS:
        raise ValueError(f"Artifact exceeds the {_MAX_ROWS}-row limit.")
    rows = [
        VariableDataRow(*(None if value is None else float(value) for value in row))
        for row in table[["mjd", "source1", "source2", "error1", "error2", "error_mse"]]
    ]
    for row in rows:
        for name, value in (("mjd", row.jd), ("source1", row.source1), ("source2", row.source2), ("error1", row.error1), ("error2", row.error2), ("error_mse", row.error_mse)):
            if value is not None:
                _finite(value, name, positive=name.startswith("error"))
    return rows


def _error(file: FileMetadata, code: str, message: str, result_type):
    return result_type(file=file, errors=[ToolError(code=code, message=message)])


def load_variable_star_lightcurve(
    path: str | Path, *, output_name: str | None = None, subdir: str = "variable_star"
) -> VariableStarLightCurve:
    """Stage 1. Validate, merge, and persist a paired-source CSV light curve."""
    file = _describe(path)
    if not file.exists:
        return _error(file, "file_not_found", "Variable-star file does not exist.", VariableStarLightCurve)
    if not file.is_file:
        return _error(file, "not_a_file", "Variable-star path is not a regular file.", VariableStarLightCurve)
    try:
        raw_rows = _read_csv(Path(file.path))
    except (OSError, ValueError) as exc:
        return _error(file, "invalid_schema", str(exc), VariableStarLightCurve)
    source_ids = list(dict.fromkeys(row["id"] for row in raw_rows))
    if len(source_ids) != 2:
        return _error(file, "invalid_schema", "CSV must contain exactly two source IDs.", VariableStarLightCurve)
    try:
        subdir = _validated_subdir(subdir)
    except ValueError as exc:
        return _error(file, "invalid_input", str(exc), VariableStarLightCurve)
    merged = with_error_mse(merge_sources_by_mjd(raw_rows))
    table = Table(
        {
            "mjd": [row.jd for row in merged], "source1": [row.source1 for row in merged],
            "source2": [row.source2 for row in merged], "error1": [row.error1 for row in merged],
            "error2": [row.error2 for row in merged], "error_mse": [row.error_mse for row in merged],
        }
    )
    table.meta["source_ids"] = source_ids[:2]
    artifact = artifacts.write_table(table, (output_name or Path(file.path).stem) + "_lightcurve", subdir=subdir)
    return VariableStarLightCurve(
        file=file, artifact=artifact, rows_read=len(raw_rows), rows_merged=len(merged),
        source_ids=source_ids[:2], preview=artifacts.preview_rows(table, PREVIEW_ROWS),
    )


def compute_variable_star_periodogram(
    path: str | Path, *, variable_star: str, reference_star_magnitude: float,
    start_period: float = 0.1, end_period: float = 1.0, output_name: str | None = None,
    subdir: str = "variable_star",
) -> VariableStarPeriodogram:
    """Stage 2. Write the extracted 2,000-point weighted periodogram."""
    file = _describe(path)
    try:
        if variable_star not in {"source1", "source2"}:
            raise ValueError("variable_star must be source1 or source2.")
        reference_star_magnitude = _finite(reference_star_magnitude, "reference_star_magnitude")
        start_period, end_period = _validate_periodogram_range(start_period, end_period)
        subdir = _validated_subdir(subdir)
    except ValueError as exc:
        return _error(file, "invalid_input", str(exc), VariableStarPeriodogram)
    try:
        rows = _rows_from_artifact(file)
        samples = variable_periodogram(rows, variable_star, reference_star_magnitude, start_period, end_period)
    except FileNotFoundError as exc:
        return _error(file, "file_not_found", str(exc), VariableStarPeriodogram)
    except (OSError, ValueError, ZeroDivisionError) as exc:
        return _error(file, "invalid_input", str(exc), VariableStarPeriodogram)
    table = Table({"period": [row[0] for row in samples], "power": [row[1] for row in samples]})
    artifact = artifacts.write_table(table, (output_name or Path(file.path).stem) + "_periodogram", subdir=subdir)
    return VariableStarPeriodogram(
        file=file, artifact=artifact, samples=len(samples), start_period=start_period, end_period=end_period,
        variable_star=variable_star, preview=artifacts.preview_rows(table, PREVIEW_ROWS),
    )


def fold_variable_star_lightcurve(
    path: str | Path, *, variable_star: str, reference_star_magnitude: float, period: float,
    phase: float = 0.0, display_periods: int = 2, output_name: str | None = None,
    subdir: str = "variable_star",
) -> VariableStarFoldedLightCurve:
    """Stage 3. Fold a variable-star artifact at an explicit period."""
    file = _describe(path)
    try:
        if variable_star not in {"source1", "source2"} or display_periods not in {1, 2}:
            raise ValueError("variable_star must be source1/source2 and display_periods must be one or two.")
        reference_star_magnitude = _finite(reference_star_magnitude, "reference_star_magnitude")
        phase = _finite(phase, "phase")
        rows = _rows_from_artifact(file)
        period = _validate_fold_period(period, [row.jd for row in rows if row.jd is not None])
        subdir = _validated_subdir(subdir)
        data, errors = fold_with_error(
            rows, variable_star, reference_star_magnitude, period=period,
            phase=phase, display_periods=display_periods,
        )
    except FileNotFoundError as exc:
        return _error(file, "file_not_found", str(exc), VariableStarFoldedLightCurve)
    except (OSError, ValueError, IndexError) as exc:
        return _error(file, "invalid_input", str(exc), VariableStarFoldedLightCurve)
    table = Table({
        "phase": [row[0] for row in data], "magnitude": [row[1] for row in data],
        "error_low": [row[1] for row in errors], "error_high": [row[2] for row in errors],
    })
    artifact = artifacts.write_table(table, (output_name or Path(file.path).stem) + "_folded", subdir=subdir)
    return VariableStarFoldedLightCurve(
        file=file, artifact=artifact, period=period, phase=phase, display_periods=display_periods,
        rows_folded=len(data), preview=artifacts.preview_rows(table, PREVIEW_ROWS),
    )
