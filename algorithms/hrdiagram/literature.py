"""Published cluster parameters, by name -- open clusters and globular clusters.

Two independent catalogue families, since no single one covers both cluster
types with everything hr.fit needs:

  - Open clusters: Cantat-Gaudin & Anders (2020), a Gaia-DR2 based
    re-derivation for ~2000 clusters -- distance/age/reddening AND
    parallax/proper motion all in one table, on the same Gaia astrometric
    footing as gaia.py's crossmatch photometry.
  - Globular clusters: Harris (1996, 2010 edition) for distance/E(B-V)/[Fe/H],
    plus Vasiliev & Baumgardt (2021) for Gaia-based parallax/proper motion --
    Harris doesn't publish astrometry, and neither publishes per-cluster ages
    (globular clusters are all old and hard to age-date precisely from
    integrated-light catalogues).

Both catalogue families are on VizieR, queried directly (no algorithms.query
backend covers them -- that registry is shaped around photometric reference
catalogues bound to algorithms.catalogs declarations, a different kind of lookup).
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Vizier catalog of Gaia-DR2-based open-cluster parameters (Cantat-Gaudin & Anders
# 2020, A&A 640, A1). Chosen over WEBDA because it is queryable through astroquery
# without HTML scraping and its distance/age/extinction are on the same Gaia
# astrometric footing as gaia.py's crossmatch photometry.
CLUSTER_CATALOG = "J/A+A/640/A1/table1"
CLUSTER_CATALOG_CITATION = "Cantat-Gaudin & Anders 2020, A&A 640, A1 (VizieR J/A+A/640/A1)"

# Globular clusters aren't in the open-cluster catalog above (different Vizier
# name convention too: "NGC 1851", not "NGC_1851"). Two catalogs, because no
# single one has both: Harris gives distance/reddening/metallicity but no
# proper motion; Vasiliev & Baumgardt gives Gaia-based parallax/proper motion
# (needed for field-star removal, see membership.py) but not those.
GLOBULAR_CLUSTER_CATALOG = "VII/202/catalog"
GLOBULAR_CLUSTER_CATALOG_CITATION = "Harris 1996 (2010 edition), VizieR VII/202"
GLOBULAR_CLUSTER_PM_CATALOG = "J/MNRAS/505/5978/tablea1"
GLOBULAR_CLUSTER_PM_CATALOG_CITATION = "Vasiliev & Baumgardt 2021, MNRAS 505, 5978 (VizieR J/MNRAS/505/5978)"
# Harris doesn't publish a per-cluster age (globular clusters are all old and
# hard to age-date precisely from integrated catalogs); used only when the
# caller doesn't supply log_age explicitly. ~12.6 Gyr, a typical old-GC value.
DEFAULT_GLOBULAR_CLUSTER_LOG_AGE = 10.10


def resolve_cluster_name(name: str) -> str:
    """Return a Vizier-J/A+A/640/A1-style designation ("NGC_2168") for a cluster name.

    Tries the name itself first (whitespace collapsed to a single underscore),
    then falls back to SIMBAD's alias list (e.g. "M35" -> "NGC 2168") and tries
    each alias in turn.
    """
    from astroquery.vizier import Vizier
    from astroquery.simbad import Simbad

    def normalize(raw: str) -> str:
        return re.sub(r"\s+", "_", raw.strip())

    vizier = Vizier(columns=["Cluster"])
    vizier.ROW_LIMIT = 1

    candidates = [normalize(name)]
    try:
        ids = Simbad.query_objectids(name)
        if ids is not None:
            candidates += [normalize(str(row[0])) for row in ids]
    except Exception:
        logger.warning("resolve_cluster_name: SIMBAD alias lookup failed for %r", name, exc_info=True)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = vizier.query_constraints(catalog=CLUSTER_CATALOG, Cluster=candidate)
        except Exception:
            continue
        if result:
            return candidate

    raise ValueError(
        f"Could not find {name!r} (tried: {', '.join(sorted(seen))}) in {CLUSTER_CATALOG}. "
        "The catalog covers ~2000 nearby open clusters; if this one isn't in it, supply "
        "literature parameters manually instead of calling get_literature_cluster_params()."
    )


def get_literature_open_cluster_params(name: str) -> dict[str, Any]:
    """Published age / distance / reddening for a named open cluster.

    Source: Cantat-Gaudin & Anders (2020), a Gaia-DR2 based re-derivation for
    ~2000 clusters -- chosen so distance and reddening are on the same Gaia
    astrometric footing as gaia.crossmatch_gaia()'s photometry.
    """
    from astroquery.vizier import Vizier

    resolved = resolve_cluster_name(name)
    vizier = Vizier(columns=["Cluster", "RA_ICRS", "DE_ICRS", "plx", "pmRA*", "pmDE", "AgeNN", "AVNN", "DMNN", "DistPc"])
    vizier.ROW_LIMIT = 1
    result = vizier.query_constraints(catalog=CLUSTER_CATALOG, Cluster=resolved)
    if not result:
        raise ValueError(f"{resolved!r} resolved but no longer matched {CLUSTER_CATALOG}")
    row = result[0][0]

    log_age = float(row["AgeNN"])
    av = float(row["AVNN"])
    ebv = av / 3.1  # Rv=3.1, matching hrfit.get_extinction's default
    distance_pc = float(row["DistPc"])

    return {
        "cluster": name,
        "resolved_name": resolved,
        "cluster_type": "open",
        "ra_deg": float(row["RA_ICRS"]),
        "dec_deg": float(row["DE_ICRS"]),
        "parallax_mas": float(row["plx"]),
        "pmra_mas_yr": float(row["pmRA*"]),
        "pmdec_mas_yr": float(row["pmDE"]),
        "log_age": log_age,
        "age_myr": 10.0 ** log_age / 1.0e6,
        "av": av,
        "ebv": ebv,
        "distance_pc": distance_pc,
        "distance_kpc": distance_pc / 1000.0,
        "distance_modulus": float(row["DMNN"]),
        "source": CLUSTER_CATALOG_CITATION,
    }


def resolve_globular_cluster_name(name: str) -> str:
    """Return a Harris-catalog-style designation ("NGC 1851") for a globular
    cluster name. Same alias-fallback strategy as resolve_cluster_name(), but
    Harris/Vasiliev-Baumgardt use a single space ("NGC 1851"), not the
    open-cluster catalog's underscore ("NGC_1851").
    """
    from astroquery.vizier import Vizier
    from astroquery.simbad import Simbad

    def normalize(raw: str) -> str:
        return re.sub(r"\s+", " ", raw.strip())

    vizier = Vizier(columns=["ID"])
    vizier.ROW_LIMIT = 1

    candidates = [normalize(name)]
    try:
        ids = Simbad.query_objectids(name)
        if ids is not None:
            candidates += [normalize(str(row[0])) for row in ids]
    except Exception:
        logger.warning("resolve_globular_cluster_name: SIMBAD alias lookup failed for %r", name, exc_info=True)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = vizier.query_constraints(catalog=GLOBULAR_CLUSTER_CATALOG, ID=candidate)
        except Exception:
            continue
        if result:
            return candidate

    raise ValueError(
        f"Could not find {name!r} (tried: {', '.join(sorted(seen))}) in {GLOBULAR_CLUSTER_CATALOG}. "
        "That catalog covers ~157 Milky Way globular clusters; if this one isn't in it, "
        "supply literature parameters manually instead of calling this function."
    )


def get_literature_globular_cluster_params(name: str, log_age: float | None = None) -> dict[str, Any]:
    """Published distance / reddening / metallicity (+ Gaia astrometry) for a
    named globular cluster.

    Distance, E(B-V) and [Fe/H] come from Harris (1996, 2010 edition); parallax
    and proper motion -- needed for membership.select_cluster_members()'s
    field-star removal, which Harris doesn't publish -- come from Vasiliev &
    Baumgardt's Gaia EDR3 astrometry. `log_age` defaults to
    DEFAULT_GLOBULAR_CLUSTER_LOG_AGE since Harris doesn't publish per-cluster
    ages either; pass your own if you have a better isochrone-fit age for this
    cluster from another source.
    """
    from astroquery.vizier import Vizier

    resolved = resolve_globular_cluster_name(name)

    harris = Vizier(columns=["ID", "RAJ2000", "DEJ2000", "Rsun", "E(B-V)", "(m-M)V", "[Fe/H]"])
    harris.ROW_LIMIT = 1
    hresult = harris.query_constraints(catalog=GLOBULAR_CLUSTER_CATALOG, ID=resolved)
    if not hresult:
        raise ValueError(f"{resolved!r} resolved but no longer matched {GLOBULAR_CLUSTER_CATALOG}")
    hrow = hresult[0][0]

    pm = Vizier(columns=["Name", "pmRA", "pmDE", "plx"])
    pm.ROW_LIMIT = 1
    presult = pm.query_constraints(catalog=GLOBULAR_CLUSTER_PM_CATALOG, Name=resolved)
    pmra_mas_yr = pmdec_mas_yr = parallax_mas = None
    if presult:
        prow = presult[0][0]
        pmra_mas_yr = float(prow["pmRA"])
        pmdec_mas_yr = float(prow["pmDE"])
        parallax_mas = float(prow["plx"])
        astrometry_source = GLOBULAR_CLUSTER_PM_CATALOG_CITATION
    else:
        logger.warning(
            "get_literature_globular_cluster_params: no Gaia astrometry for %r in %s -- "
            "membership.select_cluster_members() (field-star removal) will not be usable "
            "for this cluster.",
            resolved, GLOBULAR_CLUSTER_PM_CATALOG,
        )
        astrometry_source = "not found"

    age_is_default = log_age is None
    log_age = DEFAULT_GLOBULAR_CLUSTER_LOG_AGE if age_is_default else log_age

    distance_kpc = float(hrow["Rsun"])
    ebv = float(hrow["E(B-V)"])
    av = 3.1 * ebv  # Rv=3.1, matching hrfit.get_extinction's default
    apparent_distance_modulus = float(hrow["(m-M)V"])

    # Harris' RAJ2000/DEJ2000 are sexagesimal strings ("05 14 06.3", "-40 02 50"),
    # not decimal degrees like the open-cluster catalog's RA_ICRS/DE_ICRS.
    from astropy.coordinates import SkyCoord
    from astropy import units as u
    coord = SkyCoord(str(hrow["RAJ2000"]), str(hrow["DEJ2000"]), unit=(u.hourangle, u.deg))

    return {
        "cluster": name,
        "resolved_name": resolved,
        "cluster_type": "globular",
        "ra_deg": float(coord.ra.deg),
        "dec_deg": float(coord.dec.deg),
        "parallax_mas": parallax_mas,
        "pmra_mas_yr": pmra_mas_yr,
        "pmdec_mas_yr": pmdec_mas_yr,
        "log_age": log_age,
        "age_myr": 10.0 ** log_age / 1.0e6,
        "age_is_literature_default": age_is_default,
        "av": av,
        "ebv": ebv,
        "feh": float(hrow["[Fe/H]"]),
        "distance_pc": distance_kpc * 1000.0,
        "distance_kpc": distance_kpc,
        "distance_modulus": apparent_distance_modulus - av,
        "source": f"{GLOBULAR_CLUSTER_CATALOG_CITATION}; astrometry: {astrometry_source}",
    }


def get_literature_cluster_params(name: str) -> dict[str, Any]:
    """Published parameters for a named cluster, open or globular.

    Tries the open-cluster catalog (Cantat-Gaudin & Anders 2020) first, since
    it's Gaia-astrometry-consistent and gives a real per-cluster age; falls
    back to the globular-cluster catalogs (Harris 2010 + Vasiliev & Baumgardt
    2021) if the name isn't found there. Check the returned "cluster_type"
    ("open" or "globular") -- globular-cluster results carry a "feh" key and
    may have "age_is_literature_default": True (see
    get_literature_globular_cluster_params).
    """
    try:
        return get_literature_open_cluster_params(name)
    except ValueError as open_exc:
        try:
            return get_literature_globular_cluster_params(name)
        except ValueError as globular_exc:
            raise ValueError(
                f"{name!r} not found as an open cluster ({open_exc}) or a globular "
                f"cluster ({globular_exc})."
            ) from globular_exc
