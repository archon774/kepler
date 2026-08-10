# WCS extraction from Skynet

Astrometric (WCS) calibration, lifted out of the Skynet monorepo into a
standalone package. This is an **extraction, not a rewrite**: every algorithm,
numeric expression and comment is byte-identical to the source. The only edits
are import rewiring and severed infrastructure dependencies, each marked inline
with an `# EXTRACTED:` comment.

Source tree: `/home/claude/skynet` (read-only; nothing in it was modified).

Current package note: the copied Skylib files described below now live under
`kepler/skylib_lite/`; historical paths in this record describe the original
extraction layout.

---

## 1. What the code does

`wcs.solve_wcs()` is the entry point. Per frame it:

1. Extracts sources (`sep`-based detector) and keeps the brightest
   `max_sources`.
2. Derives coordinate hints, in strict priority order — explicit settings →
   header WCS centre → FITS pointing keywords (`OBJRA`/`TELRA`/`RA`, …) → an
   ICRS guess from the header. Every hint comes from the frame itself.
3. Derives an expected output parity from the header WCS determinant, then maps
   it per backend (the two backends read `SolveRequest.parity` in **opposite**
   conventions — see `_solve_request_parity_from_expected`).
4. Tries the **astrometry.net** backend (subprocess `solve-field` over an
   xylist), then falls back to the in-process **ATLAS** triangle solver (writes
   a temp FITS, blind triangle-invariant search against a local UCAC catalog).
5. Validates the candidate against expected parity and distance-from-hint
   (`_accept_solution`); a rejected solution is discarded and the next backend
   runs.
6. Records CRPIX/CRVAL/CD, derived scale/rotation/parity and pointing error,
   then strips stale WCS keywords and writes the accepted solution into the FITS
   header (preserving observation-time keywords).

---

## 2. Layout

```
wcs/
├── EXTRACTION.md            this file
├── __init__.py              package overview
├── wcs.py                   the pipeline
├── source_extraction.py     header-WCS construction + the source list
├── schemas.py               WCS-related settings / data objects
├── header_utils.py          pixel-scale + RA/Dec guesses from FITS keywords
├── config.py                SEAM: backend configuration (was Dynaconf)
├── state.py                 SEAM: plain objects for the ORM rows
└── skylib/                  vendored subset of Skynet's `skylib` package
    ├── astrometry/          the whole solver stack
    │   ├── main.py, types.py
    │   ├── anet/            astrometry.net subprocess backend (+ ngc2000.dat)
    │   └── atlas/           in-process triangle solver
    │       ├── catalog/     UCAC4 / UCAC5 zone readers
    │       ├── extract/     the ATLAS backend's own scipy extractor
    │       ├── match/       triangle invariants + kd-tree
    │       ├── solve/       blind (triangle) and oriented (offset-vote) solvers
    │       └── wcs/         similarity → WCS construction
    ├── extraction/          the `sep`-based detector (anet path source list)
    ├── calibration/         `background` only (dependency of `extraction`)
    ├── util/                `angle`, `fits`
    └── io/                  `fits_compression` (science-HDU selection)
```

---

## 3. Exact provenance

All source paths are relative to `/home/claude/skynet/packages/py/`.
"Lines" is the destination file's line count; where it differs from the source,
the delta is the marked import rewiring and/or a provenance header.

### 3.1 Pipeline (from `skynet-db`)

| Destination | Source | Src lines | Dst lines | Change |
|---|---|---|---|---|
| `wcs.py` | `skynet-db/skynet_db/runners/observation_asset_processing/optical_data_processing/wcs.py` | 932 | 957 | imports + 8-line provenance header only |
| `source_extraction.py` | `.../optical_data_processing/source_extraction.py` | 310 | 330 | imports + provenance header only |
| `header_utils.py` | `skynet-db/skynet_db/runners/utils.py` **lines 159–441** | 907 (whole file) | 315 | subset extraction; bodies verbatim |
| `schemas.py` | `skynet-db/skynet_db/runners/common/schemas.py` (subset) + `skynet-sdk/skynet_sdk/schemas/processing_settings.py` (`PlateSolveSettings` only) | 331 / 171 | 226 | subset; field definitions verbatim; base class replaced (§5.4) |
| `state.py` | modelled on `skynet-db/skynet_db/models/jobs/observation_asset_processing_run_details.py` and `.../observation_asset_processing_run.py` | 108 / — | 106 | rewritten as plain dataclasses (§5.2) |
| `config.py` | replaces `skynet-db/skynet_db/config.py` | — | 68 | new seam (§5.1) |

Functions taken from `runners/utils.py` into `header_utils.py`:
`_get_any`, `_binning_from_header`, `_arcsec_from_wcs`,
`_arcsec_from_direct_keywords`, `_arcsec_from_optics`,
`estimate_pixel_scale_arcsec_per_pix`, `_first_present`,
`_parse_ra_dec_values`, `_frame_from_header`, `guess_icrs_radec_from_header`.

Models taken from `runners/common/schemas.py` into `schemas.py`:
`Mag`, `IPhotometry`, `ISourceMeta`, `IAstrometry`, `IFwhm`, `ISourceId`,
`SourceExtractionSettings`, `SourceExtractionData`, `WcsCalibrationSettings`,
`ICatalogSource`, `CatalogSource`.

### 3.2 Solver stack (from `skylib`, source root `skylib/skylib/`)

Every file below is **byte-identical** to its source except where the "Change"
column says otherwise. `__init__.py` files with 0 lines are empty in both.

| Destination (`wcs/skylib/`) | Source (`skylib/skylib/`) | Lines | Change |
|---|---|---|---|
| `astrometry/__init__.py` | `astrometry/__init__.py` | 10 | — |
| `astrometry/main.py` | `astrometry/main.py` | 186 | — |
| `astrometry/types.py` | `astrometry/types.py` | 161 | — |
| `astrometry/anet/__init__.py` | `astrometry/anet/__init__.py` | 47 | — |
| `astrometry/anet/backend.py` | `astrometry/anet/backend.py` | 470 (src 468) | 1 import → relative |
| `astrometry/anet/config.py` | `astrometry/anet/config.py` | 35 | — |
| `astrometry/anet/engine.py` | `astrometry/anet/engine.py` | 225 | — |
| `astrometry/anet/errors.py` | `astrometry/anet/errors.py` | 162 | — |
| `astrometry/anet/ngc2000.dat` | `astrometry/anet/ngc2000.dat` | 1 282 922 bytes | — (binary-identical data file) |
| `astrometry/atlas/__init__.py` | `astrometry/atlas/__init__.py` | 4 | — |
| `astrometry/atlas/backend.py` | `astrometry/atlas/backend.py` | 193 (src 192) | 1 import → relative |
| `astrometry/atlas/config.py` | `astrometry/atlas/config.py` | 83 | — |
| `astrometry/atlas/catalog/__init__.py` | same | 42 | — |
| `astrometry/atlas/catalog/ucac4.py` | same | 133 | — |
| `astrometry/atlas/catalog/ucac5.py` | same | 301 | — |
| `astrometry/atlas/extract/__init__.py` | same | 0 | — |
| `astrometry/atlas/extract/sources.py` | same | 456 (src 454) | 1 import → relative |
| `astrometry/atlas/match/__init__.py` | same | 0 | — |
| `astrometry/atlas/match/triangles.py` | same | 129 | — |
| `astrometry/atlas/solve/__init__.py` | same | 0 | — |
| `astrometry/atlas/solve/solver.py` | same | 935 (src 934) | 6 imports → relative |
| `astrometry/atlas/solve/oriented.py` | same | 374 (src 373) | 5 imports → relative |
| `astrometry/atlas/wcs/__init__.py` | same | 0 | — |
| `astrometry/atlas/wcs/build.py` | same | 49 | — |
| `extraction/__init__.py` | `extraction/__init__.py` | 8 | — |
| `extraction/main.py` | `extraction/main.py` | 381 | — |
| `extraction/centroiding.py` | `extraction/centroiding.py` | 315 | — |
| `calibration/background.py` | `calibration/background.py` | 76 | — |
| `util/angle.py` | `util/angle.py` | 60 | — |
| `util/fits.py` | `util/fits.py` | 211 | — |
| `io/fits_compression.py` | `io/fits_compression.py` | 181 | — |
| `__init__.py`, `util/__init__.py`, `io/__init__.py`, `calibration/__init__.py` | corresponding upstream files | 9 / 11 / 8 / 15 | upstream docstring kept; imports of non-vendored siblings dropped, noted inline |

Verification: `diff` between each vendored file and its source shows changed
lines **only** inside import blocks. The full tree byte-compiles, and every
module imports cleanly.

---

## 4. What was deliberately left behind

**`calc_solution` (`runners/utils.py` lines 469–603).** Named in the brief as a
candidate, but it is not astrometry — it is the **photometric zero-point /
limiting-magnitude solver**. It takes `list[PhotometryData]`, iterates a
weighted mean of `ref_mag - mag` with Chauvenet rejection and a `brenth` solve
for the intrinsic scatter, and returns `(m0, m0_error, sigma, limmag,
rej_percent)`. `wcs.py` does not import it and no WCS code path reaches it. It
belongs to the field-calibration / photometry extraction. Left in place. (Its
helper `_sigma_eq` and the `sind`/`cosd`/… trig shims at lines 445–471 go with
it.)

**The rest of `runners/utils.py`** — S3 asset download, worker temp paths, Vizier
cache pruning, compressed-FITS product writing, filter/ref-mag resolution,
`query_catalogs_for_image`. Infrastructure or other pipelines.

**Photometry / fieldcal models in `runners/common/schemas.py`** —
`PhotometrySettings`, `IAperture`, `Photometry`, `PhotometryData`, `Catalog`,
`PhotometricCalibrationSettings`, `FieldCalResult`, `ImageProperties`. Not
reachable from the solve.

**The rest of `skynet_sdk/schemas/processing_settings.py`** — reduction settings,
header cards, and the other per-stage product settings. Only `PlateSolveSettings`
(the two knobs `solve_wcs` actually reads) came across.

**SQLAlchemy models, sessions, S3 clients, the job/stage machinery.** See §5.2.

**Skynet's Dynaconf configuration layer.** See §5.1.

**`skynet_sdk.schemas.base.SkynetBaseModel` machinery** — camelCase alias
generator, the cross-SDK model/union rebuild registry, NaN-scrubbing serializer,
FastAPI schema-title stripping. Transport concern. See §5.4.

**Non-vendored `skylib` siblings** — `skylib.util.stats`, `skylib.util.overlap`,
`skylib.io.conversion`, and the bias/dark/flat/cosmic/cosmetic modules under
`skylib.calibration`. Not reachable from the solve.

**`build_pointing_seed()`** — already removed upstream (2026-08-03). The
explanatory comment block in `wcs.py` documenting *why* is preserved verbatim.

---

## 5. Infrastructure seams cut

Every seam is marked in the code with `# EXTRACTED: was <original symbol>`.

### 5.1 Configuration — `config.py`
- **Was:** `from skynet_db.config import settings` — a Dynaconf instance layered
  over `config/settings.toml` + `config/environments/dev.local.toml` with a
  `SKYNET_` env-var prefix.
- **Now:** `wcs/config.py` exposes a `SolverSettings` object with the same four
  attribute names the builders read (`ANET_INDEX_PATH`, `ATLAS_CATALOG_ROOT`,
  `ATLAS_CATALOG`, `ATLAS_TIMEOUT_S`), sourced from the environment.
- **Behaviour:** unchanged. `build_anet_config` / `build_atlas_config` read these
  only through `getattr(cfg, NAME, None)`, and both already handle `None` (anet
  logs a warning and disables itself; atlas returns `None`). Callers with their
  own config can pass any object to the builders or reassign `wcs.settings`.

### 5.2 ORM rows — `state.py`
- **Was:** `from skynet_db.models import ObservationAssetProcessingRun`
  (SQLAlchemy), whose `ensure_wcs_solution()` creates and `session.add()`s an
  `ObservationTaskAssetProcessingRunWcsSolution` row.
- **Now:** `state.ProcessingRun` / `state.WcsSolution`, plain dataclasses. The
  25 solution columns are reproduced 1:1 in name, order and `None` default; the
  `processing_run_id` primary key, the relationship and the `session.add()` are
  dropped as persistence-only. `ProcessingRun` keeps only the three members the
  solve touches (`id`, `observation_asset_id`, `wcs_solution`).
- **Preserved quirk:** `wcs._clear_wcs_solution_fields()` resets attribute names
  that do **not** all match the mapped columns — it clears `ra`, `dec`,
  `pixel_scale` and `rotation`, whereas the solve writes `ra_deg`, `dec_deg`,
  `pixel_scale_arcsec_per_px` and `rotation_deg`. On a SQLAlchemy instance,
  `setattr` of an unmapped name silently creates a throwaway instance
  attribute, so upstream those four clears are no-ops and the corresponding
  columns retain their previous values after a failed solve. `WcsSolution` is a
  plain (non-`slots`) dataclass **specifically so this reproduces exactly**
  rather than raising `AttributeError`. Not fixed — reported here.

### 5.3 Clock — `state.now()`
- **Was:** `from ..common import now`
  (`skynet_db.runners.observation_asset_processing.common`).
- **Now:** the same one-line `datetime.now(timezone.utc)`, in `state.py`.

### 5.4 Pydantic base — `schemas.py`
- **Was:** `from skynet_sdk.schemas import SkynetBaseModel`.
- **Now:** a local `SkynetBaseModel(BaseModel)` preserving the two behaviours the
  models rely on: `populate_by_name=True` (so `Field(alias=...)` fields still
  accept their Python names) and `from_attributes=True`. The dropped machinery
  (camelCase alias generation, model/union rebuild registry, NaN-scrubbing
  serializer, FastAPI title stripping) affects **serialization only** — no
  field, default or validator changed, so no numeric behaviour changed.

### 5.5 Import rewiring inside the vendored `skylib`
- **Was:** absolute `skylib.*` imports resolving to the installed package.
- **Now:** relative imports within `wcs/skylib/`, so the extraction does not
  depend on an installed `skylib`. Only import lines changed.
- `wcs/skylib/__init__.py` drops upstream's `from ._version import __version__`
  (no packaged version file here). The `util`, `io` and `calibration`
  `__init__.py` files keep their upstream docstrings and note which siblings were
  not vendored.

### 5.6 Not a seam — logging
`logging` is untouched throughout. The log lines are load-bearing diagnostics
(they record hints, parity, scale windows, accept/reject reasons and elapsed
time per backend), so they were left exactly as they are, including
`solver.py`'s module-level `logging.basicConfig(...)` call.

---

## 6. External dependencies

Required to import and run:

| Package | Why |
|---|---|
| `numpy` | everywhere |
| `astropy` | `io.fits`, `wcs.WCS`, `stats.sigma_clipped_stats`, `coordinates`, `table.Table`, `convolution`, `modeling` |
| `scipy` | `spatial.cKDTree` (matching), `ndimage` (ATLAS extractor), `optimize.leastsq` (centroiding) |
| `pydantic` (v2) | `schemas.py` |
| `sep` | the `sep`-based extractor + background estimation |
| `numba` | `@njit` in `skylib/util/angle.py` and `skylib/extraction/centroiding.py` — a **hard import-time** dependency of the whole `skylib.astrometry` package (upstream too: `astrometry/__init__.py` → `main` → `anet` → `backend` → `util.angle`) |

Optional:

| Package | Why |
|---|---|
| `photutils` | `Background2D` in `atlas/extract/sources.py::estimate_background_2d`; falls back to a flat global median if absent |
| `matplotlib` | debug source-overlay PNG only (`debug_overlay_path`) |

`scipy.spatial.cKDTree` has a pure-numpy fallback in
`atlas/match/triangles.py`, used automatically if scipy is missing — but scipy
is still needed elsewhere, so treat it as required.

### Non-Python

| Requirement | Why |
|---|---|
| `solve-field` binary (astrometry.net) | the anet backend. Resolved via explicit config → `SKYLIB_ASTROMETRYNET_SOLVE_FIELD` / `SKYLIB_ANET_SOLVE_FIELD` → `PATH`. Absent ⇒ `is_available()` is `False` and the solve falls through to ATLAS. |
| astrometry.net index files | `ANET_INDEX_PATH`, or `SKYLIB_ASTROMETRYNET_INDEX_PATH` / `SKYLIB_ANET_INDEX_ROOT`. Recognized layouts: `index-*.fits`, `<prefix>-index-*.fits` (UCAC5), suffixless `index-NNN` (TYCHO2). |
| UCAC4 or UCAC5 catalog on local disk | the ATLAS backend. `ATLAS_CATALOG_ROOT` (or `SKYLIB_UCAC5_ROOT`). UCAC5 accepts either the `u5z` zone directory or its parent; `build_atlas_config` normalizes a path ending in `u5z` to its parent. |
| `ngc2000.dat` | bundled at `skylib/astrometry/anet/ngc2000.dat`; drives globular-cluster core masking in `solve_field_glob`. Loaded by path relative to `engine.py`, so it must stay beside it. |

Both backends degrade to "unavailable" rather than failing, so the package
imports and `solve_wcs` runs (returning no solution) with none of the external
data installed.

---

## 7. Judgment calls

1. **`skylib/astrometry` was taken whole**, not just `main.py` + `types.py` as
   the brief listed. Those two files are dispatch and dataclasses; the actual
   algorithms live in `anet/` (subprocess driver, index discovery, structured
   errors, globular-cluster masking) and `atlas/` (triangle invariants,
   similarity fitting, coarse/tight/mid verification gates, the oriented
   offset-vote solver, catalog zone readers, WCS construction). Extracting only
   the two named files would have left the solver behind.

2. **`calc_solution` was excluded** despite being named in the brief. It is the
   photometric zero-point solver, not astrometry, and `wcs.py` does not import
   it. See §4. If it is wanted here anyway it is a self-contained copy of
   `runners/utils.py` lines 469–603 plus `_sigma_eq` and
   `skylib.util.stats.chauvenet`.

3. **`source_extraction.py` was taken whole**, though only
   `build_wcs_from_header`, `get_source_xy` and `perform_source_extraction` are
   imported by `wcs.py`. Splitting it would have meant editing `__all__` and
   fragmenting a cohesive module; `get_source_radec` came along unused.

4. **`skylib.extraction` (+ `skylib.calibration.background`) was vendored** even
   though it is a general-purpose `sep` detector shared with Skynet's photometry
   and fieldcal pipelines. It produces the star list the astrometry.net backend
   solves from, so leaving it out meant `wcs.wcs` could not be imported at all.
   Note this is the **anet path only** — the ATLAS backend runs its own
   self-contained scipy extractor
   (`skylib/astrometry/atlas/extract/sources.py`). If the photometry and
   fieldcal extractions land in sibling Kepler folders, this module will be
   duplicated across them; consolidating it into a shared package is a
   repo-level decision outside this extraction's scope.

5. **`skylib/io/fits_compression.py` was copied whole** (181 lines) though only
   `select_image_hdu` is reached. It is astropy+numpy only, self-contained, and
   splitting it would have gained nothing.

6. **`numba` was left as a hard dependency.** Making
   `skylib/util/angle.py`'s `@njit` optional would change how the numeric code
   is compiled and executed — a redesign, not an extraction.

7. **The `_clear_wcs_solution_fields` name mismatch was preserved, not fixed**
   (§5.2). It is an upstream behaviour that a plain-dataclass port could easily
   have converted into a crash or a silent behaviour change; `state.py` is
   shaped to reproduce it.

---

## 8. Verification performed

- `python -m compileall` over the whole tree: clean.
- `diff` of every vendored `skylib` file against its Skynet source: changes
  confined to import lines.
- `diff` of `wcs.py` and `source_extraction.py` against their sources: changes
  confined to the import block plus a provenance comment header.
- Import smoke test of all 41 modules (with `numba`/`sep`/`scipy` stubbed, since
  they are absent from this environment): every module imports, including
  `wcs.wcs`.
- Spot-checked behaviour: `WCS_REGEX` keyword matching, `_angular_sep_deg`,
  `_parse_ra_hours` / `_parse_dec_deg` sexagesimal parsing, `decompose_linear`,
  `wcs_from_similarity` → `_wcs_parity` round trip, `WcsCalibrationSettings` /
  `PlateSolveSettings` defaults, `build_anet_config` / `build_atlas_config`
  returning `None` when unconfigured, and `_clear_wcs_solution_fields` against
  `state.WcsSolution`.
- **Not** run: an end-to-end solve. That needs `solve-field` plus astrometry.net
  index files or a UCAC catalog on disk, none of which are present here.
