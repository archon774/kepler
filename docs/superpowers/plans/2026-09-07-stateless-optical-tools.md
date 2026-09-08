# Stateless Optical Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the optical processing-run and batch architecture while preserving all scientific and public-tool behaviour described in `docs/working/optical-tools.md` phases S0–S6.

**Architecture:** Algorithms receive explicit in-memory inputs and return immutable or typed results; tools retain file, environment, network, timeout, error-translation, and persistence responsibilities. WCS returns a frozen result instead of mutating a run record; extraction, photometry, and field calibration compose through explicit parameters only.

**Tech Stack:** Python 3.14, Astropy, NumPy, SciPy, Pydantic, pytest, uv.

**Spec:** `docs/working/optical-tools.md`

## Global Constraints

- Preserve all numerical expressions, constants, ordering, thresholds, and documented parity quirks.
- Do not modify `algorithms/skylib_lite/`, `algorithms/fieldcal/solution.py`, or `algorithms/fieldcal/ref_mag.py`.
- Do not add a run, context, request, session, stage, progress, job object, or replacement batch command.
- Keep FITS paths, environment reads, remote catalog queries, diagnostics translation, and persistence in `tools/`.
- `file_id` is optional provenance; never synthesize it from a path hash.
- Default tests remain offline and deterministic; solver and network tests stay opt-in.

---

## File structure

- `algorithms/wcs/results.py` — frozen `WcsSolveMetadata` and `WcsSolveResult` result contract.
- `algorithms/wcs/wcs.py` — explicit-input solver and metadata construction, with untouched numerical blocks.
- `algorithms/wcs/source_extraction.py`, `algorithms/photometry/source_extraction.py`, `algorithms/photometry/photometry.py` — retain only explicit extraction and photometry APIs.
- `algorithms/fieldcal/field_cal.py` — deterministic explicit-input calibration composition.
- `tools/wcs.py`, `tools/photometry.py`, `tools/claude_photometry_haiku_tool.py` — tool-owned filesystem/catalog orchestration.
- `algorithms/hrdiagram_py/observations.py`, `tools/radio_sources.py` — consumers that stop manufacturing `file_id` values.
- `tests/test_wcs_solution.py`, `tests/test_wcs_solve_tool.py`, `tests/test_photometry_extraction.py`, `tests/test_photometry_pipeline.py`, `tests/test_fieldcal_pipeline.py`, `tests/test_fieldcal_reference.py`, `tests/test_fieldcal_afterglow_parity.py`, `tests/test_hrdiagram_py.py`, `tests/test_radio_sources.py` — characterization and migration coverage.
- `tests/test_repository_shape.py` — prevents reintroduction of removed optical run/batch APIs.
- `docs/tool-architecture.md`, `docs/repository-folders.md`, `docs/extraction.md`, `tests/README.md`, package docs — maintained architecture and provenance.

### Task 1: S0 baseline and removal inventory

**Files:**
- Modify: `docs/working/optical-tools.md`
- Test: complete default suite

- [ ] Run `uv run --python 3.14 pytest -q` and record final pass, skip, and warning counts in the S0 checklist.
- [ ] Record the executable removal inventory: `algorithms/wcs/state.py`; WCS reconstruction helpers; three run-shaped extraction/photometry adapters; `algorithms/fieldcal/deps.py`; `ProcessingRunRef`; `wire_fieldcal_deps`; path-hash consumers; and `algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py`.
- [ ] Classify planning and provenance references separately so S5 removes only current APIs.
- [ ] Commit the baseline record: `docs: record stateless rollout baseline`.

### Task 2: S1 explicit immutable WCS solve results

**Files:**
- Create: `algorithms/wcs/results.py`
- Modify: `algorithms/wcs/wcs.py`, `algorithms/wcs/__init__.py`, `tools/wcs.py`
- Delete: `algorithms/wcs/state.py`
- Test: `tests/test_wcs_solution.py`, `tests/test_wcs_solve_tool.py`

**Interfaces:**
- Produces: `solve_wcs(header, data, tmpdir, *, file_id=None, pixel_scale_hint_arcsec=None, extraction_settings=None, solve_settings=None, solver_settings=None, solver_attempts=None, solver_failures=None) -> WcsSolveResult`.
- Produces: frozen `WcsSolveResult(wcs: WCS | None, catalog_sources: tuple[CatalogSource, ...], metadata: WcsSolveMetadata)`.

- [ ] Add characterization tests for solved, no-solution, and backend-failure output, including WCS header effects and both diagnostic lists.
- [ ] Run the focused tests and confirm the existing stateful interface is the only source of failures.
- [ ] Add frozen result dataclasses with every metadata field and the required `n_field=0` default; use `delta_ra_arcsec` and `delta_dec_arcsec` names without changing their values.
- [ ] Change `solve_wcs` to accept explicit inputs, call `run_source_extraction(..., file_id=file_id)`, assemble metadata, and return `WcsSolveResult`; retain in-memory accepted-WCS header updates.
- [ ] Migrate `tools.wcs.solve_astrometry` to read `result.wcs` and diagnostics while preserving its protection and atomic-write paths.
- [ ] Delete state and reconstruction APIs after all imports and tests migrate.
- [ ] Run WCS tests and commit: `refactor: return stateless WCS solve results`.

### Task 3: S2 explicit extraction and photometry composition

**Files:**
- Modify: `algorithms/wcs/source_extraction.py`, `algorithms/photometry/source_extraction.py`, `algorithms/photometry/photometry.py`, `algorithms/wcs/wcs.py`, `algorithms/hrdiagram_py/observations.py`, `tools/radio_sources.py`
- Test: `tests/test_photometry_extraction.py`, `tests/test_photometry_pipeline.py`, `tests/test_hrdiagram_py.py`, `tests/test_radio_sources.py`

**Interfaces:**
- Retains: `run_source_extraction(data, header, settings, *, file_id=None) -> tuple[list[SourceExtractionData], np.ndarray, np.ndarray]`.
- Retains: `run_photometry(data, header, sources, settings, *, wcs=None, background=None, background_rms=None) -> list[PhotometryData]`.

- [ ] Add failing consumer tests that assert explicit `file_id=None` for HR/radio and the same source/photometry results.
- [ ] Replace each `perform_source_extraction` and `perform_photometry` call with explicit composition.
- [ ] Remove the three run-shaped adapter definitions and exports.
- [ ] Remove every optical `hash(str(fits_path))` call; callers without a numeric domain ID pass nothing.
- [ ] Run the focused tests and commit: `refactor: make optical extraction inputs explicit`.

### Task 4: S3 deterministic explicit field calibration

**Files:**
- Modify: `algorithms/fieldcal/field_cal.py`, `algorithms/fieldcal/__init__.py`, `algorithms/fieldcal/schemas.py`
- Delete: `algorithms/fieldcal/deps.py`
- Test: `tests/test_fieldcal_pipeline.py`, `tests/test_fieldcal_reference.py`, `tests/test_fieldcal_afterglow_parity.py`, `tests/test_fieldcal_solution.py`, `tests/test_fieldcal_ref_mag.py`

**Interfaces:**
- Produces: `perform_field_calibration(header, data, *, wcs, catalog_sources, variable_sources=None, file_id=None, field_cal_settings=None, photometry_settings=None, extraction_settings=None, detected_sources=None, use_provided_photometry=False) -> tuple[float | None, FieldCalResult] | None`.

- [ ] Extend characterization tests around real-frame and recorded-source parity; add a test that monkeypatches query entry points to fail if the algorithm invokes them.
- [ ] Replace dependency registry calls with normal imports of extraction, RA/Dec conversion, and photometry functions.
- [ ] Require supplied catalog rows; preserve missing-reference and missing-WCS errors without catalog lookup.
- [ ] Pass variable-source rows into filtering; generate call-local source IDs with no timestamp/run ID.
- [ ] Preserve the `apcorr_tol=0.0` calibration path and in-memory FITS calibration keywords.
- [ ] Delete `ProcessingRunRef` and `deps.py` after migration, then run focused tests and commit: `refactor: make field calibration deterministic`.

### Task 5: S4 tool-owned catalog orchestration

**Files:**
- Modify: `tools/photometry.py`, `tools/claude_photometry_haiku_tool.py`
- Test: `tests/test_fieldcal_reference.py`, `tests/test_photometry_tool_smoke.py`, `tests/test_calibration_tool.py`

- [ ] Add tests proving recorded catalog replay makes zero query and VSX calls, and deterministic fakes proving live tool orchestration passes catalog and variable rows to the algorithm.
- [ ] Put catalog selection, `query_catalogs`, and optional VSX query in a private `tools.photometry` helper.
- [ ] Update the registered and compatibility photometry paths to use that helper and invoke explicit field calibration inputs.
- [ ] Preserve structured tool error codes, comparisons, warnings, and tool-owned writes.
- [ ] Run focused tests and commit: `refactor: move calibration queries to tools`.

### Task 6: S5 remove batch architecture and prevent regression

**Files:**
- Delete: `algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py`
- Create: `tests/test_repository_shape.py`
- Modify: affected imports and test references

- [ ] Write a shape test that scans current executable Python modules for the forbidden run, dependency-wiring, and batch-export concepts while excluding declared historical docs.
- [ ] Delete the batch exporter and remaining obsolete exports.
- [ ] Run the complete forbidden-artifact inventory and remove current executable matches only.
- [ ] Run the scientific focused suites and commit: `refactor: remove optical batch architecture`.

### Task 7: S6 documentation and release verification

**Files:**
- Modify: `docs/tool-architecture.md`, `docs/repository-folders.md`, `docs/extraction.md`, `tests/README.md`, `algorithms/wcs/__init__.py`, `algorithms/fieldcal/__init__.py`, `docs/working/optical-tools.md`

- [ ] State that one tool call is the execution unit, describe explicit algorithm inputs, and retain upstream run/ORM terms only as historical provenance.
- [ ] Mark S0–S6 completed with baseline, focused-test, and optional-check evidence.
- [ ] Review protected kernel files for zero diff and inspect mixed-module diffs for numerical changes.
- [ ] Run `uv run --python 3.14 pytest -q`, `uv run --python 3.14 python -m compileall tools algorithms`, and `git diff --check`.
- [ ] Run `ANET_INDEX_PATH=/usr/share/astrometry/data uv run pytest -m solver` only if indexes and solver executable are present; report any unrun optional network checks.
- [ ] Commit documentation and verification evidence: `docs: describe stateless optical tool boundary`.
