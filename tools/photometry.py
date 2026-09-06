"""Photometry tool wrappers.

Thin `tools/`-convention wrappers (plain functions, Pydantic-model return
values) over the already-working, already-tested photometry pipeline in
``tools.claude_photometry_haiku_tool`` -- target resolution, source
extraction, zero-point resolution (CLI override / FITS header / live
field-calibration), and the two plots (photometry, zero-point fit). This
module does not reimplement any of that; it imports and reuses it directly,
so a prompt run through ``tools.runner`` produces exactly what the standalone
CLI script produces.

There is no live image archive behind photometry -- see
``list_photometry_targets``. That fixed, local library is the reason a
caller (human or Claude, via ``tools.runner``) should always check what's
bundled before claiming to have analyzed something that isn't.

Not the same job as ``tools.hr_diagram``, despite both running source
extraction over a FITS frame. This module reports one frame's own calibrated
photometry (a verified zero point, a photometry plot) and stops there --
``algorithms.hrdiagram_py.observations`` (behind
``tools.hr_diagram.extract_photometry_from_fits``) runs a cheaper,
uncalibrated extraction whose only job is handing sky positions to a Gaia
cross-match, since Gaia's own magnitudes -- not the frame's -- are what an HR
diagram is fit against. The two intentionally use different
``algorithms.photometry`` settings (fixed aperture + zero point here, "auto"
Kron-like apertures with no zero point there) for that reason; this is not
duplicated logic to consolidate. What IS shared: ``run_photometry_on_target``'s
``write_source_table=True`` writes the same ``ra_deg``/``dec_deg`` columns
``extract_photometry_from_fits`` does, so its CSV can be handed straight to
``tools.hr_diagram.crossmatch_gaia`` if a bundled target turns out to be a
cluster worth an HR diagram.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools.artifacts import describe_file
from tools.claude_photometry_haiku_tool import (
    compute_photometry,
    list_bundled_targets,
    magnitude_label_for,
    plot_photometry,
    plot_zero_point_solution,
    resolve_fits_path,
)
from tools.config import artifact_directory
from tools.models import (
    ArtifactRef,
    FileMetadata,
    PhotometryRunResult,
    PhotometryTargetLibrary,
    SourceSummary,
    ZeropointSolution,
)

__all__ = ["list_photometry_targets", "run_photometry_on_target"]


def list_photometry_targets() -> PhotometryTargetLibrary:
    """List the local FITS library photometry can actually run on.

    This has no live archive query behind it -- ``run_photometry_on_target``
    only resolves a target name that ships in ``test_data/optical/``. This is
    the discovery step for what's actually on hand, so a caller isn't left
    guessing or hitting a bare "not found" for a target that was never
    bundled.
    """
    categories = list_bundled_targets()
    return PhotometryTargetLibrary(
        categories=categories,
        total_count=sum(len(stems) for stems in categories.values()),
    )


def _source_row(result: object) -> dict:
    # Same column names algorithms.hrdiagram_py.observations.extract_photometry_from_fits
    # uses (ra_deg/dec_deg, not the underlying result's ra_hours/dec_degs) -- so both
    # _source_summary and _write_source_table's output drop straight into
    # tools.hr_diagram.crossmatch_gaia / select_cluster_members without renaming.
    ra_hours = getattr(result, "ra_hours", None)
    return {
        "x": getattr(result, "x", None),
        "y": getattr(result, "y", None),
        "ra_deg": (ra_hours * 15.0) if ra_hours is not None else None,
        "dec_deg": getattr(result, "dec_degs", None),
        "mag": getattr(result, "mag", None),
        "mag_error": getattr(result, "mag_error", None),
        "flux": getattr(result, "flux", None),
        "flux_error": getattr(result, "flux_error", None),
    }


def _source_summary(result: object) -> SourceSummary | None:
    if result is None:
        return None
    return SourceSummary(**_source_row(result))


def _write_source_table(results: list[object], path: Path) -> None:
    rows = [_source_row(r) for r in results]
    pd.DataFrame(rows).dropna(subset=["ra_deg", "dec_deg"]).to_csv(path, index=False)


def run_photometry_on_target(
    target: str,
    *,
    use_field_cal: bool = True,
    catalogs: list[str] | None = None,
    zero_point_mag: float | None = None,
    output_dir: str | Path | None = None,
    write_source_table: bool = False,
) -> PhotometryRunResult:
    """Run source extraction, and optionally a verified zero-point solve, on
    a bundled FITS target.

    ``target`` resolves the same way the CLI script does: an explicit path,
    or a bundled stem such as ``"ngc1846_cluster_r_000"`` (see
    ``list_photometry_targets``). A target that doesn't resolve is reported
    as an ordinary ``errors``-populated result, not an exception.

    ``use_field_cal`` (default ``True``) queries a reference catalog over the
    network to independently verify the zero point -- this is the only path
    that populates ``zero_point`` and can take 30-90 seconds. Pass ``False``
    for a fast, offline, instrumental-magnitude-only run when a verified
    zero point isn't needed.

    ``write_source_table`` (default ``False``, opt-in so the artifact count
    stays stable for existing callers) additionally writes every detected
    source's position and photometry to a CSV artifact, columns ``x, y,
    ra_deg, dec_deg, mag, flux`` -- the same ``ra_deg``/``dec_deg`` naming
    ``algorithms.hrdiagram_py.observations.extract_photometry_from_fits``
    uses, so the artifact can be handed straight to
    ``tools.hr_diagram.crossmatch_gaia`` or ``select_cluster_members`` without
    renaming, if the frame this ran on happens to be a star cluster and the
    caller wants an HR diagram next.

    Always writes the photometry plot, and the zero-point plot too when the
    zero point was independently verified, to ``output_dir`` (default: the
    shared `tools` artifact directory, ``tools.config.artifact_directory`` --
    not the CLI script's own ``~/Downloads`` default), returned as
    ``artifacts``.
    """
    try:
        fits_path = resolve_fits_path(target)
    except FileNotFoundError:
        return PhotometryRunResult(
            file=FileMetadata(path=str(target), exists=False),
            errors=[
                {
                    "code": "target_not_found",
                    "message": (
                        f"{target!r} is not in the local FITS library. "
                        "Call list_photometry_targets to see what's available."
                    ),
                }
            ],
        )

    data, results, zero_point = compute_photometry(
        fits_path,
        zero_point_mag=zero_point_mag,
        use_field_cal=use_field_cal,
        catalogs=catalogs,
    )
    magnitude_label = magnitude_label_for(zero_point)

    artifact_dir = artifact_directory(output_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    plot_path = artifact_dir / f"{fits_path.stem}_photometry.png"
    plot_photometry(data, results, plot_path, magnitude_label=magnitude_label)
    artifacts = [ArtifactRef(path=str(plot_path), format="png")]

    zero_point_model: ZeropointSolution | None = None
    if zero_point.verified:
        diagnostics = zero_point.diagnostics or {}
        zero_point_model = ZeropointSolution(
            zero_point=zero_point.value,
            zero_point_error_mag=diagnostics.get("zero_point_error_mag"),
            zero_point_slop=diagnostics.get("zero_point_slop"),
            rej_percent=diagnostics.get("rejection_percent"),
            source_count=diagnostics.get("num_calibration_stars", 0),
        )
        zp_plot_path = artifact_dir / f"{fits_path.stem}_photometry_zeropoint.png"
        if plot_zero_point_solution(zero_point, zp_plot_path) is not None:
            artifacts.append(ArtifactRef(path=str(zp_plot_path), format="png"))

    if write_source_table and results:
        table_path = artifact_dir / f"{fits_path.stem}_photometry_sources.csv"
        _write_source_table(results, table_path)
        artifacts.append(ArtifactRef(path=str(table_path), format="csv", row_count=len(results)))

    valid_results = [r for r in results if r.mag is not None]
    brightest = min(valid_results, key=lambda r: r.mag) if valid_results else None
    faintest = max(valid_results, key=lambda r: r.mag) if valid_results else None

    # Same exp_length for every source in a frame (it's read once from the FITS
    # header, not per-source) -- one result[0] lookup is enough. See
    # PhotometryRunResult.exposure_seconds: without this, flux and mag look
    # mutually inconsistent by several magnitudes to anyone checking the math.
    exposure_seconds = getattr(results[0], "exp_length", None) if results else None

    return PhotometryRunResult(
        file=describe_file(fits_path),
        source_count=len(results),
        magnitude_label=magnitude_label,
        exposure_seconds=exposure_seconds,
        zero_point_source=zero_point.source,
        zero_point=zero_point_model,
        brightest=_source_summary(brightest),
        faintest=_source_summary(faintest),
        artifacts=artifacts,
    )
