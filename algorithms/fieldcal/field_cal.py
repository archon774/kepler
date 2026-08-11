"""Photometric calibration helpers for optical observation asset processing.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/
observation_asset_processing/optical_data_processing/field_cal.py (701 lines).

Copied verbatim.  The only edits are import rewrites and the four
cross-domain call seams routed through ``fieldcal.deps`` (photometry, source
extraction, WCS construction) — every marked with an ``# EXTRACTED:`` comment.
No algorithm, constant, ordering or comment has been changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Iterable, Mapping

import numpy as np
from astropy.wcs import WCS
from scipy.spatial import cKDTree

# EXTRACTED: was `from skylib.util.angle import angdist` /
# `from skylib.util.fits import get_fits_time` (installed skylib package) —
# now the shared vendored copy under algorithms.skylib_lite.
from algorithms.skylib_lite.util.angle import angdist
from algorithms.skylib_lite.util.fits import get_fits_time

# EXTRACTED: was `from skynet_db.models import ObservationAssetProcessingRun`
# (SQLAlchemy ORM row).  Field calibration reads only `.id` and
# `.observation_asset_id` off it, so the parameter is duck-typed as `Any`; see
# `schemas.ProcessingRunRef` for a concrete stand-in.
# EXTRACTED: was `from skynet_db.runners.common.schemas import (...)`
from .schemas import (
    FieldCalResult,
    Mag,
    PhotometricCalibrationSettings,
    PhotometryData,
    PhotometrySettings,
    SourceExtractionData,
    SourceExtractionSettings,
)
# EXTRACTED: was `from skynet_db.runners.utils import calc_solution,
# resolve_ref_mag_for_filter` (907-line grab-bag module; the two field-cal
# functions now live in fieldcal/solution.py and fieldcal/ref_mag.py).
from .solution import calc_solution
from .ref_mag import resolve_ref_mag_for_filter
# Catalog metadata (band tables and colour transforms) is read directly from
# Kepler's catalogs package: it is pure data and pulls in no network stack.
# The queries themselves go through deps.query_catalogs -- see deps.py.
from algorithms.catalogs import CATALOGS
# EXTRACTED: was `from .photometry import run_photometry`,
# `from .source_extraction import get_source_radec, run_source_extraction` and
# `from .wcs import build_wcs_for_processing_run` — sibling optical-processing
# stages that are not field calibration.  They are reached through the
# `fieldcal.deps` seam module (imported as a module so late injection works).
from . import deps
from .schemas import CatalogSource

__all__ = ["perform_field_calibration"]

logger = logging.getLogger(__name__)

def _normalize_catalog_sources(
    sources: Iterable[CatalogSource | Mapping[str, object]],
    *,
    file_id: int | None,
) -> list[CatalogSource]:
    normalized: list[CatalogSource] = []
    for source in sources:
        if isinstance(source, CatalogSource):
            data = source.model_dump(exclude_unset=True)
        else:
            data = dict(source)
        if data.get("file_id") is None:
            data["file_id"] = file_id
        normalized.append(CatalogSource(**data))
    return normalized


def _ensure_unique_source_ids(
    sources: list[CatalogSource],
    *,
    run_id: int | None,
) -> None:
    prefix = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{run_id or 'fieldcal'}_"
    source_ids: set[str | tuple[str, int | None]] = set()
    for idx, source in enumerate(sources):
        source_id = getattr(source, "id", None)
        if source_id is None:
            source.id = source_id = prefix + str(idx + 1)
        source_key = source_id
        if getattr(source, "file_id", None) is not None:
            source_key = (source_id, source.file_id)
        if source_key in source_ids:
            raise ValueError(f'Non-unique source ID "{source_id}"')
        source_ids.add(source_key)


def _attach_catalog_magnitudes(sources: list[CatalogSource]) -> None:
    for source in sources:
        mags = getattr(source, "mags", {}) or {}
        for name, val in list(mags.items()):
            if isinstance(val, dict):
                mags[name] = Mag(**val)
        source.mags = mags


def _has_reference_magnitudes(sources: list[CatalogSource]) -> bool:
    for source in sources:
        if getattr(source, "ref_mag", None) is not None:
            return True
        if (getattr(source, "mags", None) or {}):
            return True
    return False


def _catalogs_from_sources(sources: list[CatalogSource]) -> list[str]:
    catalogs: list[str] = []
    seen: set[str] = set()
    for source in sources:
        catalog_name = getattr(source, "catalog_name", None)
        if catalog_name and catalog_name not in seen:
            catalogs.append(catalog_name)
            seen.add(catalog_name)
    return catalogs


def _image_filter_from_header(header) -> str | None:
    """Extract the FILTER keyword from a FITS header, returning None if absent or blank."""
    if header is None:
        return None
    try:
        val = header.get("FILTER")
    except Exception:
        return None
    if val is None:
        return None
    return str(val).strip() or None


def _catalog_filter_lookup(catalog_name: str | None) -> dict[str, str]:
    if not catalog_name:
        return {}
    catalog = CATALOGS.get(catalog_name)
    if catalog is None:
        return {}
    return getattr(catalog, "filter_lookup", {}) or {}


def _catalog_filter_lookup_map(
    sources: Iterable[CatalogSource],
    configured_catalogs: Iterable[str] | None = None,
) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for catalog_name in configured_catalogs or []:
        if catalog_name:
            lookup[catalog_name] = dict(_catalog_filter_lookup(catalog_name))
    for source in sources:
        catalog_name = getattr(source, "catalog_name", None)
        if catalog_name:
            lookup[catalog_name] = dict(_catalog_filter_lookup(catalog_name))
    return lookup


def _filter_variable_stars(
    sources: list[CatalogSource],
    *,
    processing_run: Any,  # EXTRACTED: was ObservationAssetProcessingRun
    wcs: WCS | None,
    header,
    data: np.ndarray,
    variable_check_tol: float | None,
) -> list[CatalogSource]:
    if not variable_check_tol or variable_check_tol <= 0:
        return sources
    if wcs is None:
        return sources

    try:
        var_stars = deps.query_catalogs(
            ["VSX"],
            wcs=wcs,
            skip_failed=True,
        )
    except Exception:
        return sources

    if not var_stars:
        return sources

    epoch = get_fits_time(header)[0]

    filtered: list[CatalogSource] = []
    for source in sources:
        # EXTRACTED: was `get_source_radec(...)` from .source_extraction
        ra, dec = deps.get_source_radec(
            SourceExtractionData(**source.model_dump(exclude={"mags", "catalog_name", "label"})),
            epoch,
            wcs,
        )
        if ra is None or dec is None:
            filtered.append(source)
            continue
        is_variable = any(
            angdist(ra, dec, star.ra_hours, star.dec_degs) * 3600 < variable_check_tol
            for star in var_stars
            if getattr(star, "ra_hours", None) is not None and getattr(star, "dec_degs", None) is not None
        )
        if not is_variable:
            filtered.append(source)
    return filtered


def _match_detected_sources(
    catalog_sources: list[CatalogSource],
    detected_sources: list[SourceExtractionData],
    *,
    wcs: WCS | None,
    header,
    data: np.ndarray,
    source_match_tol: float | None,
) -> list[CatalogSource]:
    if not detected_sources:
        return catalog_sources
    if source_match_tol is None or source_match_tol <= 0:
        raise ValueError("Positive catalog source match tolerance expected")

    epoch = get_fits_time(header)[0]
    file_ids = sorted({getattr(source, "file_id", None) for source in detected_sources})
    catalog_sources_for_file: dict[int | None, list[CatalogSource]] = {
        file_id: [] for file_id in file_ids
    }
    for catalog_source in catalog_sources:
        catalog_file_id = getattr(catalog_source, "file_id", None)
        if catalog_file_id is None:
            for file_id in file_ids:
                catalog_sources_for_file[file_id].append(catalog_source)
        else:
            if catalog_file_id in catalog_sources_for_file:
                catalog_sources_for_file[catalog_file_id].append(catalog_source)

    # When all detected sources carry sky coordinates (ra_hours, dec_degs), use
    # angular distance matching instead of WCS-projected pixel distance.
    # This is WCS-quality-independent: if the detected source RA/Dec comes from
    # the same plate solution used to generate the catalog, the catalog star at a
    # detected source's sky position is its nearest neighbour regardless of any
    # fitting error in the harness-constructed WCS.
    # The flat-sky tolerance is expressed in arcseconds.  source_match_tol is in
    # pixels, so it is converted using the WCS pixel scale when available.
    det_ra_h = [getattr(s, "ra_hours", None) for s in detected_sources]
    det_dec_d = [getattr(s, "dec_degs", None) for s in detected_sources]
    use_angular = all(v is not None for v in det_ra_h) and all(v is not None for v in det_dec_d)

    if not use_angular and wcs is None:
        raise ValueError("Missing WCS for catalog source matching")

    # In angular mode the kd-tree is built in flat-sky arcsec coordinates, so the
    # tolerance must be in arcsec.  Convert from pixels via the WCS pixel scale.
    if use_angular and wcs is not None:
        try:
            from astropy.wcs.utils import proj_plane_pixel_scales as _ppps
            pixel_scale_arcsec = float(np.mean(np.abs(_ppps(wcs)))) * 3600.0
            tol_arcsec = source_match_tol * pixel_scale_arcsec
        except Exception:
            tol_arcsec = float(source_match_tol)  # treat as arcsec if conversion fails
    else:
        tol_arcsec = float(source_match_tol)

    # ---- build catalog match coordinates ----------------------------------------
    # Both angular and pixel paths need the epoch-corrected catalog RA/Dec.
    # For the pixel path they are additionally projected through the WCS.
    catalog_source_coord_for_file: dict[int | None, np.ndarray] = {}
    catalog_source_kdtree_for_file: dict[int | None, cKDTree | None] = {}

    # Reference point for the flat-sky projection used in angular mode.
    if use_angular:
        ra_ref = float(np.mean([float(v) * 15.0 for v in det_ra_h if v is not None]))
        dec_ref = float(np.mean([float(v) for v in det_dec_d if v is not None]))
        cos_dec_ref = float(np.cos(np.deg2rad(dec_ref)))

    for file_id, catalog_source_list in catalog_sources_for_file.items():
        if not catalog_source_list:
            catalog_source_kdtree_for_file[file_id] = None
            continue
        catalog_xy_data = []
        for source in catalog_source_list:
            x = getattr(source, "x", None)
            if x is None:
                x = np.nan
            y = getattr(source, "y", None)
            if y is None:
                y = np.nan
            ra = getattr(source, "ra_hours", None)
            if ra is None:
                ra = np.nan
            else:
                ra = float(ra) * 15.0
            dec = getattr(source, "dec_degs", None)
            if dec is None:
                dec = np.nan
            pm_epoch = getattr(source, "pm_epoch", None)
            if epoch is None or pm_epoch is None:
                pm_epoch = np.nan
                pm_sky = pm_pos_angle_sky = 0
                pm_pixel = pm_pos_angle_pixel = 0
            else:
                pm_sky = getattr(source, "pm_sky", 0) or 0
                pm_pos_angle_sky = getattr(source, "pm_pos_angle_sky", 0) or 0
                pm_pixel = getattr(source, "pm_pixel", 0) or 0
                pm_pos_angle_pixel = getattr(source, "pm_pos_angle_pixel", 0) or 0
            catalog_xy_data.append([x, y, ra, dec, pm_epoch, pm_sky, pm_pos_angle_sky, pm_pixel, pm_pos_angle_pixel])

        x, y, ra, dec, pm_epoch, pm_sky, pm_pos_angle_sky, pm_pixel, pm_pos_angle_pixel = np.transpose(catalog_xy_data)
        pm_epoch = np.asarray(pm_epoch, dtype=object)
        have_radec = np.isfinite(ra) & np.isfinite(dec)
        if have_radec.any():
            if epoch is not None:
                have_pm_epoch = np.array([isinstance(val, datetime) for val in pm_epoch])
                have_pm = have_radec & have_pm_epoch
                if have_pm.any():
                    mu = pm_sky[have_pm] * np.asarray(
                        [(epoch - dt).total_seconds() for dt in pm_epoch[have_pm]]
                    )
                    theta = np.deg2rad(pm_pos_angle_sky[have_pm])
                    cd = np.clip(np.cos(np.deg2rad(dec[have_pm])), 1e-7, None)
                    ra[have_pm] = (ra[have_pm] + mu * np.sin(theta) / cd) % 360
                    dec[have_pm] = np.clip(dec[have_pm] + mu * np.cos(theta), -90, 90)

            if use_angular:
                # Flat-sky coordinates in arcsec (consistent with detected-source coords below)
                cx = np.where(have_radec, (ra - ra_ref) * cos_dec_ref * 3600.0, np.nan)
                cy = np.where(have_radec, (dec - dec_ref) * 3600.0, np.nan)
            else:
                # Project to pixels via WCS (original behaviour)
                x[have_radec], y[have_radec] = wcs.all_world2pix(
                    ra[have_radec], dec[have_radec], 1, quiet=True,
                )

        if not use_angular:
            if epoch is not None:
                have_pm_epoch = np.array([isinstance(val, datetime) for val in pm_epoch])
                have_pm = have_pm_epoch & (pm_pixel != 0)
                if have_pm.any():
                    mu = pm_pixel[have_pm] * np.asarray(
                        [(epoch - dt).total_seconds() for dt in pm_epoch[have_pm]]
                    )
                    theta = np.deg2rad(pm_pos_angle_pixel[have_pm])
                    x[have_pm] += mu * np.cos(theta)
                    y[have_pm] += mu * np.sin(theta)
            coords = np.transpose([x, y])
        else:
            coords = np.column_stack([cx, cy])

        catalog_source_coord_for_file[file_id] = coords
        catalog_source_kdtree_for_file[file_id] = cKDTree(coords)

    # ---- build detected-source match coordinates --------------------------------
    detected_sources_for_file: dict[int | None, list[SourceExtractionData]] = {}
    detected_source_file_idx: dict[int, tuple[int | None, int]] = {}
    for source in detected_sources:
        file_id = getattr(source, "file_id", None)
        idx = len(detected_sources_for_file.get(file_id, []))
        detected_sources_for_file.setdefault(file_id, []).append(source)
        detected_source_file_idx[id(source)] = (file_id, idx)

    detected_source_coord_for_file: dict[int | None, np.ndarray] = {}
    detected_source_kdtree_for_file: dict[int | None, cKDTree] = {}
    for file_id, sources in detected_sources_for_file.items():
        if use_angular:
            det_ra_deg = np.array([float(getattr(s, "ra_hours", 0)) * 15.0 for s in sources])
            det_dec_deg = np.array([float(getattr(s, "dec_degs", 0)) for s in sources])
            coords = np.column_stack([
                (det_ra_deg - ra_ref) * cos_dec_ref * 3600.0,
                (det_dec_deg - dec_ref) * 3600.0,
            ])
        else:
            coords = np.array([(s.x, s.y) for s in sources])
        detected_source_coord_for_file[file_id] = coords
        detected_source_kdtree_for_file[file_id] = cKDTree(coords)

    # ---- mutual nearest-neighbour matching --------------------------------------
    # In angular mode the kd-tree units are arcsec; use tol_arcsec.
    # In pixel mode use source_match_tol (pixels) directly.
    match_tol = tol_arcsec if use_angular else source_match_tol
    matched_sources: list[CatalogSource] = []
    for source in detected_sources:
        file_id, src_idx = detected_source_file_idx[id(source)]
        tree = catalog_source_kdtree_for_file.get(file_id)
        if tree is None:
            continue
        catalog_source_list = catalog_sources_for_file[file_id]
        det_coord = detected_source_coord_for_file[file_id][src_idx]
        i = tree.query(det_coord, distance_upper_bound=match_tol)[1]
        if i >= len(catalog_source_list):
            continue
        catalog_source = catalog_source_list[i]
        cat_coord = catalog_source_coord_for_file[file_id][i]
        detected_source_list = detected_sources_for_file[file_id]
        reverse_tree = detected_source_kdtree_for_file[file_id]
        j = reverse_tree.query(cat_coord, distance_upper_bound=match_tol)[1]
        if j >= len(detected_source_list) or detected_source_list[j] is not source:
            continue

        source_map = source.model_dump(
            exclude={
                "time",
                "filter",
                "telescope",
                "exp_length",
                "fwhm_x",
                "fwhm_y",
                "theta",
            }
        )
        for attr in (
            "id",
            "catalog_name",
            "mags",
            "label",
            "mag",
            "mag_error",
            "ref_mag",
            "ref_mag_error",
            "flux",
            "flux_error",
            "pm_sky",
            "pm_pos_angle_sky",
            "pm_ra",
            "pm_dec",
            "pm_ra_error",
            "pm_dec_error",
            "pm_pixel",
            "pm_pos_angle_pixel",
            "pm_epoch",
            "sat_pixels",
        ):
            val = getattr(catalog_source, attr, None)
            if val is not None:
                source_map[attr] = val

        matched_sources.append(CatalogSource(**source_map))

    if not matched_sources:
        raise RuntimeError("Could not match any detected sources to catalog sources")

    return matched_sources


def _collect_calibration_sources(
    photometry_results: list[PhotometryData],
    catalog_sources: list[CatalogSource],
    *,
    catalog_filter_lookup: dict[str, dict[str, str]] | None,
    custom_filter_lookup: dict[str, dict[str, str]] | None,
    allow_preferred_band_fallback: bool = True,
) -> list[PhotometryData]:
    sources: list[PhotometryData] = []
    catalogs_by_id = {source.id: source for source in catalog_sources if source.id is not None}
    inferred_catalog_name = None
    if catalog_filter_lookup and len(catalog_filter_lookup) == 1:
        inferred_catalog_name = next(iter(catalog_filter_lookup))

    for source in photometry_results:
        catalog_source = catalogs_by_id.get(source.id)
        if catalog_source is None:
            continue

        catalog_name = catalog_source.catalog_name or inferred_catalog_name
        if catalog_name and not catalog_source.catalog_name:
            catalog_source.catalog_name = catalog_name

        ref_mag = getattr(catalog_source, "ref_mag", None)
        ref_err = getattr(catalog_source, "ref_mag_error", None)
        if ref_mag is None:
            lookup = dict(catalog_filter_lookup or {})
            if custom_filter_lookup:
                for custom_catalog_name, filters in custom_filter_lookup.items():
                    lookup.setdefault(custom_catalog_name, {}).update(filters)
            ref_mag, ref_err = resolve_ref_mag_for_filter(
                image_filter=getattr(source, "filter", None),
                catalog_name=catalog_name,
                cs_mags=catalog_source.mags,
                custom_filter_lookup=lookup or None,
                allow_preferred_band_fallback=allow_preferred_band_fallback,
            )
        if ref_mag is None:
            continue

        source.ref_mag = ref_mag
        if ref_err is not None:
            source.ref_mag_error = ref_err
        source.catalog_name = catalog_name
        sources.append(source)

    return sources


def perform_field_calibration(
    processing_run: Any,  # EXTRACTED: was ObservationAssetProcessingRun
    header,
    data: np.ndarray,
    *,
    field_cal_settings: PhotometricCalibrationSettings | None = None,
    photometry_settings: PhotometrySettings | None = None,
    extraction_settings: SourceExtractionSettings | None = None,
    catalog_names: Iterable[str] | None = None,
    catalog_sources: Iterable[CatalogSource | Mapping[str, object]] | None = None,
    detected_sources: list[SourceExtractionData] | None = None,
    use_provided_photometry: bool = False,
) -> tuple[float | None, FieldCalResult] | None:
    settings = field_cal_settings or PhotometricCalibrationSettings()
    phot_settings = photometry_settings or PhotometrySettings()
    configured_catalogs = list(catalog_names) if catalog_names else list(settings.catalogs or [])

    file_id = getattr(processing_run, "observation_asset_id", None)
    logger.info(
        "Starting field calibration for run_id=%s file_id=%s",
        getattr(processing_run, "id", None),
        file_id,
    )
    # EXTRACTED: was `build_wcs_for_processing_run(...)` from .wcs
    wcs = deps.build_wcs_for_processing_run(processing_run, header)
    logger.info("WCS available for field calibration: %s", wcs is not None)

    sources_input = catalog_sources if catalog_sources is not None else settings.catalog_sources
    sources = _normalize_catalog_sources(sources_input, file_id=file_id) if sources_input else []
    _attach_catalog_magnitudes(sources)

    if not sources or not _has_reference_magnitudes(sources):
        catalogs = list(configured_catalogs)
        if not catalogs and sources:
            catalogs = _catalogs_from_sources(sources)
        if not catalogs:
            raise ValueError("Missing catalog sources or catalog list for field calibration")
        if wcs is None:
            raise ValueError("Missing WCS needed to query catalogs for calibration")
        image_filter = _image_filter_from_header(header)
        logger.info(
            "Querying catalogs for field calibration: %s (filter=%r)",
            ", ".join(catalogs),
            image_filter,
        )
        sources = deps.query_catalogs(
            catalogs,
            wcs=wcs,
            skip_failed=True,
            stop_on_success=True,
            image_filter=image_filter,
            custom_filter_lookup=settings.custom_filter_lookup or None,
        )
        _attach_catalog_magnitudes(sources)
        logger.info("Catalog query returned %d sources", len(sources))
    else:
        logger.info("Using %d provided catalog sources for field calibration", len(sources))

    if not sources:
        raise RuntimeError("No catalog sources available for calibration")

    _ensure_unique_source_ids(sources, run_id=getattr(processing_run, "id", None))
    sources = _filter_variable_stars(
        sources,
        processing_run=processing_run,
        wcs=wcs,
        header=header,
        data=data,
        variable_check_tol=settings.variable_check_tol,
    )
    logger.info("Catalog sources after variable-star filter: %d", len(sources))

    background: np.ndarray | None = None
    background_rms: np.ndarray | None = None

    if extraction_settings is not None and detected_sources is None:
        # EXTRACTED: was `run_source_extraction(...)` from .source_extraction
        detected_sources, background, background_rms = deps.run_source_extraction(
            data,
            header,
            extraction_settings,
            file_id=file_id,
        )

    sources = _match_detected_sources(
        sources,
        detected_sources or [],
        wcs=wcs,
        header=header,
        data=data,
        source_match_tol=settings.source_match_tol,
    )
    logger.info("Catalog sources after detected-source matching: %d", len(sources))
    logger.info(
        "Matched %d detected sources to catalogs: %s",
        len(sources),
        ", ".join(_catalogs_from_sources(sources)) or "unknown",
    )

    if use_provided_photometry:
        # Legacy "photometry disabled" mode: do not re-measure fluxes; use the
        # magnitudes already carried by the matched sources (e.g. Afterglow-
        # measured photometry supplied via detected_sources). This lets callers
        # exercise the real selection + zero-point algorithm on externally
        # measured photometry. The FILTER is restored from the header because
        # _match_detected_sources drops it from the matched source.
        image_filter = _image_filter_from_header(header)
        photometry_results = []
        for source in sources:
            src_map = source.model_dump(
                exclude={"mags", "catalog_name", "label", "ref_mag", "ref_mag_error"}
            )
            if src_map.get("file_id") is None:
                src_map["file_id"] = file_id
            if not src_map.get("filter"):
                src_map["filter"] = image_filter
            photometry_results.append(PhotometryData(**src_map))
    else:
        normalized_sources: list[SourceExtractionData] = []
        for source in sources:
            src_map = source.model_dump(
                exclude_unset=True,
                exclude={
                    "catalog_name",
                    "label",
                    "mags",
                    "ref_mag",
                    "ref_mag_error",
                    "mag",
                    "mag_error",
                    "flux_error",
                },
            )
            if src_map.get("file_id") is None:
                src_map["file_id"] = file_id
            normalized_sources.append(SourceExtractionData(**src_map))

        # LEGACY AFTERGLOW PARITY — DO NOT "CLEAN UP".  Forcing apcorr_tol to 0
        # is what disables aperture correction for calibration photometry: the
        # aperture-photometry kernel gates its correction pass on
        # `apcorr_tol > 0`.  Restoring the caller's apcorr_tol (default 1e-4)
        # silently switches aperture correction on and the zero point diverges
        # from legacy Afterglow output.  (Annotation added by the extraction;
        # the statement itself is verbatim from field_cal.py:612.)
        cal_phot_settings = phot_settings.model_copy(update={"apcorr_tol": 0.0})
        # EXTRACTED: was `run_photometry(...)` from .photometry
        photometry_results = deps.run_photometry(
            data,
            header,
            normalized_sources,
            cal_phot_settings,
            wcs=wcs,
            background=None,
            background_rms=None,
        )
    photometry_results = [source for source in photometry_results if source.mag is not None]

    if not photometry_results:
        raise RuntimeError("No catalog sources could be photometered")
    logger.info("Photometry produced %d catalog-linked measurements", len(photometry_results))

    min_snr = settings.min_snr or 0
    max_snr = settings.max_snr or np.inf
    if settings.min_snr or settings.max_snr:
        photometry_results = [
            source
            for source in photometry_results
            if not getattr(source, "mag_error", None)
            or min_snr <= 1 / getattr(source, "mag_error", 1) <= max_snr
        ]
        logger.info("Photometry results after SNR filter: %d", len(photometry_results))
        if not photometry_results:
            raise RuntimeError("All sources violate SNR constraints")

    calibration_sources = _collect_calibration_sources(
        photometry_results,
        sources,
        catalog_filter_lookup=_catalog_filter_lookup_map(sources, configured_catalogs),
        custom_filter_lookup=settings.custom_filter_lookup or None,
        allow_preferred_band_fallback=not settings.strict_filter_parity,
    )
    logger.info("Calibration sources after ref-mag resolution: %d", len(calibration_sources))

    if not calibration_sources:
        raise RuntimeError("No calibration sources matched catalog magnitudes")

    # max_stars: limit to brightest N calibration stars (by ref_mag, ascending = brightest first)
    max_stars = settings.max_stars
    if max_stars and len(calibration_sources) > max_stars:
        calibration_sources = sorted(
            calibration_sources,
            key=lambda s: getattr(s, "ref_mag", np.inf) or np.inf,
        )[:max_stars]
        logger.info("Calibration sources after max_stars=%d limit: %d", max_stars, len(calibration_sources))

    logger.info(
        "Resolving zero-point from %d sources (catalogs: %s)",
        len(calibration_sources),
        ", ".join(_catalogs_from_sources(sources)) or "unknown",
    )

    m0, m0_error, slop, limmag, rej_percent = calc_solution(calibration_sources)
    logger.info(
        "Field calibration solution: m0=%.4f m0_err=%s slop=%s limmag=%s rej=%.1f%%",
        m0,
        m0_error,
        slop,
        limmag,
        rej_percent,
    )

    # Write photometric zero-point to FITS header if accessible
    try:
        zero_point_offset = getattr(phot_settings, "zero_point_mag", 0) or 0
        header["PHOT_M0"] = (
            float(m0) + float(zero_point_offset),
            "Photometric zero point",
        )
        if m0_error is not None and np.isfinite(m0_error):
            header["PHOT_M0E"] = (float(m0_error), "Photometric zero point error")
        catalog_str = ", ".join(_catalogs_from_sources(calibration_sources)) or "unknown"
        header["PHOT_CAL"] = (catalog_str[:68], "Photometric calibration catalog")
    except Exception as exc:
        logger.warning("Could not write photometric keywords to header: %s", exc)

    result = FieldCalResult(
        file_id=file_id,
        phot_results=calibration_sources,
        zero_point_corr=m0,
        zero_point_error_mag=m0_error,
        zero_point_slop=slop,
        limmag5=limmag,
        rej_percent=rej_percent,
    )
    return result.zero_point_corr, result
