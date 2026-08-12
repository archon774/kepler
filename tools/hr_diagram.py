"""HR-diagram (star-cluster colour-magnitude diagram) tool wrappers."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

from algorithms.hrdiagram import gaia as _gaia
from algorithms.hrdiagram import literature as _literature
from algorithms.hrdiagram import membership as _membership
from algorithms.hrdiagram import observations as _observations
from algorithms.hrdiagram.fit import fit_and_compare as _fit_and_compare
from algorithms.hrdiagram.fit import plot_observed_cmd as _plot_observed_cmd
from tools.artifacts import describe_artifact_file, describe_file
from tools.astrometry import locate_target_in_image
from tools.config import ARTIFACT_DIR_ENV, artifact_directory
from tools.models import (
    ArtifactMetadata,
    ClusterLiteratureParams,
    ClusterMembershipResult,
    GaiaCrossmatchSummary,
    HrDiagramFitResult,
    ObservedCmdResult,
    PhotometryTableSummary,
    TableSummary,
    ToolError,
    ToolWarning,
)


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


_ISOCHRONE_CACHE_DIR = (Path(__file__).resolve().parent.parent / "isochrone_cache")


def _hr_output_dir(directory: str | Path | None) -> Path:
    """Where every HR-diagram output (plots, members/photometry CSVs) gets
    written.

    An explicit `directory` argument always wins. Otherwise -- unless
    KEPLER_ARTIFACT_DIR was set deliberately -- this defaults to
    isochrone_cache/ next to the repo root, not tools.config's generic
    ./artifacts default, so an HR diagram lands in the same predictable,
    already-gitignored place no matter which entry point produced it
    (hr_agent.py, ask_hr_diagram.py, a standalone script, or calling this
    module directly).
    """
    if directory is not None or os.environ.get(ARTIFACT_DIR_ENV):
        return artifact_directory(directory)
    return _ISOCHRONE_CACHE_DIR.resolve()


def _table_summary(df: pd.DataFrame) -> TableSummary:
    return TableSummary(row_count=len(df), columns=list(df.columns))


def extract_photometry_from_fits(
    fits_path: str,
    threshold: float = 2.5,
    directory: str | Path | None = None,
) -> PhotometryTableSummary:
    """Detect sources in a plate-solved FITS frame and measure instrumental photometry."""
    try:
        df = _observations.extract_photometry_from_fits(fits_path, threshold=threshold)
    except Exception as exc:
        return PhotometryTableSummary(
            file=describe_file(fits_path),
            table=TableSummary(),
            errors=[ToolError(code="invalid_input", message=str(exc))],
        )

    out_path = _hr_output_dir(directory) / f"{Path(fits_path).stem}_photometry.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return PhotometryTableSummary(
        file=describe_file(out_path),
        table=_table_summary(df),
        n_sources=len(df),
        filters=sorted(df["filter"].dropna().unique().tolist()),
        ra_center_deg=float(df["ra_deg"].mean()) if len(df) else None,
        dec_center_deg=float(df["dec_deg"].mean()) if len(df) else None,
    )


def load_photometry_table(
    csv_path: str,
    mag_col: str = "calibrated_mag",
    err_col: str = "mag_error",
    directory: str | Path | None = None,
) -> PhotometryTableSummary:
    """Load an existing calibrated photometry table (e.g. an Afterglow export)."""
    try:
        df = _observations.load_afterglow_photometry(csv_path, mag_col=mag_col, err_col=err_col)
    except Exception as exc:
        return PhotometryTableSummary(
            file=describe_file(csv_path),
            table=TableSummary(),
            errors=[ToolError(code="invalid_input", message=str(exc))],
        )

    filters = [c for c in df.columns if c not in ("id", "ra_deg", "dec_deg") and not c.endswith("_err")]
    out_path = _hr_output_dir(directory) / f"{Path(csv_path).stem}_wide.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return PhotometryTableSummary(
        file=describe_file(out_path),
        table=_table_summary(df),
        n_sources=len(df),
        filters=filters,
        ra_center_deg=float(df["ra_deg"].mean()) if len(df) else None,
        dec_center_deg=float(df["dec_deg"].mean()) if len(df) else None,
    )


def crossmatch_gaia(
    csv_path: str,
    radius_arcsec: float = 2.0,
    mag_limit: float = 20.0,
    directory: str | Path | None = None,
) -> GaiaCrossmatchSummary:
    """Match sources in csv_path to Gaia DR3, attaching G/BP/RP + parallax/proper motion."""
    df = pd.read_csv(csv_path)
    try:
        matched = _gaia.crossmatch_gaia(df, radius_arcsec=radius_arcsec, mag_limit=mag_limit)
    except Exception as exc:
        return GaiaCrossmatchSummary(
            file=describe_file(csv_path),
            table=TableSummary(),
            n_input=len(df),
            errors=[ToolError(code="provider_unavailable", message=str(exc))],
        )

    out_path = _hr_output_dir(directory) / f"{Path(csv_path).stem}_gaia.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    matched.to_csv(out_path, index=False)
    return GaiaCrossmatchSummary(
        file=describe_file(out_path),
        table=_table_summary(matched),
        n_input=len(df),
        n_matched=len(matched),
        median_separation_arcsec=float(matched["sep_arcsec"].median()) if len(matched) else None,
    )


def get_literature_cluster_params(cluster_name: str) -> ClusterLiteratureParams:
    """Published parameters for a named cluster, open or globular.

    Tries the open-cluster catalog (Cantat-Gaudin & Anders 2020) first, falls
    back to the globular-cluster catalogs (Harris 2010 + Vasiliev & Baumgardt
    2021). Check the returned `cluster_type` ("open" or "globular") --
    globular results carry a real `feh` and may have
    `age_is_literature_default: true` (Harris doesn't publish per-cluster ages).
    """
    try:
        params = _literature.get_literature_cluster_params(cluster_name)
    except Exception as exc:
        return ClusterLiteratureParams(
            cluster=cluster_name,
            errors=[ToolError(code="not_found", message=str(exc))],
        )
    return ClusterLiteratureParams(**params)


def select_cluster_members(
    csv_path: str,
    cluster_name: str,
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
    directory: str | Path | None = None,
) -> ClusterMembershipResult:
    """Remove field-star contamination via a parallax + proper-motion cut."""
    df = pd.read_csv(csv_path)
    literature = get_literature_cluster_params(cluster_name)
    if literature.errors:
        return ClusterMembershipResult(
            file=describe_file(csv_path), n_input=len(df),
            plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr,
            errors=literature.errors,
        )
    try:
        members = _membership.select_cluster_members(
            df, literature.model_dump(), plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr,
        )
    except Exception as exc:
        return ClusterMembershipResult(
            file=describe_file(csv_path), n_input=len(df),
            plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr,
            errors=[ToolError(code="no_solution", message=str(exc))],
        )

    out_path = _hr_output_dir(directory) / f"{Path(csv_path).stem}_members.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    members.to_csv(out_path, index=False)
    return ClusterMembershipResult(
        file=describe_file(out_path), n_input=len(df), n_members=len(members),
        plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr,
    )


def fit_hr_diagram(
    members_csv_path: str,
    cluster_name: str,
    blue: str = "BP",
    red: str = "RP",
    lum: str = "G",
    mh: float | None = None,
    max_error: float = 0.1,
    logage_half_width: float = 0.3,
    isochrone_source: str = "mist",
    pre_dereddened_ebv: float = 0.0,
    directory: str | Path | None = None,
) -> HrDiagramFitResult:
    """Fetch an isochrone, fit distance/E(B-V)/age, compare to literature, plot."""
    members = pd.read_csv(members_csv_path)
    literature = get_literature_cluster_params(cluster_name)
    if literature.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=literature.errors)

    out_dir = _hr_output_dir(directory)
    # Filter combo is part of the filename, not just the cluster name -- two
    # fits of the same cluster in different bands (e.g. B-R vs V and V-I vs
    # V) are different results worth keeping side by side, not one silently
    # overwriting the other.
    filters_tag = _slug(f"{blue}-{red}_{lum}")
    stem = f"{_slug(cluster_name)}_{filters_tag}"
    csv_path = out_dir / f"_members_{stem}.csv"
    out_png_path = out_dir / f"_hr_{stem}.png"

    try:
        report = _fit_and_compare(
            members, literature.model_dump(), cluster_name, csv_path, out_png_path,
            blue=blue, red=red, lum=lum, mh=mh, max_error=max_error,
            logage_half_width=logage_half_width, isochrone_source=isochrone_source,
            pre_dereddened_ebv=pre_dereddened_ebv,
        )
    except Exception as exc:
        return HrDiagramFitResult(
            cluster=cluster_name, literature=literature, isochrone_source=isochrone_source,
            errors=[ToolError(code="no_solution", message=str(exc))],
        )

    fitted, comparison = report["fitted"], report["comparison"]
    warnings = [
        ToolWarning(code="isochrone_coverage", message=message)
        for message in report.get("warnings", [])
    ]
    return HrDiagramFitResult(
        cluster=cluster_name,
        distance_kpc=fitted["distance_kpc"], ebv=fitted["ebv"], ebv_residual=fitted["ebv_residual"],
        pre_dereddened_ebv=fitted["pre_dereddened_ebv"], log_age=fitted["log_age"], age_myr=fitted["age_myr"],
        fspot=fitted.get("fspot"),
        n_stars_fitted=fitted["n_stars_fitted"], reduced_cost=fitted["reduced_cost"],
        literature=literature,
        distance_pct_diff=comparison["distance_pct_diff"], ebv_diff=comparison["ebv_diff"],
        age_pct_diff=comparison["age_pct_diff"], isochrone_source=isochrone_source,
        isochrone_path=report["isochrone_path"],
        png=describe_artifact_file(report["png_path"]),
        members_csv=describe_file(report["members_csv_path"]),
        warnings=warnings,
    )


def plot_observed_cmd(
    csv_path: str,
    blue: str,
    red: str,
    lum: str,
    max_error: float | None = None,
    title: str | None = None,
    directory: str | Path | None = None,
) -> ObservedCmdResult:
    """Plot a plain observed CMD (blue - red vs lum) with no distance/reddening
    correction -- use when there's no literature match to fit against."""
    df = pd.read_csv(csv_path)
    out_dir = _hr_output_dir(directory)
    stem = _slug(Path(csv_path).stem)
    input_csv_path = out_dir / f"_observed_cmd_input_{stem}.csv"
    out_png_path = out_dir / f"_observed_cmd_{stem}.png"
    try:
        report = _plot_observed_cmd(
            df, blue, red, lum, input_csv_path, out_png_path, max_error=max_error, title=title,
        )
    except Exception as exc:
        return ObservedCmdResult(
            n_input=len(df),
            png=ArtifactMetadata(file=describe_file(out_png_path), artifact_type="image"),
            errors=[ToolError(code="invalid_input", message=str(exc))],
        )
    return ObservedCmdResult(
        n_stars=report["n_stars"], n_input=report["n_input"],
        png=describe_artifact_file(report["png_path"]),
    )


def run_hr_diagram_pipeline(
    fits_path: str,
    cluster_name: str,
    gaia_match_radius_arcsec: float = 2.0,
    gaia_mag_limit: float = 20.0,
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
    max_error: float = 0.1,
    isochrone_source: str = "mist",
    directory: str | Path | None = None,
) -> HrDiagramFitResult:
    """FITS frame + cluster name -> HR diagram, fitted vs. literature.

    Checks the cluster's literature sky position actually falls inside the
    frame (via its WCS -- see tools.astrometry.locate_target_in_image)
    before running anything else: extract_photometry_from_fits on a frame
    pointed elsewhere would otherwise just silently produce zero matching
    members several stages later, after the (slow) extraction and Gaia
    crossmatch already ran. Then chains extract_photometry_from_fits ->
    crossmatch_gaia -> select_cluster_members -> fit_hr_diagram,
    short-circuiting to an error result (rather than raising) on the first
    failed stage.
    """
    literature = get_literature_cluster_params(cluster_name)
    if literature.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=literature.errors)

    location = locate_target_in_image(fits_path, ra_deg=literature.ra_deg, dec_deg=literature.dec_deg)
    if location.errors:
        return HrDiagramFitResult(cluster=cluster_name, literature=literature, isochrone_source=isochrone_source, errors=location.errors)
    if location.in_bounds is False:
        detail = ""
        if location.image_shape is not None and location.pixel_x is not None:
            height, width = location.image_shape
            detail = f" (pixel {location.pixel_x:.1f}, {location.pixel_y:.1f} vs. a {width}x{height} image)"
        return HrDiagramFitResult(
            cluster=cluster_name, literature=literature, isochrone_source=isochrone_source,
            errors=[ToolError(
                code="target_not_in_frame",
                message=(
                    f"{cluster_name}'s literature position (RA={literature.ra_deg:.4f}, "
                    f"Dec={literature.dec_deg:.4f}) falls outside {fits_path!r}'s image{detail}. "
                    "Check this is the right frame for this cluster before running photometry on it."
                ),
            )],
        )

    detected = extract_photometry_from_fits(fits_path, threshold=2.5, directory=directory)
    if detected.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=detected.errors)

    matched = crossmatch_gaia(
        detected.file.path, radius_arcsec=gaia_match_radius_arcsec, mag_limit=gaia_mag_limit, directory=directory,
    )
    if matched.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=matched.errors)

    members = select_cluster_members(
        matched.file.path, cluster_name, plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr, directory=directory,
    )
    if members.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=members.errors)

    result = fit_hr_diagram(
        members.file.path, cluster_name, max_error=max_error,
        isochrone_source=isochrone_source, directory=directory,
    )
    result.n_detected = detected.n_sources
    result.n_gaia_matched = matched.n_matched
    result.n_members = members.n_members
    return result


def run_hr_diagram_pipeline_from_photometry(
    csv_path: str,
    cluster_name: str,
    blue: str = "B",
    red: str = "R",
    lum: str = "V",
    mag_col: str = "calibrated_mag",
    err_col: str = "mag_error",
    gaia_match_radius_arcsec: float = 2.0,
    gaia_mag_limit: float = 21.0,
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
    max_error: float = 0.1,
    isochrone_source: str = "mist",
    pre_dereddened_ebv: float = 0.0,
    directory: str | Path | None = None,
) -> HrDiagramFitResult:
    """Photometry table + cluster name -> HR diagram, fitted vs. literature.

    Works for open or globular clusters. Chains load_photometry_table ->
    crossmatch_gaia -> select_cluster_members -> fit_hr_diagram,
    short-circuiting to an error result on the first failed stage.
    """
    detected = load_photometry_table(csv_path, mag_col=mag_col, err_col=err_col, directory=directory)
    if detected.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=detected.errors)

    matched = crossmatch_gaia(
        detected.file.path, radius_arcsec=gaia_match_radius_arcsec, mag_limit=gaia_mag_limit, directory=directory,
    )
    if matched.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=matched.errors)

    members = select_cluster_members(
        matched.file.path, cluster_name, plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr, directory=directory,
    )
    if members.errors:
        return HrDiagramFitResult(cluster=cluster_name, isochrone_source=isochrone_source, errors=members.errors)

    result = fit_hr_diagram(
        members.file.path, cluster_name, blue=blue, red=red, lum=lum, max_error=max_error,
        isochrone_source=isochrone_source, pre_dereddened_ebv=pre_dereddened_ebv, directory=directory,
    )
    result.n_detected = detected.n_sources
    result.n_gaia_matched = matched.n_matched
    result.n_members = members.n_members
    return result
