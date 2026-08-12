"""algorithms.radio.matching - detected sources <-> an arbitrary VizieR catalog table.

``tools.vizier.search_vizier(category="radio")`` returns one table per
matched catalog with no fixed schema -- NVSS, TGSS, VLSSr, SUMSS, GLEAM, and
every other radio survey each name their RA/Dec columns differently. This
module guesses the column names from a short list of conventions VizieR
tables actually use, rather than hardcoding one catalog's names the way
``algorithms.hrdiagram_py.matching.match_sources_to_gaia`` hardcodes Gaia's.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

__all__ = ["guess_radec_columns", "match_sources_to_catalog"]

#: Tried in order; the first pair present (case-insensitively) in the table wins.
_RADEC_CANDIDATES = [
    ("RAJ2000", "DEJ2000"),
    ("RA_ICRS", "DE_ICRS"),
    ("_RAJ2000", "_DEJ2000"),
    ("RAdeg", "DEdeg"),
    ("RA2000", "DEC2000"),
    ("RA", "DEC"),
    ("RA", "Dec"),
    ("ra", "dec"),
]


def _coerce_degrees(series: pd.Series, is_ra: bool) -> np.ndarray | None:
    """Best-effort conversion of an RA/Dec column to decimal degrees.

    VizieR tables mix decimal-degree columns with legacy sexagesimal string
    columns (e.g. ``"23 23 25.32"``) under the very same conventional names
    (confirmed live: a catalog matched by the ``"RA"``/``"DEC"`` fallback
    returned exactly this). Returns ``None`` rather than raising when neither
    a numeric nor a sexagesimal reading works, so the caller can skip this
    one catalog instead of failing the whole cross-match.
    """
    try:
        return series.to_numpy(dtype=float)
    except (TypeError, ValueError):
        pass
    try:
        from astropy.coordinates import Angle
        import astropy.units as u

        unit = u.hourangle if is_ra else u.deg
        return Angle(series.astype(str).to_numpy(), unit=unit).degree
    except Exception:
        return None


def guess_radec_columns(table: pd.DataFrame) -> tuple[str, str] | None:
    """Return the (ra, dec) column names in ``table``, or ``None`` if no
    known convention matches."""
    lookup = {str(c).lower(): str(c) for c in table.columns}
    for ra_name, dec_name in _RADEC_CANDIDATES:
        ra_actual = lookup.get(ra_name.lower())
        dec_actual = lookup.get(dec_name.lower())
        if ra_actual is not None and dec_actual is not None:
            return ra_actual, dec_actual
    return None


def match_sources_to_catalog(
    sources_df: pd.DataFrame,
    catalog_df: pd.DataFrame,
    radius_arcsec: float,
    ra_col: str | None = None,
    dec_col: str | None = None,
) -> list[dict]:
    """Nearest-catalog-neighbour within ``radius_arcsec`` for every row in
    ``sources_df`` (expects ``ra_deg``/``dec_deg`` columns).

    Not mutual-nearest-neighbour (contrast with
    ``algorithms.hrdiagram_py.matching.match_sources_to_gaia``) -- catalog
    source density varies enormously between radio surveys, so requiring the
    catalog row's own nearest detection to be this one would reject real
    matches in a sparse detected-source field against a dense catalog.
    Returns one entry per matched source (not per candidate), each carrying
    the full matched catalog row so the caller can read whatever
    flux/frequency/name columns that particular catalog happens to have.
    """
    if sources_df.empty or catalog_df.empty:
        return []

    if ra_col is None or dec_col is None:
        guessed = guess_radec_columns(catalog_df)
        if guessed is None:
            return []
        ra_col, dec_col = guessed

    catalog_df = catalog_df.dropna(subset=[ra_col, dec_col]).reset_index(drop=True)
    if catalog_df.empty:
        return []

    catalog_ra = _coerce_degrees(catalog_df[ra_col], is_ra=True)
    catalog_dec = _coerce_degrees(catalog_df[dec_col], is_ra=False)
    if catalog_ra is None or catalog_dec is None:
        return []

    ra0 = float(sources_df["ra_deg"].mean())
    dec0 = float(sources_df["dec_deg"].mean())
    cos_dec0 = np.cos(np.deg2rad(dec0))

    def to_xy_arcsec(ra_deg: np.ndarray, dec_deg: np.ndarray) -> np.ndarray:
        x = (ra_deg - ra0) * cos_dec0 * 3600.0
        y = (dec_deg - dec0) * 3600.0
        return np.column_stack([x, y])

    source_xy = to_xy_arcsec(
        sources_df["ra_deg"].to_numpy(dtype=float), sources_df["dec_deg"].to_numpy(dtype=float)
    )
    catalog_xy = to_xy_arcsec(catalog_ra, catalog_dec)

    catalog_tree = cKDTree(catalog_xy)
    distances, indices = catalog_tree.query(source_xy, distance_upper_bound=radius_arcsec)

    matches = []
    for source_pos, (separation, catalog_pos) in enumerate(zip(distances, indices)):
        if not np.isfinite(separation) or catalog_pos >= len(catalog_df):
            continue
        matches.append(
            {
                "source_index": sources_df.index[source_pos],
                "separation_arcsec": float(separation),
                "catalog_row": catalog_df.iloc[catalog_pos].to_dict(),
            }
        )
    return matches
