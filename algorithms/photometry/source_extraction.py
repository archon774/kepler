"""Source extraction helpers for optical observation asset processing."""
from __future__ import annotations

from datetime import datetime
import math
import re

import numpy as np
from astropy.wcs import WCS
# EXTRACTED: was `from skylib.extraction import ...` / `from skylib.util.fits import ...`
# (installed skylib package) — now the shared vendored copy under algorithms.skylib_lite.
from algorithms.skylib_lite.extraction import auto_sat_level, extract_sources
from algorithms.skylib_lite.util.fits import get_fits_exp_length, get_fits_gain, get_fits_time

# EXTRACTED: was `from skynet_db.models import ObservationAssetProcessingRun`
# (SQLAlchemy ORM row for a processing job). `perform_source_extraction()` only
# ever reads `.observation_asset_id` off it via getattr, so the parameter is now
# duck-typed — see the seam note there.
# EXTRACTED: was `from skynet_db.runners.common.schemas import ...`
from .schemas import SourceExtractionData, SourceExtractionSettings

#: SIP distortion keywords (A_/B_/AP_/BP_ orders, coefficients, and DMAX).
_SIP_KEY_REGEX = re.compile(r'^(A|B|AP|BP)_(ORDER|DMAX|\d+_\d+)$')


def _strip_orphan_sip(hdr) -> None:
    """Drop SIP distortion coeffs that lack a matching ``-SIP`` CTYPE suffix.

    Some upstream reductions leave ``A_*/B_*`` SIP coefficients in a header but
    write a plain ``RA---TAN`` CTYPE (no ``-SIP``). astropy's ``WCS(header)``
    constructor then logs "Inconsistent SIP distortion information" and applies
    the orphaned coefficients. We build header WCS objects only to derive
    pixel<->sky positions for source extraction / a solve hint, so the linear
    terms suffice — drop the orphaned SIP rather than apply it.

    A consistent header (CTYPE ends in ``-SIP``) and a SIP-free header are both
    left untouched, so this never alters a real distortion solution.
    """
    ctype1 = str(hdr.get("CTYPE1", "")).upper()
    if ctype1.endswith("-SIP"):
        return
    if not any(k in hdr for k in ("A_ORDER", "B_ORDER", "AP_ORDER", "BP_ORDER")):
        return
    for key in list(hdr.keys()):
        if _SIP_KEY_REGEX.match(key):
            del hdr[key]


def build_wcs_from_header(header) -> WCS | None:
    """Return an Astropy WCS from a FITS header, or None if it has no celestial WCS.

    Works on a copy so the caller's header is never mutated. Orphaned SIP
    coefficients (present without a ``-SIP`` CTYPE) are dropped so astropy
    doesn't apply an inconsistent distortion (or log about it).
    """
    try:
        tmp = header.copy()
        if "CRVAL1" in tmp:
            tmp["CRVAL1"] %= 360
        _strip_orphan_sip(tmp)
        wcs = WCS(tmp, relax=True)
        return wcs if wcs.has_celestial else None
    except Exception:
        return None


__all__ = [
    "SIGMA_TO_FWHM",
    "get_source_radec",
    "get_source_xy",
    "perform_source_extraction",
    "run_source_extraction",
]


SIGMA_TO_FWHM = 2.0 * math.sqrt(2.0 * math.log(2.0))


def _crop_data(
    data: np.ndarray,
    settings: SourceExtractionSettings,
) -> tuple[np.ndarray, int, int]:
    if data.ndim != 2:
        raise ValueError("Source extraction expects a 2D image array")

    height, width = data.shape
    try:
        x0 = int(settings.x)
        y0 = int(settings.y)
    except Exception as exc:
        raise ValueError("Source extraction region coordinates must be integers") from exc

    if x0 < 1 or x0 > width:
        raise ValueError("Source extraction X must be within image bounds")
    if y0 < 1 or y0 > height:
        raise ValueError("Source extraction Y must be within image bounds")

    x0 -= 1
    y0 -= 1

    w = settings.width
    h = settings.height

    if not w:
        w = width - x0
    else:
        w = int(w)
    if not h:
        h = height - y0
    else:
        h = int(h)

    if w <= 0 or w > width - x0:
        raise ValueError("Source extraction width must be positive and within bounds")
    if h <= 0 or h > height - y0:
        raise ValueError("Source extraction height must be positive and within bounds")

    if (x0, y0, w, h) == (0, 0, width, height):
        return data, x0, y0

    return data[y0 : y0 + h, x0 : x0 + w], x0, y0


def get_source_xy(
    source: SourceExtractionData,
    epoch: datetime | None,
    wcs: WCS | None,
) -> tuple[float | None, float | None]:
    if None not in (source.ra_hours, source.dec_degs, wcs):
        ra = float(source.ra_hours) * 15.0
        dec = float(source.dec_degs)
        if epoch is not None and None not in (
            source.pm_sky,
            source.pm_pos_angle_sky,
            source.pm_epoch,
        ):
            mu = float(source.pm_sky) * (epoch - source.pm_epoch).total_seconds()
            theta = math.radians(float(source.pm_pos_angle_sky))
            cd = math.cos(math.radians(dec))
            if cd:
                ra = (ra + mu * math.sin(theta) / cd) % 360.0
            dec = float(np.clip(dec + mu * math.cos(theta), -90.0, 90.0))
        return wcs.all_world2pix(ra, dec, 1, quiet=True)

    if (
        epoch is not None
        and None not in (source.pm_pixel, source.pm_pos_angle_pixel, source.pm_epoch)
        and source.x is not None
        and source.y is not None
    ):
        mu = float(source.pm_pixel) * (epoch - source.pm_epoch).total_seconds()
        theta = math.radians(float(source.pm_pos_angle_pixel))
        return (
            float(source.x) + mu * math.cos(theta),
            float(source.y) + mu * math.sin(theta),
        )

    if source.x is None or source.y is None:
        return None, None

    return float(source.x), float(source.y)


def get_source_radec(
    source: SourceExtractionData,
    epoch: datetime | None,
    wcs: WCS | None,
) -> tuple[float | None, float | None]:
    if None not in (source.ra_hours, source.dec_degs):
        ra = float(source.ra_hours)
        dec = float(source.dec_degs)
        if epoch is not None and None not in (
            source.pm_sky,
            source.pm_pos_angle_sky,
            source.pm_epoch,
        ):
            mu = float(source.pm_sky) * (epoch - source.pm_epoch).total_seconds()
            theta = math.radians(float(source.pm_pos_angle_sky))
            cd = math.cos(math.radians(dec))
            if cd:
                ra = (ra + mu / 15.0 * math.sin(theta) / cd) % 24.0
            dec = float(np.clip(dec + mu * math.cos(theta), -90.0, 90.0))
        return ra, dec

    if wcs is None:
        return None, None

    if None in (source.pm_pixel, source.pm_pos_angle_pixel, source.pm_epoch):
        ra_deg, dec_deg = wcs.all_pix2world(source.x, source.y, 1)
    else:
        mu = float(source.pm_pixel) * (epoch - source.pm_epoch).total_seconds()
        theta = math.radians(float(source.pm_pos_angle_pixel))
        ra_deg, dec_deg = wcs.all_pix2world(
            float(source.x) + mu * math.cos(theta),
            float(source.y) + mu * math.sin(theta),
            1,
        )
    return (float(ra_deg) % 360.0) / 15.0, float(dec_deg)


def run_source_extraction(
    data: np.ndarray,
    header,
    settings: SourceExtractionSettings,
    *,
    file_id: int | None = None,
) -> tuple[list[SourceExtractionData], np.ndarray | None, np.ndarray | None]:
    extraction_kw = dict(
        downsample=settings.downsample,
        threshold=settings.threshold,
        bkg_kw=dict(
            size=settings.bk_size,
            filter_size=settings.bk_filter_size,
        ),
        fwhm=settings.fwhm,
        ratio=settings.ratio,
        theta=settings.theta,
        min_pixels=settings.min_pixels,
        min_fwhm=settings.min_fwhm,
        max_fwhm=settings.max_fwhm,
        max_ellipticity=settings.max_ellipticity,
        deblend=settings.deblend,
        deblend_levels=settings.deblend_levels,
        deblend_contrast=settings.deblend_contrast,
        clean=settings.clean,
        centroid=settings.centroid,
        discard_saturated=settings.discard_saturated,
        max_sources=settings.max_sources,
    )

    pixels, ofs_x, ofs_y = _crop_data(data, settings)

    gain = get_fits_gain(header) if settings.gain is None else settings.gain
    texp = get_fits_exp_length(header)
    epoch = get_fits_time(header)[0]
    flt = header.get("FILTER")
    scope = header.get("TELESCOP")

    sat_img = None
    if settings.discard_saturated > 0:
        if settings.auto_sat_level:
            sat_level = auto_sat_level(pixels)
            if sat_level is None:
                sat_level = settings.sat_level
        else:
            sat_level = settings.sat_level
        sat_img = pixels >= sat_level

    if settings.clip_lo > 0 or settings.clip_hi < 100:
        if settings.clip_lo > 0 and settings.clip_hi < 100:
            lo, hi = np.percentile(pixels, (settings.clip_lo, settings.clip_hi))
        elif settings.clip_lo > 0:
            lo, hi = np.percentile(pixels, settings.clip_lo), None
        else:
            lo, hi = None, np.percentile(pixels, settings.clip_hi)
        pixels = np.clip(pixels, lo, hi)

    source_table, background, background_rms = extract_sources(
        pixels, gain=gain, sat_img=sat_img, **extraction_kw
    )

    if source_table is None or len(source_table) == 0:
        return [], background, background_rms

    #Checker to see if there is any positive flux in the sources
    try:
        flux_values = source_table["flux"]
        total_flux= float(np.nansum(flux_values))
    except Exception:
        #Fallback to iterate through rows
        total_flux = 0.0
        for row in source_table:
            try:
                total_flux += float(row["flux"])
            except Exception:
                continue
    if total_flux > 0.0:
        if file_id is not None:
            print(f"[source_extraction] file_id={file_id} total_flux={total_flux} num_sources={len(source_table)}")
        else:
            print(f"[source_extraction] total_flux={total_flux}")

    if settings.limit and len(source_table) > settings.limit:
        source_table.sort(order="flux")
        source_table = source_table[: -(settings.limit + 1) : -1]

    wcs = build_wcs_from_header(header)

    sources = [
        SourceExtractionData.from_numpy_row(
            row,
            ofs_x=ofs_x,
            ofs_y=ofs_y,
            wcs=wcs,
            file_id=file_id,
            time=epoch,
            filter=flt,
            telescope=scope,
            exp_length=texp,
        )
        for row in source_table
    ]

    return sources, background, background_rms


def perform_source_extraction(
    # EXTRACTED: was `processing_run: ObservationAssetProcessingRun` (skynet_db ORM
    # model). The annotation is dropped, not the behavior: the body already read
    # the run duck-typed, so any object exposing `.observation_asset_id` works.
    processing_run,
    header,
    data: np.ndarray,
    *,
    settings: SourceExtractionSettings | None = None,
) -> tuple[list[SourceExtractionData], np.ndarray | None, np.ndarray | None]:
    settings = settings or SourceExtractionSettings()
    file_id = getattr(processing_run, "observation_asset_id", None)
    return run_source_extraction(data, header, settings, file_id=file_id)
