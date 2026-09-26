"""algorithms.hrdiagram_py.membership - field-star removal (parallax + proper-motion cut).

Pure pandas/numpy: no network.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

import numpy as np
import pandas as pd

__all__ = ["select_cluster_members"]

logger = logging.getLogger(__name__)

#: km/s -> mas/yr conversion constant (4.74047 km/s per AU/yr): a transverse
#: velocity v (km/s) at distance d (kpc) subtends v / (4.74 * d) mas/yr.
_KM_S_PER_AU_YR = 4.74


# PORTED: was the elliptical branch of `updateClusterFieldSources`
# (git-history:algorithms/hrdiagram/photometry/cluster-data.service.util.ts:101-120,
# Astromancer TypeScript). Faithful translation of the acceptance-test
# formula; `select_cluster_members` below is what supplies its per-source
# semi-axes, which is original code, not part of this port.
def _elliptical_pm_mask(
    pmra: np.ndarray,
    pmdec: np.ndarray,
    center_pmra: float,
    center_pmdec: float,
    a: np.ndarray,
    b: np.ndarray,
) -> np.ndarray:
    """The elliptical proper-motion acceptance test from Astromancer's
    ``updateClusterFieldSources``
    (``git-history:algorithms/hrdiagram/photometry/cluster-data.service.util.ts:101-120``).

    A star is a member if ``(pmra, pmdec)`` falls inside the ellipse centred
    on ``(center_pmra, center_pmdec)`` with semi-axes ``a`` (pm_ra) and ``b``
    (pm_dec). Upstream used one scalar ``a``/``b`` per selection (a human
    picked one slider range for the whole sample); here they may be arrays,
    one value per star -- the same elementwise formula handles both.

    Preserves upstream's documented "correct by accident" behaviour
    (``docs/extraction.md``, HR Diagram TypeScript defect #8): for a star with
    ``|pmra - center_pmra| > a``, ``1 - ((pmra-center_pmra)/a)**2`` is
    negative, so ``decDiff`` is ``NaN``, and the subsequent bound comparison
    evaluates to ``False`` in both TypeScript and here -- the right rejection,
    reached through a NaN rather than an explicit "outside the semi-axis"
    branch. ``np.errstate`` suppresses the resulting RuntimeWarning rather
    than treating this expected NaN as a problem.
    """
    with np.errstate(invalid="ignore"):
        dec_half_width = b * np.sqrt(1.0 - ((pmra - center_pmra) / a) ** 2)
    return (pmdec >= center_pmdec - dec_half_width) & (pmdec <= center_pmdec + dec_half_width)


def select_cluster_members(
    gaia_matched: pd.DataFrame,
    literature: Mapping[str, Any],
    plx_sigma: float = 3.0,
    pm_sigma: float = 3.0,
    pm_dispersion_km_s: float = 3.0,
) -> pd.DataFrame:
    """Keep sources consistent with the cluster's parallax and proper motion.

    The parallax gate is a per-source error-scaled window, unchanged:
    ``|parallax - literature_parallax| <= max(plx_sigma * parallax_error, 0.05)``.

    The proper-motion gate is Astromancer's real elliptical acceptance region
    (see ``_elliptical_pm_mask``) rather than the isotropic circle this
    function used before -- but the ellipse's *shape* alone does not fix
    anything: a circle and an axis-aligned ellipse of the same fixed radius
    reject the same points. What actually matters is *sizing* each axis per
    source, the same way the parallax gate already does, instead of one fixed
    mas/yr number for every star regardless of distance or measurement
    precision:

    ``a_i = max(pm_sigma * pmra_error_i, pm_floor_mas_yr)``,
    ``b_i = max(pm_sigma * pmdec_error_i, pm_floor_mas_yr)``

    where ``pm_floor_mas_yr = pm_dispersion_km_s / (4.74 * distance_kpc)``
    converts an assumed cluster internal velocity dispersion (km/s) to an
    angular proper-motion floor through the cluster's *own* literature
    distance. This is the piece that matters in practice: angular PM
    dispersion for a fixed physical velocity dispersion scales as
    ``1/distance``, so a single fixed mas/yr tolerance cannot be right for
    both a nearby cluster (e.g. the Pleiades at 128 pc) and a distant one
    (e.g. NGC 6124 at 654 pc) -- confirmed live: a 1.5 mas/yr window rejects
    roughly two-thirds of the Pleiades' own parallax-confirmed candidates
    (whose real proper-motion scatter around the literature centre is ~2
    mas/yr, far larger than their ~0.02-0.1 mas/yr measurement errors),
    while the same window is already generous for NGC 6124.

    ``pm_dispersion_km_s=3.0`` was chosen by sweeping 1-5 km/s against both
    clusters and comparing the resulting isochrone fit to the literature: 1.0
    (a "typical" cluster velocity dispersion guess) turned out too tight,
    reproducing the original problem for the Pleiades (10 members, a poorly
    constrained fit) while barely changing NGC 6124; 3.0 recovers a
    fit-quality plateau for both (the Pleiades' age-vs-literature error drops
    from 78% to ~12%; NGC 6124's own already-good fit is essentially
    unchanged from its pre-port baseline). This is still one global default
    for a hard cut, not the mixture-model membership probabilities
    Cantat-Gaudin's own catalog is built from -- widen or narrow it per
    cluster (richer/older clusters and ones with a real high-velocity
    subpopulation may need a different value) rather than treating 3.0 as
    universally correct.

    Requires ``gaia_matched`` to carry ``pmra_error``/``pmdec_error`` (both
    ``tools.hr_diagram``'s Gaia-fetch paths attach these -- see
    ``matching.match_sources_to_gaia`` and ``tools.hr_diagram._fetch_gaia_for_position``).
    """
    df = gaia_matched.dropna(
        subset=["parallax", "parallax_error", "pmra", "pmdec", "pmra_error", "pmdec_error"]
    ).copy()

    plx_tol = np.maximum(plx_sigma * df["parallax_error"].to_numpy(), 0.05)
    plx_ok = np.abs(df["parallax"].to_numpy() - literature["parallax_mas"]) <= plx_tol

    pm_floor_mas_yr = pm_dispersion_km_s / (_KM_S_PER_AU_YR * literature["distance_kpc"])
    a = np.maximum(pm_sigma * df["pmra_error"].to_numpy(), pm_floor_mas_yr)
    b = np.maximum(pm_sigma * df["pmdec_error"].to_numpy(), pm_floor_mas_yr)
    pm_ok = _elliptical_pm_mask(
        df["pmra"].to_numpy(), df["pmdec"].to_numpy(),
        literature["pmra_mas_yr"], literature["pmdec_mas_yr"], a, b,
    )

    members = df[plx_ok & pm_ok].reset_index(drop=True)
    logger.info(
        "select_cluster_members: %d / %d sources kept as cluster members "
        "(plx_sigma=%s, pm_sigma=%s, pm_dispersion_km_s=%s, pm_floor_mas_yr=%.4f)",
        len(members), len(df), plx_sigma, pm_sigma, pm_dispersion_km_s, pm_floor_mas_yr,
    )
    if members.empty:
        raise RuntimeError(
            "No sources survived the parallax/proper-motion membership cut. Widen "
            "plx_sigma / pm_sigma / pm_dispersion_km_s, or check that the literature "
            "parameters resolved the intended cluster."
        )
    return members
