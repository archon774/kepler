"""Catalog query orchestration.

The entry points callers use. Each one resolves *where* to query from the
arguments, narrows the catalog list by filter, issues the per-catalog queries,
and clips the results back to what was actually asked for.

Three ways to say where:

``ra_hours``/``dec_degs`` plus a radius or a width/height
    A single explicit region.
``wcs``
    One or more solved images; query each footprint and keep sources that land
    on a detector, with pixel coordinates stamped on.
``source_ids``
    Specific named objects, no region at all.

They are mutually exclusive, and the argument checking below is deliberately
strict about it — a request that silently ignores half its arguments produces a
result that looks fine and covers the wrong sky.

EXTRACTED FROM:

* ``skynet/.../optical_data_processing/catalog_query.py`` (lines 251-436)
  -> ``query_catalogs``.
* ``skynet/packages/py/skynet-db/skynet_db/runners/utils.py`` (lines 872-930)
  -> ``query_catalogs_for_image``.
* ``afterglow-core/.../job_plugins/catalog_query_job.py`` (347 lines) — the same
  orchestration as a job body, reading its images from a data-file store. Its
  distinctive parts, the combined-FOV bounding box and the FOV geometry, are in
  ``query/geometry.py``; the job/ORM wrapper is not extracted.

SEVERED: upstream's signature led with a ``processing_run``
(``ObservationAssetProcessingRun``) SQLAlchemy row that the function never read
— it was there for call-site symmetry. Kepler drops the parameter rather than
carry a duck-typed placeholder.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import numpy as np
from astropy.wcs import WCS

from kepler.catalogs.schemas import CatalogSource

from .geometry import (
    boxes_from_wcs,
    clip_sources_to_wcs,
    image_boxes_from_wcs,
    infer_image_shape,
    normalize_wcs_list,
    remove_duplicate_sources,
)
from .registry import CATALOGS, UnknownCatalogError
from .selection import select_catalogs_for_filter

__all__ = ["query_catalogs", "query_catalogs_for_image"]

logger = logging.getLogger(__name__)


def _validate_region_args(
    ra_hours: Optional[float],
    dec_degs: Optional[float],
    radius_arcmins: Optional[float],
    width_arcmins: Optional[float],
    height_arcmins: Optional[float],
    wcs_list: list,
    source_ids: list,
    constraints: Optional[dict],
) -> Optional[float]:
    """Check the three region modes are not mixed. Returns resolved height.

    Preserved verbatim from upstream, including message wording — these are the
    errors callers see.
    """
    if ra_hours is None:
        if dec_degs is not None:
            raise ValueError("dec_degs assumes ra_hours")
        if not wcs_list and not source_ids:
            raise ValueError("Either ra_hours/dec_degs, WCS, or source_ids are required")
        if wcs_list and source_ids:
            raise ValueError("WCS is mutually exclusive with source_ids")
        if source_ids and constraints:
            raise ValueError("Cannot set constraints for query by source IDs")
        if radius_arcmins is not None:
            raise ValueError("radius_arcmins assumes ra_hours/dec_degs")
        if width_arcmins is not None:
            raise ValueError("width_arcmins assumes ra_hours/dec_degs")
        if height_arcmins is not None:
            raise ValueError("height_arcmins assumes ra_hours/dec_degs")
        return height_arcmins

    if dec_degs is None:
        raise ValueError("ra_hours assumes dec_degs")
    if source_ids:
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
    return height_arcmins


def query_catalogs(
    catalogs: Iterable[str],
    *,
    wcs: WCS | Iterable[WCS] | None = None,
    ra_hours: Optional[float] = None,
    dec_degs: Optional[float] = None,
    radius_arcmins: Optional[float] = None,
    width_arcmins: Optional[float] = None,
    height_arcmins: Optional[float] = None,
    constraints: Optional[dict[str, str]] = None,
    source_ids: Optional[Iterable[str]] = None,
    skip_failed: bool = False,
    stop_on_success: bool = False,
    image_filter: Optional[str] = None,
    custom_filter_lookup: Optional[dict] = None,
) -> list[CatalogSource]:
    """Query catalogs over a region, a set of images, or a list of names.

    :param catalogs: catalog names, in priority order.
    :param wcs: one or more solved WCS objects; query their footprints.
    :param ra_hours, dec_degs: explicit region centre.
    :param radius_arcmins: circular region; excludes width/height.
    :param width_arcmins, height_arcmins: rectangular region; height defaults to
        width.
    :param constraints: provider column constraints, ``{column: expression}``.
        A ``None`` value makes the entry a VizieR keyword instead of a filter.
    :param source_ids: query these objects by name instead of by region.
    :param skip_failed: in WCS mode, let a failing catalog be skipped as long as
        another remains to try. The *last* catalog always raises — otherwise a
        total outage would look like an empty field.
    :param stop_on_success: return as soon as one catalog yields sources, rather
        than merging all of them. This is how a priority-ordered list becomes a
        fallback chain.
    :param image_filter: narrow ``catalogs`` to those able to resolve this
        filter; see ``query/selection.py``.
    :param custom_filter_lookup: per-catalog filter-lookup overlay.

    :return: matching sources. In WCS mode each carries ``x``/``y`` for the image
        it landed on.
    """
    catalog_list = list(catalogs)
    if not catalog_list:
        raise ValueError("Missing catalog IDs")

    for catalog in catalog_list:
        if catalog not in CATALOGS:
            raise UnknownCatalogError(catalog)

    source_ids_list = list(source_ids) if source_ids is not None else []
    wcs_list = normalize_wcs_list(wcs)

    logger.info("Catalog query requested for catalogs: %s", ", ".join(catalog_list))

    height_arcmins = _validate_region_args(
        ra_hours,
        dec_degs,
        radius_arcmins,
        width_arcmins,
        height_arcmins,
        wcs_list,
        source_ids_list,
        constraints,
    )

    # Narrow to catalogs that can resolve the image filter. Falls back to the
    # full list when image_filter is absent or nothing supports it.
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

    sources: list[CatalogSource] = []

    if source_ids_list:
        logger.info("Querying catalogs by source IDs (%d IDs)", len(source_ids_list))
        for catalog in catalog_list:
            catalog_sources = CATALOGS[catalog].query_objects(source_ids_list)
            if catalog_sources:
                logger.info(
                    "Catalog %s returned %d sources by ID", catalog, len(catalog_sources)
                )
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
        for catalog in catalog_list:
            if radius_arcmins is None:
                catalog_sources = CATALOGS[catalog].query_box(
                    ra_hours, dec_degs, width_arcmins, height_arcmins, constraints
                )
                shape = "box"
            else:
                catalog_sources = CATALOGS[catalog].query_circ(
                    ra_hours, dec_degs, radius_arcmins, constraints
                )
                shape = "circle"
            if catalog_sources:
                logger.info(
                    "Catalog %s returned %d sources for %s query",
                    catalog,
                    len(catalog_sources),
                    shape,
                )
                if stop_on_success:
                    return catalog_sources
                sources += catalog_sources
        return sources

    # WCS footprint mode.
    boxes: list[tuple[float, float, float, float]] = []
    for wcs_item in wcs_list:
        boxes += boxes_from_wcs(wcs_item)

    if not boxes:
        return []

    logger.info("Catalog query using %d WCS box(es)", len(boxes))

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
                catalog_sources = remove_duplicate_sources(catalog_sources)
            logger.info(
                "Catalog %s returned %d sources for WCS query",
                catalog,
                len(catalog_sources),
            )
            clipped = clip_sources_to_wcs(catalog_sources, wcs_list)
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
                logger.warning("Catalog %s failed; trying the next", catalog, exc_info=True)
                continue
            raise

    return sources


def query_catalogs_for_image(
    catalogs: list[str],
    wcs: WCS,
    *,
    shape: Optional[tuple[int, int]] = None,
    header=None,
    data: Optional[np.ndarray] = None,
    constraints: Optional[dict[str, str]] = None,
) -> list[CatalogSource]:
    """Query catalogs over one image's field of view.

    The lenient counterpart to ``query_catalogs``'s WCS mode: it derives the
    footprint from pixel scales via ``image_boxes_from_wcs``, so it works when
    the WCS has no ``array_shape`` and the caller supplies a header or the data
    array instead.

    That leniency costs accuracy — the pixel-scale footprint ignores rotation
    and the cos(dec) narrowing. Prefer ``query_catalogs(wcs=...)`` when the WCS
    carries its shape.

    Unlike ``query_catalogs`` this merges every catalog's results without
    filter-aware narrowing or ``stop_on_success``; upstream kept it as the
    simple path.
    """
    if not catalogs:
        raise ValueError("Missing catalog IDs")

    for catalog in catalogs:
        if catalog not in CATALOGS:
            raise UnknownCatalogError(catalog)

    boxes = image_boxes_from_wcs(wcs, shape=shape, header=header, data=data)

    sources: list[CatalogSource] = []
    for catalog in catalogs:
        for ra_deg, dec_deg, width_deg, height_deg in boxes:
            sources += CATALOGS[catalog].query_box(
                ra_deg / 15.0,
                dec_deg,
                width_deg * 60.0,
                height_deg * 60.0,
                constraints or {},
            )

    # Keep only sources landing on the detector, stamping pixel coordinates.
    height, width = infer_image_shape(wcs, shape=shape, header=header, data=data)
    final: list[CatalogSource] = []
    for source in sources:
        if getattr(source, "ra_hours", None) is None or getattr(source, "dec_degs", None) is None:
            continue
        x, y = wcs.all_world2pix(source.ra_hours * 15.0, source.dec_degs, 0, quiet=True)
        if 0 <= x < width and 0 <= y < height:
            source.x, source.y = float(x), float(y)
            final.append(source)
    return final
