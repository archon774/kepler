"""algorithms.hrdiagram_py.matching - detected sources <-> catalog rows by sky position.

Pure geometry: no network, no astroquery import. A single FITS frame is one
filter, which is not enough for a colour-magnitude diagram on its own --
callers fetch a comparison catalog (Gaia DR3, in practice) themselves and pass
the resulting table in here. Fetching lives one layer up, in
``tools.hr_diagram``, via ``tools.vizier.search_vizier`` -- that tool already
does unbounded, all-column VizieR queries by position (see its module
docstring), so there is nothing left for this package to fetch on its own.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

__all__ = ["field_footprint", "match_sources_to_gaia"]

logger = logging.getLogger(__name__)


def _flat_sky_xy(ra_deg: np.ndarray, dec_deg: np.ndarray, ra0_deg: float, dec0_deg: float) -> np.ndarray:
    """Small-field flat-sky projection in arcsec, for KD-tree matching."""
    cos_dec0 = np.cos(np.deg2rad(dec0_deg))
    x = (ra_deg - ra0_deg) * cos_dec0 * 3600.0
    y = (dec_deg - dec0_deg) * 3600.0
    return np.column_stack([x, y])


def field_footprint(sources: pd.DataFrame, pad_arcsec: float = 0.0) -> tuple[float, float, float]:
    """Return (ra0_deg, dec0_deg, radius_deg) covering every row in ``sources``.

    The centroid plus half the sky-projected diagonal, padded by
    ``pad_arcsec`` -- sized for a single cone-search request that covers the
    whole frame's footprint, e.g. to fetch a comparison catalog once rather
    than once per detected source.
    """
    ra0 = float(sources["ra_deg"].mean())
    dec0 = float(sources["dec_deg"].mean())
    cos_dec0 = max(0.2, abs(np.cos(np.deg2rad(dec0))))
    half_diag_deg = float(
        np.hypot(
            (sources["ra_deg"].max() - sources["ra_deg"].min()) * cos_dec0,
            sources["dec_deg"].max() - sources["dec_deg"].min(),
        )
    ) / 2.0
    return ra0, dec0, half_diag_deg + pad_arcsec / 3600.0


def match_sources_to_gaia(sources: pd.DataFrame, gaia: pd.DataFrame, radius_arcsec: float = 2.0) -> pd.DataFrame:
    """Match ``sources`` (x, y, ra_deg, dec_deg, ...) to ``gaia`` by sky position.

    ``gaia`` is expected in VizieR's native ``I/355/gaiadr3`` column naming
    (``RA_ICRS``, ``DE_ICRS``, ``Source``, ``Gmag``, ``e_Gmag``, ``BPmag``,
    ``e_BPmag``, ``RPmag``, ``e_RPmag``, ``Plx``, ``e_Plx``, ``pmRA``,
    ``pmDE``, ``e_pmRA``, ``e_pmDE``) -- the shape ``tools.vizier.search_vizier``
    returns for that catalog, unrenamed. Mutual nearest-neighbour (the matched
    Gaia source's nearest detection must be this one), same approach as
    ``algorithms.fieldcal.field_cal``'s angular matching.

    Attaches Gaia's own G/BP/RP magnitudes, parallax, and proper motion (plus
    their formal errors, as ``parallax_error``/``pmra_error``/``pmdec_error``)
    to each matched row -- this is what supplies the colour for the HR
    diagram, and what ``membership.select_cluster_members`` needs to size its
    error-aware membership cut, since the frame's instrumental magnitude
    alone is single-band and carries no astrometric error of its own.
    """
    ra0 = float(sources["ra_deg"].mean())
    dec0 = float(sources["dec_deg"].mean())
    gaia = gaia.dropna(subset=["BPmag", "RPmag"]).reset_index(drop=True)
    if gaia.empty:
        raise RuntimeError("No Gaia rows with both BP and RP magnitudes to match against")

    det_xy = _flat_sky_xy(sources["ra_deg"].to_numpy(), sources["dec_deg"].to_numpy(), ra0, dec0)
    gaia_xy = _flat_sky_xy(gaia["RA_ICRS"].to_numpy(), gaia["DE_ICRS"].to_numpy(), ra0, dec0)
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
                "gaia_source_id": int(g["Source"]),
                "G": float(g["Gmag"]),
                "BP": float(g["BPmag"]),
                "RP": float(g["RPmag"]),
                "G_err": float(g["e_Gmag"]) if pd.notna(g["e_Gmag"]) else np.nan,
                "BP_err": float(g["e_BPmag"]) if pd.notna(g["e_BPmag"]) else np.nan,
                "RP_err": float(g["e_RPmag"]) if pd.notna(g["e_RPmag"]) else np.nan,
                "parallax": float(g["Plx"]) if pd.notna(g["Plx"]) else np.nan,
                "parallax_error": float(g["e_Plx"]) if pd.notna(g["e_Plx"]) else np.nan,
                "pmra": float(g["pmRA"]) if pd.notna(g["pmRA"]) else np.nan,
                "pmdec": float(g["pmDE"]) if pd.notna(g["pmDE"]) else np.nan,
                "pmra_error": float(g["e_pmRA"]) if pd.notna(g["e_pmRA"]) else np.nan,
                "pmdec_error": float(g["e_pmDE"]) if pd.notna(g["e_pmDE"]) else np.nan,
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
    logger.info("match_sources_to_gaia: matched %d / %d detected sources", len(df), len(sources))
    return df
