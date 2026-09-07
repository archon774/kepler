# Stateless Optical Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the retained Skynet processing-run and automated batch wrappers so Kepler's existing optical algorithms can be called with explicit scientific inputs from an agentic tool harness without changing their numerical behavior.

**Architecture:** Public tools own FITS I/O, remote catalog queries, solver configuration, error translation, and optional persistence. Algorithm entry points receive arrays, headers, WCS objects, catalog rows, source rows, settings, and an optional provenance `file_id`, then return typed results; the existing source-extraction, plate-solving, photometry, matching, reference-magnitude, and zero-point expressions remain unchanged.

**Tech Stack:** Python 3.14, Astropy, NumPy, SciPy, SEP, Pydantic v2, pytest, uv

**Spec:** `docs/superpowers/specs/2026-09-07-stateless-optical-tools-design.md`

## Global Constraints

- PR #47 is a prerequisite. Rebase this branch on `dev` after PR #47 merges so `tools.wcs.solve_astrometry` is migrated in this PR.
- Keep Python 3.14 and all dependency versions unchanged.
- Do not change plate-solver search order, acceptance thresholds, timeout behavior, source extraction, aperture/PSF photometry, matching, reference-band selection, or zero-point mathematics.
- Do not edit numerical kernels under `algorithms/skylib_lite/`, `algorithms/fieldcal/solution.py`, or `algorithms/fieldcal/ref_mag.py`.
- In mixed algorithm/orchestration modules, limit edits to imports, signatures, explicit input plumbing, result construction, logging identifiers, and removal of job-state mutation. Preserve every numerical expression and the order in which calculations run.
- Do not introduce a replacement run, request-context, session, stage, progress, or job object.
- Do not introduce a replacement batch command or a compatibility alias for the deleted batch exporter.
- Algorithm modules must not open caller-selected FITS paths, query remote catalogs, read tool configuration from environment variables, mutate module-level dependency slots, or persist job state.
- `file_id: int | None` is optional provenance only. Callers without a meaningful identifier pass `None`; they must not hash a path to manufacture one.
- Preserve public tool response models, structured error codes, warnings, backend-attempt reporting, fixture protection, concurrent-file-change checks, and atomic writes.
- Preserve current gated behavior for `network` and `solver_data` tests.

## Execution Preflight

- [ ] **Step 1: Confirm PR #47 has merged into `dev`**

Run:

```bash
gh pr view 47 --json state,mergedAt,baseRefName,headRefName
```

Expected: `state` is `MERGED`, `baseRefName` is `dev`, and `mergedAt` is non-null. Do not start implementation against a branch that lacks `tools/wcs.py`.

- [ ] **Step 2: Rebase the feature branch on current `dev` without a worktree**

Run:

```bash
git checkout agent/remove-processing-run-architecture
git fetch origin dev
git rebase origin/dev
```

Expected: the branch contains the Phase 4 `solve_astrometry` tool and the two planning documents. Resolve documentation-only conflicts without discarding either document.

- [ ] **Step 3: Record a clean Python 3.14 baseline**

Run:

```bash
uv run --python 3.14 pytest -q
uv run --python 3.14 python -m compileall tools algorithms
git diff --check
```

Expected: the default suite, syntax check, and whitespace check pass before implementation. Record the pytest pass/skip counts for comparison with the final run.

---

### Task 1: Lock The Existing WCS Result Mathematics

**Files:**
- Modify: `tests/test_wcs_solution.py`

**Interfaces:**
- Consumes: Phase 4 `solve_wcs(processing_run, header, data, tmpdir, ..., solver_settings=None, solver_attempts=None, solver_failures=None) -> tuple[WCS | None, list[CatalogSource]]`
- Produces: A characterization helper and assertions covering every WCS value that the current solver stores on `WcsSolution`; Task 2 must make the same assertions pass against `WcsSolveResult.metadata`.

- [ ] **Step 1: Add deterministic successful-solve fixtures to the WCS test module**

Add imports for `Path`, `SourceExtractionData`, and `Solution`, then add these helpers immediately before the solve tests:

```python
def _known_linear_wcs() -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [11.0, 11.0]
    wcs.wcs.crval = [180.0, 30.0]
    wcs.wcs.cd = np.array([[-0.001, 0.0], [0.0, 0.001]])
    wcs.array_shape = (21, 21)
    return wcs


def _run_characterized_success(monkeypatch, tmp_path: Path):
    expected_wcs = _known_linear_wcs()
    header = expected_wcs.to_header(relax=True)
    header["NAXIS1"] = 21
    header["NAXIS2"] = 21
    source = SourceExtractionData(x=10.0, y=10.0, flux=1000.0)

    monkeypatch.setattr(
        "algorithms.wcs.wcs.perform_source_extraction",
        lambda *args, **kwargs: ([source], None, None),
    )
    monkeypatch.setattr("algorithms.wcs.wcs.build_anet_config", lambda cfg: object())
    monkeypatch.setattr("algorithms.wcs.wcs.build_atlas_config", lambda cfg: None)
    monkeypatch.setattr(
        "algorithms.wcs.wcs.AstrometryNetBackend.is_available",
        lambda self: True,
    )
    monkeypatch.setattr(
        "algorithms.wcs.wcs.anet_solve_field_glob",
        lambda request, config: Solution(wcs=expected_wcs),
    )

    run = ProcessingRun(observation_asset_id=73)
    solved_wcs, catalog_sources = solve_wcs(
        run,
        header,
        np.zeros((21, 21), dtype=np.float32),
        tmp_path,
    )
    return run.wcs_solution, solved_wcs, catalog_sources, header
```

- [ ] **Step 2: Assert the complete successful metadata contract**

Add:

```python
def test_successful_solve_characterizes_all_scientific_outputs(monkeypatch, tmp_path):
    metadata, solved_wcs, catalog_sources, header = _run_characterized_success(
        monkeypatch, tmp_path
    )

    assert solved_wcs is not None
    assert catalog_sources == []
    assert metadata is not None
    assert metadata.found_solution == 1
    assert metadata.crpix1 == pytest.approx(11.0)
    assert metadata.crpix2 == pytest.approx(11.0)
    assert metadata.crval1 == pytest.approx(180.0)
    assert metadata.crval2 == pytest.approx(30.0)
    assert metadata.cd11 == pytest.approx(-0.001)
    assert metadata.cd12 == pytest.approx(0.0)
    assert metadata.cd21 == pytest.approx(0.0)
    assert metadata.cd22 == pytest.approx(0.001)
    assert metadata.cdelt1 is None
    assert metadata.cdelt2 is None
    assert metadata.ra_deg == pytest.approx(180.0)
    assert metadata.dec_deg == pytest.approx(30.0)
    assert metadata.pixel_scale_arcsec_per_px == pytest.approx(3.6)
    assert metadata.crota2 == pytest.approx(0.0)
    assert metadata.rotation_deg == pytest.approx(180.0)
    assert metadata.mirrored == 1
    assert metadata.width_px == 21
    assert metadata.height_px == 21
    assert metadata.n_field == 1
    assert metadata.pointing_error_arcsec == pytest.approx(0.0, abs=1e-9)
    assert metadata.delta_ra_deg == pytest.approx(0.0, abs=1e-9)
    assert metadata.delta_dec_deg == pytest.approx(0.0, abs=1e-9)
    assert metadata.date_solved is not None
    assert metadata.date_solved.tzinfo is not None
    assert header["CTYPE1"].startswith("RA---")
    assert header["CTYPE2"].startswith("DEC--")
```

- [ ] **Step 3: Characterize no-solution dimensions and source count**

Add:

```python
def test_unsuccessful_solve_retains_dimensions_and_detected_count(monkeypatch, tmp_path):
    header = fits.Header({"NAXIS1": 9, "NAXIS2": 7})
    sources = [SourceExtractionData(x=2.0, y=3.0, flux=10.0)]
    monkeypatch.setattr(
        "algorithms.wcs.wcs.perform_source_extraction",
        lambda *args, **kwargs: (sources, None, None),
    )
    monkeypatch.setattr("algorithms.wcs.wcs.build_anet_config", lambda cfg: None)
    monkeypatch.setattr("algorithms.wcs.wcs.build_atlas_config", lambda cfg: None)

    run = ProcessingRun(observation_asset_id=91)
    solved_wcs, catalog_sources = solve_wcs(
        run,
        header,
        np.zeros((7, 9), dtype=np.float32),
        tmp_path,
    )

    assert solved_wcs is None
    assert catalog_sources == []
    assert run.wcs_solution.width_px == 9
    assert run.wcs_solution.height_px == 7
    assert run.wcs_solution.n_field == 1
    assert run.wcs_solution.found_solution is None
```

- [ ] **Step 4: Run the characterization tests**

Run:

```bash
uv run --python 3.14 pytest tests/test_wcs_solution.py::test_successful_solve_characterizes_all_scientific_outputs tests/test_wcs_solution.py::test_unsuccessful_solve_retains_dimensions_and_detected_count -q
```

Expected: 2 passed against the pre-refactor processing-run implementation.

- [ ] **Step 5: Commit the parity lock**

```bash
git add tests/test_wcs_solution.py
git commit -m "test(wcs): characterize solve result metadata"
```

---

### Task 2: Return WCS Results Without Processing State

**Files:**
- Create: `algorithms/wcs/results.py`
- Modify: `algorithms/wcs/wcs.py`
- Modify: `algorithms/wcs/source_extraction.py`
- Modify: `algorithms/wcs/__init__.py`
- Modify: `tools/wcs.py`
- Modify: `tests/test_wcs_solution.py`
- Modify: `tests/test_wcs_solve_tool.py`
- Delete: `algorithms/wcs/state.py`

**Interfaces:**
- Consumes: `run_source_extraction(data, header, settings, file_id=None)` and Phase 4 `SolverSettings`, `solver_attempts`, and `solver_failures` behavior.
- Produces: `WcsSolveMetadata`, `WcsSolveResult`, and `solve_wcs(header, data, tmpdir, *, file_id=None, pixel_scale_hint_arcsec=None, extraction_settings=None, solve_settings=None, solver_settings=None, solver_attempts=None, solver_failures=None) -> WcsSolveResult`.

- [ ] **Step 1: Change the characterization tests to describe the stateless contract**

Replace state imports with:

```python
from dataclasses import FrozenInstanceError

from algorithms.wcs.results import WcsSolveMetadata, WcsSolveResult
from algorithms.wcs.schemas import SourceExtractionData
from algorithms.wcs.wcs import solve_wcs
```

Change the extraction monkeypatch target to `algorithms.wcs.wcs.run_source_extraction`, call `solve_wcs(header, data, tmp_path, file_id=73)`, and return the single `WcsSolveResult`. Keep every numeric assertion from Task 1, with these mechanical field changes only:

```python
assert isinstance(result, WcsSolveResult)
assert result.wcs is not None
assert result.catalog_sources == ()
metadata = result.metadata
assert metadata.mirrored is True
assert metadata.delta_ra_arcsec == pytest.approx(0.0, abs=1e-9)
assert metadata.delta_dec_arcsec == pytest.approx(0.0, abs=1e-9)
```

Add immutability coverage:

```python
def test_wcs_solve_metadata_is_immutable():
    metadata = WcsSolveMetadata(width_px=9)
    with pytest.raises(FrozenInstanceError):
        metadata.width_px = 10
```

For the no-solution test, assert:

```python
result = solve_wcs(
    header,
    np.zeros((7, 9), dtype=np.float32),
    tmp_path,
    file_id=91,
)
assert result.wcs is None
assert result.catalog_sources == ()
assert result.metadata == WcsSolveMetadata(width_px=9, height_px=7, n_field=1)
```

- [ ] **Step 2: Run the new result-contract tests to verify they fail**

Run:

```bash
uv run --python 3.14 pytest tests/test_wcs_solution.py -q
```

Expected: collection fails because `algorithms.wcs.results` does not exist.

- [ ] **Step 3: Define the immutable result types**

Create `algorithms/wcs/results.py` with exactly the contract approved in the spec:

```python
"""Typed outputs from stateless WCS solving."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from astropy.wcs import WCS

from .schemas import CatalogSource


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
    catalog_sources: tuple[CatalogSource, ...] = ()
    metadata: WcsSolveMetadata = field(default_factory=WcsSolveMetadata)


__all__ = ["WcsSolveMetadata", "WcsSolveResult"]
```

- [ ] **Step 4: Remove the WCS source-extraction adapter**

In `algorithms/wcs/source_extraction.py`, delete the `ProcessingRun` import, delete `perform_source_extraction`, and remove it from `__all__`. Do not change `run_source_extraction`, `build_wcs_from_header`, `get_source_xy`, or any extraction expression.

- [ ] **Step 5: Change only WCS solve plumbing and return construction**

In `algorithms/wcs/wcs.py`:

1. Replace the state imports with `from datetime import datetime, timezone` and `from .results import WcsSolveMetadata, WcsSolveResult`.
2. Import `run_source_extraction` rather than `perform_source_extraction`.
3. Delete `build_wcs_from_processing_run_solution`, `build_wcs_for_processing_run`, and `_clear_wcs_solution_fields`.
4. Change the public signature to the exact `solve_wcs` interface in this task's `Produces` line.
5. Set `file_id` from the explicit keyword and call `run_source_extraction(data, header, extraction_settings, file_id=file_id)`.
6. Leave backend selection, request construction, scale windows, acceptance checks, exception boundaries, and header write-back in their current order.
7. Return `WcsSolveResult` for every exit.

Use this exact no-solution metadata construction in both the caught-backend-failure and ordinary-miss paths:

```python
empty_metadata = WcsSolveMetadata(
    width_px=width,
    height_px=height,
    n_field=int(len(sources)),
)
return WcsSolveResult(
    wcs=None,
    catalog_sources=tuple(atlas_catalog_sources),
    metadata=empty_metadata,
)
```

For success, preserve the existing calculations in place and pass their values directly to `WcsSolveMetadata`. The delta values retain the existing `* 3600.0` calculation and receive corrected unit names:

```python
pointing_error_arcsec = None
delta_ra_arcsec = None
delta_dec_arcsec = None
if ra_hint_deg is not None and dec_hint_deg is not None:
    dra_deg = ((ra - ra_hint_deg + 180.0) % 360.0) - 180.0
    dra = dra_deg * math.cos(math.radians(dec))
    ddec = dec - dec_hint_deg
    pointing_error_arcsec = math.hypot(dra * 3600.0, ddec * 3600.0)
    delta_ra_arcsec = dra * 3600.0
    delta_dec_arcsec = ddec * 3600.0

metadata = WcsSolveMetadata(
    ra_deg=ra,
    dec_deg=dec,
    crpix1=float(wcs_params.crpix[0]),
    crpix2=float(wcs_params.crpix[1]),
    crval1=float(wcs_params.crval[0]),
    crval2=float(wcs_params.crval[1]),
    cdelt1=cdelt1,
    cdelt2=cdelt2,
    cd11=float(A[0, 0]),
    cd12=float(A[0, 1]),
    cd21=float(A[1, 0]),
    cd22=float(A[1, 1]),
    crota2=float(0.5 * (pa_x + pa_y)),
    width_px=width,
    height_px=height,
    rotation_deg=float(180.0 - np.degrees(np.arctan2(A[0, 1], A[1, 1]))),
    pixel_scale_arcsec_per_px=0.5 * (sx + sy),
    mirrored=bool(det < 0),
    date_solved=datetime.now(timezone.utc),
    pointing_error_arcsec=pointing_error_arcsec,
    delta_ra_arcsec=delta_ra_arcsec,
    delta_dec_arcsec=delta_dec_arcsec,
    n_field=int(len(sources)),
)
_write_wcs_to_header(header, wcs_obj, solution=solution)
return WcsSolveResult(
    wcs=wcs_obj,
    catalog_sources=tuple(atlas_catalog_sources),
    metadata=metadata,
)
```

Keep the existing `has_cd()` branch for `cdelt1`/`cdelt2`; only replace assignments onto the old record with local variables.

- [ ] **Step 6: Migrate the public WCS tool**

In `tools/wcs.py`, remove the `ProcessingRun` import and object construction. Call:

```python
solve_result = _solve_wcs(
    header,
    data,
    Path(tmpdir),
    file_id=None,
    pixel_scale_hint_arcsec=pixel_scale_hint,
    solver_settings=solver_settings,
    solver_attempts=attempted_backends,
    solver_failures=solver_failures,
)
solved_wcs = solve_result.wcs
```

Do not change any return branch before or after this call. Update fake solver functions in `tests/test_wcs_solve_tool.py` to accept `(header, data, tmpdir, *, file_id=None, ...)` and return `WcsSolveResult(wcs=..., metadata=...)` instead of a tuple. Remove assertions about a processing-run instance and replace them with `assert captured["file_id"] is None`.

- [ ] **Step 7: Remove obsolete state tests and exports**

Delete tests for `_clear_wcs_solution_fields`, non-slotted `WcsSolution`, processing-run WCS reconstruction, and `now()`. Update the opt-in live solve to use `result = solve_wcs(stripped, np.array(data), tmp_path)` and `solved = result.wcs`. Export the result types from `algorithms/wcs/__init__.py`, then delete `algorithms/wcs/state.py`.

- [ ] **Step 8: Run focused WCS tests**

Run:

```bash
uv run --python 3.14 pytest tests/test_wcs_solution.py tests/test_wcs_solve_tool.py tests/test_wcs_headers.py -q -m "not solver_data"
```

Expected: all selected tests pass; successful and unsuccessful characterization values match Task 1, and no external solver data is needed.

- [ ] **Step 9: Prove core astrometry code was not changed**

Run:

```bash
git diff origin/dev -- algorithms/skylib_lite
```

Expected: no output.

- [ ] **Step 10: Commit the stateless WCS contract**

```bash
git add algorithms/wcs tools/wcs.py tests/test_wcs_solution.py tests/test_wcs_solve_tool.py tests/test_wcs_headers.py
git commit -m "refactor(wcs): return solve results without run state"
```

---

### Task 3: Remove Source-Extraction And Photometry Run Adapters

**Files:**
- Modify: `algorithms/photometry/source_extraction.py`
- Modify: `algorithms/photometry/photometry.py`
- Modify: `algorithms/hrdiagram_py/observations.py`
- Modify: `tools/radio_sources.py`
- Verify: `tests/test_photometry_extraction.py`
- Verify: `tests/test_photometry_pipeline.py`
- Modify: `tests/test_hrdiagram_py.py`
- Modify: `tests/test_radio_sources.py`

**Interfaces:**
- Consumes: Existing, unchanged `run_source_extraction(data, header, settings, file_id=None)` and `run_photometry(data, header, sources, settings, *, wcs=None, background=None, background_rms=None)`.
- Produces: All consumers explicitly compose extraction and photometry; `perform_source_extraction` and `perform_photometry` no longer exist.

- [ ] **Step 1: Add consumer tests for explicit composition and absent synthetic IDs**

In `tests/test_hrdiagram_py.py`, import `algorithms.hrdiagram_py.observations` and add:

```python
def test_observations_compose_explicit_photometry_inputs(monkeypatch, tmp_path):
    path = tmp_path / "stars.fits"
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [4.0, 4.0]
    wcs.wcs.crval = [180.0, 0.0]
    wcs.wcs.cdelt = [-0.001, 0.001]
    fits.writeto(path, np.zeros((8, 8)), header=wcs.to_header())

    source = SourceExtractionData(id="detected-1", x=4.0, y=5.0, flux=100.0)
    seen = {}

    def fake_extract(data, header, settings, *, file_id=None):
        seen["file_id"] = file_id
        return [source], None, None

    def fake_photometry(data, header, sources, settings, *, wcs=None, **kwargs):
        seen["sources"] = sources
        seen["wcs"] = wcs
        return [
            PhotometryData(
                id="detected-1",
                x=4.0,
                y=5.0,
                ra_hours=12.0,
                dec_degs=0.0,
                flux=100.0,
                mag=12.0,
            )
        ]

    monkeypatch.setattr(observations, "run_source_extraction", fake_extract)
    monkeypatch.setattr(observations, "run_photometry", fake_photometry)

    result = observations.extract_photometry_from_fits(str(path))

    assert seen["file_id"] is None
    assert seen["sources"] == [source]
    assert seen["wcs"] is not None
    assert result.loc[0, "inst_mag"] == pytest.approx(12.0)
```

In `tests/test_radio_sources.py`, import the `tools.radio_sources` module and add this private-extractor test:

```python
def test_radio_extraction_composes_explicit_photometry_inputs(monkeypatch, tmp_path):
    path = tmp_path / "radio.fits"
    _write_synthetic_fits(path, with_wcs=True, with_source=False)
    source = SourceExtractionData(id="detected-1", x=4.0, y=5.0, flux=100.0)
    seen = {}

    def fake_extract(data, header, settings, *, file_id=None):
        seen["file_id"] = file_id
        return [source], None, None

    def fake_photometry(data, header, sources, settings, *, wcs=None, **kwargs):
        seen["sources"] = sources
        seen["wcs"] = wcs
        return [
            PhotometryData(
                id="detected-1",
                x=4.0,
                y=5.0,
                ra_hours=12.0,
                dec_degs=0.0,
                flux=100.0,
                mag=12.0,
            )
        ]

    monkeypatch.setattr(radio_sources, "run_source_extraction", fake_extract)
    monkeypatch.setattr(radio_sources, "run_photometry", fake_photometry)

    result = radio_sources._extract_radio_sources(str(path))

    assert seen["file_id"] is None
    assert seen["sources"] == [source]
    assert seen["wcs"] is not None
    assert result.loc[0, "flux"] == pytest.approx(100.0)
```

Add the required `SourceExtractionData` and `PhotometryData` imports from `algorithms.photometry.schemas` to both test modules.

- [ ] **Step 2: Run the new consumer tests to verify they fail**

Run:

```bash
uv run --python 3.14 pytest tests/test_hrdiagram_py.py::test_observations_compose_explicit_photometry_inputs tests/test_radio_sources.py::test_radio_extraction_composes_explicit_photometry_inputs -q
```

Expected: failure because the consumers still construct `ProcessingRun` and call `perform_photometry`.

- [ ] **Step 3: Compose the existing functions in both consumers**

In `algorithms/hrdiagram_py/observations.py` and `tools/radio_sources.py`:

```python
sources, background, background_rms = run_source_extraction(
    data,
    header,
    extraction_settings,
    file_id=None,
)
wcs = build_wcs_from_header(header)
results = run_photometry(
    data,
    header,
    sources,
    photometry_settings,
    wcs=wcs,
    background=background,
    background_rms=background_rms,
)
```

Use each module's existing variable names and settings. Delete `ProcessingRun`, `perform_photometry`, and path-hash imports/expressions. Do not change result sorting, filtering, cross-matching, or serialization.

- [ ] **Step 4: Delete the two run-shaped adapters**

Delete `perform_source_extraction` from `algorithms/photometry/source_extraction.py` and `perform_photometry` from `algorithms/photometry/photometry.py`. Remove their imports and `__all__` entries. Do not edit the bodies of `run_source_extraction` or `run_photometry`.

- [ ] **Step 5: Run extraction, photometry, and consumer parity tests**

Run:

```bash
uv run --python 3.14 pytest tests/test_photometry_extraction.py tests/test_photometry_pipeline.py tests/test_hrdiagram_py.py tests/test_radio_sources.py -q
```

Expected: the source counts, background maps, fluxes, magnitudes, WCS-derived coordinates, HR-diagram observations, and radio-source behavior all pass existing tolerances.

- [ ] **Step 6: Prove the numerical photometry implementation is unchanged**

Run:

```bash
git diff origin/dev -- algorithms/photometry/photometry.py algorithms/photometry/source_extraction.py
```

Expected: the diff contains only imports, `__all__`, and deletion of the two adapter functions. The `run_source_extraction` and `run_photometry` bodies have no changed lines.

- [ ] **Step 7: Commit explicit photometry composition**

```bash
git add algorithms/photometry algorithms/hrdiagram_py/observations.py tools/radio_sources.py tests/test_hrdiagram_py.py tests/test_radio_sources.py
git commit -m "refactor(photometry): remove processing run adapters"
```

---

### Task 4: Characterize Field Calibration With Supplied Inputs

**Files:**
- Modify: `tests/test_fieldcal_pipeline.py`
- Verify: `tests/test_fieldcal_afterglow_parity.py`

**Interfaces:**
- Consumes: Current processing-run and `fieldcal.deps` based calibration entry point.
- Produces: Parity assertions for explicit reference rows, variable-star exclusion, calibration photometry settings, solution diagnostics, selected calibration rows, and FITS keywords; Task 5 must retain them under the explicit-input signature.

- [ ] **Step 1: Strengthen the existing real-frame parity assertions**

Extend `test_perform_field_calibration_end_to_end_on_a_real_frame` without changing fixture generation:

```python
assert result.file_id == 1
assert result.zero_point_corr == pytest.approx(zero_point)
assert result.zero_point_error_mag is not None
assert np.isfinite(result.zero_point_error_mag)
assert result.zero_point_slop is not None
assert result.limmag5 is not None
assert result.rej_percent is not None
assert all(source.catalog_name == "APASS" for source in result.phot_results)
assert all(source.ref_mag is not None for source in result.phot_results)
assert header["PHOT_M0E"] == pytest.approx(result.zero_point_error_mag)
```

- [ ] **Step 2: Add a supplied-variable-row characterization test**

Import `_filter_variable_stars` and add this test against the current query seam:

```python
def test_variable_star_filter_preserves_non_variable_order(monkeypatch):
    references = [
        CatalogSource(id="ref-1", ra_hours=12.0000, dec_degs=0.0),
        CatalogSource(id="ref-2", ra_hours=12.0010, dec_degs=0.0),
        CatalogSource(id="ref-3", ra_hours=12.0020, dec_degs=0.0),
    ]
    variable = CatalogSource(id="vsx-1", ra_hours=12.0010, dec_degs=0.0)
    monkeypatch.setattr(deps, "query_catalogs", lambda *args, **kwargs: [variable])
    monkeypatch.setattr(
        deps,
        "get_source_radec",
        lambda source, epoch, wcs: (source.ra_hours, source.dec_degs),
    )

    filtered = _filter_variable_stars(
        references,
        processing_run=object(),
        wcs=_wcs(),
        header={},
        data=np.zeros((4, 4), dtype=np.float32),
        variable_check_tol=5.0,
    )

    assert [source.id for source in filtered] == ["ref-1", "ref-3"]
```

- [ ] **Step 3: Preserve the independent Afterglow parity suite unchanged**

Run:

```bash
git diff -- tests/test_fieldcal_afterglow_parity.py
uv run --python 3.14 pytest tests/test_fieldcal_afterglow_parity.py -q
```

Expected: the diff has no output and the recorded zero point, error, limiting magnitude, aperture-correction setting, and web-value parity tests pass.

- [ ] **Step 4: Run the field-calibration characterization suite**

Run:

```bash
uv run --python 3.14 pytest tests/test_fieldcal_pipeline.py tests/test_fieldcal_afterglow_parity.py tests/test_fieldcal_solution.py tests/test_fieldcal_ref_mag.py -q
```

Expected: all tests pass against the pre-refactor implementation.

- [ ] **Step 5: Commit the calibration parity lock**

```bash
git add tests/test_fieldcal_pipeline.py
git commit -m "test(fieldcal): lock explicit-input parity"
```

---

### Task 5: Make Field Calibration A Deterministic Explicit-Input Algorithm

**Files:**
- Modify: `algorithms/fieldcal/field_cal.py`
- Modify: `algorithms/fieldcal/__init__.py`
- Modify: `tests/test_fieldcal_pipeline.py`
- Delete: `algorithms/fieldcal/deps.py`

**Interfaces:**
- Consumes: `build_wcs_from_header`, `get_source_radec`, `run_source_extraction`, `run_photometry`, `CatalogSource`, supplied `variable_sources`, and existing field-calibration settings.
- Produces: `perform_field_calibration(header, data, *, wcs, catalog_sources, variable_sources=(), file_id=None, field_cal_settings=None, photometry_settings=None, extraction_settings=None, detected_sources=None, use_provided_photometry=False) -> tuple[float | None, FieldCalResult]`.

- [ ] **Step 1: Rewrite orchestration tests for ordinary imports and explicit arguments**

Remove the dependency-stub, default-query, late-injection, and `restore_deps` tests and fixture. Update calls to the target signature:

```python
zero_point, result = perform_field_calibration(
    header,
    data,
    wcs=wcs,
    catalog_sources=catalog_sources,
    variable_sources=variable_sources,
    file_id=1,
    field_cal_settings=field_cal_settings,
    photometry_settings=photometry_settings,
    extraction_settings=extraction_settings,
    detected_sources=detected,
)
```

Monkeypatch deterministic imports at their use site when a spy is required:

```python
monkeypatch.setattr(field_cal, "run_photometry", spy_run_photometry)
monkeypatch.setattr(field_cal, "run_source_extraction", fake_run_source_extraction)
```

Add these explicit-boundary tests:

```python
def test_field_calibration_requires_supplied_reference_sources():
    with pytest.raises(ValueError, match="Missing catalog sources"):
        perform_field_calibration(
            {},
            np.zeros((4, 4), dtype=np.float32),
            wcs=None,
            catalog_sources=[],
        )


def test_field_calibration_requires_wcs_for_pixel_matching():
    catalog_sources = [
        CatalogSource(
            id="c1",
            ra_hours=12.0,
            dec_degs=0.0,
            mags={"V": Mag(value=12.0, error=0.02)},
        )
    ]
    with pytest.raises(ValueError, match="Missing WCS"):
        perform_field_calibration(
            {"FILTER": "V"},
            np.zeros((4, 4), dtype=np.float32),
            wcs=None,
            catalog_sources=catalog_sources,
            detected_sources=[SourceExtractionData(id="d1", x=1.0, y=1.0)],
        )
```

Convert Task 4's variable-star test to the new explicit contract without changing its rows or expected order:

```python
filtered = _filter_variable_stars(
    references,
    variable_sources=[variable],
    wcs=_wcs(),
    header={},
    variable_check_tol=5.0,
)
assert [source.id for source in filtered] == ["ref-1", "ref-3"]
```

- [ ] **Step 2: Run the explicit-input tests to verify they fail**

Run:

```bash
uv run --python 3.14 pytest tests/test_fieldcal_pipeline.py -q
```

Expected: failures show that the old leading processing-run argument and `deps` calls still exist.

- [ ] **Step 3: Replace the service locator with deterministic imports**

In `algorithms/fieldcal/field_cal.py`, remove `datetime`, `timezone`, `Any`, and `.deps`. Add:

```python
from algorithms.photometry.photometry import run_photometry
from algorithms.photometry.source_extraction import get_source_radec, run_source_extraction
```

Do not import `algorithms.query` or any tool module.

- [ ] **Step 4: Make generated IDs call-local**

Change `_ensure_unique_source_ids` to:

```python
def _ensure_unique_source_ids(sources: list[CatalogSource]) -> None:
    source_ids: set[str | tuple[str, int | None]] = set()
    for idx, source in enumerate(sources):
        source_id = getattr(source, "id", None)
        if source_id is None:
            source.id = source_id = f"fieldcal_{idx + 1}"
        source_key = source_id
        if getattr(source, "file_id", None) is not None:
            source_key = (source_id, source.file_id)
        if source_key in source_ids:
            raise ValueError(f'Non-unique source ID "{source_id}"')
        source_ids.add(source_key)
```

Update the ID test to expect `fieldcal_1`, `fieldcal_2`, and stable repetition across calls. This identifier is bookkeeping only and must not enter a numerical calculation.

- [ ] **Step 5: Filter against supplied variable stars**

Change `_filter_variable_stars` to accept `variable_sources` and use ordinary `get_source_radec`:

```python
def _filter_variable_stars(
    sources: list[CatalogSource],
    *,
    variable_sources: Iterable[CatalogSource | Mapping[str, object]],
    wcs: WCS | None,
    header,
    variable_check_tol: float | None,
) -> list[CatalogSource]:
    if not variable_check_tol or variable_check_tol <= 0 or wcs is None:
        return sources
    var_stars = _normalize_catalog_sources(variable_sources, file_id=None)
    if not var_stars:
        return sources
    epoch = get_fits_time(header)[0]
    filtered: list[CatalogSource] = []
    for source in sources:
        ra, dec = get_source_radec(
            SourceExtractionData(
                **source.model_dump(exclude={"mags", "catalog_name", "label"})
            ),
            epoch,
            wcs,
        )
        if ra is None or dec is None:
            filtered.append(source)
            continue
        is_variable = any(
            angdist(ra, dec, star.ra_hours, star.dec_degs) * 3600 < variable_check_tol
            for star in var_stars
            if star.ra_hours is not None and star.dec_degs is not None
        )
        if not is_variable:
            filtered.append(source)
    return filtered
```

This preserves the angular-distance expression and comparison direction exactly; only acquisition of `var_stars` changes.

- [ ] **Step 6: Change the calibration entry signature and input setup**

Replace the public signature with:

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
```

Replace processing-run field reads, WCS reconstruction, and catalog-query branches with:

```python
settings = field_cal_settings or PhotometricCalibrationSettings()
phot_settings = photometry_settings or PhotometrySettings()
configured_catalogs = list(settings.catalogs or [])
logger.info("Starting field calibration for file_id=%s", file_id)
logger.info("WCS available for field calibration: %s", wcs is not None)

sources = _normalize_catalog_sources(catalog_sources, file_id=file_id)
_attach_catalog_magnitudes(sources)
if not sources or not _has_reference_magnitudes(sources):
    raise ValueError("Missing catalog sources or reference magnitudes for field calibration")

_ensure_unique_source_ids(sources)
sources = _filter_variable_stars(
    sources,
    variable_sources=variable_sources,
    wcs=wcs,
    header=header,
    variable_check_tol=settings.variable_check_tol,
)
```

Keep matching, the `apcorr_tol=0.0` override, SNR selection, reference-band resolution, `max_stars`, `calc_solution`, and FITS keyword expressions unchanged. Replace `deps.run_source_extraction` and `deps.run_photometry` with the imported functions only.

- [ ] **Step 7: Delete global dependency exports**

Delete `algorithms/fieldcal/deps.py`. In `algorithms/fieldcal/__init__.py`, remove `deps`, remove wiring instructions, and describe the explicit input pipeline. Do not export a dependency container under another name.

- [ ] **Step 8: Run field-calibration parity suites**

Run:

```bash
uv run --python 3.14 pytest tests/test_fieldcal_pipeline.py tests/test_fieldcal_afterglow_parity.py tests/test_fieldcal_solution.py tests/test_fieldcal_ref_mag.py -q
```

Expected: all pre-refactor numerical assertions from Task 4 still pass, the aperture-correction spy sees exactly `[0.0]`, supplied VSX rows are excluded, and the algorithm performs no query.

- [ ] **Step 9: Prove calibration math files are unchanged**

Run:

```bash
git diff origin/dev -- algorithms/fieldcal/solution.py algorithms/fieldcal/ref_mag.py algorithms/skylib_lite
```

Expected: no output.

- [ ] **Step 10: Commit deterministic field calibration**

```bash
git add algorithms/fieldcal tests/test_fieldcal_pipeline.py tests/test_fieldcal_afterglow_parity.py
git commit -m "refactor(fieldcal): accept explicit calibration inputs"
```

---

### Task 6: Move Catalog Orchestration Into The Tool Layer

**Files:**
- Modify: `tools/photometry.py`
- Modify: `tools/claude_photometry_haiku_tool.py`
- Modify: `tests/test_photometry_tool_smoke.py`
- Modify: `tests/test_photometry_registry_smoke.py`
- Modify: `tests/test_fieldcal_reference.py`

**Interfaces:**
- Consumes: Explicit-input `perform_field_calibration`, `build_wcs_from_header`, `select_catalogs_for_filter`, and `query_catalogs`.
- Produces: `_prepare_fieldcal_catalogs(header, *, wcs, catalog_sources, catalogs, variable_check_tol, custom_filter_lookup=None) -> tuple[list[str], list[CatalogSource], list[CatalogSource]]`; both calibration tool paths use it without global wiring.

- [ ] **Step 1: Add offline and online orchestration tests**

Add tests around `_prepare_fieldcal_catalogs`:

```python
def test_prepare_fieldcal_catalogs_offline_never_queries(monkeypatch, frame_header):
    header = frame_header("ngc3628")
    supplied = [CatalogSource(id="a", catalog_name="APASS", ref_mag=12.0)]
    monkeypatch.setattr(
        "tools.photometry.query_catalogs",
        lambda *args, **kwargs: pytest.fail("offline replay must not query"),
    )
    selected, references, variables = _prepare_fieldcal_catalogs(
        header,
        wcs=build_wcs_from_header(header),
        catalog_sources=supplied,
        catalogs=None,
        variable_check_tol=5.0,
    )
    assert selected == ["APASS"]
    assert references == supplied
    assert variables == []


def test_prepare_fieldcal_catalogs_queries_references_then_vsx(monkeypatch, frame_header):
    header = frame_header("ngc3628")
    wcs = build_wcs_from_header(header)
    reference = CatalogSource(id="a", catalog_name="APASS", ref_mag=12.0)
    variable = CatalogSource(id="v", catalog_name="VSX", ra_hours=12.0, dec_degs=0.0)
    calls = []

    def fake_query(catalogs, **kwargs):
        calls.append((list(catalogs), kwargs))
        return [variable] if list(catalogs) == ["VSX"] else [reference]

    monkeypatch.setattr("tools.photometry.query_catalogs", fake_query)

    selected, references, variables = _prepare_fieldcal_catalogs(
        header,
        wcs=wcs,
        catalog_sources=None,
        catalogs=["APASS"],
        variable_check_tol=5.0,
        custom_filter_lookup={"APASS": {"V": "V"}},
    )

    assert selected == ["APASS"]
    assert references == [reference]
    assert variables == [variable]
    assert [call[0] for call in calls] == [["APASS"], ["VSX"]]
    assert calls[0][1]["wcs"] is wcs
    assert calls[0][1]["stop_on_success"] is True
    assert calls[0][1]["custom_filter_lookup"] == {"APASS": {"V": "V"}}
    assert calls[1][1]["wcs"] is wcs
    assert calls[1][1]["skip_failed"] is True
```

- [ ] **Step 2: Run the new tool-orchestration tests to verify they fail**

Run:

```bash
uv run --python 3.14 pytest tests/test_photometry_tool_smoke.py::test_prepare_fieldcal_catalogs_offline_never_queries tests/test_photometry_tool_smoke.py::test_prepare_fieldcal_catalogs_queries_references_then_vsx -q
```

Expected: collection or attribute failure because `_prepare_fieldcal_catalogs` does not exist.

- [ ] **Step 3: Implement the private tool-layer helper**

In `tools/photometry.py`, delete `wire_fieldcal_deps`. Add these imports, keeping them beside the other algorithm imports:

```python
from algorithms.catalogs import CATALOGS
from algorithms.catalogs.schemas import CatalogSource
from algorithms.query.runner import query_catalogs
from algorithms.query.selection import select_catalogs_for_filter
```

Then implement:

```python
def _prepare_fieldcal_catalogs(
    header,
    *,
    wcs,
    catalog_sources: list[CatalogSource] | None,
    catalogs: list[str] | None,
    variable_check_tol: float | None,
    custom_filter_lookup: dict[str, dict[str, str]] | None = None,
) -> tuple[list[str], list[CatalogSource], list[CatalogSource]]:
    if catalog_sources is not None:
        catalog_names = {
            getattr(source, "catalog_name", None) for source in catalog_sources
        }
        selected = list(catalogs) if catalogs else sorted(
            name for name in catalog_names if name
        )
        return selected, list(catalog_sources), []

    image_filter = header.get("FILTER") if hasattr(header, "get") else None
    selected = list(catalogs) if catalogs else select_catalogs_for_filter(
        list(CATALOGS), image_filter
    )
    if not selected:
        raise ValueError(
            f"No calibration catalog supports filter {image_filter!r}; "
            "pass catalogs= or catalog_sources=."
        )
    references = query_catalogs(
        selected,
        wcs=wcs,
        skip_failed=True,
        stop_on_success=True,
        image_filter=image_filter,
        custom_filter_lookup=custom_filter_lookup,
    )
    variables = []
    if variable_check_tol and variable_check_tol > 0:
        try:
            variables = query_catalogs(["VSX"], wcs=wcs, skip_failed=True)
        except Exception:
            variables = []
    return selected, references, variables
```

The best-effort VSX exception behavior is preserved from the old `_filter_variable_stars`; the reference query remains a tool-level failure.

- [ ] **Step 4: Migrate `calibrate_zeropoint`**

Build WCS once from the loaded header, return the current structured missing-WCS error when absent, call `_prepare_fieldcal_catalogs`, and invoke:

```python
outcome = perform_field_calibration(
    header.copy(),
    data,
    wcs=wcs,
    catalog_sources=reference_sources,
    variable_sources=variable_sources,
    file_id=None,
    field_cal_settings=field_cal_settings,
    photometry_settings=photometry_settings,
    extraction_settings=SourceExtractionSettings(),
)
```

Preserve `field_cal_settings.variable_check_tol=0` for offline replay, comparison lookup, result model construction, and current error codes. Remove `ProcessingRunRef`, `catalog_names`, and wiring calls.

- [ ] **Step 5: Migrate the standalone Claude compatibility path**

In `tools/claude_photometry_haiku_tool.py`, import and call `_prepare_fieldcal_catalogs`, then call the explicit-input calibration interface with the already-built WCS. Delete the local `ProcessingRun` class and replace its source-extraction call with:

```python
sources, background, background_rms = run_source_extraction(
    data,
    header,
    extraction_settings,
    file_id=None,
)
```

Retain its return tuple, fallback error strings, diagnostic dictionary, plotting, and magnitude behavior.

- [ ] **Step 6: Run tool and offline replay tests**

Run:

```bash
uv run --python 3.14 pytest tests/test_photometry_tool_smoke.py tests/test_photometry_registry_smoke.py tests/test_fieldcal_reference.py tests/test_fieldcal_afterglow_parity.py -q
```

Expected: offline replay makes zero query calls, online spies see reference then VSX orchestration, and public result schemas remain unchanged.

- [ ] **Step 7: Commit tool-owned catalog orchestration**

```bash
git add tools/photometry.py tools/claude_photometry_haiku_tool.py tests/test_photometry_tool_smoke.py tests/test_photometry_registry_smoke.py tests/test_fieldcal_reference.py
git commit -m "refactor(tools): own field calibration orchestration"
```

---

### Task 7: Delete Batch And Run Schema Artifacts

**Files:**
- Delete: `algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py`
- Modify: `algorithms/fieldcal/schemas.py`
- Modify: `algorithms/fieldcal/__init__.py`
- Create: `tests/test_optical_architecture.py`

**Interfaces:**
- Consumes: Final stateless APIs from Tasks 2, 3, 5, and 6.
- Produces: No `ProcessingRun`, `ProcessingRunRef`, dependency-wiring API, WCS state module, or automated WCS/photometry/zero-point batch driver in current Python code.

- [ ] **Step 1: Write a repository architecture test**

Create `tests/test_optical_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_OPTICAL_PATHS = [
    ROOT / "algorithms" / "wcs",
    ROOT / "algorithms" / "photometry",
    ROOT / "algorithms" / "fieldcal",
    ROOT / "algorithms" / "hrdiagram_py",
    ROOT / "tools",
]
FORBIDDEN_NAMES = {
    "ProcessingRun",
    "ProcessingRunRef",
    "ensure_wcs_solution",
    "build_wcs_for_processing_run",
    "build_wcs_from_processing_run_solution",
    "wire_fieldcal_deps",
    "perform_source_extraction",
    "perform_photometry",
}


def test_processing_run_architecture_is_absent_from_current_python_apis():
    offenders: list[str] = []
    for directory in CURRENT_OPTICAL_PATHS:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                name = None
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = node.name
                elif isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.alias):
                    name = node.asname or node.name.rsplit(".", 1)[-1]
                if name in FORBIDDEN_NAMES:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
    assert offenders == []


def test_automated_batch_and_state_modules_are_deleted():
    assert not (ROOT / "algorithms/wcs/state.py").exists()
    assert not (ROOT / "algorithms/fieldcal/deps.py").exists()
    assert not (
        ROOT / "algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py"
    ).exists()
```

- [ ] **Step 2: Run the architecture test to verify it fails**

Run:

```bash
uv run --python 3.14 pytest tests/test_optical_architecture.py -q
```

Expected: failures identify `ProcessingRunRef` and the existing batch exporter.

- [ ] **Step 3: Remove the obsolete schema and batch file**

Delete `ProcessingRunRef` from `algorithms/fieldcal/schemas.py` and its export from `algorithms/fieldcal/__init__.py`. Delete `algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py` without replacement. Do not move any directory iteration, CSV aggregation, broad exception handling, or FITS mutation into a tool.

- [ ] **Step 4: Run architecture and package import tests**

Run:

```bash
uv run --python 3.14 pytest tests/test_optical_architecture.py tests/test_repository_shape.py -q
uv run --python 3.14 python -c "import algorithms.wcs, algorithms.photometry, algorithms.fieldcal, tools.photometry, tools.wcs"
```

Expected: tests pass and imports complete without global wiring.

- [ ] **Step 5: Commit artifact removal**

```bash
git add algorithms/fieldcal tests/test_optical_architecture.py
git commit -m "refactor(optical): remove automated batch artifacts"
```

---

### Task 8: Document The Agentic Execution Boundary

**Files:**
- Modify: `docs/tool-architecture.md`
- Modify: `docs/repository-folders.md`
- Modify: `docs/extraction.md`
- Modify: `tests/README.md`
- Modify: `algorithms/wcs/__init__.py`
- Modify: `algorithms/photometry/__init__.py`
- Modify: `algorithms/fieldcal/__init__.py`

**Interfaces:**
- Consumes: Final explicit APIs and the historical provenance already documented in `docs/extraction.md`.
- Produces: Current documentation treats a tool call as the execution boundary and describes removed Skynet artifacts only as historical provenance.

- [ ] **Step 1: Update the architecture guide**

Add a concise section to `docs/tool-architecture.md` stating:

```markdown
## Execution boundary

A public tool call is Kepler's unit of execution. Tools resolve files, query
remote services, select configuration, translate failures, and write requested
artifacts. Optical algorithms receive explicit in-memory arrays, FITS headers,
WCS objects, catalog rows, source rows, and settings, and return explicit values.

Kepler does not expose a processing-run, job, stage, or batch-pipeline context.
Callers that want to process several frames invoke a tool once per frame and
inspect each structured result before choosing the next action.
```

- [ ] **Step 2: Update folder and package reference docs**

In `docs/repository-folders.md` and the three optical package docstrings:

- list `algorithms/wcs/results.py` and its immutable result contract;
- list only `run_source_extraction` and `run_photometry` as photometry entry points;
- describe field calibration as supplied WCS plus catalog rows plus optional VSX rows;
- remove `state.py`, `deps.py`, dependency wiring, run adapters, and the batch exporter from current-file lists.

- [ ] **Step 3: Preserve provenance while marking seams deliberately removed**

In `docs/extraction.md`, keep upstream file/type names and parity notes, but rewrite current-state paragraphs to say:

```markdown
The upstream `ObservationAssetProcessingRun` and WCS solution ORM rows are
historical provenance only. Kepler originally retained plain stand-ins while
validating the extraction; the agentic tool architecture now passes `file_id`
explicitly and returns `WcsSolveResult`. No run-shaped compatibility API remains.
```

Document that field calibration imports deterministic extraction/photometry functions normally, receives catalog results explicitly, and cannot query the network. Mark the automated batch exporter as deliberately deleted because orchestration belongs to the calling agent/tool layer.

- [ ] **Step 4: Update test coverage documentation**

In `tests/README.md`, remove the batch-driver coverage gap. Add `tests/test_optical_architecture.py` and note that parity coverage protects source rows/backgrounds, photometry values, WCS metadata, field-calibration diagnostics, public tool schemas, and the absence of run/batch APIs.

- [ ] **Step 5: Audit current documentation language**

Run:

```bash
rg -n "ProcessingRun|ProcessingRunRef|ensure_wcs_solution|build_wcs_for_processing_run|wire_fieldcal_deps|perform_source_extraction|perform_photometry|batch_wcs_photometry_zeropoint_export" docs algorithms tools tests
```

Expected: matches remain only in the approved spec/plan, point-in-time historical plans, explicit historical provenance in `docs/extraction.md`, and the architecture test's forbidden-name set. No current API documentation or Python implementation advertises these concepts.

- [ ] **Step 6: Commit documentation**

```bash
git add docs tests/README.md algorithms/wcs/__init__.py algorithms/photometry/__init__.py algorithms/fieldcal/__init__.py
git commit -m "docs: describe stateless optical tool architecture"
```

---

### Task 9: Verify Numerical Parity And PR Readiness

**Files:**
- Verify only: all files changed by Tasks 1-8

**Interfaces:**
- Consumes: Complete stateless optical-tool implementation.
- Produces: Review evidence that only orchestration changed, all default checks pass on Python 3.14, optional checks remain correctly gated, and the branch is ready for a separate PR to `dev`.

- [ ] **Step 1: Review the complete diff for forbidden mathematical changes**

Run:

```bash
git diff --stat origin/dev...HEAD
git diff origin/dev...HEAD -- algorithms/skylib_lite algorithms/fieldcal/solution.py algorithms/fieldcal/ref_mag.py
git diff origin/dev...HEAD -- algorithms/wcs/wcs.py algorithms/photometry/photometry.py algorithms/photometry/source_extraction.py algorithms/fieldcal/field_cal.py
```

Expected: the first command shows the intended wrapper/result/tool/docs migration; the second command has no output; the third contains no changed numerical constants, thresholds, calculation order, solver requests, matching expressions, reference-band logic, or zero-point expressions.

- [ ] **Step 2: Run focused optical parity tests**

Run:

```bash
uv run --python 3.14 pytest tests/test_wcs_solution.py tests/test_wcs_solve_tool.py tests/test_wcs_headers.py tests/test_photometry_extraction.py tests/test_photometry_pipeline.py tests/test_fieldcal_pipeline.py tests/test_fieldcal_afterglow_parity.py tests/test_fieldcal_solution.py tests/test_fieldcal_ref_mag.py tests/test_fieldcal_reference.py tests/test_photometry_tool_smoke.py tests/test_hrdiagram_py.py tests/test_radio_sources.py tests/test_optical_architecture.py -q -m "not solver_data and not network"
```

Expected: all selected tests pass at their existing tolerances.

- [ ] **Step 3: Run the complete default verification suite**

Run:

```bash
uv run --python 3.14 pytest -q
uv run --python 3.14 python -m compileall tools algorithms
npm run typecheck
git diff --check
```

Expected: pytest pass/skip counts are consistent with the preflight baseline plus the new tests; compileall, TypeScript typecheck, and diff check pass.

- [ ] **Step 4: Run optional solver-data coverage when local indexes are available**

Run:

```bash
ANET_INDEX_PATH=/usr/share/astrometry/data uv run --python 3.14 pytest tests/test_wcs_solution.py tests/test_wcs_solve_tool.py -q -m solver_data
```

Expected: the live solver test passes or self-skips for uncovered field scale. Record the outcome in the PR validation section. Do not download or commit solver data.

- [ ] **Step 5: Re-run the forbidden-artifact audit on executable Python**

Run:

```bash
uv run --python 3.14 pytest tests/test_optical_architecture.py -q
rg -n "abs\(hash\(str\(fits_path\)\)\)|fieldcal\.deps|from algorithms\.wcs\.state|from \.state" algorithms tools
```

Expected: architecture tests pass and `rg` returns no matches.

- [ ] **Step 6: Inspect branch status and commit graph**

Run:

```bash
git status --short --branch
git log --oneline --decorate origin/dev..HEAD
```

Expected: the worktree is clean and the branch contains focused characterization, refactor, removal, and documentation commits.

- [ ] **Step 7: Push and open the separate PR to `dev`**

Run:

```bash
git push -u origin agent/remove-processing-run-architecture
gh pr create --base dev --head agent/remove-processing-run-architecture --title "Remove processing-run optical pipeline artifacts" --body-file /tmp/kepler-stateless-optical-pr.md
```

The PR body must use the repository template headings and report:

```markdown
## Summary

- replaces mutable processing-run WCS state with an immutable solve result
- makes extraction, photometry, and field calibration accept explicit inputs
- moves catalog/network orchestration into tools and removes the automated batch exporter
- preserves the extracted numerical algorithms and their recorded parity behavior

## Validation

- `uv run --python 3.14 pytest -q`
- `uv run --python 3.14 python -m compileall tools algorithms`
- `npm run typecheck`
- `git diff --check`
- optional solver-data outcome recorded here

## Notes

- targets `dev` after PR #47
- no dependency or Python-version changes
- no source-extraction, photometry, matching, reference-band, plate-solver, or zero-point math changes
```

- [ ] **Step 8: Watch PR checks to completion**

Run:

```bash
gh pr checks --watch
```

Expected: Python tests, syntax, repository shape, actionlint, workflow safety, secret scan, and all other required checks pass before requesting merge.
