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
    load_fits_image,
    magnitude_label_for,
    plot_photometry,
    plot_zero_point_solution,
    resolve_fits_path,
)
from tools.config import artifact_directory
from tools.fieldcal_reference import (
    CATALOG_FIXTURES,
    _variable_sources_warning,
    compare_zeropoint_to_reference,
    load_catalog_response,
    load_zeropoint_reference,
    replay_catalog_sources,
    replay_variable_sources,
)
from tools.models import (
    ArtifactRef,
    FileMetadata,
    PhotometryRunResult,
    PhotometryTargetLibrary,
    SourceSummary,
    ToolError,
    ToolWarning,
    ZeropointComparison,
    ZeropointSolution,
)

__all__ = [
    "list_photometry_targets",
    "run_photometry_on_target",
    "calibrate_zeropoint",
]


def _resolve_calibration_inputs(
    header,
    wcs,
    *,
    catalog_sources: list | None,
    catalogs: list[str] | None,
    variable_check_tol: float | None,
    variable_sources: list | None = None,
) -> tuple[list, list | None, list[str]]:
    """Resolve remote catalog data at the tool boundary for one calibration call.

    ``variable_sources`` already in hand (the recorded VSX rows of a replay)
    are passed through; the VSX query runs only when they are not.
    """
    from algorithms.catalogs import CATALOGS
    from algorithms.query.runner import query_catalogs
    from algorithms.query.selection import select_catalogs_for_filter

    image_filter = header.get("FILTER") if hasattr(header, "get") else None
    selected_catalogs = list(catalogs) if catalogs else select_catalogs_for_filter(
        list(CATALOGS), image_filter
    )
    if catalog_sources is None:
        if not selected_catalogs:
            raise ValueError(f"No calibration catalog supports filter {image_filter!r}")
        catalog_sources = query_catalogs(
            selected_catalogs,
            wcs=wcs,
            skip_failed=True,
            stop_on_success=True,
            image_filter=image_filter,
        )
    elif not selected_catalogs:
        selected_catalogs = sorted(
            {name for name in (getattr(source, "catalog_name", None) for source in catalog_sources) if name}
        )

    if (
        variable_sources is None
        and catalog_sources is not None
        and variable_check_tol
        and variable_check_tol > 0
    ):
        try:
            variable_sources = query_catalogs(["VSX"], wcs=wcs, skip_failed=True)
        except Exception:
            variable_sources = None
    return list(catalog_sources), variable_sources, selected_catalogs


def list_photometry_targets() -> PhotometryTargetLibrary:
    """List the local FITS library photometry can actually run on.

    This has no live archive query behind it -- ``run_photometry_on_target``
    only resolves a target name that ships in ``data/optical/``. This is
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


def calibrate_zeropoint(
    path: str | Path,
    *,
    catalog_sources: list | None = None,
    catalog_fixture: str | None = None,
    catalogs: list[str] | None = None,
    compare_to: str | None = None,
) -> ZeropointComparison:
    """Solve a photometric zero point from a local frame's own pixels, then
    place it against the recorded ground truth.

    The real chain: source extraction -> aperture photometry -> match to
    catalog rows -> resolve reference magnitudes -> ``calc_solution``. The
    zero point returned is ABSOLUTE, on ``field_cal.py``'s aperture-correction-
    off magnitude scale.

    Two offline paths, neither of which opens a socket. ``catalog_fixture``
    names a recorded input for the solve ``compare_to`` names, one of
    ``tools.fieldcal_reference.CATALOG_FIXTURES``:

    * ``"selected_rows"`` -- the APASS rows Skynet actually matched. Every
      row is already known to match, so this validates photometry ->
      matching -> ref-mag -> solve, not catalog selection. The variable-star
      cross-check is disabled: it would query VSX, and could drop rows that
      are in the recorded matched set.
    * ``"full_response"`` -- the end-to-end selection replay: the recorded
      APASS response for the whole field, clipped to the frame as the live
      query path clips it, with the recorded VSX rows applied as the
      variable-star filter, so the matches are chosen from the candidates
      exactly as a live solve chooses them.

    ``catalog_sources`` is the same offline path with the rows supplied
    directly (``tools.fieldcal_reference.replay_catalog_sources`` builds
    them); it and ``catalog_fixture`` are mutually exclusive. Without either,
    the tool-owned calibration-input helper queries a reference catalog over
    the network, exactly as ``run_photometry_on_target(use_field_cal=True)``
    does.

    ``compare_to`` names a recorded solve (e.g. ``"ngc5128_b_002"``); the
    result is a :class:`~tools.models.ZeropointComparison` against it. Omit it
    and ``reference`` is ``None`` -- just the solved ``zero_point``.

    All four recorded solves can now be driven end to end (P8); only
    ``ngc5128_b_002`` has a recorded full response, so ``"full_response"``
    remains limited to it while ``"selected_rows"`` works for all four. This
    path re-measures the photometry from pixels, so it is a real solve, not a
    bit-exact one; ``tools.fieldcal_reference.replay_field_calibration`` is
    the bit-exact selection replay over the recorded detections.

    ``compare_to`` handles the two fixture families' differing
    instrumental-magnitude scales: the solved value is put on the reference's
    scale (``ZeropointReference.instrumental_zero_mag``, 20.0 for the three
    NGC 5286 B solves and 0.0 for ``ngc5128_b_002``) before the comparison, so
    ``delta_vs_skynet`` means the same thing for every field. The returned
    ``zero_point`` is the value as measured, on Kepler's own scale.
    """
    # Argument errors first, before the filesystem is touched.
    warnings: list = []
    variable_sources: list | None = None
    if catalog_fixture is not None:
        if catalog_sources is not None:
            return ZeropointComparison(
                errors=[
                    ToolError(
                        code="conflicting_catalog_inputs",
                        message="Pass either catalog_sources or catalog_fixture, not both.",
                    )
                ]
            )
        if catalog_fixture not in CATALOG_FIXTURES:
            return ZeropointComparison(
                errors=[
                    ToolError(
                        code="unknown_catalog_fixture",
                        message=f"catalog_fixture must be one of "
                        f"{', '.join(CATALOG_FIXTURES)}; got {catalog_fixture!r}.",
                    )
                ]
            )
        if compare_to is None:
            return ZeropointComparison(
                errors=[
                    ToolError(
                        code="catalog_fixture_requires_compare_to",
                        message="catalog_fixture replays the rows recorded for a "
                        "solve; name it with compare_to (e.g. 'ngc5128_b_002').",
                    )
                ]
            )
        catalog_sources = replay_catalog_sources(compare_to, fixture=catalog_fixture)
        if not catalog_sources:
            # Present-but-unusable is a different diagnosis from absent.
            response = load_catalog_response(compare_to) if catalog_fixture == "full_response" else None
            if response is not None and not response.errors:
                return ZeropointComparison(
                    errors=[
                        ToolError(
                            code="catalog_fixture_empty",
                            message=f"The recorded {response.catalog} response for "
                            f"{compare_to!r} ({response.row_count} rows) has no row the "
                            f"{response.catalog} mapping can use. Nothing was queried.",
                        )
                    ]
                )
            return ZeropointComparison(
                errors=[
                    ToolError(
                        code="catalog_fixture_missing",
                        message=f"No {catalog_fixture!r} catalog rows are recorded for "
                        f"{compare_to!r}; only ngc5128_b_002 carries them. Nothing was "
                        "queried.",
                    )
                ]
            )
        if catalog_fixture == "full_response":
            variable_sources = replay_variable_sources(compare_to)
            if not variable_sources:
                warnings.append(
                    _variable_sources_warning(compare_to, load_catalog_response(compare_to, "VSX"))
                )
                variable_sources = None

    file_meta = describe_file(path)
    if not file_meta.exists or not file_meta.is_file:
        return ZeropointComparison(
            errors=[
                ToolError(
                    code="file_not_found",
                    message=f"{path!r} is not a readable local FITS file.",
                )
            ],
            warnings=warnings,
        )

    try:
        data, header = load_fits_image(Path(file_meta.path))
    except (OSError, ValueError) as exc:
        return ZeropointComparison(
            errors=[ToolError(code="fits_read_error", message=str(exc))],
            warnings=warnings,
        )

    from algorithms.fieldcal.field_cal import perform_field_calibration
    from algorithms.fieldcal.schemas import PhotometricCalibrationSettings

    # The same settings classes the CLI field-cal path constructs -- the ones
    # the wired ``run_photometry`` / ``run_source_extraction`` expect.
    from algorithms.photometry.photometry import PhotometrySettings
    from algorithms.photometry.schemas import SourceExtractionSettings

    from algorithms.photometry.source_extraction import build_wcs_from_header

    offline = catalog_sources is not None
    selected_catalogs = list(catalogs) if catalogs else None
    if selected_catalogs is None and offline:
        selected_catalogs = sorted(
            {
                name
                for name in (getattr(s, "catalog_name", None) for s in catalog_sources)
                if name
            }
        )
    # Offline, the variable-star cross-check runs only against recorded VSX
    # rows: with the full response they are part of the recorded selection,
    # while replaying the exact rows upstream fed calc_solution it would query
    # VSX over the network and could drop rows already in the matched set.
    check_variables = not offline or variable_sources is not None
    field_cal_settings = PhotometricCalibrationSettings(
        catalogs=selected_catalogs or ["APASS"],
        variable_check_tol=(
            PhotometricCalibrationSettings().variable_check_tol if check_variables else 0
        ),
    )
    photometry_settings = PhotometrySettings(
        mode="aperture", a=5.0, a_in_px=8.0, a_out_px=12.0
    )

    try:
        wcs = build_wcs_from_header(header)
        if wcs is None:
            raise ValueError("Missing WCS needed for calibration")
        if catalog_fixture == "full_response":
            # The recorded response is the whole cone; the live query path
            # clips a response to the detector before the solve sees a row.
            from algorithms.query.geometry import clip_sources_to_wcs

            catalog_sources = clip_sources_to_wcs(catalog_sources, [wcs])
            if variable_sources is not None:
                variable_sources = clip_sources_to_wcs(variable_sources, [wcs])
        resolved_sources, variable_sources, selected_catalogs = _resolve_calibration_inputs(
            header,
            wcs,
            catalog_sources=catalog_sources,
            catalogs=selected_catalogs,
            variable_check_tol=field_cal_settings.variable_check_tol,
            variable_sources=variable_sources,
        )
        outcome = perform_field_calibration(
            header.copy(),
            data,
            wcs=wcs,
            field_cal_settings=field_cal_settings,
            photometry_settings=photometry_settings,
            extraction_settings=SourceExtractionSettings(),
            catalog_sources=resolved_sources,
            variable_sources=variable_sources,
        )
    except Exception as exc:  # noqa: BLE001 -- no match, no convergence, network down
        return ZeropointComparison(
            errors=[ToolError(code="field_calibration_failed", message=str(exc))],
            warnings=warnings,
        )

    if outcome is None:
        return ZeropointComparison(
            errors=[ToolError(code="no_solution", message="field calibration returned no solution")],
            warnings=warnings,
        )
    zero_point, _result = outcome
    if zero_point is None:
        return ZeropointComparison(
            errors=[ToolError(code="no_solution", message="field calibration did not converge")],
            warnings=warnings,
        )
    zero_point = float(zero_point)

    if compare_to is not None:
        # The solve above measures on Kepler's own instrumental scale, whose
        # zero is 0.0. A recorded run that used a different one is not directly
        # comparable, so put this value on the reference's scale first -- for
        # the three NGC 5286 B solves that is a clean 20 magnitudes, which is
        # exactly the size of miss the Afterglow base-20 guard exists to catch.
        # ``zero_point`` on the returned comparison stays as measured.
        reference = load_zeropoint_reference(compare_to)
        instrumental_zero = reference.instrumental_zero_mag or 0.0
        comparison = compare_zeropoint_to_reference(zero_point - instrumental_zero, compare_to)
        comparison.zero_point = zero_point
        comparison.warnings = warnings + list(comparison.warnings)
        return comparison
    return ZeropointComparison(zero_point=zero_point, reference=None, warnings=warnings)
