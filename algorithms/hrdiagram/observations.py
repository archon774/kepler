"""Sources for HR-diagram photometry: a FITS frame, or an existing table.

extract_photometry_from_fits() measures instrumental photometry on a FITS
frame via algorithms.photometry / algorithms.wcs -- a single frame is one filter,
which is why crossmatch_gaia() (see gaia.py) exists as the bridge to a colour.

load_afterglow_photometry() instead starts from a photometry table someone
else already produced (Afterglow's long-format export: one row per source per
filter), reshaping it to the wide layout hrfit.py's load_photometry() expects.
No network in this module.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from astropy.io import fits

from algorithms.photometry.photometry import perform_photometry
from algorithms.photometry.schemas import PhotometrySettings, SourceExtractionSettings
from algorithms.photometry.source_extraction import build_wcs_from_header
from algorithms.wcs.state import ProcessingRun

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
    data). This does not invoke the astrometry.net/ATLAS solver in
    algorithms.wcs.wcs -- that needs local index files most setups won't have. If
    the header has no WCS, re-solve the frame first (see
    algorithms.wcs.wcs.solve_wcs) or supply ra_deg/dec_deg some other way.

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

    # SourceExtractionData.file_id is typed int|None (it's just a log label), so
    # derive a stable small int from the path rather than passing the path itself.
    processing_run = ProcessingRun(observation_asset_id=abs(hash(str(fits_path))) % 10**8)
    results = perform_photometry(
        processing_run,
        header,
        data,
        settings=photometry_settings,
        extraction_settings=extraction_settings,
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
            "filter": r.filter,
        }
        for r in results
    ]
    df = pd.DataFrame(rows).dropna(subset=["ra_deg", "dec_deg"]).reset_index(drop=True)
    logger.info("extract_photometry_from_fits: %d sources with sky coordinates", len(df))
    return df


def load_afterglow_photometry(
    csv_path: str,
    mag_col: str = "calibrated_mag",
    err_col: str = "mag_error",
) -> pd.DataFrame:
    """Reshape an Afterglow-style long-format photometry export (one row per
    source per filter) into one row per source, with a magnitude and error
    column per filter -- the wide layout hrfit.py's load_photometry() expects.

    `mag_col` defaults to `calibrated_mag` (mag + zero_point_correction, i.e.
    the already-zero-point-corrected magnitude) rather than the raw `mag`
    column, so the caller doesn't have to re-apply the zero point by hand.
    """
    long_df = pd.read_csv(csv_path)
    required = {"id", "filter", mag_col}
    missing = required - set(long_df.columns)
    if missing:
        raise KeyError(f"{csv_path!r} is missing expected columns {missing}. Have: {list(long_df.columns)}")

    mag_wide = long_df.pivot_table(index="id", columns="filter", values=mag_col, aggfunc="first")
    positions = long_df.groupby("id")[["ra_hours", "dec_degs"]].first()

    wide = positions.join(mag_wide)
    wide = wide.rename(columns={"ra_hours": "ra_hours_"})  # keep raw hours around pre-conversion
    wide["ra_deg"] = wide.pop("ra_hours_") * 15.0
    wide = wide.rename(columns={"dec_degs": "dec_deg"})

    if err_col in long_df.columns:
        err_wide = long_df.pivot_table(index="id", columns="filter", values=err_col, aggfunc="first")
        err_wide = err_wide.rename(columns={c: f"{c}_err" for c in err_wide.columns})
        wide = wide.join(err_wide)

    wide = wide.reset_index()
    logger.info(
        "load_afterglow_photometry: %d sources, filters=%s",
        len(wide), sorted(long_df["filter"].unique()),
    )
    return wide
