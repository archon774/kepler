"""algorithms.hrdiagram_py.observations - FITS frame -> detected sources.

Calls into ``algorithms.photometry`` for source extraction/aperture photometry;
owns neither. No new algorithm code lives here, only the glue that turns one
FITS frame into a table of instrumental photometry.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from astropy.io import fits

from algorithms.photometry.photometry import run_photometry
from algorithms.photometry.schemas import PhotometrySettings, SourceExtractionSettings
from algorithms.photometry.source_extraction import build_wcs_from_header, run_source_extraction

__all__ = ["extract_photometry_from_fits"]

logger = logging.getLogger(__name__)


def extract_photometry_from_fits(
    fits_path: str,
    hdu_index: int = 0,
    threshold: float = 2.5,
    extraction_settings: SourceExtractionSettings | None = None,
    photometry_settings: PhotometrySettings | None = None,
) -> pd.DataFrame:
    """Detect sources in a FITS frame and measure instrumental photometry.

    Requires a celestial WCS already present in the header (from plate-solved
    data). This module does not invoke the astrometry.net/ATLAS solver in
    ``algorithms.wcs.wcs`` -- that needs local index files most setups won't
    have. If the header has no WCS, re-solve the frame first (see
    ``algorithms.wcs.wcs.solve_wcs``).

    Returns a DataFrame with columns: x, y, ra_deg, dec_deg, inst_mag,
    inst_mag_err, flux, filter.
    """
    with fits.open(fits_path) as hdul:
        header = hdul[hdu_index].header
        data = np.asarray(hdul[hdu_index].data, dtype=np.float64)

    if build_wcs_from_header(header) is None:
        raise ValueError(
            f"{fits_path!r} has no celestial WCS in its header. Plate-solve the "
            "frame first; this module only measures photometry, it does not solve "
            "astrometry."
        )

    extraction_settings = extraction_settings or SourceExtractionSettings(threshold=threshold)
    # "auto" (Kron-like, sized from each source's own detected FWHM) rather than
    # "aperture" (default mode, but requires an aperture radius the caller would
    # otherwise have to know in advance).
    photometry_settings = photometry_settings or PhotometrySettings(mode="auto")

    wcs = build_wcs_from_header(header)
    sources, background, background_rms = run_source_extraction(
        data,
        header,
        extraction_settings,
    )
    results = run_photometry(
        data, header, sources, photometry_settings,
        wcs=wcs, background=background, background_rms=background_rms,
    )

    if not results:
        raise RuntimeError(f"No sources detected/measured in {fits_path!r}")

    rows = [
        {
            "x": r.x,
            "y": r.y,
            "ra_deg": (r.ra_hours * 15.0) if r.ra_hours is not None else None,
            "dec_deg": r.dec_degs,
            "inst_mag": r.mag,
            "inst_mag_err": r.mag_error,
            "flux": r.flux,
            "flux_error": r.flux_error,
            "filter": r.filter,
        }
        for r in results
    ]
    df = pd.DataFrame(rows).dropna(subset=["ra_deg", "dec_deg"]).reset_index(drop=True)
    logger.info("extract_photometry_from_fits: %d sources with sky coordinates", len(df))
    return df
