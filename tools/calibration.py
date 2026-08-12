"""Photometric calibration tool wrappers."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from algorithms.fieldcal.ref_mag import resolve_ref_mag_for_filter
from algorithms.fieldcal.schemas import CatalogSource, Mag, PhotometryData
from algorithms.fieldcal.solution import calc_solution
from tools.models import ToolError, ToolWarning, ZeropointSolution


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _to_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Expected a mapping or Pydantic model, got {type(value).__name__}")


def _normalize_catalog_source(value: Any) -> CatalogSource:
    source = value if isinstance(value, CatalogSource) else CatalogSource(**_to_mapping(value))
    mags = getattr(source, "mags", {}) or {}
    normalized_mags = {
        name: mag if isinstance(mag, Mag) else Mag(**mag) if isinstance(mag, Mapping) else Mag(value=mag)
        for name, mag in mags.items()
    }
    source.mags = normalized_mags
    return source


def _normalize_measurement(value: Any) -> PhotometryData:
    return value if isinstance(value, PhotometryData) else PhotometryData(**_to_mapping(value))


def _catalog_by_id(catalog_sources: list[CatalogSource]) -> dict[str, CatalogSource]:
    return {
        str(source.id): source
        for source in catalog_sources
        if getattr(source, "id", None) is not None
    }


def solve_zeropoint_from_measurements(
    measurements: Iterable[Mapping[str, Any] | PhotometryData],
    catalog_sources: Iterable[Mapping[str, Any] | CatalogSource],
) -> ZeropointSolution:
    """Solve a photometric zero point from local measurements and catalog rows."""

    normalized_measurements = [_normalize_measurement(item) for item in measurements]
    normalized_catalog_sources = [_normalize_catalog_source(item) for item in catalog_sources]
    catalogs_by_id = _catalog_by_id(normalized_catalog_sources)

    warnings: list[ToolWarning] = []
    usable_sources: list[PhotometryData] = []

    for index, measurement in enumerate(normalized_measurements):
        source = measurement.model_copy(deep=True)
        if source.mag is None:
            warnings.append(ToolWarning(code="missing_mag", message=f"Measurement {index} has no instrumental mag."))
            continue

        catalog_source = None
        if source.id is not None:
            catalog_source = catalogs_by_id.get(str(source.id))
        if catalog_source is None and index < len(normalized_catalog_sources):
            catalog_source = normalized_catalog_sources[index]

        if source.ref_mag is None and catalog_source is not None:
            if getattr(catalog_source, "ref_mag", None) is not None:
                source.ref_mag = catalog_source.ref_mag
                source.ref_mag_error = catalog_source.ref_mag_error
            elif source.filter:
                ref_mag, ref_error = resolve_ref_mag_for_filter(
                    image_filter=source.filter,
                    catalog_name=catalog_source.catalog_name,
                    cs_mags=catalog_source.mags,
                )
                source.ref_mag = ref_mag
                source.ref_mag_error = ref_error
            source.catalog_name = source.catalog_name or catalog_source.catalog_name

        if source.ref_mag is None:
            warnings.append(
                ToolWarning(
                    code="missing_ref_mag",
                    message=f"Measurement {index} has no resolvable catalog reference magnitude.",
                )
            )
            continue

        usable_sources.append(source)

    if not usable_sources:
        return ZeropointSolution(
            source_count=0,
            warnings=warnings,
            errors=[
                ToolError(
                    code="no_usable_sources",
                    message="No measurements had both instrumental and reference magnitudes.",
                )
            ],
        )

    try:
        m0, m0_error, slop, limmag, rej_percent = calc_solution(usable_sources)
    except ValueError as exc:
        # calc_solution's weighted-variance formula can take sqrt() of a
        # value that floating-point cancellation pushed slightly negative --
        # observed with near-zero-scatter input (see
        # tests/test_fieldcal_solution.py::test_zero_scatter_input_is_a_known_failure_mode).
        # Real photometry always carries some scatter, so this is a rare edge
        # case, not a common failure -- but it must return "unknown," not crash.
        return ZeropointSolution(
            source_count=len(usable_sources),
            warnings=warnings,
            errors=[ToolError(code="numerical_error", message=str(exc))],
        )
    return ZeropointSolution(
        zero_point_corr=_finite(m0),
        zero_point_error_mag=_finite(m0_error),
        zero_point_slop=_finite(slop),
        limmag5=_finite(limmag),
        rej_percent=_finite(rej_percent),
        source_count=len(usable_sources),
        warnings=warnings,
    )
