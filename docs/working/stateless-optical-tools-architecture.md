# Stateless Optical Tools Architecture

**Status:** Approved for the follow-up PR after #47

**Date:** 2026-09-07

## Purpose

Kepler exposes astronomy capabilities as tools that an agent invokes one call at
a time. It is not the automated Skynet batch pipeline from which several optical
algorithms were extracted. The remaining `ProcessingRun` types, ORM-shaped state,
module-global dependency wiring, and batch exporter force tool callers to emulate
a job system that Kepler neither owns nor needs.

This change removes that architecture while preserving the numerical behavior of
source extraction, plate solving, photometry, and field calibration. Algorithm
functions will receive explicit scientific inputs and return explicit results.
Public tools will own filesystem access, remote catalog access, configuration,
timeouts, error translation, and artifact persistence.

## Scope

The follow-up PR will:

- remove `algorithms.wcs.state.ProcessingRun` and the ORM-shaped mutable
  `WcsSolution` record;
- remove `algorithms.fieldcal.schemas.ProcessingRunRef`;
- remove source-extraction and photometry adapters whose only purpose is reading
  `processing_run.observation_asset_id`;
- replace WCS mutation with a typed return value;
- replace field calibration's process-global `deps` service locator with explicit
  inputs and ordinary imports of deterministic algorithm functions;
- move catalog-query orchestration to `tools.photometry`;
- update every tool and algorithm consumer to pass `file_id` and WCS explicitly;
- delete the retained Skynet batch WCS/photometry/zero-point exporter; and
- update extraction and repository documentation to describe the agentic tool
  architecture rather than instructing callers to recreate a processing run.

This change will not:

- change Python 3.14 or dependency versions;
- change plate-solver search order, acceptance thresholds, or timeout behavior;
- change source-extraction, aperture/PSF photometry, matching, reference-band
  selection, or zero-point mathematics;
- introduce a replacement run, request-context, session, stage, progress, or job
  object;
- introduce a new batch CLI or preserve the legacy batch exporter behind a
  compatibility alias; or
- change the public tool response models except where additional diagnostics are
  required to preserve information currently hidden in mutable run state.

PR #47 is a prerequisite. The implementation branch must be rebased on `dev`
after #47 merges so `tools.wcs.solve_astrometry` is migrated in the same PR.

## Architectural Boundary

### Algorithm layer

Modules under `algorithms/` operate on in-memory scientific values. They may use
Astropy, NumPy, SciPy, SEP, and other algorithm dependencies, but they do not:

- open caller-selected FITS paths;
- query remote catalogs;
- read tool configuration from environment variables;
- mutate module-level dependency slots;
- persist job, stage, or progress state; or
- create identifiers from a pipeline run.

An optional `file_id: int | None` remains valid as provenance attached to source
rows. It is data, not execution state. Callers pass it directly. Callers that do
not have a meaningful numeric identifier pass `None`; they do not hash a path to
manufacture one.

### Tool layer

Modules under `tools/` resolve files, read FITS data, choose local or remote
services, invoke algorithms, write requested artifacts, and convert failures into
the established `ToolError` and `ToolWarning` models. A tool call is the unit of
execution. No state survives solely to connect one tool call to another.

## WCS Contract

`algorithms/wcs/state.py` will be deleted. A focused result module will define
immutable solve output:

```python
@dataclass(frozen=True)
class WcsSolveMetadata:
    science_hdu_index: int | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    crpix1: float | None = None
    crpix2: float | None = None
    crval1: float | None = None
    crval2: float | None = None
    cdelt1: float | None = None
    cdelt2: float | None = None
    cd11: float | None = None
    cd12: float | None = None
    cd21: float | None = None
    cd22: float | None = None
    crota2: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    rotation_deg: float | None = None
    pixel_scale_arcsec_per_px: float | None = None
    mirrored: bool | None = None
    date_solved: datetime | None = None
    pointing_error_arcsec: float | None = None
    delta_ra_arcsec: float | None = None
    delta_dec_arcsec: float | None = None
    n_field: int = 0


@dataclass(frozen=True)
class WcsSolveResult:
    wcs: WCS | None
    catalog_sources: tuple[CatalogSource, ...]
    metadata: WcsSolveMetadata
```

The public algorithm entry point becomes:

```python
def solve_wcs(
    header: fits.Header,
    data: np.ndarray,
    tmpdir: Path,
    *,
    file_id: int | None = None,
    pixel_scale_hint_arcsec: float | None = None,
    extraction_settings: SourceExtractionSettings | None = None,
    solve_settings: PlateSolveSettings | None = None,
    solver_settings: SolverSettings | None = None,
    solver_attempts: list[str] | None = None,
    solver_failures: list[str] | None = None,
) -> WcsSolveResult:
    ...
```

The solve continues updating the caller-provided in-memory FITS header with an
accepted WCS because downstream calculations in the same call depend on it. It
does not write a file. Failure and no-solution results contain dimensions and
detected-source count without pretending that a persisted solution row exists.
The historical stale-field clearing bug disappears with mutable reusable state;
there is no previous result to clear.

`build_wcs_from_processing_run_solution` and `build_wcs_for_processing_run` are
deleted. Consumers use the returned `WCS` directly or call
`build_wcs_from_header(header)` when the WCS is already in a FITS header.

`tools.wcs.solve_astrometry` consumes `WcsSolveResult`. Its existing error codes,
backend-attempt reporting, fixture protection, concurrent-file-change check, and
atomic WCS-header write remain unchanged.

## Source Extraction And Photometry Contracts

Both source-extraction packages already expose deterministic functions accepting
`file_id` explicitly. Those functions become the only supported entry points:

```python
run_source_extraction(data, header, settings, file_id=None)
run_photometry(data, header, sources, settings, *, wcs=None,
               background=None, background_rms=None)
```

The two `perform_source_extraction(processing_run, ...)` adapters and
`perform_photometry(processing_run, ...)` are deleted. Callers that need the old
combined flow call `run_source_extraction`, build the WCS from the header, and
then call `run_photometry`. This composition stays in the calling tool or focused
domain adapter, where its inputs are visible.

`algorithms.hrdiagram_py.observations` and `tools.radio_sources` stop generating
process-random path hashes. They pass `file_id=None`; neither public result exposes
the internal source-row file identifier.

## Field Calibration Contract

`algorithms.fieldcal.deps` and `wire_fieldcal_deps()` are deleted. Field
calibration will have no process-global callable registry. The deterministic
calibration entry point receives all externally acquired data explicitly:

```python
def perform_field_calibration(
    header,
    data: np.ndarray,
    *,
    wcs: WCS | None,
    catalog_sources: Iterable[CatalogSource | Mapping[str, object]],
    variable_sources: Iterable[CatalogSource | Mapping[str, object]] = (),
    file_id: int | None = None,
    field_cal_settings: PhotometricCalibrationSettings | None = None,
    photometry_settings: PhotometrySettings | None = None,
    extraction_settings: SourceExtractionSettings | None = None,
    detected_sources: list[SourceExtractionData] | None = None,
    use_provided_photometry: bool = False,
) -> tuple[float | None, FieldCalResult]:
    ...
```

The function normalizes and matches provided catalog data, optionally filters it
against the provided variable-star rows, runs deterministic extraction and
photometry functions through ordinary imports, and calculates the same solution.
It never queries a catalog. If reference sources are absent it raises the existing
missing-input `ValueError`; if WCS is required for matching but absent it raises
the existing missing-WCS `ValueError`.

Unique generated source IDs use a call-local prefix such as `fieldcal_1` and are
only collision-free within the supplied rows. They no longer include a timestamp
or processing-run ID. These IDs are bookkeeping and do not participate in
matching or numerical results.

`tools.photometry.calibrate_zeropoint` performs catalog selection and calls
`algorithms.query.runner.query_catalogs`. When variable-star rejection is enabled,
the tool also queries VSX and passes those results as `variable_sources`. Offline
recorded-source replay makes no network calls. Shared tool-layer preparation is a
private helper in `tools.photometry`; the standalone Claude compatibility module
calls that helper rather than wiring global state.

The calibration algorithm may continue writing `PHOT_M0`, `PHOT_M0E`, and
`PHOT_CAL` to its in-memory header because those values are explicit scientific
outputs consumed during the same tool call. The tool remains responsible for any
filesystem write.

## Batch Artifact Removal

`algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py` is deleted rather
than ported. It is an automated directory runner with modes, implicit iteration,
CSV aggregation, broad exception swallowing, and mutable FITS writes. Those are
Skynet harness responsibilities, not reusable field-calibration algorithms.

No replacement batch command is introduced. An agent can enumerate known inputs
and invoke `solve_astrometry` or `calibrate_zeropoint` deliberately, inspecting a
structured result after each call.

Before completion, the implementation will audit Python and documentation for
remaining optical-pipeline artifacts. In this scope, forbidden retained concepts
are `ProcessingRun`, `ProcessingRunRef`, `ensure_wcs_solution`,
`build_wcs_for_processing_run`, `wire_fieldcal_deps`, mutable `fieldcal.deps`
assignments, and the WCS/photometry/zero-point batch driver. Historical prose in
`docs/extraction.md` may name upstream Skynet types only when clearly describing
provenance, not as a current Kepler API.

## Error Handling

- Invalid explicit inputs continue to raise `ValueError` at the algorithm layer.
- A valid solve that finds no acceptable WCS returns `WcsSolveResult(wcs=None, ...)`.
- Backend execution failures remain recorded through the existing
  `solver_failures` diagnostic channel so `tools.wcs` can distinguish failure from
  an ordinary miss.
- Remote query failures are handled in the tool layer and translated into current
  structured tool errors or warnings.
- The field-calibration algorithm does not catch dependency or I/O failures
  because it performs neither dependency lookup nor I/O.
- No broad exception handling is added to preserve batch-style “continue with the
  next frame” behavior.

## Migration Sequence

1. Capture characterization tests for WCS metadata and no-solution behavior.
2. Introduce `WcsSolveResult`, return it from `solve_wcs`, and migrate all callers.
3. Remove WCS processing-run state and reconstruction helpers.
4. Migrate source-extraction and photometry consumers to explicit `file_id`, WCS,
   and source lists; then delete the run-shaped adapters.
5. Characterize field calibration with supplied catalog rows and variable-star
   rows, then change it to explicit inputs and ordinary deterministic imports.
6. Move live catalog orchestration into `tools.photometry`, migrate both public
   tool entry paths, and delete global dependency wiring.
7. Delete the batch exporter and obsolete schema types.
8. Update architecture, extraction, folder, and test documentation; run the
   forbidden-artifact audit and full verification.

Each step must leave its focused tests passing. Temporary compatibility code is
allowed only within an uncommitted red-green-refactor cycle; the final PR contains
no deprecated run-based facade.

## Parity And Verification

Parity means identical scientific outputs within the tolerances already used by
the repository, not identical incidental ORM state. Tests will cover:

- source rows, fluxes, background arrays, and file identifiers from both
  source-extraction implementations;
- photometry positions, fluxes, magnitudes, errors, and WCS-derived coordinates;
- successful and unsuccessful WCS outputs, matrix values, center, pixel scale,
  rotation, parity, pointing deltas, detected-source count, backend attempts, and
  failure diagnostics;
- field-calibration source matching, variable-star exclusion, reference-band
  resolution, selected calibration rows, zero point, error, slop, limiting
  magnitude, rejection percentage, and in-memory FITS keywords;
- offline recorded calibration replay without network access;
- public tool schemas and structured failures; and
- absence of the forbidden batch/run artifacts from current Python APIs.

Required final checks use the repository's Python 3.14 environment:

```bash
uv run --python 3.14 pytest -q
uv run --python 3.14 python -m compileall tools algorithms
git diff --check
```

The existing opt-in solver-data and live-query tests remain gated. When their
local data or credentials are available, they are run in addition to the default
suite and their outcomes are recorded in the PR.

## Documentation Outcome

`docs/tool-architecture.md` will state that a tool call is Kepler's execution
boundary. `docs/repository-folders.md` and package documentation will reference
explicit algorithm inputs rather than dependency wiring. `docs/extraction.md`
will retain provenance and parity notes while marking ORM/job-runner adapters and
the batch driver as deliberately removed from the maintained architecture.
