"""Kepler: FITS frame -> HR diagram -> literature comparison.

Chains together pieces that already exist:

    algorithms.hrdiagram_py.observations   FITS -> detected sources (instrumental photometry)
    tools.vizier.search_vizier             Gaia DR3 (I/355/gaiadr3) + cluster-parameter lookup
    algorithms.hrdiagram_py.matching        detected sources <-> Gaia rows, by sky position
    algorithms.hrdiagram_py.literature       a fetched catalog row -> age/distance/E(B-V)
    algorithms.hrdiagram_py.membership       field-star removal (parallax + PM cut)
    algorithms.hrdiagram_py.isochrones       local Girardi isochrone fit, CMD/HR plot

A single FITS frame is one filter, which is not enough for a colour-magnitude
diagram on its own. The bridge is Gaia: sources detected in the frame are
matched by sky position to Gaia DR3, and Gaia's own G/BP/RP magnitudes (not
the frame's instrumental magnitude) are what gets fitted.

A FITS frame is not required, though: ``crossmatch_gaia_by_position`` and
``run_full_hr_pipeline_from_catalog`` skip the FITS/detection step entirely
and pull every Gaia DR3 source around the cluster's own resolved position
directly -- Gaia's own photometry stands in for a frame's instrumental
photometry, so there is nothing to detect first. This is the path for a plain
"show me an HR diagram for X" request where the user has not supplied a FITS
file; ``run_full_hr_pipeline`` remains the path for a user who has a specific
frame and wants that frame's own detections driving the fit.

Every remote catalog lookup here goes through ``tools.vizier.search_vizier``
-- reused wholesale, not reimplemented -- because VizieR mirrors Gaia DR3
(``I/355/gaiadr3``) and because a cluster's own catalog row is found by
resolving the cluster's *name* to a position the same way ``target=`` already
does for every other tool in this file (VizieR's resolver, same one SIMBAD
uses). Neither needs a dedicated query module.

The individual tool functions below round-trip through CSV artifacts between
steps -- deliberately, so a multi-turn agent conversation hands a path string
between tool calls instead of a full source table (see ``tools/registry.py``).
``run_full_hr_pipeline`` skips that round trip and chains the same underlying
calls directly for a single-call result.

Not the same job as ``tools.photometry``, despite ``extract_photometry_from_fits``
also running source extraction over a FITS frame here. ``tools.photometry``
reports one frame's own scientifically calibrated photometry (a verified zero
point against a reference catalog, a photometry plot) -- overkill for this
pipeline, which only needs each source's sky position to hand to a Gaia
cross-match and discards the frame's own magnitude entirely once Gaia's
(higher-quality, multi-band) magnitudes are fetched. That's why
``extract_photometry_from_fits`` uses cheaper "auto" Kron-like apertures with
no zero-point solve rather than reusing ``tools.photometry``'s pipeline. If a
target is instead a bundled photometry test frame that happens to be a
cluster, ``tools.photometry.run_photometry_on_target(..., write_source_table=True)``
writes a CSV in the same ``ra_deg``/``dec_deg`` shape ``crossmatch_gaia``
expects, as an alternative entry point into this pipeline's later steps.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
from astropy.table import Table

from algorithms.hrdiagram_py import isochrones, literature, matching, membership, observations
from tools import artifacts, config
from tools.config import ARTIFACT_DIR, PREVIEW_ROWS
from tools.models import ArtifactRef, ToolResult
from tools.vizier import search_vizier

__all__ = [
    "extract_photometry_from_fits",
    "crossmatch_gaia",
    "crossmatch_gaia_by_position",
    "get_literature_cluster_params",
    "select_cluster_members",
    "fit_and_compare_hr_diagram",
    "run_full_hr_pipeline",
    "run_full_hr_pipeline_from_catalog",
]

logger = logging.getLogger(__name__)

GAIA_DR3_CATALOG = "I/355/gaiadr3"

_SUBDIR = "hrdiagram"


class _NotFound(Exception):
    """A lookup came back empty -- an ordinary outcome, not a tool error."""


def _safe_stem(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "hrdiagram"


def _output_path(stem: str, suffix: str) -> Path:
    directory = ARTIFACT_DIR / _SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{_safe_stem(stem)}{suffix}"


def _read_table_artifact(path: str) -> pd.DataFrame:
    return Table.read(path).to_pandas()


def _write_df_artifact(df: pd.DataFrame, stem: str) -> ArtifactRef:
    return artifacts.write_table(Table.from_pandas(df), stem, subdir=_SUBDIR)


def _preview(df: pd.DataFrame) -> list[dict]:
    return df.head(PREVIEW_ROWS).to_dict(orient="records")


# ---------------------------------------------------------------------------
# Shared fetch helpers -- used by both the individual tools and the composite
# ---------------------------------------------------------------------------
def _fetch_gaia_and_match(sources: pd.DataFrame, radius_arcsec: float, mag_limit: float) -> pd.DataFrame:
    # Pad the fetch radius by the match tolerance plus a 72" (0.02 deg) safety
    # margin, so every detected source's match candidates are inside the cone.
    ra0, dec0, radius_deg = matching.field_footprint(sources, pad_arcsec=radius_arcsec + 72.0)
    result = search_vizier(
        ra_hours=ra0 / 15.0,
        dec_degs=dec0,
        radius_arcmin=radius_deg * 60.0,
        catalog=GAIA_DR3_CATALOG,
        column_filters={"Gmag": f"<{mag_limit}"},
        max_catalogs=None,
    )
    if result.status == "not_found":
        raise _NotFound(
            f"No Gaia DR3 sources brighter than G={mag_limit} within {radius_deg * 3600:.0f}\" "
            f"of RA={ra0:.4f} Dec={dec0:.4f}"
        )
    if result.status == "error":
        raise RuntimeError("; ".join(e.message for e in result.errors) or "search_vizier failed")
    if not result.artifacts:
        raise _NotFound(f"VizieR returned no {GAIA_DR3_CATALOG} rows for this field")

    gaia = _read_table_artifact(result.artifacts[0].path)
    return matching.match_sources_to_gaia(sources, gaia, radius_arcsec=radius_arcsec)


def _fetch_gaia_for_position(ra_deg: float, dec_deg: float, radius_arcmin: float, mag_limit: float) -> pd.DataFrame:
    # No detected sources to match against here -- Gaia's own row *is* the
    # star, so this renames straight to the schema membership.py and
    # isochrones.py expect (matching.match_sources_to_gaia's column names)
    # instead of going through a KD-tree nearest-neighbour match.
    result = search_vizier(
        ra_hours=ra_deg / 15.0,
        dec_degs=dec_deg,
        radius_arcmin=radius_arcmin,
        catalog=GAIA_DR3_CATALOG,
        column_filters={"Gmag": f"<{mag_limit}"},
        max_catalogs=None,
    )
    if result.status == "not_found":
        raise _NotFound(
            f"No Gaia DR3 sources brighter than G={mag_limit} within {radius_arcmin:.1f}' "
            f"of RA={ra_deg:.4f} Dec={dec_deg:.4f}"
        )
    if result.status == "error":
        raise RuntimeError("; ".join(e.message for e in result.errors) or "search_vizier failed")
    if not result.artifacts:
        raise _NotFound(f"VizieR returned no {GAIA_DR3_CATALOG} rows for this field")

    gaia = _read_table_artifact(result.artifacts[0].path).rename(columns={
        "Gmag": "G", "e_Gmag": "G_err", "BPmag": "BP", "e_BPmag": "BP_err",
        "RPmag": "RP", "e_RPmag": "RP_err", "Plx": "parallax", "e_Plx": "parallax_error",
        "pmRA": "pmra", "pmDE": "pmdec", "e_pmRA": "pmra_error", "e_pmDE": "pmdec_error",
    }).dropna(subset=["BP", "RP", "G"])
    if gaia.empty:
        raise _NotFound(
            f"No Gaia DR3 sources within {radius_arcmin:.1f}' of RA={ra_deg:.4f} Dec={dec_deg:.4f} "
            "have full BP/RP/G photometry"
        )
    return gaia


def _fetch_literature_params(cluster_name: str) -> dict[str, Any]:
    # search_vizier's target= path calls astroquery's query_object(), which has
    # no radius_arcmin parameter of its own -- passing one here would be a
    # silent no-op, so it's omitted. The cone radius is VizieR's own
    # query_object default.
    result = search_vizier(
        target=cluster_name,
        catalog=literature.CLUSTER_CATALOG,
        max_catalogs=None,
    )
    if result.status == "not_found":
        raise _NotFound(
            f"{cluster_name!r} did not resolve to a position VizieR could match against "
            f"{literature.CLUSTER_CATALOG} (Cantat-Gaudin & Anders 2020). The catalog covers "
            "~2000 nearby open clusters; if this one isn't in it, supply literature "
            "parameters manually instead."
        )
    if result.status == "error":
        raise RuntimeError("; ".join(e.message for e in result.errors) or "search_vizier failed")
    if not result.artifacts:
        raise _NotFound(f"VizieR returned no {literature.CLUSTER_CATALOG} rows near {cluster_name!r}")

    rows = _read_table_artifact(result.artifacts[0].path)
    # Confirmed live (tools/runner.py's system prompt): target= resolution orders
    # matches by increasing separation from the resolved position, so the first
    # row is the nearest catalog entry -- for a cluster-parameter catalog, that
    # is the cluster itself. Not independently re-verified for this specific
    # catalog against a live VizieR response.
    return literature.parse_cluster_params(rows.iloc[0].to_dict(), cluster_name)


# ---------------------------------------------------------------------------
# 1. FITS -> detected sources
# ---------------------------------------------------------------------------
def extract_photometry_from_fits(fits_path: str, threshold: float = 2.5) -> ToolResult:
    """Detect sources in a plate-solved FITS frame and measure instrumental photometry.

    The frame must already have a WCS in its header. Returns a summary + an
    artifact CSV path for the next step (``crossmatch_gaia``). Uncalibrated
    and deliberately cheap -- the frame's own magnitude is discarded once Gaia's
    is fetched. For a scientifically calibrated photometry report of a frame on
    its own, use ``tools.photometry.run_photometry_on_target`` instead.
    """
    try:
        df = observations.extract_photometry_from_fits(fits_path, threshold=threshold)
    except ValueError as exc:
        return ToolResult(status="error", errors=[{"code": "invalid_input", "message": str(exc)}])
    except RuntimeError as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])

    artifact = _write_df_artifact(df, f"{Path(fits_path).stem}_photometry")
    return ToolResult(
        status="ok",
        count=len(df),
        preview=_preview(df),
        columns=list(df.columns),
        artifact=artifact,
    )


# ---------------------------------------------------------------------------
# 2. Detected sources -> Gaia DR3 multi-band photometry
# ---------------------------------------------------------------------------
def crossmatch_gaia(csv_path: str, radius_arcsec: float = 2.0, mag_limit: float = 20.0) -> ToolResult:
    """Match detected sources (from ``extract_photometry_from_fits``) to Gaia DR3.

    Attaches Gaia's G/BP/RP magnitudes, parallax, and proper motion by sky
    position -- this is what supplies the colour for the HR diagram, since a
    single FITS frame is only one filter. Widen ``radius_arcsec`` if
    ``n_matched`` comes back 0 or low.
    """
    sources = _read_table_artifact(csv_path)
    try:
        matched = _fetch_gaia_and_match(sources, radius_arcsec, mag_limit)
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except RuntimeError as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    artifact = _write_df_artifact(matched, f"{Path(csv_path).stem}_gaia")
    return ToolResult(
        status="ok",
        count=len(matched),
        preview=_preview(matched),
        columns=list(matched.columns),
        artifact=artifact,
    )


# ---------------------------------------------------------------------------
# 2b. Cluster name -> Gaia DR3 photometry directly, no FITS frame
# ---------------------------------------------------------------------------
def crossmatch_gaia_by_position(
    cluster_name: str, radius_arcmin: float = 20.0, mag_limit: float = 17.0
) -> ToolResult:
    """Fetch Gaia DR3 photometry around a named cluster's own position -- no FITS frame needed.

    Unlike ``crossmatch_gaia`` (which matches sources already detected in a
    FITS frame to Gaia by position), this looks the cluster's own coordinates
    up via the literature catalog and pulls every Gaia DR3 source within
    ``radius_arcmin`` of it directly -- there is nothing to detect first,
    since Gaia's own photometry is what gets fitted either way. Returns the
    same column shape ``crossmatch_gaia`` does (G/BP/RP + errors, parallax,
    proper motion), so its artifact feeds directly into
    ``select_cluster_members`` and ``fit_and_compare_hr_diagram``.
    """
    try:
        params = _fetch_literature_params(cluster_name)
        gaia = _fetch_gaia_for_position(params["ra_deg"], params["dec_deg"], radius_arcmin, mag_limit)
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except RuntimeError as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    artifact = _write_df_artifact(gaia, f"{_safe_stem(cluster_name)}_gaia")
    return ToolResult(
        status="ok",
        count=len(gaia),
        preview=_preview(gaia),
        columns=list(gaia.columns),
        artifact=artifact,
    )


# ---------------------------------------------------------------------------
# 3. Cluster name -> published parameters
# ---------------------------------------------------------------------------
def get_literature_cluster_params(cluster_name: str) -> ToolResult:
    """Published age / distance / reddening for a named open cluster.

    Source: Cantat-Gaudin & Anders (2020), a Gaia-DR2 based re-derivation for
    ~2000 clusters, via VizieR -- chosen so distance and reddening are on the
    same Gaia astrometric footing as ``crossmatch_gaia``'s photometry.
    Resolves common aliases (e.g. "M35" -> NGC 2168) the same way every other
    tool's ``target=`` does, through VizieR's own name resolver.
    """
    try:
        params = _fetch_literature_params(cluster_name)
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except (RuntimeError, KeyError, ValueError) as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    return ToolResult(status="ok", count=1, preview=[params], columns=list(params.keys()))


# ---------------------------------------------------------------------------
# 4. Field-star removal (parallax + proper-motion cut)
# ---------------------------------------------------------------------------
def select_cluster_members(
    csv_path: str,
    cluster_name: str,
    plx_sigma: float = 3.0,
    pm_sigma: float = 3.0,
    pm_dispersion_km_s: float = 3.0,
) -> ToolResult:
    """Remove field-star contamination from Gaia-matched sources.

    Cuts on parallax (per-source error-scaled window) and proper motion
    (Astromancer's real elliptical acceptance region, ported into
    ``algorithms.hrdiagram_py.membership``) relative to the cluster's
    published values. ``pm_sigma`` scales each source's own proper-motion
    error the same way ``plx_sigma`` already scales its parallax error;
    ``pm_dispersion_km_s`` is an assumed cluster internal velocity dispersion
    that sets a distance-aware angular floor beneath that per-source scaling
    -- widen either if too few stars survive (a nearby cluster needs a larger
    floor for the same physical dispersion than a distant one does), or
    narrow them if too many (likely field contamination) do.
    """
    matched = _read_table_artifact(csv_path)
    try:
        params = _fetch_literature_params(cluster_name)
        members = membership.select_cluster_members(
            matched, params, plx_sigma=plx_sigma, pm_sigma=pm_sigma,
            pm_dispersion_km_s=pm_dispersion_km_s,
        )
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except RuntimeError as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    artifact = _write_df_artifact(members, f"{Path(csv_path).stem}_members")
    return ToolResult(
        status="ok",
        count=len(members),
        preview=_preview(members),
        columns=list(members.columns),
        artifact=artifact,
    )


# ---------------------------------------------------------------------------
# 5. Fit distance/reddening/age, compare to literature, plot
# ---------------------------------------------------------------------------
def fit_and_compare_hr_diagram(
    members_csv_path: str,
    cluster_name: str,
    mh: float = 0.0,
    max_error: float = 0.1,
    logage_half_width: float = 0.3,
) -> ToolResult:
    """Fit distance/E(B-V)/age to cluster members against the configured
    local Girardi grid near the cluster's published age, and plot the HR diagram.

    Returns the fitted values, the literature values, and their
    percent/absolute differences, plus the saved PNG artifact.
    """
    members = _read_table_artifact(members_csv_path)
    stem = _safe_stem(cluster_name)
    try:
        params = _fetch_literature_params(cluster_name)
        report = isochrones.fit_and_compare(
            members, params, cluster_name,
            members_csv_path=_output_path(f"{stem}_members", ".csv"),
            out_png=_output_path(f"hr_{stem}", ".png"),
            mh=mh, max_error=max_error, logage_half_width=logage_half_width,
            grid_dir=config.ISOCHRONE_DIR,
        )
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except RuntimeError as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    png_path = Path(report.pop("png_path"))
    csv_path = Path(report.pop("members_csv_path"))
    return ToolResult(
        status="ok",
        count=1,
        preview=[report],
        artifacts=[
            ArtifactRef(path=str(csv_path), format="csv", row_count=len(members), columns=list(members.columns)),
            ArtifactRef(path=str(png_path), format="png"),
        ],
    )


# ---------------------------------------------------------------------------
# 6. Composite entry point
# ---------------------------------------------------------------------------
def run_full_hr_pipeline(
    fits_path: str,
    cluster_name: str,
    gaia_match_radius_arcsec: float = 2.0,
    gaia_mag_limit: float = 20.0,
    plx_sigma: float = 3.0,
    pm_sigma: float = 3.0,
    pm_dispersion_km_s: float = 3.0,
) -> ToolResult:
    """Run the entire pipeline in one call: extract photometry from a FITS
    frame, cross-match to Gaia, look up literature cluster parameters, remove
    field stars, fit an isochrone, and plot the HR diagram against the
    literature values.

    Chains the same underlying calls as the individual tools directly (no
    intermediate CSV round trip) for a single-call result. See
    ``select_cluster_members`` for what ``pm_sigma``/``pm_dispersion_km_s`` mean.
    """
    stem = _safe_stem(cluster_name)
    try:
        detected = observations.extract_photometry_from_fits(fits_path)
        matched = _fetch_gaia_and_match(detected, gaia_match_radius_arcsec, gaia_mag_limit)
        params = _fetch_literature_params(cluster_name)
        members = membership.select_cluster_members(
            matched, params, plx_sigma=plx_sigma, pm_sigma=pm_sigma,
            pm_dispersion_km_s=pm_dispersion_km_s,
        )
        report = isochrones.fit_and_compare(
            members, params, cluster_name,
            members_csv_path=_output_path(f"{stem}_members", ".csv"),
            out_png=_output_path(f"hr_{stem}", ".png"),
            grid_dir=config.ISOCHRONE_DIR,
        )
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except (ValueError, RuntimeError) as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    png_path = Path(report.pop("png_path"))
    csv_path = Path(report.pop("members_csv_path"))
    report["n_detected"] = len(detected)
    report["n_gaia_matched"] = len(matched)
    report["n_members"] = len(members)
    return ToolResult(
        status="ok",
        count=1,
        preview=[report],
        artifacts=[
            ArtifactRef(path=str(csv_path), format="csv", row_count=len(members), columns=list(members.columns)),
            ArtifactRef(path=str(png_path), format="png"),
        ],
    )


# ---------------------------------------------------------------------------
# 7. Composite entry point, no FITS frame
# ---------------------------------------------------------------------------
def run_full_hr_pipeline_from_catalog(
    cluster_name: str,
    radius_arcmin: float = 20.0,
    gaia_mag_limit: float = 17.0,
    plx_sigma: float = 3.0,
    pm_sigma: float = 3.0,
    pm_dispersion_km_s: float = 3.0,
    mh: float = 0.0,
    max_error: float = 0.2,
    logage_half_width: float = 0.4,
) -> ToolResult:
    """Build an HR diagram for a named cluster directly from Gaia DR3 and
    literature catalogs -- no FITS frame required.

    Looks up the cluster's own published parameters (Cantat-Gaudin & Anders
    2020 -- open clusters only, see ``get_literature_cluster_params``) for a
    position plus a comparison age/distance/E(B-V), pulls every Gaia DR3
    source within ``radius_arcmin`` of that position, removes field stars by
    parallax + proper motion (see ``select_cluster_members`` for what
    ``pm_sigma``/``pm_dispersion_km_s`` mean), and fits/plots the isochrone.
    This is the path for a plain "build/show the HR diagram for X" request
    where the user has not supplied a FITS file -- for a user who does have a
    specific frame, use ``run_full_hr_pipeline`` instead, since that frame's
    own detections (not a wide catalog cone) should drive the fit.
    """
    stem = _safe_stem(cluster_name)
    try:
        params = _fetch_literature_params(cluster_name)
        gaia = _fetch_gaia_for_position(params["ra_deg"], params["dec_deg"], radius_arcmin, gaia_mag_limit)
        members = membership.select_cluster_members(
            gaia, params, plx_sigma=plx_sigma, pm_sigma=pm_sigma,
            pm_dispersion_km_s=pm_dispersion_km_s,
        )
        report = isochrones.fit_and_compare(
            members, params, cluster_name,
            members_csv_path=_output_path(f"{stem}_members", ".csv"),
            out_png=_output_path(f"hr_{stem}", ".png"),
            mh=mh, max_error=max_error, logage_half_width=logage_half_width,
            grid_dir=config.ISOCHRONE_DIR,
        )
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except (ValueError, RuntimeError) as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    png_path = Path(report.pop("png_path"))
    csv_path = Path(report.pop("members_csv_path"))
    report["n_gaia_fetched"] = len(gaia)
    report["n_members"] = len(members)
    return ToolResult(
        status="ok",
        count=1,
        preview=[report],
        artifacts=[
            ArtifactRef(path=str(csv_path), format="csv", row_count=len(members), columns=list(members.columns)),
            ArtifactRef(path=str(png_path), format="png"),
        ],
    )
