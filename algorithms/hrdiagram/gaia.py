"""Gaia DR3 crossmatch: attaches multi-band photometry and astrometry.

A single FITS frame (or an existing photometry table in one instrument's
filters) is not enough to build a colour-magnitude diagram or to do field-star
removal on its own. crossmatch_gaia() bridges both gaps at once: it matches
detected sources to Gaia DR3 by sky position and attaches G/BP/RP magnitudes
plus parallax/proper motion -- the parallax/PM is what membership.py's
field-star removal needs, whether or not the caller ends up fitting Gaia's own
G/BP/RP or the frame's/table's own filters.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)


def _flat_sky_xy(ra_deg: np.ndarray, dec_deg: np.ndarray, ra0_deg: float, dec0_deg: float) -> np.ndarray:
    """Small-field flat-sky projection in arcsec, for KD-tree matching."""
    cos_dec0 = np.cos(np.deg2rad(dec0_deg))
    x = (ra_deg - ra0_deg) * cos_dec0 * 3600.0
    y = (dec_deg - dec0_deg) * 3600.0
    return np.column_stack([x, y])


def crossmatch_gaia(
    sources: pd.DataFrame,
    radius_arcsec: float = 2.0,
    mag_limit: float = 20.0,
) -> pd.DataFrame:
    """Match detected sources to Gaia DR3 by sky position and attach G/BP/RP.

    One cone query covers the frame's whole footprint (padded), then each
    detected source is matched to its nearest Gaia neighbour within
    `radius_arcsec` (mutual nearest-neighbour, same approach as
    algorithms.fieldcal.field_cal's angular matching).
    """
    from astroquery.gaia import Gaia

    ra0 = float(sources["ra_deg"].mean())
    dec0 = float(sources["dec_deg"].mean())
    cos_dec0 = max(0.2, abs(np.cos(np.deg2rad(dec0))))
    half_diag_deg = float(
        np.hypot(
            (sources["ra_deg"].max() - sources["ra_deg"].min()) * cos_dec0,
            sources["dec_deg"].max() - sources["dec_deg"].min(),
        )
    ) / 2.0
    radius_deg = half_diag_deg + radius_arcsec / 3600.0 + 0.02  # pad for match tolerance + safety margin

    adql = f"""
        SELECT source_id, ra, dec, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag,
               phot_g_mean_flux_over_error, phot_bp_mean_flux_over_error, phot_rp_mean_flux_over_error,
               parallax, parallax_error, pmra, pmdec, pmra_error, pmdec_error
        FROM gaiadr3.gaia_source
        WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra0}, {dec0}, {radius_deg}))
          AND phot_g_mean_mag < {mag_limit}
          AND phot_bp_mean_mag IS NOT NULL AND phot_rp_mean_mag IS NOT NULL
    """
    gaia = Gaia.launch_job(adql).get_results().to_pandas()
    if gaia.empty:
        raise RuntimeError(
            f"No Gaia DR3 sources brighter than G={mag_limit} within {radius_deg * 3600:.0f}\" "
            f"of RA={ra0:.4f} Dec={dec0:.4f}"
        )

    det_xy = _flat_sky_xy(sources["ra_deg"].to_numpy(), sources["dec_deg"].to_numpy(), ra0, dec0)
    gaia_xy = _flat_sky_xy(gaia["ra"].to_numpy(), gaia["dec"].to_numpy(), ra0, dec0)
    det_tree = cKDTree(det_xy)
    gaia_tree = cKDTree(gaia_xy)

    matched_rows = []
    for i, det_pt in enumerate(det_xy):
        j = gaia_tree.query(det_pt, distance_upper_bound=radius_arcsec)[1]
        if j >= len(gaia):
            continue
        # mutual nearest-neighbour: the matched Gaia source's nearest detection must be this one
        back = det_tree.query(gaia_xy[j], distance_upper_bound=radius_arcsec)[1]
        if back != i:
            continue
        row = sources.iloc[i].to_dict()
        g = gaia.iloc[j]
        row.update(
            {
                "gaia_source_id": int(g["source_id"]),
                "G": float(g["phot_g_mean_mag"]),
                "BP": float(g["phot_bp_mean_mag"]),
                "RP": float(g["phot_rp_mean_mag"]),
                "G_err": 1.0857 / float(g["phot_g_mean_flux_over_error"]) if g["phot_g_mean_flux_over_error"] else np.nan,
                "BP_err": 1.0857 / float(g["phot_bp_mean_flux_over_error"]) if g["phot_bp_mean_flux_over_error"] else np.nan,
                "RP_err": 1.0857 / float(g["phot_rp_mean_flux_over_error"]) if g["phot_rp_mean_flux_over_error"] else np.nan,
                "parallax": float(g["parallax"]) if pd.notna(g["parallax"]) else np.nan,
                "parallax_error": float(g["parallax_error"]) if pd.notna(g["parallax_error"]) else np.nan,
                "pmra": float(g["pmra"]) if pd.notna(g["pmra"]) else np.nan,
                "pmdec": float(g["pmdec"]) if pd.notna(g["pmdec"]) else np.nan,
                "sep_arcsec": float(np.hypot(*(det_pt - gaia_xy[j]))),
            }
        )
        matched_rows.append(row)

    if not matched_rows:
        raise RuntimeError(
            f"None of the {len(sources)} detected sources matched a Gaia source within "
            f"{radius_arcsec}\". Check the frame's WCS, or widen radius_arcsec."
        )

    df = pd.DataFrame(matched_rows)
    logger.info("crossmatch_gaia: matched %d / %d detected sources", len(df), len(sources))
    return df
