"""Catalog query helpers for observation asset processing.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/
observation_asset_processing/optical_data_processing/catalog_query.py
(436 lines), copied verbatim except for the import seams marked below.

Everything here is calibration-side catalog *matching* logic:
filter-aware catalog preselection, WCS-footprint box construction, duplicate
removal and footprint clipping.  The actual network fetches are delegated to
``CATALOGS[...].query_box / query_circ / query_objects``, whose backends were
severed by the extraction (see ``catalogs/__init__.py`` and EXTRACTION.md).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

import numpy as np
from astropy.wcs import WCS

# EXTRACTED: was `from skynet_db.models import ObservationAssetProcessingRun`
# (SQLAlchemy ORM row).  ``processing_run`` is accepted for signature parity
# with the Skynet call sites but is never read anywhere in this module, so the
# ORM type is replaced by a duck-typed ``Any``.
from .catalogs import CATALOGS
# EXTRACTED: was `from skynet_db.runners.common.schemas import CatalogSource`.
from .schemas import CatalogSource

__all__ = ["query_catalogs_for_processing_run"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filter-aware catalog selection helpers
# ---------------------------------------------------------------------------

_MATH_BUILTINS: frozenset[str] = frozenset(("sqrt", "log10", "abs", "exp", "log"))


def _expression_deps(expr: str) -> set[str]:
    """Return variable names referenced in expr, excluding known math builtins."""
    try:
        return {
            name
            for name in compile(expr, "<string>", "eval").co_names
            if name not in _MATH_BUILTINS
        }
    except (SyntaxError, ValueError):
        return set()


def _filter_token_candidates(image_filter: str) -> list[str]:
    """Return candidate tokens to try when matching a filter against catalog metadata.

    Tries: raw, stripped, lower-case, upper-case, and typographic-prime-normalized forms.
    Preserves the original token's casing to avoid rewriting meaningful tokens like g', Halpha.
    """
    seen: list[str] = []
    for t in (
        image_filter,
        image_filter.strip(),
        image_filter.lower(),
        image_filter.upper(),
        # Normalize typographic single-quote variants to ASCII apostrophe
        image_filter.replace("′", "'").replace("’", "'"),
    ):
        if t not in seen:
            seen.append(t)
    return seen


def normalize_filter_token(image_filter: str | None) -> str | None:
    """Return a stripped filter token, or None if blank/None."""
    if image_filter is None:
        return None
    return image_filter.strip() or None


def _lookup_resolves(
    target: str,
    catalog_mags: set[str],
    effective_lookup: dict[str, str],
) -> bool:
    """Return True if target resolves to a valid magnitude in catalog_mags.

    Handles up to two levels of indirection (e.g. g' -> gprime -> expression(g, r)).
    """
    # Direct band alias
    if target in catalog_mags:
        return True
    # One more level: target is itself a lookup key (alias-of-alias)
    target2 = effective_lookup.get(target)
    if target2 is not None:
        if target2 in catalog_mags:
            return True
        deps2 = _expression_deps(target2)
        if deps2 and all(d in catalog_mags for d in deps2):
            return True
    # Expression at this level — all referenced bands must exist in catalog mags
    deps = _expression_deps(target)
    if deps and all(d in catalog_mags for d in deps):
        return True
    return False


def catalog_supports_filter(
    catalog_name: str,
    image_filter: str,
    *,
    custom_filter_lookup: dict | None = None,
) -> bool:
    """Return True if catalog_name can resolve a reference magnitude for image_filter.

    Checks against the catalog's mags keys and filter_lookup, supporting
    up to two levels of filter-name indirection to mirror the resolution
    logic of resolve_ref_mag_for_filter.
    """
    catalog = CATALOGS.get(catalog_name)
    if catalog is None:
        return False

    catalog_mags: set[str] = set(getattr(catalog, "mags", {}) or {})
    if not catalog_mags:
        return False

    # Effective lookup: instance filter_lookup already merges class-level + constructor args
    effective_lookup: dict[str, str] = dict(getattr(catalog, "filter_lookup", {}) or {})
    if custom_filter_lookup and catalog_name in custom_filter_lookup:
        effective_lookup.update(custom_filter_lookup[catalog_name])

    wildcard_target = effective_lookup.get("*")

    for token in _filter_token_candidates(image_filter):
        # 1. Direct band key in catalog mags
        if token in catalog_mags:
            return True
        # 2. Explicit filter_lookup match, plus wildcard fallback
        target = effective_lookup.get(token) or wildcard_target
        if target is not None and _lookup_resolves(target, catalog_mags, effective_lookup):
            return True

    return False


def select_catalogs_for_filter(
    catalog_names: Sequence[str],
    image_filter: str | None,
    *,
    custom_filter_lookup: dict | None = None,
) -> list[str]:
    """Narrow catalog_names to those that can resolve image_filter.

    Preserves the configured priority order among compatible catalogs.
    If image_filter is None/blank, returns the original list unchanged.
    If no catalog supports the filter, logs a warning and falls back to
    the full configured list to preserve backward compatibility.
    """
    norm = normalize_filter_token(image_filter)
    if not norm:
        return list(catalog_names)

    logger.debug(
        "Filter-aware catalog selection: raw=%r normalized=%r configured=%s",
        image_filter,
        norm,
        list(catalog_names),
    )

    compatible = [
        c
        for c in catalog_names
        if catalog_supports_filter(c, norm, custom_filter_lookup=custom_filter_lookup)
    ]

    logger.debug("Filter-compatible catalogs for %r: %s", norm, compatible)

    if not compatible:
        logger.warning(
            "No configured catalog supports filter %r (configured: %s); "
            "falling back to full configured list",
            norm,
            list(catalog_names),
        )
        return list(catalog_names)

    return compatible


# ---------------------------------------------------------------------------
# WCS / geometry helpers
# ---------------------------------------------------------------------------

def _wcs_array_shape(wcs: WCS) -> tuple[int, int]:
    shape = getattr(wcs, "array_shape", None)
    if not shape:
        raise ValueError("WCS array_shape is required for catalog query")
    height, width = shape
    return int(height), int(width)


def _catalog_boxes_from_wcs(
    wcs: WCS,
) -> list[tuple[float, float, float, float]]:
    height, width = _wcs_array_shape(wcs)
    center = wcs.all_pix2world((width - 1) / 2, (height - 1) / 2, 0)
    center[0] %= 360

    wcs0 = wcs.deepcopy()
    wcs0.wcs.crval = [0, 0]
    ras, decs = wcs0.all_pix2world(
        [(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)],
        0,
    ).T
    ras %= 360
    width_deg = ras[ras < 180].max() - ras[ras >= 180].min() + 360
    height_deg = decs.max() - decs.min()

    return [(center[0], center[1], width_deg, height_deg)]


def _normalize_wcs_list(wcs: WCS | Iterable[WCS] | None) -> list[WCS]:
    if wcs is None:
        return []
    if isinstance(wcs, WCS):
        return [wcs]
    return [item for item in wcs if item is not None]


def _remove_duplicate_sources(sources: list[CatalogSource]) -> list[CatalogSource]:
    i = 0
    while i < len(sources):
        source = sources[i]
        source_id = [getattr(source, name, None) for name in ("id", "ra_hours", "dec_degs")]
        j = i + 1
        while j < len(sources):
            other = sources[j]
            other_id = [getattr(other, name, None) for name in ("id", "ra_hours", "dec_degs")]
            if other_id == source_id:
                del sources[j]
            else:
                j += 1
        i += 1
    return sources


# ---------------------------------------------------------------------------
# Main catalog query entry point
# ---------------------------------------------------------------------------

def query_catalogs_for_processing_run(
    processing_run: Any,  # EXTRACTED: was ObservationAssetProcessingRun; unused in this body
    catalogs: Iterable[str],
    *,
    wcs: WCS | Iterable[WCS] | None = None,
    header=None,
    data: np.ndarray | None = None,
    ra_hours: float | None = None,
    dec_degs: float | None = None,
    radius_arcmins: float | None = None,
    width_arcmins: float | None = None,
    height_arcmins: float | None = None,
    constraints: dict[str, str] | None = None,
    source_ids: Iterable[str] | None = None,
    skip_failed: bool = False,
    stop_on_success: bool = False,
    image_filter: str | None = None,
    custom_filter_lookup: dict | None = None,
) -> list[CatalogSource]:
    catalog_list = list(catalogs)
    if not catalog_list:
        raise ValueError("Missing catalog IDs")

    for catalog in catalog_list:
        if catalog not in CATALOGS:
            raise ValueError(f'Unknown catalog "{catalog}"')

    source_ids_list = list(source_ids) if source_ids is not None else []
    wcs_list = _normalize_wcs_list(wcs)

    logger.info("Catalog query requested for catalogs: %s", ", ".join(catalog_list))

    # Narrow the catalog list to those that can resolve the image filter.
    # Falls back to the full configured list when image_filter is absent or
    # no catalog supports the filter (backward compatibility).
    catalog_list = select_catalogs_for_filter(
        catalog_list,
        image_filter,
        custom_filter_lookup=custom_filter_lookup,
    )
    logger.info(
        "Catalog list after filter-aware selection (filter=%r): %s",
        image_filter,
        ", ".join(catalog_list),
    )

    if ra_hours is None:
        if dec_degs is not None:
            raise ValueError("dec_degs assumes ra_hours")
        if not wcs_list and not source_ids_list:
            raise ValueError("Either ra_hours/dec_degs, WCS, or source_ids are required")
        if wcs_list and source_ids_list:
            raise ValueError("WCS is mutually exclusive with source_ids")
        if source_ids_list and constraints:
            raise ValueError("Cannot set constraints for query by source IDs")
        if radius_arcmins is not None:
            raise ValueError("radius_arcmins assumes ra_hours/dec_degs")
        if width_arcmins is not None:
            raise ValueError("width_arcmins assumes ra_hours/dec_degs")
        if height_arcmins is not None:
            raise ValueError("height_arcmins assumes ra_hours/dec_degs")
    else:
        if dec_degs is None:
            raise ValueError("ra_hours assumes dec_degs")
        if source_ids_list:
            raise ValueError("source_ids is mutually exclusive with ra_hours/dec_degs")
        if wcs_list:
            raise ValueError("WCS is mutually exclusive with ra_hours/dec_degs")
        if radius_arcmins is None:
            if width_arcmins is None:
                raise ValueError("Either radius_arcmins or width_arcmins is required")
            if height_arcmins is None:
                height_arcmins = width_arcmins
        elif width_arcmins is not None:
            raise ValueError("width_arcmins is mutually exclusive with radius_arcmins")
        elif height_arcmins is not None:
            raise ValueError("height_arcmins is mutually exclusive with radius_arcmins")

    sources: list[CatalogSource] = []

    if source_ids_list:
        logger.info("Querying catalogs by source IDs (%d IDs)", len(source_ids_list))
        for catalog in catalog_list:
            catalog_sources = CATALOGS[catalog].query_objects(source_ids_list)
            if catalog_sources:
                logger.info("Catalog %s returned %d sources by ID", catalog, len(catalog_sources))
                if stop_on_success:
                    return list(catalog_sources)
                sources += list(catalog_sources)
        return sources

    if ra_hours is not None:
        logger.info(
            "Querying catalogs by sky coordinates ra=%s hours dec=%s deg",
            ra_hours,
            dec_degs,
        )
        if radius_arcmins is None:
            for catalog in catalog_list:
                catalog_sources = CATALOGS[catalog].query_box(
                    ra_hours,
                    dec_degs,
                    width_arcmins,
                    height_arcmins,
                    constraints,
                )
                if catalog_sources:
                    logger.info(
                        "Catalog %s returned %d sources for box query",
                        catalog,
                        len(catalog_sources),
                    )
                    if stop_on_success:
                        return catalog_sources
                    sources += catalog_sources
        else:
            for catalog in catalog_list:
                catalog_sources = CATALOGS[catalog].query_circ(
                    ra_hours,
                    dec_degs,
                    radius_arcmins,
                    constraints,
                )
                if catalog_sources:
                    logger.info(
                        "Catalog %s returned %d sources for circle query",
                        catalog,
                        len(catalog_sources),
                    )
                    if stop_on_success:
                        return catalog_sources
                    sources += catalog_sources
        return sources

    # WCS footprint mode — query each catalog, clip to footprint, then optionally stop.
    boxes: list[tuple[float, float, float, float]] = []
    for wcs_item in wcs_list:
        boxes += _catalog_boxes_from_wcs(wcs_item)

    if not boxes:
        return []

    logger.info("Catalog query using %d WCS box(es)", len(boxes))
    wcs_shapes = list(wcs_list)

    for idx, catalog in enumerate(catalog_list):
        try:
            catalog_sources: list[CatalogSource] = []
            for ra_deg, dec_deg, width_deg, height_deg in boxes:
                catalog_sources += CATALOGS[catalog].query_box(
                    ra_deg / 15.0,
                    dec_deg,
                    width_deg * 60.0,
                    height_deg * 60.0,
                    constraints,
                )
            if len(boxes) > 1 and catalog_sources:
                catalog_sources = _remove_duplicate_sources(catalog_sources)
            logger.info(
                "Catalog %s returned %d sources for WCS query",
                catalog,
                len(catalog_sources),
            )
            clipped = _filter_sources_to_wcs(catalog_sources, wcs_shapes)
            logger.info(
                "Catalog %s: %d sources after WCS footprint clipping",
                catalog,
                len(clipped),
            )
            if clipped:
                if stop_on_success:
                    return clipped
                sources += clipped
        except Exception:
            if skip_failed and idx < len(catalog_list) - 1:
                continue
            raise

    return sources


def _filter_sources_to_wcs(
    sources: list[CatalogSource],
    wcs_list: list[WCS],
) -> list[CatalogSource]:
    final_sources: list[CatalogSource] = []
    for source in sources:
        for wcs_item in wcs_list:
            x, y = wcs_item.all_world2pix(
                source.ra_hours * 15.0,
                source.dec_degs,
                0,
                quiet=True,
            )
            height, width = wcs_item.array_shape
            if 0 <= x < width and 0 <= y < height:
                source.x, source.y = float(x), float(y)
                final_sources.append(source)
                break

    return final_sources
