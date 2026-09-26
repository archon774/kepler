"""Variable-star source merging and differential-light-curve primitives.

# PORTED: git-history:algorithms/lightcurve/variable/variable-lightcurve.ingest.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Mapping, Sequence


@dataclass(frozen=True)
class VariableDataRow:
    """One time-aligned pair of source measurements."""

    jd: float | None
    source1: float | None
    source2: float | None
    error1: float | None
    error2: float | None
    error_mse: float | None


def error_mse(error1: float | None, error2: float | None) -> float | None:
    """Return the upstream combined uncertainty for a paired observation.

    # PORTED: variable-lightcurve.types.ts::errorMSE
    """
    if error1 is None or error2 is None:
        return None
    return sqrt(error1**2 + error2**2) / 2


def with_error_mse(rows: Sequence[VariableDataRow]) -> list[VariableDataRow]:
    """Apply the TypeScript ``VariableData.setData`` error-MSE normalization."""
    return [
        VariableDataRow(
            row.jd,
            row.source1,
            row.source2,
            row.error1,
            row.error2,
            error_mse(row.error1, row.error2),
        )
        for row in rows
    ]


def differential_data(
    rows: Sequence[VariableDataRow], variable_star: str, reference_star_magnitude: float
) -> list[tuple[float, float]]:
    """Return target-minus-comparison magnitudes for complete source pairs.

    # PORTED: variable-lightcurve.algorithms.ts::getChartVariableDataArray
    """
    if variable_star == "none":
        return []
    values: list[tuple[float, float]] = []
    for row in rows:
        if row.jd is None or row.source1 is None or row.source2 is None:
            continue
        magnitude = (
            row.source1 - row.source2 + reference_star_magnitude
            if variable_star == "source1"
            else row.source2 - row.source1 + reference_star_magnitude
        )
        values.append((row.jd, magnitude))
    return values


def differential_errors(
    rows: Sequence[VariableDataRow], variable_star: str, reference_star_magnitude: float
) -> list[tuple[float, float, float]]:
    """Return differential-magnitude error bars for complete, error-carrying rows.

    # PORTED: variable-lightcurve.algorithms.ts::getChartVariableErrorArray
    """
    if variable_star == "none":
        return []
    values: list[tuple[float, float, float]] = []
    for row in rows:
        if (
            row.jd is None
            or row.source1 is None
            or row.source2 is None
            or row.error_mse is None
        ):
            continue
        magnitude = (
            row.source1 - row.source2 + reference_star_magnitude
            if variable_star == "source1"
            else row.source2 - row.source1 + reference_star_magnitude
        )
        values.append((row.jd, magnitude - row.error_mse, magnitude + row.error_mse))
    return values


def jd_range(rows: Sequence[VariableDataRow]) -> float:
    """Return the upstream four-decimal observation baseline."""
    values = [row.jd for row in rows if row.jd is not None]
    return float(f"{max(values) - min(values):.4f}")


def merge_sources_by_mjd(data: Sequence[Mapping[str, object]]) -> list[VariableDataRow]:
    """Merge the first two encountered source IDs using the upstream MJD join."""
    sources = list(dict.fromkeys(row.get("id") for row in data))
    if len(sources) < 2:
        return []

    def parsed(source: object) -> list[tuple[float, float, float]]:
        values: list[tuple[float, float, float]] = []
        for row in data:
            if row.get("id") != source:
                continue
            try:
                values.append(
                    (float(row["mjd"]), float(row["mag"]), float(row["mag_error"]))
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(values, key=lambda value: value[0])

    source1 = parsed(sources[0])
    source2 = parsed(sources[1])
    result: list[VariableDataRow] = []
    left = right = 0
    threshold = 0.00000001
    while left < len(source1) and right < len(source2):
        first, second = source1[left], source2[right]
        if abs(first[0] - second[0]) < threshold:
            result.append(VariableDataRow(first[0], first[1], second[1], first[2], second[2], None))
            left += 1
            right += 1
        elif first[0] < second[0]:
            result.append(VariableDataRow(first[0], first[1], None, first[2], None, None))
            left += 1
        else:
            result.append(VariableDataRow(second[0], None, second[1], None, second[2], None))
            right += 1
    result.extend(
        VariableDataRow(row[0], row[1], None, row[2], None, None)
        for row in source1[left:]
    )
    result.extend(
        VariableDataRow(row[0], None, row[1], None, row[2], None)
        for row in source2[right:]
    )
    return result
