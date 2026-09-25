"""The declared vocabulary of :class:`~tools.models.ToolError` and
:class:`~tools.models.ToolWarning` codes.

Every coded signal any Kepler tool raises is named here with a one-line
meaning. ``tests/test_tool_codes.py`` AST-scans ``tools/`` and ``algorithms/``
and fails if a code is constructed that is not declared, or declared that is
not constructed -- so this file cannot drift from the code without a test
saying so.

**Why a mapping and not a ``Literal``.**
``docs/analysis/applicable-designs.md`` §3 recommended promoting
``ToolError.code`` to a closed ``Literal``, on the finding that it had *"exactly
three values in use"*. That finding was drawn from the database tools alone,
where an error is built as a ``{"code": ..., "message": ...}`` dict literal --
``invalid_input``, ``provider_unavailable``, ``dependency_missing`` are exactly
the three codes visible that way. The other 38 are constructed through
``ToolError(code=...)`` and were not in view. A ``Literal`` over 41 values would
also be unsatisfiable at the six sites that build a code from a variable
(``tools/pulsar.py`` re-raising ``_LoadError.code``, and
``tools/variable_star.py::_error``), which is why the vocabulary is *declared
and tested* rather than *typed*.

A code is added when a caller would act on it differently. Two situations that
a caller handles the same way share a code; two that it does not, do not.
"""

from __future__ import annotations

__all__ = ["TOOL_ERROR_CODES", "TOOL_WARNING_CODES"]


#: Every ``ToolError.code`` a Kepler tool constructs, and what it means.
TOOL_ERROR_CODES: dict[str, str] = {
    "ambiguous": "A name matched more than one frame or fixture; nothing was chosen.",
    "catalog_fixture_empty": "The named recorded catalog response holds no row the catalog mapping can use.",
    "catalog_fixture_missing": "No catalog rows are recorded for the named solve.",
    "catalog_fixture_requires_compare_to": "catalog_fixture replays the rows of a specific solve and needs compare_to to name it.",
    "conflicting_catalog_inputs": "catalog_sources and catalog_fixture were both given; they are alternatives.",
    "dependency_missing": "A required credential or optional dependency is not configured.",
    "directory_not_found": "A configured data directory does not exist.",
    "field_calibration_failed": "The zero-point solve raised rather than converging.",
    "file_changed": "The file changed on disk between reading it and writing it back.",
    "file_not_found": "The named path does not exist.",
    "fits_header_error": "The FITS header could not be parsed.",
    "fits_read_error": "The FITS file could not be read.",
    "fits_write_error": "The FITS file could not be written.",
    "fixture_empty": "A recorded response is present but holds no usable row.",
    "fixture_missing": "A recorded response the replay needs is not present.",
    "frame_not_bundled": "The frame the operation needs is not in the bundled library.",
    "frame_not_checked_out": "The frame is a Git LFS pointer rather than the frame itself.",
    "invalid_input": "An argument was missing, malformed, or out of range.",
    "invalid_schema": "A tabular input did not have the columns or shape the tool requires.",
    "invalid_search_bounds": "The plate-solve search radius or scale window is not usable as given.",
    "invalid_timeout": "A timeout argument was not at least one finite second.",
    "missing_fit_data": "The recorded solve carries no fit_data.csv detections.",
    "no_data": "Every sample was unusable after ingest.",
    "no_solution": "The algorithm ran and produced no solution.",
    "no_usable_sources": "No measurement carried both an instrumental and a reference magnitude.",
    "not_a_file": "The named path exists but is not a regular file.",
    "not_found": "The named record does not exist in the local registry.",
    "numerical_error": "The fit failed numerically.",
    "parse_error": "A light-curve file could not be parsed.",
    "plot_failed": "Rendering the plot raised.",
    "provider_unavailable": "A remote astronomy service errored, timed out, or refused the query.",
    "refusing_to_modify_fixture": "The write targets a bundled FITS fixture; see tools/wcs.py's guard.",
    "search_radius_without_hint": "A search radius was given for a frame with no pointing hint to centre it on.",
    "solver_failed": "A plate-solving backend raised rather than returning no solution.",
    "target_not_found": "The named target is not in the local FITS library.",
    "too_many_fixtures": "The fixture listing exceeds its file limit.",
    "tool_exception": "A served tool raised instead of returning a result; the MCP server reports it as this call's error.",
    "unknown_catalog": "The named photometric catalog is not in the registry.",
    "unknown_catalog_fixture": "The named catalog fixture is not one of the recorded ones.",
    "unknown_tool": "The MCP server was asked for a tool the registry does not serve.",
    "unsupported_image_shape": "The image is not 2-D and the operation requires that it be.",
    "write_failed": "Writing an artifact raised.",
    "zero_duration": "The observation spans no time, so there is nothing to render.",
}


#: Every ``ToolWarning.code`` a Kepler tool constructs, and what it means.
#:
#: A warning is how this surface reports a bound on an answer that is still an
#: answer. Several of them mark the silent failures the tools exist to make
#: visible -- ``peak_does_not_fold`` and ``weak_or_absent_pulse`` above all,
#: because a fold at a wrong period returns a flat profile rather than an error.
TOOL_WARNING_CODES: dict[str, str] = {
    "afterglow_base_convention": "The zero point matches Afterglow's base-20 correction, not an absolute magnitude.",
    "back_scale_too_narrow": "The background window is too narrow for the sample spacing; the running median degenerates.",
    "background_not_subtracted": "No baseline subtraction, so the receiver's drifting continuum dominates long periods.",
    "blank_filter": "No image filter was supplied, so no reference band could be matched to one.",
    "bundle_not_installed": "An optional data bundle this tool reads is not installed; `kepler-mcp fetch-data` fetches it.",
    "catalog_match_rate": "How many detected sources matched at least one catalog, and within what radius.",
    "catalogs_capped": "More catalogs matched than max_catalogs allowed to be written.",
    "category_tags_whole_catalog": "A category tags a whole catalog, so matched rows are not all in that band.",
    "columns_vary_per_catalog": "Columns differ per catalog; read each artifact's own column list.",
    "conflicting_position_inputs": "Both a target name and coordinates were given; the coordinates were used.",
    "curated_periods_unavailable": "No usable curated-period file, so scans report no curated_period_s.",
    "download_root_outside_data_dir": "The download root resolves outside the data directory and is searched flat, not walked.",
    "field_radius_capped": "The detected sources span more than the search cap, so catalog coverage is limited to it.",
    "flat_light_curve": "The light curve is constant, so the render is silent.",
    "frame_not_bundled": "A frame the replay wanted is not present in the bundled library.",
    "frame_not_checked_out": "A frame is a Git LFS pointer rather than the frame itself.",
    "frames_not_checked_out": "Some frames are Git LFS pointers and were left out of this listing.",
    "frequency_filter_ignored": "A frequency filter was given for a table it does not apply to.",
    "frequency_filtered": "Rows were dropped by the requested frequency bounds; the count reflects that.",
    "legacy_download_root_present": "A non-empty legacy download directory exists that this search does not cover.",
    "listing_truncated": "More frames were found than the per-root cap returns; the total is named.",
    "max_results_capped": "max_results was capped at a Kepler-side safety limit, not a service limit.",
    "missing_fit_data": "The recorded solve carries no fit_data.csv, so detections are unavailable.",
    "missing_image_shape": "The FITS header carries no usable NAXIS1/NAXIS2.",
    "missing_mag": "A measurement carried no instrumental magnitude and was skipped.",
    "missing_ref_mag": "A measurement carried no resolvable catalog reference magnitude and was skipped.",
    "mono_source": "The file carries one flux column, so the render is mono.",
    "no_abstract": "The bibcode resolved but no abstract text is on file for it.",
    "no_celestial_wcs": "The FITS header contains no celestial WCS.",
    "no_period_in_artifact": "The folded artifact carries no period_s, so the axis is auto-scaled.",
    "no_products_for_observations": "The observations are real but carry no data products.",
    "no_products_matched": "No product matched the given filters, so nothing was downloaded.",
    "no_solution": "The configured plate-solving backends returned no solution.",
    "observations_capped": "More observations matched than products were fetched for; the cap is adjustable.",
    "peak_below_confidence": "The periodogram peak clears no false-alarm threshold; treat it as a non-detection.",
    "peak_does_not_fold": "The strongest peak folds to a weak profile, so it is probably interference or baseline residual.",
    "period_exceeds_baseline": "The fold period is longer than the observation, so it covers less than one rotation.",
    "playback_not_real_time": "The rendered audio drifts against the observation clock; do not read a period off it.",
    "products_downloaded": "Files were downloaded and now resolve through the local frame registry.",
    "resolved_from_truncated_listing": "The match was made among the frames read; frames past the cap were not considered.",
    "solver_backend_unavailable": "Some configured solver inputs were ignored; the solve ran without them.",
    "solver_unavailable": "A plate-solving backend is not configured or not reachable.",
    "sources_skipped": "Identified sources were skipped; the count above covers the rest only.",
    "stat_failed": "A file could not be stat'd while building a listing.",
    "unfolded_rendering": "No period was given, so the raw scan plays through once rather than folded.",
    "unsupported_filter": "The catalog has no reference-band mapping for the image's filter.",
    "variable_sources_not_recorded": "The recorded run's variable-star filter is skipped, so the selection may differ.",
    "wcs_from_header": "The header already carried a celestial WCS, so solving was skipped.",
    "wcs_projection_failed": "A WCS is present but the field centre could not be projected.",
    "weak_or_absent_pulse": "The folded profile peaks weakly: either the period is wrong or the source is too faint.",
}
