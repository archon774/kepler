"""Field-star removal: parallax + proper-motion membership cut.

Pure numpy/pandas, no network -- operates on whatever gaia.crossmatch_gaia()
already attached.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def select_cluster_members(
    gaia_matched: pd.DataFrame,
    literature: Mapping[str, Any],
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
) -> pd.DataFrame:
    """Keep sources consistent with the cluster's parallax and proper motion.

    This is a simplified stand-in for the elliptical (pm_ra, pm_dec) region
    intersected with a distance interval that Astromancer's field-star-removal
    module uses (hrdiagram/fsr/, the TypeScript extraction at repo root) -- an
    isotropic circular cut in proper motion plus a parallax window, rather
    than a fitted ellipse. Good enough to clear obvious field-star
    contamination; adjust plx_sigma / pm_tol_mas_yr, or port the elliptical
    FSR from hrdiagram/fsr/cmd-fsr.util.ts, for tighter work.

    Requires `gaia_matched` to carry parallax/pmra/pmdec (e.g. from
    gaia.crossmatch_gaia()) and `literature` to carry the cluster's own
    parallax_mas/pmra_mas_yr/pmdec_mas_yr --
    literature.get_literature_globular_cluster_params() leaves these None if
    its astrometry catalog didn't have the cluster, in which case this raises
    rather than silently comparing against None.
    """
    missing_lit = [k for k in ("parallax_mas", "pmra_mas_yr", "pmdec_mas_yr") if literature.get(k) is None]
    if missing_lit:
        raise ValueError(
            f"literature is missing {missing_lit} -- field-star removal needs the "
            "cluster's own parallax and proper motion. For a globular cluster this "
            "means it wasn't found in the Vasiliev & Baumgardt astrometry catalog; "
            "supply these three values yourself if you have them from elsewhere."
        )

    df = gaia_matched.dropna(subset=["parallax", "parallax_error", "pmra", "pmdec"]).copy()

    plx_tol = np.maximum(plx_sigma * df["parallax_error"].to_numpy(), 0.05)
    plx_ok = np.abs(df["parallax"].to_numpy() - literature["parallax_mas"]) <= plx_tol

    pm_sep = np.hypot(
        df["pmra"].to_numpy() - literature["pmra_mas_yr"],
        df["pmdec"].to_numpy() - literature["pmdec_mas_yr"],
    )
    pm_ok = pm_sep <= pm_tol_mas_yr

    members = df[plx_ok & pm_ok].reset_index(drop=True)
    logger.info(
        "select_cluster_members: %d / %d sources kept as cluster members (plx_sigma=%s, pm_tol=%s mas/yr)",
        len(members), len(df), plx_sigma, pm_tol_mas_yr,
    )
    if members.empty:
        raise RuntimeError(
            "No sources survived the parallax/proper-motion membership cut. Widen "
            "plx_sigma / pm_tol_mas_yr, or check that literature.get_literature_cluster_params() "
            "resolved the intended cluster."
        )
    return members
