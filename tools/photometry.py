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
"""

from __future__ import annotations

from pathlib import Path

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


def _source_summary(result: object) -> SourceSummary | None:
    if result is None:
        return None
    return SourceSummary(
        x=getattr(result, "x", None),
        y=getattr(result, "y", None),
        mag=getattr(result, "mag", None),
        flux=getattr(result, "flux", None),
    )


def run_photometry_on_target(
    target: str,
    *,
    use_field_cal: bool = True,
    catalogs: list[str] | None = None,
    zero_point_mag: float | None = None,
    output_dir: str | Path | None = None,
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
            zero_point_corr=zero_point.value,
            zero_point_error_mag=diagnostics.get("zero_point_error_mag"),
            zero_point_slop=diagnostics.get("zero_point_slop"),
            rej_percent=diagnostics.get("rejection_percent"),
            source_count=diagnostics.get("num_calibration_stars", 0),
        )
        zp_plot_path = artifact_dir / f"{fits_path.stem}_photometry_zeropoint.png"
        if plot_zero_point_solution(zero_point, zp_plot_path) is not None:
            artifacts.append(ArtifactRef(path=str(zp_plot_path), format="png"))

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
