"""algorithms.hrdiagram_py.literature - a fetched cluster-catalog row -> published parameters.

Pure parsing: no network, no astroquery import. The catalog row itself is
fetched one layer up, in ``tools.hr_diagram``, via
``tools.vizier.search_vizier(target=cluster_name, catalog=CLUSTER_CATALOG)`` --
VizieR's own name resolver (the same one SIMBAD uses; confirmed live and
documented in ``tools/agent/prompt.py``) turns a common name or
alias ("M35") into a position, and a position-based query against a
cluster-parameter catalog finds that cluster's own row by proximity. That
sidesteps needing a bespoke alias-resolution cascade here entirely: name
resolution already *is* position resolution for a lookup like this one.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["CLUSTER_CATALOG", "CLUSTER_CATALOG_CITATION", "parse_cluster_params"]

# Vizier catalog of Gaia-DR2-based open-cluster parameters (Cantat-Gaudin & Anders
# 2020, A&A 640, A1). Chosen over WEBDA because it is queryable through astroquery
# without HTML scraping and its distance/age/extinction are on the same Gaia
# astrometric footing as the crossmatch photometry used here.
CLUSTER_CATALOG = "J/A+A/640/A1/table1"
CLUSTER_CATALOG_CITATION = "Cantat-Gaudin & Anders 2020, A&A 640, A1 (VizieR J/A+A/640/A1)"


def parse_cluster_params(row: Mapping[str, Any], cluster_name: str) -> dict[str, Any]:
    """Turn one ``CLUSTER_CATALOG`` row into age/distance/reddening parameters.

    ``row`` uses VizieR's own column names for this catalog: ``RA_ICRS``,
    ``DE_ICRS``, ``plx``, ``pmRA*``, ``pmDE``, ``AgeNN``, ``AVNN``, ``DMNN``,
    ``DistPc``. Source: Cantat-Gaudin & Anders (2020), a Gaia-DR2 based
    re-derivation for ~2000 clusters -- chosen so distance and reddening are
    on the same Gaia astrometric footing as the frame's Gaia crossmatch.
    """
    log_age = float(row["AgeNN"])
    av = float(row["AVNN"])
    ebv = av / 3.1  # Rv=3.1, matching hrfit.get_extinction's default
    distance_pc = float(row["DistPc"])

    return {
        "cluster": cluster_name,
        "resolved_name": str(row.get("Cluster", cluster_name)),
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
