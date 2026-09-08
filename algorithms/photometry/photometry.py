"""Photometry helpers for optical observation asset processing."""
from __future__ import annotations

import logging
from typing import Mapping, Sequence

import numpy as np
import sep
from astropy.wcs import WCS
# EXTRACTED: was `from skylib...` (installed skylib package) — now the shared
# vendored copy under algorithms.skylib_lite where modules are reused.
from algorithms.skylib_lite.extraction.centroiding import centroid_sources
from algorithms.skylib_lite.photometry import aperture_photometry
from algorithms.skylib_lite.util.fits import get_fits_exp_length, get_fits_gain, get_fits_time

# EXTRACTED: was `from skynet_db.runners.common.schemas import ...`
from .schemas import (
    PhotometryData,
    PhotometrySettings,
    SourceExtractionData,
    SourceExtractionSettings,
)
from .source_extraction import SIGMA_TO_FWHM, build_wcs_from_header, get_source_xy

__all__ = ["run_photometry"]

logger = logging.getLogger(__name__)

def _ensure_native_contiguous(arr):
    a = np.asarray(arr)
    if not a.dtype.isnative:
        # convert byteorder without changing values
        a = np.array(a, dtype=a.dtype.newbyteorder("="))
    return np.ascontiguousarray(a)


def _row_to_mapping(row: np.void) -> Mapping[str, float]:
    return {name: row[name] for name in row.dtype.names}


def _apply_wcs_to_source(source: SourceExtractionData, wcs: WCS | None) -> SourceExtractionData:
    if wcs is None:
        return source
    if source.x is None or source.y is None:
        return source
    # Always recompute RA/Dec from current x/y — legacy parity (legacy always overwrote via wcs arg)
    ra_deg, dec_deg = wcs.all_pix2world(source.x, source.y, 1)
    return source.model_copy(
        update={
            "ra_hours": (float(ra_deg) % 360.0) / 15.0,
            "dec_degs": float(dec_deg),
        }
    )


def run_photometry(
    data: np.ndarray,
    header,
    sources: Sequence[SourceExtractionData],
    settings: PhotometrySettings,
    wcs: WCS | None = None,
    background: np.ndarray | None = None,
    background_rms: np.ndarray | None = None,
) -> list[PhotometryData]:
    if not sources:
        return []

    logger.info(
        "Running %s photometry for %d sources",
        settings.mode,
        len(sources),
    )

    if settings.mode == "aperture":
        if settings.a is None:
            raise ValueError("Missing aperture radius/semi-major axis for mode=\"aperture\"")
        if settings.a <= 0:
            raise ValueError("Aperture radius/semi-major axis must be positive")
        phot_kw = dict(
            a=settings.a,
            b=settings.b,
            theta=settings.theta,
            a_in=settings.a_in_px,
            a_out=settings.a_out_px,
            b_out=settings.b_out_px,
            theta_out=settings.theta_out_deg,
        )
    elif settings.mode == "auto":
        phot_kw = dict(
            k=settings.a if settings.a else 2.5,
            k_in=settings.a_in_px,
            k_out=settings.a_out_px,
            fix_aper=settings.fix_aper,
            fix_ell=settings.fix_ell,
            fix_rot=settings.fix_rot,
        )
    else:
        raise ValueError('Photometry mode must be "aperture" or "auto"')

    phot_kw["apcorr_tol"] = settings.apcorr_tol
    phot_kw["reject_outliers"] = settings.reject_bkg_outliers

    if wcs is None:
        wcs = build_wcs_from_header(header)
    logger.info("WCS available for photometry: %s", wcs is not None)

    gain = None
    if settings.gain is None or settings.gain == 1:
        gain = get_fits_gain(header)
    else:
        gain = settings.gain
    if gain:
        phot_kw["gain"] = gain

    texp = get_fits_exp_length(header)
    epoch = get_fits_time(header, texp)[1]
    if texp:
        phot_kw["texp"] = texp

    flt = header.get("FILTER")
    scope = header.get("TELESCOP")

    logger.info(
        "Photometry metadata: filter=%s telescope=%s exp_length=%s gain=%s",
        flt,
        scope,
        texp,
        gain,
    )

    valid_sources: list[SourceExtractionData] = []
    positions: list[tuple[float, float]] = []

    for source in sources:
        x, y = get_source_xy(source, epoch, wcs)
        if x is None or y is None:
            continue
        if 0 <= x < data.shape[1] and 0 <= y < data.shape[0]:
            update = {
                "x": float(x),
                "y": float(y),
                "time": epoch,
                "filter": flt,
                "telescope": scope,
                "exp_length": texp,
            }
            valid_sources.append(source.model_copy(update=update))
            positions.append((x, y))

    if not valid_sources:
        if wcs is None:
            raise ValueError("Missing WCS and no source XYs given")
        raise ValueError("All sources are outside image boundaries")

    source_table = np.zeros(
        len(valid_sources),
        [
            ("x", float),
            ("y", float),
            ("a", float),
            ("b", float),
            ("theta", float),
            ("flux", float),
            ("saturated", int),
            ("flag", int),
        ],
    )

    for idx, (x, y) in enumerate(positions):
        source_table[idx]["x"] = x
        source_table[idx]["y"] = y

    r_cent = settings.centroid_radius
    if settings.mode == "auto":
        phot_kw["radius"] = r_cent
        for idx, source in enumerate(valid_sources):
            row = source_table[idx]
            row["a"] = getattr(source, "fwhm_x", None) or 0
            row["b"] = getattr(source, "fwhm_y", None) or 0
            row["theta"] = getattr(source, "theta", None) or 0
            row["flux"] = getattr(source, "flux", None) or 0

            sat_val = getattr(source, "sat_pixels", None)
            if sat_val is None:
                sat_val = 0
            try:
                row["saturated"] = int(sat_val)
            except Exception:
                row["saturated"] = 0
            if (not row["a"] or not row["b"]) and r_cent <= 0:
                raise ValueError(
                    "Centroiding radius must be provided for adaptive photometry with no FWHM info"
                )
        source_table["a"] /= SIGMA_TO_FWHM
        source_table["b"] /= SIGMA_TO_FWHM
        source_table["theta"] = np.deg2rad(source_table["theta"])

    if r_cent > 0:
        data = _ensure_native_contiguous(data)
        x_arr = _ensure_native_contiguous(source_table["x"])
        y_arr = _ensure_native_contiguous(source_table["y"])
        centroid_sources(data, x_arr, y_arr, r_cent)
        source_table["x"] = x_arr
        source_table["y"] = y_arr


    source_table = aperture_photometry(data, source_table, background, background_rms, **phot_kw)
    logger.info(
        "Photometry solution computed using %s mode for %d sources",
        settings.mode,
        len(source_table),
    )

    results: list[PhotometryData] = []
    for row, source in zip(source_table, valid_sources):
        if row["flag"] & (0xF0 & ~sep.APER_HASMASKED):
            continue
        if not np.isfinite(
            [row["x"], row["y"], row["flux"], row["flux_err"], row["mag"], row["mag_err"]]
        ).all():
            continue
        # Translate skylib output column names to unit-suffixed schema names
        row_dict = _row_to_mapping(row)
        if "flux_err" in row_dict:
            row_dict["flux_err_counts"] = row_dict.pop("flux_err")
        if "mag_err" in row_dict:
            row_dict["magnitude_err_mag"] = row_dict.pop("mag_err")
        # Build PhotometryData first (sets x/y from row, including centroided positions),
        # then apply WCS so RA/Dec reflects the row's (centroided) pixel position — legacy parity.
        phot_data = PhotometryData.from_source_and_row(
            source=source,
            row=row_dict,
            zero_point_mag=settings.zero_point_mag,
        )
        phot_data = _apply_wcs_to_source(phot_data, wcs)
        results.append(phot_data)

    logger.info("Photometry produced %d valid measurements", len(results))
    return results
