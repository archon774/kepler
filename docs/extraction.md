# Algorithm Extraction Records

This document consolidates the extraction records for every algorithm package under `algorithms/`.
The records were previously kept as one `EXTRACTION.md` file per package; this is now the authoritative master record.

Internal section references such as `§5.2` are local to the package section they appear in unless they explicitly name another section.

## Contents
- [WCS](#wcs)
- [Photometry](#photometry)
- [Field Calibration](#field-calibration)
- [Catalogs](#catalogs)
- [Query](#query)
- [HR Diagram / Isochrone Matching](#hr-diagram-isochrone-matching)
- [Light Curve](#light-curve)
- [Periodogram](#periodogram)

## WCS

_Former source: `algorithms/wcs/EXTRACTION.md`._

### WCS extraction from Skynet

Astrometric (WCS) calibration, lifted out of the Skynet monorepo into
`algorithms/wcs/`. This is an **extraction, not a rewrite**: every algorithm,
numeric expression and comment is byte-identical to the source. The only edits
are import rewiring and severed infrastructure dependencies, each marked inline
with an `# EXTRACTED:` comment.

Source tree: `/home/claude/skynet` (read-only; nothing in it was modified).

Current package note: the copied Skylib files described below now live under
`algorithms/skylib_lite/`; historical paths in this record describe the original
extraction layout.

---

#### 1. What the code does

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

#### 2. Layout

```
algorithms/wcs/
├── __init__.py              package overview
├── wcs.py                   the pipeline
├── source_extraction.py     header-WCS construction + the source list
├── schemas.py               WCS-related settings / data objects
├── header_utils.py          pixel-scale + RA/Dec guesses from FITS keywords
├── config.py                SEAM: backend configuration (was Dynaconf)
└── state.py                 SEAM: plain objects for the ORM rows
algorithms/skylib_lite/
├── astrometry/              the whole solver stack
│   ├── main.py, types.py
│   ├── anet/                astrometry.net subprocess backend (+ ngc2000.dat)
│   └── atlas/               in-process triangle solver
│       ├── catalog/         UCAC4 / UCAC5 zone readers
│       ├── extract/         the ATLAS backend's own scipy extractor
│       ├── match/           triangle invariants + kd-tree
│       ├── solve/           blind (triangle) and oriented (offset-vote) solvers
│       └── wcs/             similarity -> WCS construction
├── extraction/              the `sep`-based detector (anet path source list)
├── calibration/             `background` only (dependency of `extraction`)
├── util/                    `angle`, `fits`
└── io/                      `fits_compression` (science-HDU selection)
```

---

#### 3. Exact provenance

All source paths are relative to `/home/claude/skynet/packages/py/`.
"Lines" is the destination file's line count; where it differs from the source,
the delta is the marked import rewiring and/or a provenance header.

##### 3.1 Pipeline (from `skynet-db`)

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

##### 3.2 Solver stack (from `skylib`, source root `skylib/skylib/`)

Every file below is **byte-identical** to its source except where the "Change"
column says otherwise. `__init__.py` files with 0 lines are empty in both.

| Destination (`algorithms/skylib_lite/`) | Source (`skylib/skylib/`) | Lines | Change |
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

#### 4. What was deliberately left behind

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

#### 5. Infrastructure seams cut

Every seam is marked in the code with `# EXTRACTED: was <original symbol>`.

##### 5.1 Configuration — `config.py`
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

##### 5.2 ORM rows — `state.py`
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

##### 5.3 Clock — `state.now()`
- **Was:** `from ..common import now`
  (`skynet_db.runners.observation_asset_processing.common`).
- **Now:** the same one-line `datetime.now(timezone.utc)`, in `state.py`.

##### 5.4 Pydantic base — `schemas.py`
- **Was:** `from skynet_sdk.schemas import SkynetBaseModel`.
- **Now:** a local `SkynetBaseModel(BaseModel)` preserving the two behaviours the
  models rely on: `populate_by_name=True` (so `Field(alias=...)` fields still
  accept their Python names) and `from_attributes=True`. The dropped machinery
  (camelCase alias generation, model/union rebuild registry, NaN-scrubbing
  serializer, FastAPI title stripping) affects **serialization only** — no
  field, default or validator changed, so no numeric behaviour changed.

##### 5.5 Import rewiring inside the vendored `skylib`
- **Was:** absolute `skylib.*` imports resolving to the installed package.
- **Now:** imports resolve through `algorithms.skylib_lite`, so the extraction
  does not depend on an installed `skylib`. Only import lines changed.
- `algorithms/skylib_lite/__init__.py` drops upstream's
  `from ._version import __version__` (no packaged version file here). The
  `util`, `io` and `calibration`
  `__init__.py` files keep their upstream docstrings and note which siblings were
  not vendored.

##### 5.6 Not a seam — logging
`logging` is untouched throughout. The log lines are load-bearing diagnostics
(they record hints, parity, scale windows, accept/reject reasons and elapsed
time per backend), so they were left exactly as they are, including
`solver.py`'s module-level `logging.basicConfig(...)` call.

---

#### 6. External dependencies

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

##### Non-Python

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

#### 7. Judgment calls

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

#### 8. Verification performed

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

## Photometry

_Former source: `algorithms/photometry/EXTRACTION.md`._

### Photometry extraction record

Source: `/home/claude/skynet` (read-only). Current destination:
`/home/claude/Kepler/algorithms/photometry/`, with shared Skylib code in
`/home/claude/Kepler/algorithms/skylib_lite/`.

This is a **verbatim extraction**, not a port. Every algorithm, constant, comment,
and numeric quirk is preserved exactly as it was in Skynet. The only edits are
import rewiring and the removal of hard dependencies on Skynet's ORM and
plate-solving stage, each marked in-place with an `# EXTRACTED:` comment.

Current package note: the copied Skylib files described below now live under
`algorithms/skylib_lite/`; historical paths in this record describe the original
extraction layout.

---

#### 1. Layout

```
algorithms/photometry/
├── __init__.py            new
├── pipeline/              the observation-asset processing stage (orchestration)
│   ├── __init__.py        new
│   ├── photometry.py      edited: 3 seams
│   ├── source_extraction.py  edited: 2 seams
│   └── schemas.py         subset + base-model shim
algorithms/skylib_lite/    vendored algorithmic core (all files byte-identical)
├── photometry/{__init__,aperture,aperture_numba,exposure}.py
├── extraction/{__init__,main,centroiding}.py
├── calibration/{__init__,background}.py
└── util/{__init__,overlap,stats,angle,fits}.py
```

`pipeline/` orchestrates; `algorithms/skylib_lite/` does the math. The split
mirrors the original package boundary (`skynet-db` runner vs. the `skylib`
library).

---

#### 2. What was copied

##### 2.1 Vendored skylib — byte-identical, zero edits

Verified with `diff -q` against the source after copying. All paths below are
relative to `/home/claude/skynet/packages/py/skylib/skylib/`.

| Source | Lines | Destination |
|---|---:|---|
| `photometry/aperture.py` | 570 | `algorithms/skylib_lite/photometry/aperture.py` |
| `photometry/aperture_numba.py` | 873 | `algorithms/skylib_lite/photometry/aperture_numba.py` |
| `photometry/exposure.py` | 647 | `algorithms/skylib_lite/photometry/exposure.py` |
| `photometry/__init__.py` | 5 | `algorithms/skylib_lite/photometry/__init__.py` |
| `extraction/main.py` | 381 | `algorithms/skylib_lite/extraction/main.py` |
| `extraction/centroiding.py` | 315 | `algorithms/skylib_lite/extraction/centroiding.py` |
| `extraction/__init__.py` | 8 | `algorithms/skylib_lite/extraction/__init__.py` |
| `calibration/background.py` | 76 | `algorithms/skylib_lite/calibration/background.py` |
| `util/overlap.py` | 385 | `algorithms/skylib_lite/util/overlap.py` |
| `util/stats.py` | 772 | `algorithms/skylib_lite/util/stats.py` |
| `util/angle.py` | 60 | `algorithms/skylib_lite/util/angle.py` |
| `util/fits.py` | 211 | `algorithms/skylib_lite/util/fits.py` |
| `util/__init__.py` | 8 | `algorithms/skylib_lite/util/__init__.py` |

**3,311 lines, unmodified.** Their intra-package relative imports
(`from ..calibration.background import ...`, `from ..util.stats import ...`,
`from .aperture_numba import ...`) resolve unchanged inside the vendored tree —
that is why the skylib directory layout was preserved rather than flattened.

`skylib/__init__.py` and `skylib/calibration/__init__.py` are the only two new
files in that tree; the originals pulled in `_version.py` and the bias/dark/flat
calibration modules respectively, neither of which came along.

Modules that came along but are **not on the photometry call path**:

- `photometry/exposure.py` — exposure-time calculator, sky-brightness model
  (Henyey–Greenstein scattering), Planck's law, CCM dust extinction. In the
  `skylib.photometry` package and squarely algorithmic, so it was pulled in as
  instructed, but nothing in `pipeline/` calls it. Its only internal dependency
  is `util/angle.airmass_for_el`.
- `util/angle.py` `angdist` / `average_radec`, `util/fits.py` `get_fits_fov`,
  `util/stats.py` `chauvenet2*` / `chauvenet3*` / `chauvenet` / `stddev2` /
  `stddev3`. These files were taken whole rather than sliced: they are
  self-contained (numpy + numba + astropy only) and cutting them apart would
  have risked silently changing behavior for no benefit.

##### 2.2 Pipeline stage

| Source (under `skynet/packages/py/skynet-db/skynet_db/`) | Lines | Destination | Lines |
|---|---:|---|---:|
| `runners/observation_asset_processing/optical_data_processing/photometry.py` | 264 | `pipeline/photometry.py` | 289 |
| `runners/observation_asset_processing/optical_data_processing/source_extraction.py` | 310 | `pipeline/source_extraction.py` | 319 |
| `runners/common/schemas.py` (subset) | 331 total | `pipeline/schemas.py` | 311 |

The growth in the first two files is entirely `# EXTRACTED:` comment blocks. No
executable line was altered other than the import statements and the two
parameter annotations listed in §3.

`pipeline/schemas.py` takes these classes verbatim from `runners/common/schemas.py`:
`IPhotometry` (19–28), `IAperture` (31–40), `PhotometrySettings` (43–60),
`ISourceMeta` (63–68), `IAstrometry` (71–86), `IFwhm` (89–92), `ISourceId` (95–96),
`SourceExtractionSettings` (98–126), `SourceExtractionData` (129–157),
`Photometry` (176–192), `PhotometryData` (195–240). `Photometry` is not called by
the extracted code; it is kept because it documents the unit-suffixed output
names (`flux_err_counts`, `magnitude_err_mag`) that `run_photometry` translates
the skylib columns into.

---

#### 3. Infrastructure seams cut

Every seam is marked in the source with `# EXTRACTED: was <original symbol>`.

| # | File | Cut | Consequence |
|---|---|---|---|
| 1 | `pipeline/photometry.py`, `pipeline/source_extraction.py` | `from skylib...` (installed package) -> `from algorithms.skylib_lite...` (shared vendored copy) | None. Same code. |
| 2 | `pipeline/source_extraction.py` | `from skynet_db.models import ObservationAssetProcessingRun`; the `processing_run:` annotation on `perform_source_extraction` | None. The body already read the run duck-typed (`getattr(processing_run, "observation_asset_id", None)`); only the SQLAlchemy type annotation was dropped. |
| 3 | `pipeline/photometry.py` | Same ORM import + annotation on `perform_photometry` | None on the returned values. |
| 4 | `pipeline/photometry.py` | `from .wcs import build_wcs_from_header` -> `from .source_extraction import build_wcs_from_header` | None. Not a reimplementation: `wcs.py` itself does `from .source_extraction import build_wcs_from_header`, so this is the identical function imported from its point of definition. Avoids dragging in the astrometry.net/ATLAS plate-solving stage (which belongs to `algorithms/wcs/`). |
| 5 | `pipeline/photometry.py` | `build_wcs_for_processing_run(processing_run, header)` → `build_wcs_from_header(header)` | **Behavioral.** The original (`optical_data_processing/wcs.py:151`) is `build_wcs_from_header(header) or build_wcs_from_processing_run_solution(processing_run)`. The first term is kept; the second reconstructs a WCS from the plate solution persisted on the ORM row. If the FITS header carries no celestial WCS, `wcs` is now `None` where Skynet could still have recovered one from the database. Affects `perform_photometry()` only — `run_photometry()`, the numeric entry point, is untouched. |
| 6 | `pipeline/photometry.py` | `processing_run.ensure_photometry()` / `photometry_state.zero_point_mag = ...` | None on the returned values. Pure ORM job-state persistence; `settings.zero_point_mag` is already folded into each magnitude by `PhotometryData.from_source_and_row()`. |
| 7 | `pipeline/schemas.py` | `from skynet_sdk.schemas import SkynetBaseModel` → local base class | See below. |

##### Seam 7 in detail

`SkynetBaseModel` (`skynet-sdk/skynet_sdk/schemas/base.py:139`) carries FastAPI /
OpenAPI / SQLAlchemy plumbing — the module imports `sqlalchemy`,
`sqlalchemy_utils`, and `annotated_types` at load time, so it cannot even be
imported without a database stack installed. Two of its behaviors are load-bearing
for photometry and were reproduced verbatim:

- **`model_config`** — `alias_generator=to_camel` (base.py:85–103), plus
  `populate_by_name`, `from_attributes`, `use_enum_values`. Required because the
  pipeline constructs and round-trips these models by snake_case field name while
  `IPhotometry.flux_error` / `mag_error` rely on their *explicit* aliases
  (`flux_err_counts` / `magnitude_err_mag`) matching the columns
  `run_photometry()` renames the skylib output to.
- **`_clean_nans` wrap serializer** (base.py:122–130, 176–178) — converts NaN/Inf
  floats to `None` on every `model_dump()`. This is numeric behavior, not JSON
  cosmetics: `PhotometryData.from_source_and_row()` calls
  `source.model_dump(exclude_unset=True)`.

Dropped as pure infrastructure: `model_registry` / `union_registry` /
`rebuilt_models` class registries and `rebuild_all_models()` /
`register_union()` / `get_registered_models()` / `clear_registry()`; the
`_strip_schema_titles` `json_schema_extra` hook; and the
`protected_namespaces=("protect_me_", "also_protect_")` config entry. All exist
to serve Skynet's generated API schema.

Verified after extraction: settings construction and `model_copy(update=...)`,
`from_source_and_row` (including `zero_point_mag` folding and the annulus
derivation `annulus_b_in = aper_a_in * aper_b_out / aper_a_out`), NaN→None on
dump, and camelCase alias generation with the two explicit aliases surviving.

##### What was *not* cut

`logging` was left exactly as-is in `pipeline/photometry.py` (module logger, six
`logger.info` calls) and the `print(f"[source_extraction] ...")` diagnostic in
`run_source_extraction` was left in place. These are stdlib, carry no Skynet
dependency, and removing them would have been a rewrite.

---

#### 4. What was left behind, and why

| Left in Skynet | Reason |
|---|---|
| `optical_data_processing/wcs.py` (932 lines) | Astrometric plate solving (astrometry.net + ATLAS backends). Belongs to `algorithms/wcs/`. Only `build_wcs_from_header` was needed, and it is defined in `source_extraction.py`, which did come along. |
| `optical_data_processing/field_cal.py` (701 lines) | Photometric zero-point / field calibration. Belongs to `algorithms/fieldcal/`. **See §6 — it holds one of the legacy-parity behaviors.** |
| `optical_data_processing/catalog_query.py`, `catalogs/` | Catalog access. Belongs to `algorithms/catalogs/` and `algorithms/query/`. |
| `optical_data_processing/reduce.py`, `validate.py`, `batch_wcs_photometry_zeropoint_export.py` | Image reduction, validation harness, batch export driver. Not photometric math. |
| `optical_data_processing/test-photometry.py` (110 lines) | See §5. |
| `skylib/calibration/{bias,dark,flat,cosmic,cosmetic}.py` | Pre-photometry image calibration; not reachable from the photometry path. |
| `skylib/{astrometry,catalogs,combine,color,enhancement,ephem,io,quality,sonification}/` | Unrelated to photometry. |
| `runners/common/schemas.py`: `Mag`, `WcsCalibrationSettings`, `ICatalogSource`, `CatalogSource`, `Catalog`, `PhotometricCalibrationSettings`, `FieldCalResult`, `ImageProperties` | Other pipeline stages / other Kepler modules. |
| `skynet_db.models`, `skynet_db.config`, `runners/utils.py`, `runners/common` job machinery | ORM, S3, job-state. The seams above. |

---

#### 5. `test-photometry.py` — not brought along

**Judgment: not a useful reference test; do not port it.** It is a scratch driver,
not a test:

- No assertions and no expected values. `main()` falls off the end returning
  `None`, so `sys.exit(main())` always exits 0 — it cannot fail.
- It does not exercise photometry directly. It calls `solve_wcs()` then
  `perform_field_calibration()`, i.e. it is a *field-calibration* driver that
  reaches photometry only transitively.
- It depends on the ORM (`ObservationAssetProcessingRun`) and on the astrometry
  and fieldcal stages — all three of which are outside this extraction.
- Its fixture path is stale. It looks for
  `../skynet-data/pipeline_data/test_subjects/bvr/ngc_3628_hamburer_test_12499172_V_0003_reduced.fits`;
  that tree has since been reorganized to `test_subjects/optical/<category>/` and
  neither the `bvr/` directory nor that FITS file exists any more.

The one thing worth keeping from it is the known-good aperture configuration it
encodes, recorded here so it is not lost:

```python
PhotometrySettings(a=5, b=5, theta=0,
                   a_in_px=10, a_out_px=15, b_out_px=15,
                   theta_out_deg=0, centroid_radius=5)
```

For actual parity testing, the useful material is elsewhere and is **not** part of
this repo: `/home/claude/skynet-data/pipeline_data/afterglow_results/` holds
legacy Afterglow reference outputs (`photometry/afterglow_photometry (4).csv`,
`afterglow_web_values_*.csv`) alongside FITS subjects in
`test_subjects/optical/`. That is the ground truth the "legacy parity" comments
below are defending.

---

#### 6. Legacy Afterglow parity behaviors

These exist to reproduce a previous system's numeric output. All comments are
preserved verbatim. **Do not "clean these up".**

Preserved here:

| Location | Behavior |
|---|---|
| `pipeline/photometry.py:55` | `# Always recompute RA/Dec from current x/y — legacy parity (legacy always overwrote via wcs arg)` |
| `pipeline/photometry.py:237–238` | Build `PhotometryData` first, *then* apply WCS, so RA/Dec reflects the row's centroided pixel position — legacy parity. |
| `pipeline/schemas.py:279` | `# x/y from the row (post-centroid positions) override source positions — legacy parity` |
| `skylib/photometry/aperture.py:218` | `k = 0  # temporary fix for k = 0 not being allowed in AgA` — "AgA" is Afterglow Access. Clamps any automatic aperture factor ≤ 0.1 to 0, which then triggers the SNR-optimal aperture search. |

**No centroiding during field-calibration photometry** — this is realized by two
pieces that are both preserved: `PhotometrySettings.centroid_radius` defaults to
`0.0` (`pipeline/schemas.py`), and `run_photometry()` centroids only under
`if r_cent > 0:` (`pipeline/photometry.py:207`). `field_cal.py` does not override
`centroid_radius`, so calibration photometry runs uncentroided by default.

**`apcorr_tol=0` during calibration** — ⚠️ this one is **outside this extraction**.
It lives at `field_cal.py:612`:

```python
cal_phot_settings = phot_settings.model_copy(update={"apcorr_tol": 0.0})
```

Whoever extracts Kepler `fieldcal/` must carry that line across. Its effect is
here, in `skylib/photometry/aperture.py`: `apcorr_tol > 0` gates both the
growth-curve aperture-correction block (line 426) and the annulus-parameter setup
(lines 276, 374), so `0` disables aperture correction entirely.

---

#### 7. The numba / plain relationship

**Correction to the briefing:** `aperture_numba.py` is *not* an accelerated
alternative to `aperture.py`. They are two layers of one implementation, and
`aperture.py` imports from `aperture_numba.py` unconditionally:

```python
from .aperture_numba import sum_circle, sum_ellipse, sum_circann, sum_ellipann, _sum_circle, _sum_ellipse
```

- **`aperture.py`** is the driver: aperture/annulus geometry, isophotal analysis,
  the SNR-optimal aperture search (`scipy.optimize.minimize` over
  `calc_flux_err`), flux-weighted medians for fixed aperture/ellipticity/rotation,
  background handling, ADU→electron conversion, magnitudes, and the growth-curve
  aperture correction. It calls the kernels below to sum pixels.
- **`aperture_numba.py`** is the pixel-summation kernel layer — a Numba port of
  SEP's `sum_circle` / `sum_circann` / `sum_ellipse` / `sum_ellipann`.

So the "plain implementation" that the numba module parallels is the **`sep` C
library**, not another file in this tree. Per its own module docstring, the port
differs from `sep` in three ways:

1. It always uses exact sub-pixel math (`subpix = 0`).
2. `sum_*()` returns `(flux, fluxerr, area, flags)` — SEP returns
   `(flux, fluxerr, flags)`. The extra `area` is what lets `aperture.py` compute
   aperture and annulus areas that correctly account for masked pixels and image
   edges, instead of using analytic ellipse areas.
3. It adds optional background outlier rejection (`reject_outliers=True`), which
   SEP has no equivalent for: it least-squares fits a plane to the annulus pixels
   and iteratively drops Chauvenet outliers from the residuals
   (`util/stats.chauvenet1`).

There is **no non-numba fallback path**. `numba` is a hard runtime requirement for
aperture photometry, not an optional accelerator.

Internal structure worth knowing before touching the file: `sum_aper_factory()`
generates a *pair* of jitted kernels per aperture shape — `_sum_aper` and
`_sum_aper_reject` — from six small `@njitc(inline='always')` shape callbacks
(`_aper_init_*`, `_aper_boxextent_*`, `_aper_rpix2_*`, `_aper_compare1_*`,
`_aper_compare2_*`, `_aper_exact_*`). Exact pixel/aperture overlap comes from
`util/overlap.py` (`circoverlap`, `ellipoverlap`), a Numba port of the
Robitaille/Barbary exact-overlap code. The factory-produced kernels are compiled
`cache=False` (closures are not cacheable); everything else uses the `njitc`
default of `cache=True`.

`sep` is still required — for `sep.Background` (`calibration/background.py`),
`sep.extract` (`extraction/main.py`), `sep.winpos` (`centroiding.py`), and the
`sep.APER_*` / `sep.OBJ_*` flag constants.

---

#### 8. Preserved oddities

Verbatim extraction means these came across unchanged. Several look like bugs.
They are recorded, **not fixed** — any of them may be load-bearing for numeric
parity with legacy output.

1. `skylib/photometry/aperture_numba.py:537` — `_aper_init_ellipann` validates
   `if aper[3] > aper[3]:`, comparing a value to itself. Presumably meant
   `aper[3] > aper[4]` (inner > outer radius). The check is dead.
2. `skylib/photometry/aperture_numba.py:307` — `_sum_aper_reject` indexes the mask
   box-relative (`mask[iy - ymin, ix - xmin]`) while `_sum_aper` at line 212
   indexes it absolutely (`mask[iy, ix]`). Reached only with
   `reject_outliers=True` and a non-`None` mask.
3. `skylib/extraction/centroiding.py:305` — in the `method='win'` all-good branch,
   `y[:] = y + 1` uses the input `y` rather than the windowed result `y1`.
   Unreached on this pipeline path: `run_photometry` calls `centroid_sources`
   with the default `method='iraf'`.
4. `skylib/extraction/main.py:257–261` — the "Make sure that a >= b" block assigns
   through `sources[s][...]` where `s` is a boolean mask. Boolean indexing returns
   a copy, so those three statements are no-ops. The adjacent
   `sources['theta'] %= np.pi` (line 260) is a field view and does take effect.
5. `skylib/extraction/main.py:105–106, 280–286` — the `centroid` parameter is
   documented as using "the windowed algorithm (SExtractor's XWIN_IMAGE,
   YWIN_IMAGE)" but the code calls `centroid_iraf` / `centroid_iraf_masked`. The
   comment at line 281 (`# Centroid sources using IRAF-like method`) matches the
   code; the docstring does not.
6. `skylib/photometry/aperture.py:542–545` — a `background_rms` column is appended
   to the output record array but never assigned, so it stays 0. (The docstring
   lists it as an output field.)
7. `skylib/util/stats.py:292` — a second `from numba import njit` mid-module,
   immediately before `chauvenet1 = njit(...)(chauvenet1py)`, with the comment
   "Compile WITHOUT parallel=True to avoid parfors entirely". Redundant but
   harmless; the comment records a real constraint.

---

#### 9. External dependencies

Required by the extracted code:

| Package | Used for |
|---|---|
| `numpy` | Everywhere. Record arrays (`numpy.lib.recfunctions.append_fields`), masked arrays. |
| `scipy` | `optimize.minimize` (optimal aperture), `optimize.leastsq` (PSF centroiding), `ndimage.gaussian_filter` (downsample prefilter); `optimize.fsolve` / `least_squares` and `special.erf` in `exposure.py`. |
| `numba` | **Hard requirement.** All aperture summation kernels, exact overlap, centroiding, Chauvenet rejection, isophotal analysis. No pure-Python fallback exists. |
| `astropy` | `wcs.WCS`, `io.fits.Header`, `stats.gaussian_fwhm_to_sigma` / `gaussian_sigma_to_fwhm`, `convolution.Gaussian2DKernel` / `Kernel2D`, `modeling.models.Gaussian2D`; `time.Time` and `coordinates.*` in `exposure.py`. |
| `sep` | `Background`, `extract`, `winpos`, and the `APER_*` / `OBJ_*` flag constants. |
| `pydantic` (v2) | `pipeline/schemas.py` settings and data objects; `pydantic.alias_generators.to_pascal` backs the local `to_camel`. |

**Optional / lazy:**

| Package | Used for |
|---|---|
| `photutils` | Imported *inside* `skylib/extraction/main.py: histogram()` and only when called with `bins='background'` (`Background2D`, `ModeEstimatorBackground`, `MADStdBackgroundRMS`). The photometry path never passes that argument — `auto_sat_level()` calls `histogram(data, bins=16)` — so `photutils` is not needed unless that branch is used. |

**Not required** (severed): `sqlalchemy`, `sqlalchemy_utils`, `skynet_db`,
`skynet_sdk`, `annotated_types`, and anything S3 or job-runner related.

`astropy.coordinates.NonRotationTransformationWarning` (imported by
`exposure.py`) requires a reasonably recent astropy; note that `exposure.py` is
not on the photometry call path if that import proves inconvenient.

---

#### 10. Verification performed

- `diff -q` against source for all 13 vendored skylib files — byte-identical.
- `python3 -m compileall` over the whole tree — clean.
- Import-graph audit: no `skynet_db`, `skynet_sdk`, or absolute `skylib` imports
  remain outside `# EXTRACTED:` comments.
- `pipeline/schemas.py` executed and exercised (settings construction,
  `model_copy(update={"apcorr_tol": 0.0})`, `from_source_and_row` with
  `zero_point_mag`, annulus derivation, NaN→None dump, alias generation).

**Not** verified: no end-to-end numeric run was possible in this environment —
`scipy`, `numba`, `sep`, and `photutils` are not installed here. The vendored
skylib files are byte-identical to their source, so no numeric drift can have
been introduced there; the untested surface is limited to the import rewiring in
`pipeline/`.

## Field Calibration

_Former source: `algorithms/fieldcal/EXTRACTION.md`._

### Field calibration — extraction record

Photometric zero-point calibration, extracted from the Skynet optical
data-processing pipeline (`/home/claude/skynet`) into `algorithms/fieldcal/`.

This was an **extraction, not a rewrite**. Algorithms, numeric constants,
ordering and comments are verbatim. Every place a Skynet dependency was cut is
marked in-code with an `# EXTRACTED:` comment; this document is the index of
those seams.

Current package note: the copied Skylib utility files described below now live
under `algorithms/skylib_lite/`; historical paths in this record describe the
original extraction layout.

---

#### 1. What field calibration does

```
catalog sources (queried, or supplied by the caller)
  -> unique source-ID assignment
  -> variable-star rejection      (VSX proximity within variable_check_tol arcsec)
  -> source extraction            (optional; only if extraction_settings given)
  -> mutual nearest-neighbour match, detected sources <-> catalog sources
       (angular flat-sky arcsec mode when detections carry RA/Dec,
        otherwise WCS-projected pixel mode)
  -> aperture photometry on the matched sources, apcorr_tol forced to 0
  -> SNR window filter (min_snr / max_snr on 1/mag_error)
  -> reference-magnitude resolution per image FILTER
       (direct band -> filter_lookup alias -> colour expression -> gated fallback)
  -> max_stars trim (brightest N by ref_mag)
  -> zero-point solve: error-weighted mean of (ref_mag - mag) with an
     intrinsic-scatter term solved by brenth, iterated with Chauvenet rejection
  -> PHOT_M0 / PHOT_M0E / PHOT_CAL written into the FITS header
```

---

#### 2. Files copied — exact provenance

All source paths are relative to
`/home/claude/skynet/packages/py/skynet-db/skynet_db/runners/`
unless noted. `OPD/` abbreviates
`observation_asset_processing/optical_data_processing/`.

##### Core algorithm

| Kepler file | Lines | Source | Source lines | Fidelity |
|---|---|---|---|---|
| `field_cal.py` | 735 | `OPD/field_cal.py` | 701 (all) | Verbatim. Diff vs original is imports + 4 `deps.` call seams + 2 type annotations + the added parity annotation at the `apcorr_tol` line. No logic touched. |
| `solution.py` | 166 | `utils.py` | 468–603 (`_sigma_eq`, `calc_solution`) | **Byte-identical body** (verified by diff). |
| `ref_mag.py` | 217 | `utils.py` | 605–799 (`_SAFE_NAMES`, `_ALLOWED_TOKENS`, `_get_catalog_filter_lookup`, `_safe_eval_expr`, `_resolve_filter_lookup_candidate`, `_ref_mag_filter_token_candidates`, `resolve_ref_mag_for_filter`) | Verbatim (one blank line lost trailing whitespace). |
| `schemas.py` | 316 | `common/schemas.py` | field-cal subset of 331 | Verbatim per class; base model reduced (§4.1); catalog schemas re-exported from `algorithms/catalogs/` (§4.4). |
| `batch_wcs_photometry_zeropoint_export.py` | 195 | `OPD/batch_wcs_photometry_zeropoint_export.py` | 180 (all) | Verbatim except the repo-root discovery seam (§4.6). |
| `deps.py` | 130 | — | — | **New file.** Seam module only; contains no math. |
| `__init__.py` | 58 | — | — | **New file.** Public API surface. |

##### Catalog metadata — MOVED OUT

`fieldcal` no longer owns catalogs. What was `fieldcal/catalogs/` (13 files) and
`fieldcal/catalog_plugins.py` now lives in `algorithms/catalogs/`, and what was
`fieldcal/catalog_query.py` is `algorithms/query/selection.py`,
`algorithms/query/geometry.py` and `algorithms/query/runner.py`. Provenance for
all of it moved to the Catalogs and Query sections of this document.

The catalog *backends* severed by this extraction — the VizieR engine, SDSS's
SkyServer SQL, the SkyMapper constraint override, the astroquery cache layer —
have since been extracted into `algorithms/query/`, so the network path
described in §4.4 is no longer inert.

Field calibration now reads catalog metadata by importing `algorithms.catalogs`
directly (pure data, no network stack) and reaches the network through
`deps.query_catalogs`.

##### Vendored skylib subset (`algorithms/skylib_lite/`)

Byte-for-byte copies from `/home/claude/skynet/packages/py/skylib/skylib/`,
directory layout preserved under `algorithms/skylib_lite/` so nothing depends on
an installed `skylib`.

| Current file | Lines | Source |
|---|---|---|
| `algorithms/skylib_lite/util/stats.py` | 772 | `skylib/util/stats.py` (`chauvenet` — the rejection kernel) |
| `algorithms/skylib_lite/util/angle.py` | 60 | `skylib/util/angle.py` (`angdist`) |
| `algorithms/skylib_lite/util/fits.py` | 211 | `skylib/util/fits.py` (`get_fits_time`) |
| `algorithms/skylib_lite/util/__init__.py` | 8 | verbatim |
| `algorithms/skylib_lite/__init__.py` | 16 | rewritten header; `from ._version import __version__` dropped |

All three modules are self-contained (numpy / numba / astropy only, no
intra-skylib imports), so they were copied whole rather than sliced.

**Consolidation note:** the original extractions duplicated these files under
the WCS, photometry, and field-calibration folders. They now share the single
`algorithms/skylib_lite/` copy.

---

#### 3. What was left behind, and why

| Left in Skynet | Why |
|---|---|
| `skynet_db.models.ObservationAssetProcessingRun` | SQLAlchemy ORM row. Field calibration reads exactly two attributes off it. |
| `skynet_db.models.File`, S3 asset download (`_download_to_path`), `write_image_product_fits`, `get_worker_tmp_file_path` (`utils.py`) | Object storage / temp-file plumbing. Never reached from field calibration. |
| `skynet_sdk.schemas.SkynetBaseModel` registry (`model_registry`, `register_union`, `rebuild_all_models`) | FastAPI/SDK schema-generation infrastructure. |
| The other ~700 lines of `utils.py` (header parsing, pixel-scale estimation, RA/Dec guessing, trig helpers, DB session use) | Not field calibration. Only `calc_solution` and `resolve_ref_mag_for_filter` are reached. Its VizieR cache pruning, `query_catalogs_for_image` and WCS box helpers went to `algorithms/query/` — see the Query section of this document. |
| `OPD/photometry.py`, `OPD/source_extraction.py` | Photometry / SEP extraction — `algorithms/photometry/`. Reached via `deps`. |
| `OPD/wcs.py` (astrometry.net / ATLAS plate solving, 36 KB) | Plate solving — `algorithms/wcs/`. Reached via `deps`. |
| `OPD/catalogs/*`, the SDSS SQL backend | Catalogs and their query backends — now `algorithms/catalogs/` and `algorithms/query/`. See §6. |
| `common/schemas.py`: `WcsCalibrationSettings`, `Photometry`, `ImageProperties` | Not field-cal settings or results. |
| `skylib` beyond `util/{stats,angle,fits}.py` | Not reached from field calibration. |

---

#### 4. Every seam cut

Each is greppable in-code: `grep -rn "EXTRACTED" fieldcal/`.

##### 4.1 `SkynetBaseModel` → reduced base (`schemas.py`)

Dropped: the cross-package model/union registry. **Preserved because it is
behaviourally load-bearing:**

- `model_config` — `alias_generator=to_camel` + `populate_by_name=True` +
  `from_attributes=True` + `use_enum_values=True`. `field_cal.py` round-trips
  models through `model_dump()` / `Model(**mapping)` on *field* names
  constantly; dropping `populate_by_name` while keeping the alias generator
  would break every one of those.
- The `@model_serializer(mode="wrap")` `_clean_nans` hook — it converts NaN/inf
  floats to `None` on **every** `model_dump()`, not just JSON. Field calibration
  re-hydrates matched sources through `model_dump()`, so this is inside the
  numeric path. Verified still active: `PhotometryData(mag=nan).model_dump()["mag"] is None`.

##### 4.2 `ObservationAssetProcessingRun` → duck-typed `Any`

Two sites: `field_cal.perform_field_calibration` and
`field_cal._filter_variable_stars`.

Only `.id` (source-ID prefix + logging) and `.observation_asset_id` (used as
`file_id`) are read. `schemas.ProcessingRunRef` is a concrete stand-in for
standalone callers. The third upstream site was the catalog query entry point,
which never read the parameter at all; `algorithms/query/runner.py` drops it (§4.4).

##### 4.3 Cross-domain callables → `algorithms/fieldcal/deps.py`

| `deps` name | Was | Belongs in |
|---|---|---|
| `run_photometry` | `from .photometry import run_photometry` | `algorithms/photometry/` |
| `run_source_extraction` | `from .source_extraction import run_source_extraction` | `algorithms/photometry/` |
| `get_source_radec` | `from .source_extraction import get_source_radec` | `algorithms/photometry/` |
| `build_wcs_for_processing_run` | `from .wcs import build_wcs_for_processing_run` | `algorithms/wcs/` |
| `solve_wcs` | `from .wcs import solve_wcs` (batch driver only) | `algorithms/wcs/` |

Unassigned, each raises `FieldCalDependencyError` naming the original symbol.
Call sites use `deps.<name>(...)` rather than a `from .deps import <name>`
binding so late assignment works.

One behavioural note on `build_wcs_for_processing_run`: the Skynet original is
`build_wcs_from_header(header) or build_wcs_from_processing_run_solution(processing_run)`.
The second branch reconstructs a WCS from persisted DB rows and is ORM
persistence — it is not reproduced. A header-only implementation gives the
behaviour field calibration actually depends on.

##### 4.4 Catalog ownership → `algorithms/catalogs/` and `algorithms/query/`

Originally this extraction copied catalog metadata into `fieldcal/catalogs/` and
severed the query backends, so `query_box` / `query_circ` / `query_objects` /
`table_to_sources` raised. That is no longer the case: catalogs are their own
package and the backends are extracted.

What changed in `fieldcal`:

| Was | Now |
|---|---|
| `from .catalogs import CATALOGS` | `from algorithms.catalogs import CATALOGS` |
| `from .catalog_plugins import CATALOG_OPTIONS` | `from algorithms.catalogs import CATALOG_OPTIONS` |
| `from .catalog_query import query_catalogs_for_processing_run` | `deps.query_catalogs(...)` |
| `fieldcal.schemas` defined `CatalogSource`, `Mag`, ... | re-exported from `algorithms.catalogs.schemas` |

`deps.query_catalogs` is the one new seam, and unlike the other entries in
`deps.py` it has a **working default** — it lazily imports
`algorithms.query.runner.query_catalogs` on first call. So catalog fetching needs
no wiring, and `import algorithms.fieldcal` still pulls in no astroquery.
Override it to route queries elsewhere.

Two consequences worth noting:

* `CatalogSource` is now a single shared class. Previously `fieldcal` defined its
  own; a source produced by a query backend and a source `fieldcal` matched
  against were structurally identical but distinct types.
* `algorithms.fieldcal.__init__` no longer exports `catalog_supports_filter`,
  `select_catalogs_for_filter` or `query_catalogs_for_processing_run`. The first
  two are `algorithms.query.selection.catalog_supports_filter` and
  `algorithms.query.selection.select_catalogs_for_filter`; the third is
  `algorithms.query.runner.query_catalogs`, which drops the unused leading
  `processing_run` argument and the unused `header` / `data` arguments.

The three magnitude-math overrides — `LandoltCatalog.table_to_sources`,
`USNOB1Catalog.table_to_sources`, `VSXCatalog.table_to_sources` — were kept
throughout and are now live: the first two reach the real VizieR row mapper
through `super()` via the MRO that `algorithms/query/binding.py` constructs.

##### 4.5 `skylib` absolute imports → shared `skylib_lite` imports

`from skylib.util.{stats,angle,fits} import ...` →
`from algorithms.skylib_lite.util.{stats,angle,fits} import ...`. Mirrors the
pattern used by `algorithms/photometry/` and `algorithms/wcs/`.

##### 4.6 Repo-root discovery (batch driver)

`_find_repo_root()` walked ancestors looking for `packages/py/skynet-db`, then
derived `../skynet-data/pipeline_data`. That marker cannot exist in Kepler, so
the walk was replaced with `$KEPLER_PIPELINE_DATA_DIR` (default
`./pipeline_data`). Only *where the driver looks for data* changed; the batch
logic and every calibration setting literal are untouched.

---

#### 5. Deliberate parity behaviours preserved (do not "fix")

1. **`apcorr_tol` forced to 0** — `field_cal.py:612` (`:645` here):
   `phot_settings.model_copy(update={"apcorr_tol": 0.0})`. This is what disables
   aperture correction during calibration photometry; the aperture kernel in
   `algorithms/skylib_lite/photometry/aperture.py` gates its correction pass on
   `apcorr_tol > 0`. Restoring the caller's default
   (`1e-4`) silently switches aperture correction on and the zero point diverges
   from legacy Afterglow. Statement is verbatim; a parity comment was **added**
   by this extraction (the original carried none) and is labelled as such
   in-code.

2. **`strict_filter_parity` / `allow_preferred_band_fallback`** — the
   preferred-band fallback (`V`, `r'`, `g'`, `B`, `i'`, then any band) is a
   *non-legacy* Skynet behaviour. Legacy Afterglow skips such a source. The gate
   and both docstrings explaining it are verbatim.

3. **Direct-band-before-`filter_lookup` precedence** in
   `resolve_ref_mag_for_filter` — legacy Afterglow `field_cal_job.py` ordering,
   so a `B` image calibrates against catalog `B`, not an unrelated mapped band.

4. **`explicit_lookup_seen` early return** — once any explicit token matched a
   `filter_lookup` entry that failed to resolve, the function returns
   `(None, None)` without trying the `"*"` wildcard. Looks like a missed
   fallback; it is the legacy ordering. Preserved.

5. **Two divergent catalog registries** — `algorithms.catalogs.CATALOGS` (11
   catalogs) and `algorithms.catalogs.CATALOG_OPTIONS` (APASS + PanSTARRS). Both
   now live in `algorithms/catalogs/`; see the Catalogs section of this document
   §4. They are *not*
   duplicates and merging them would change numbers. `CATALOG_OPTIONS` carries
   `H_alpha` / `H_beta` aliases that `CATALOGS['APASS']` lacks; `CATALOGS`
   carries `Open`/`Clear`/`Lum` → `V` and the curriculum filter names that
   `CATALOG_OPTIONS` lacks. `resolve_ref_mag_for_filter` starts from
   `CATALOG_OPTIONS` and overlays the caller's lookup. Demonstrated live:
   for an APASS source, `H_alpha` resolves to `rprime` (via `CATALOG_OPTIONS`)
   while `Halpha` resolves to the Lupton R colour expression (via `CATALOGS`) —
   **different reference magnitudes for two spellings of the same filter.**
   Preserved verbatim; flagged here as a genuine latent oddity someone should
   decide about deliberately.

6. **Two divergent `Catalog.__init__` merge semantics** — preserved, and now
   documented in the Catalogs section of this document, §5.4.

7. **`background` / `background_rms` computed then discarded** —
   `perform_field_calibration` captures them from `run_source_extraction` and
   then passes `background=None, background_rms=None` to `run_photometry`,
   forcing photometry to re-estimate. Looks like a bug; it changes numeric
   output if "fixed". Preserved.

8. **VSX pydantic-coercion guards** — the `str(row['OID'])` cast and the
   `try/except (ValueError, AttributeError)` around the passband `setattr` in
   `VSXCatalog.table_to_sources`. Their inline comments record that regressions
   here get swallowed by `_filter_variable_stars`' bare `except Exception`,
   silently disabling variable-star rejection. Comments preserved verbatim.

9. **`_filter_variable_stars` swallows all exceptions** and returns the
   unfiltered list — a failed VSX query is indistinguishable from "no variables
   found". Preserved.

---

#### 6. Catalog-backend code — now extracted

This section previously listed catalog-backend code deliberately left behind.
All of it has since been extracted:

| Skynet source | Now in |
|---|---|
| `OPD/catalogs/vizier_catalogs.py` (352) | `algorithms/query/vizier.py` |
| `OPD/catalogs/config.py` (5) | `algorithms/query/config.py` |
| `OPD/catalogs/sdss_catalog.py` backend (~110) | `algorithms/query/sdss.py` |
| `OPD/catalogs/skymapper_catalog.py` override (~20) | `algorithms/query/skymapper.py` |
| `utils.py::prune_vizier_cache` (~27) | `algorithms/query/cache.py` |
| `utils.py::query_catalogs_for_image` (~105) | `algorithms/query/runner.py` |
| `common/catalog_plugins/*` | `algorithms/catalogs/catalog_options.py` |

One item from the original list is still outstanding. `OPD/catalogs/local/` — a
local catalog backend (`backend`, `config`, `engine`, `errors`, `health`,
`normalize`, `routing`) — is present in Skynet's working tree only as
`__pycache__`, with no `.py` sources. This extraction previously noted that
someone should establish whether the sources still exist.

**They do.** They are in Skynet's git history, deleted from the working tree but
recoverable from commits `a8241c83e` ("local-first PostGIS catalog backend for
the optical pipeline"), `9a6a5a6ad` and `fb643309f`. That backend routes queries
to a local PostGIS catalog instead of a remote provider, and it is the natural
second backend behind `algorithms/query/binding.py`. It was out of scope here, which covered
remote access only.

#### 7. External dependencies

Required:

- `numpy`
- `scipy` — `scipy.spatial.cKDTree` (source matching), `scipy.optimize.brenth`
  (intrinsic-scatter solve)
- `astropy` — `astropy.wcs.WCS`, `astropy.io.fits` (batch driver),
  `astropy.table.Table` (type hints on preserved `table_to_sources` overrides)
- `pydantic` v2 — `pydantic.alias_generators.to_camel`
- **`numba`** — *hard* import-time dependency of the vendored
  `algorithms/skylib_lite/util/{stats,angle}.py`. There is no non-numba fallback path;
  `chauvenet` and `angdist` are `@njit`-decorated at import.

Removed: `sqlalchemy`, `skynet_db`, `skynet_sdk`, `boto3`/S3, `astroquery`
(left with the catalog backends).

---

#### 8. Verification performed

- `python -m compileall fieldcal` — clean.
- Full package import (`import fieldcal`) succeeds.
- Both registries load; `CATALOGS` has all 11 entries, `CATALOG_OPTIONS` 2.
- `resolve_ref_mag_for_filter` exercised over `B`, `V`, `R`, `Halpha`,
  `H_alpha`, `Open`, `g'`, unknown — including the strict-parity path returning
  `(None, None)`.
- `catalog_supports_filter` / `select_catalogs_for_filter` return correct
  narrowing (`R` → `['APASS', '2MASS', 'SDSS']`).
- `calc_solution` recovers an injected zero point on synthetic data
  (`m0 = 21.3657` vs. true `21.37`) and rejects an injected 3-mag outlier;
  empty input returns `(nan, nan, nan, nan, 100.0)`.
- NaN-cleaning serializer confirmed active on `model_dump()`.
- `apcorr_tol` override confirmed: `1e-4` default → `0.0` after the
  `model_copy`.
- Byte-level diffs against every Skynet original confirm no algorithmic drift;
  `solution.py`'s body is byte-identical to `utils.py:468-603`.

**Caveat:** `scipy` and `numba` are not installed in this environment. The
runtime checks above ran against minimal stand-ins for
`scipy.spatial.cKDTree` / `scipy.optimize.brenth` and an identity `numba.njit`.
That validates structure, wiring and control flow — it is **not** a numeric
parity check of the compiled `chauvenet` or the `brenth` scatter solve. Those
need a real `scipy` + `numba` environment and reference FITS data.

## Catalogs

_Former source: `algorithms/catalogs/EXTRACTION.md`._

### Catalogs — extraction record

#### 1. What this package is

`catalogs/` is Kepler's answer to "what do we know about each photometric
catalog": band tables, colour transforms, VizieR table IDs, row limits, column
mappings, and the photometric conversions three catalogs apply to their rows.

It is declaration-only. No module here imports `astroquery` or opens a socket.
Reaching a provider is `query/`'s job, and `query/registry.py` is what a caller
wanting live catalogs imports. The split means filter matching, reference
magnitude resolution and the whole zero-point solve run without a network stack
installed.

Eleven catalogs: APASS, Landolt, PanSTARRS, SDSS, SkyMapper, Stetson, 2MASS,
Tycho-2, UCAC5, USNO-B1, VSX.

#### 2. Files copied — exact provenance

Upstream carried **two parallel catalog plugin packages** that had drifted apart.
Both are reproduced, because the drift is load-bearing (§4).

##### Primary registry — `CATALOGS`

From `skynet/packages/py/skynet-db/skynet_db/runners/observation_asset_processing/optical_data_processing/catalogs/`:

| Kepler file | Upstream file | Lines | Fidelity |
|---|---|---|---|
| `catalog.py` | `catalog.py` | 45 | Attribute set and `filter_lookup` merge preserved; docstrings rewritten, `table_to_sources` declared |
| `apass_catalog.py` | `apass_catalog.py` | 37 | Metadata verbatim |
| `landolt_catalog.py` | `landolt_catalog.py` | 83 | Metadata + `table_to_sources` transform verbatim |
| `panstarrs_catalog.py` | `panstarrs_catalog.py` | 43 | Metadata verbatim |
| `sdss_catalog.py` | `sdss_catalog.py` | 213 → 47 | Metadata verbatim; the ~110-line SkyServer backend moved to `query/sdss.py` |
| `skymapper_catalog.py` | `skymapper_catalog.py` | 58 → 43 | Metadata verbatim; `query_region` override moved to `query/skymapper.py` |
| `stetson_globs_catalog.py` | `stetson_globs_catalog.py` | 36 | Metadata verbatim |
| `twomass_catalog.py` | `twomass_catalog.py` | 40 | Metadata verbatim |
| `tycho_catalog.py` | `tycho_catalog.py` | 27 | Metadata verbatim |
| `ucac_catalog.py` | `ucac_catalog.py` | 30 | Metadata verbatim |
| `usno_catalog.py` | `usno_catalog.py` | 63 | Metadata + `table_to_sources` transform verbatim |
| `vsx_catalog.py` | `vsx_catalog.py` | 105 | Metadata + `table_to_sources` verbatim, incl. two fixed defects (§5.3) |
| `__init__.py` | `__init__.py` | 87 | `_OCL_TO_V` and every `filter_lookup` overlay verbatim |

##### Secondary registry — `CATALOG_OPTIONS`

`catalog_options.py` merges four files from
`skynet/packages/py/skynet-db/skynet_db/runners/common/catalog_plugins/`:
`catalog.py` (45), `apass_catalog.py` (37), `panstarrs_catalog.py` (43),
`__init__.py` (49). Colour transforms and `NARROWBAND_FILTER_LOOKUP` verbatim.

##### Schemas and vocabulary

| Kepler file | Upstream | Notes |
|---|---|---|
| `schemas.py` | `skynet_db/runners/common/schemas.py` (331) — catalog subset | Field names, aliases and the NaN-stripping serializer preserved |
| `simbad.py` | `skynet/apps/public-api/public_api/services/target_search.py` lines 27–234 | 206-entry otype table, verbatim |

Afterglow's `afterglow_core/models/catalogs.py` and
`afterglow_core/resources/catalog_plugins/*` are the common ancestor of the
Skynet copies. Where the two disagreed, Kepler takes Skynet's — it is the
de-Flasked, more recently maintained fork — except where noted in
the Query section of this document, §3.

#### 3. What was renamed, and why

Kepler is a separate service. It records where code came from in these markers,
but does not present itself as Skynet or Afterglow, so identity-bearing names
were changed. Behaviour was not.

| Was | Now | Where |
|---|---|---|
| `SkynetBaseModel` | `KeplerBaseModel` | `schemas.py`; `fieldcal/schemas.py` aliases it |
| `Catalog` (Pydantic settings record) | `CatalogMeta` | `schemas.py` — freed the name for the plugin base class |
| `"""Afterglow Core: …"""` headers | `"""Kepler: …"""` | all eleven plugins |
| `# n_max to Skynet filter names` | `# VSX n_max band code -> Kepler band name` | `vsx_catalog.py` |

Numeric content — every colour transform, coefficient, band table, row limit and
VizieR ID — is untouched.

#### 4. The two registries are not redundant

`CATALOGS` (11 catalogs) and `CATALOG_OPTIONS` (APASS + PanSTARRS) both exist
upstream and both are read during calibration:

* `CATALOGS` drives filter-aware catalog selection and querying.
* `CATALOG_OPTIONS` is read only by `fieldcal.ref_mag.resolve_ref_mag_for_filter`.

They disagree, and the disagreement changes results. `CATALOG_OPTIONS['APASS']`
carries `H_alpha` and `H_beta` narrowband aliases that `CATALOGS['APASS']` does
not; `CATALOGS['APASS']` carries the `_OCL_TO_V` Open/Clear/Lum mappings that
`CATALOG_OPTIONS['APASS']` does not. Merging them would silently change which
reference band a narrowband or unfiltered image calibrates against.

Verified: `resolve_ref_mag_for_filter(image_filter="H_alpha", catalog_name="APASS")`
resolves to rprime — via `CATALOG_OPTIONS` only.

#### 5. Deliberate behaviours preserved (do not "fix")

##### 5.1 `CatalogSource` silently drops four VSX fields

`VSXCatalog.table_to_sources` constructs sources with `name`, `type`,
`amplitude` and `period`. `CatalogSource` declares none of them, and Pydantic's
default `extra='ignore'` drops them. Upstream behaves identically. Field
calibration uses VSX only for positional variable-star rejection, so nothing
reads those fields — but adding them would change what downstream consumers see.

##### 5.2 Landolt's U-magnitude error uses the wrong colour index

`landolt_catalog.py` computes the uncertainty on U as
`hypot(B_err, V_R_err)` where the colour algebra calls for `U_B`. The U
*magnitudes* are correct; only their reported uncertainty is wrong. Preserved as
upstream wrote it, and flagged inline.

##### 5.3 Two VSX defects were fixed upstream, and the fixes are kept

`vsx_catalog.py` carries inline notes on both: the `OID` integer is coerced to
`str` because `CatalogSource.id` is typed as a string, and the passband
assignment is wrapped in a `try`. Without either, a Pydantic validation error
propagates into `fieldcal.field_cal._filter_variable_stars`, which swallows it —
silently disabling variable-star rejection rather than failing. Regressing
these produces wrong zero points with no error.

##### 5.4 `catalog_options.py` mutates class-level dicts

Its `_MutatingCatalog.__init__` updates the *class* `filter_lookup` in place,
where `catalog.Catalog` rebinds an instance-level copy. Both upstreams did it
their respective ways. The merged content is identical for the two
single-instantiation classes involved; the aliasing difference is preserved
rather than normalized, and the classes are private to that module.

##### 5.5 `filter_lookup` may be absent entirely

`Catalog` annotates `filter_lookup` without assigning it, so a plugin declaring
no transforms (USNO-B1, Stetson) has no such attribute at all — not an empty
dict. Every reader uses `getattr(..., {})`. Upstream had the same shape.

#### 6. Dependencies

`pydantic` v2 only. Deliberately no `astroquery`, no `astropy` except
`astropy.table.Table` as a type hint on three `table_to_sources` overrides.

#### 7. Verification performed

Offline, against synthetic astropy tables — no live provider calls:

* All 11 catalogs import and register; `catalogs` imports without pulling
  `astroquery` into `sys.modules`.
* Landolt colour-index → UBVRI transform, including negative-declination
  sexagesimal parsing and the §5.2 error term.
* USNO-B1 B/R synthesis from the two survey epochs, and its single-epoch
  fallbacks.
* VSX constant-star rejection (`V not in (0,1)`), `OID` string coercion.
* APASS row mapping, the 99-magnitude null convention, and the
  drop-rows-with-no-magnitudes rule.
* Registry filter-lookup overlays survive backend binding.
* The §4 two-registry distinction, through `resolve_ref_mag_for_filter`.

Not verified: any live VizieR or SkyServer response. See the Query section of this document, §6.

## Query

_Former source: `algorithms/query/EXTRACTION.md`._

### Query — extraction record

#### 1. What this package is

`query/` is Kepler's remote catalog access layer. It owns every network call in
the catalog path: the VizieR engine, SDSS's SkyServer SQL backend, SIMBAD
identifier resolution, the astroquery response cache, and the orchestration that
turns "these catalogs, this field, this filter" into a list of `CatalogSource`.

It sits above `catalogs/`, which declares what each catalog contains and imports
nothing network-related. `query/` imports `catalogs/`; never the reverse.

#### 2. Files copied — exact provenance

| Kepler file | Upstream source | Lines | Fidelity |
|---|---|---|---|
| `vizier.py` | `afterglow_core/resources/catalog_plugins/vizier_catalogs.py` | 373 | Engine verbatim; Flask config → `config.py`; cache patch → `cache.py`; custom-catalog loop → a function |
| `sdss.py` | `afterglow_core/.../sdss_catalog.py` lines 19–100 + 3 overrides, and the Skynet copy | ~110 | SQL generation byte-identical |
| `skymapper.py` | `afterglow_core/.../skymapper_catalog.py` lines 39–58 | 20 | `query_region` override verbatim |
| `cache.py` | `vizier_catalogs.py` lines 27–72 + `skynet_db/runners/utils.py::prune_vizier_cache` lines 132–158 | ~60 | Two copies of the same idea, merged |
| `selection.py` | `skynet/.../optical_data_processing/catalog_query.py` lines 20–191 | 172 | Verbatim apart from the registry import |
| `geometry.py` | 4 sources, see below | ~200 | Verbatim |
| `runner.py` | `catalog_query.py` lines 251–436 + `runners/utils.py::query_catalogs_for_image` | ~240 | Verbatim; `processing_run` parameter dropped |
| `simbad.py` | `skynet/apps/public-api/public_api/services/target_search.py` lines 236–297 | ~60 | SIMBAD branch only; ORM branches severed (§4) |
| `config.py` | `catalogs/config.py` (5) + Afterglow's `current_app.config` reads | — | New seam module |

`geometry.py` merges four upstreams:

* `afterglow_core/models/catalogs.py::Catalog.query_box` lines 108–170 →
  `clip_sources_to_box`
* `afterglow_core/.../job_plugins/catalog_query_job.py` lines 140–215 →
  `boxes_from_wcs`, `combined_bounding_box`
* `catalog_query.py` lines 194–249 → `wcs_array_shape`, `boxes_from_wcs`,
  `remove_duplicate_sources`, `clip_sources_to_wcs`
* `runners/utils.py` lines 800–872 → `infer_image_shape`, `image_boxes_from_wcs`

#### 3. Where the two upstreams disagreed

Afterglow and Skynet's copies had drifted. Per file, Kepler took:

| Piece | Taken from | Why |
|---|---|---|
| VizieR engine | Afterglow | Superset — Skynet dropped the configurable server and the custom-catalog factory, both restored here |
| `SDSS._args_to_payload` signature | Skynet | Afterglow passed `radius=None` to `super()`, which newer astroquery rejects |
| `mags` value type | Skynet | Lists, not tuples — Afterglow's tuples were a Marshmallow artifact |
| USNO-B1 `B`/`R` band columns | Skynet | Afterglow declared them as empty tuples, so B and R were never read |
| SDSS narrowband aliases | Skynet | Afterglow had no `Halpha`/`OIII`/`SII` entries |
| Default VizieR mirror | Skynet | `vizier.cds.unistra.fr`, replacing `vizier.cfa.harvard.edu` |

#### 4. Every seam cut

##### 4.1 Flask `current_app.config` → `query/config.py`

Afterglow read `VIZIER_SERVER`, `VIZIER_CACHE` and `VIZIER_CACHE_AGE` from Flask
config, which made importing the catalog plugins require an application context.
Kepler reads the environment. Defaults reproduce upstream values. No effect on
query results.

##### 4.2 Import-time monkey-patch → explicit call

Afterglow patched `astroquery.query.to_cache` and `AstroQuery` as a bare side
effect of module import. Kepler moves it to
`cache.install_cache_error_suppression()`, which `vizier.py` calls on import —
so the default behaviour is unchanged, but the patch is greppable and a caller
can opt out. Patching a third-party module's globals should not be invisible.

##### 4.3 `CUSTOM_VIZIER_CATALOGS` loop → `build_custom_vizier_catalog()`

Afterglow built custom catalog classes in an import-time `for` loop over Flask
config, wrapped in `try/except Exception` that logged and continued. Kepler
exposes the same class construction as a function that raises. A misconfigured
catalog should be visible where it is registered, not absent at query time.

##### 4.4 `processing_run` parameter dropped

`query_catalogs_for_processing_run` took an `ObservationAssetProcessingRun`
SQLAlchemy row as its first argument and never read it — it was there for
call-site symmetry. Kepler's `query_catalogs` omits it rather than carry a
duck-typed placeholder. `fieldcal` call sites updated.

##### 4.5 SIMBAD resolver: local-database branches severed

Upstream's `search_targets` queried SIMBAD *and* four local SQLAlchemy tables
(NORAD satellites, major solar-system bodies, MPC comets, MPC orbits), merging
them into one sorted list. Those are ORM queries against Skynet's own database,
not remote catalog access, and they pull in `skynet_db.models` entirely.

Only the SIMBAD branch is extracted. The merge-and-sort shape is preserved:
`resolve_targets(name, extra=[...])` accepts additional result lists, so a caller
with its own object database restores the combined behaviour without this module
knowing about it. Upstream's `TargetSearchResult`/`FixedPosition` ORM models
become the plain `ResolvedTarget` dataclass.

The availability probe also moved: upstream ran `add_votable_fields("otype")` at
import time, so importing the module did network-adjacent work. It is now lazy
and cached on first use.

##### 4.6 `AfterglowError` → `UnknownCatalogError(ValueError)`

`afterglow_core/errors/catalog.py` defined `UnknownCatalogError` as an
HTTP-404-carrying `AfterglowError`. Kepler is a library here, so it subclasses
`ValueError` — which keeps the `raise ValueError('Unknown catalog "…"')` that the
query runner used catchable the same way. Callers needing a 404 map it at their
edge.

##### 4.7 Job wrapper not extracted

`afterglow_core/.../job_plugins/catalog_query_job.py` (347 lines) is the same
orchestration wrapped as a Marshmallow job class reading images from a data-file
store. Its algorithmic content — the FOV geometry and the combined-FOV bounding
box — is in `geometry.py`. The `Job`/`JobResult`/`get_data_file_fits` wrapper is
service infrastructure and was left behind.

##### 4.8 Class renames

`AfterglowSDSS` → `KeplerSDSS`. Generated SQL unchanged. See
the Catalogs section of this document, §3 for the rest.

#### 5. Deliberate behaviours preserved (do not "fix")

##### 5.1 Cache rounding is observable

With the cache enabled, `query_box` and `query_circ` snap the region centre to
10 arcsec and round sizes *up* to 0.2 arcmin, so near-identical fields share a
cache entry. This means a cached query returns rows for a slightly larger,
grid-aligned region than asked for. The WCS path clips afterwards; a caller
using `query_circ` directly does not. Turning the cache off changes results near
a field edge.

##### 5.2 `_derive_columns` requests columns named `int` and `float`

The identifier filter skips NumPy exports and `str` methods but not Python
builtins, so Landolt's sexagesimal-parsing expressions contribute `'int'` and
`'float'` as VizieR column names. VizieR ignores unknown columns, so the query
still returns correct data — which is why it survived upstream unnoticed.
Left as-is: filtering builtins changes the request Kepler sends and needs
validation against a live VizieR.

##### 5.3 `build_custom_vizier_catalog`'s character class is wrong

`[^a-zA-z0-9_]` — lowercase `z` — additionally admits ``[ \ ] ^ _ ` ``. Cosmetic;
the generated name is never parsed. Preserved.

##### 5.4 Rows with no magnitudes are dropped

`table_to_sources` appends a source only `if source.mags`. A source Kepler cannot
photometer is not useful, and field calibration depends on the filtering.
`len(table)` and `len(sources)` differ routinely.

##### 5.5 A magnitude of 99 or more means "not measured"

VizieR's null convention in several tables. Applied before a `Mag` is built.

##### 5.6 `skip_failed` never skips the last catalog

In WCS mode, a failing catalog is skipped only while another remains to try. The
last one always raises — otherwise a total provider outage would be
indistinguishable from an empty field.

##### 5.7 `SkyMapperQueryBackend.query_region` mutates the caller's dict

It calls `constraints.setdefault('flags', '0')` on the dict it was handed. A
caller reusing one dict across catalogs finds `flags` added after querying
SkyMapper. Upstream did the same; Kepler's runner passes a fresh dict per call.

##### 5.8 SDSS ignores `constraints`

Accepted on all three SDSS query methods and never used — the SQL applies its own
quality predicates and upstream never wired column filters through. A caller
passing constraints to SDSS gets unfiltered results, silently. Documented on the
class rather than changed, because raising would break existing call sites that
pass a shared constraints dict to a catalog list including SDSS.

##### 5.9 `combined_bounding_box` is disabled upstream

Afterglow guarded the call with `if False:` and fell through to querying each
field separately. The reason was never recorded. Kepler keeps it as a working,
tested function that nothing calls. Enabling it is a behaviour change needing its
own validation.

##### 5.10 Two footprint implementations, both kept

`boxes_from_wcs` projects the four corners with `CRVAL` moved to (0,0), which
handles rotation and the cos(dec) narrowing. `image_boxes_from_wcs` multiplies
pixel scale by axis length, which is blind to both but works without
`array_shape`. Upstream had both; they return different widths for the same WCS
(verified: 1.02297° vs 1.02400° on a 1024² TAN field). Prefer the former.

#### 6. External dependencies

`astroquery==0.4.11` (already pinned in `pyproject.toml`; no change required),
`astropy`, `numpy`, and `catalogs/`.

Network access is required only at query time. No module makes a network call at
import time.

#### 7. Verification performed

Offline only — no live VizieR, SkyServer or SIMBAD calls were made.

* All backends bind with the intended MRO:
  `SDSSCatalogQueryable → SDSSCatalog → SDSSQueryBackend → VizierCatalog → Catalog`,
  so plugin `table_to_sources` overrides reach the engine's implementation via
  `super()` exactly as upstream's single-class arrangement did.
* Registry `filter_lookup` overlays survive binding.
* Column derivation for APASS, Landolt, VSX, Tycho, USNO — including §5.2.
* Row mapping and all three photometric transforms against synthetic astropy
  tables; see the Catalogs section of this document, §7.
* SDSS SQL generation for box, circle and north-pole regions; quality predicates
  asserted present.
* Geometry: RA-seam clipping, pole clipping, both footprint implementations,
  deduplication, detector clipping with pixel-coordinate stamping,
  `combined_bounding_box`.
* Filter-aware selection across 8 catalog/filter cases including the `'*'`
  wildcard and the no-compatible-catalog fallback.
* `catalogs` and `query.selection` import without pulling `astroquery` into
  `sys.modules`; `fieldcal` likewise.
* SIMBAD offline paths: blank-input short circuit, merge-and-sort with
  caller-supplied results.

**Not verified**: any live provider response. Nothing here has been run against
real VizieR, SkyServer or SIMBAD traffic, so response-shape assumptions —
astroquery's apostrophe/underscore column renaming in particular — remain
untested against current provider behaviour.

## HR Diagram / Isochrone Matching

_Former source: `algorithms/hrdiagram/EXTRACTION.md`._

### HR Diagram / Isochrone Matching — extraction record

Algorithmic TypeScript lifted out of the **Astromancer** "cluster" tool
(`/home/claude/astromancer`, Angular 16) into `algorithms/hrdiagram/`.

This is an **extraction, not a port**. Function bodies, comments, constants and
the author's quirks (including several bugs, flagged below) are preserved as
written. The only edits are import paths, the removal of Angular/RxJS/Highcharts
wrappers, and the lifting of methods out of components into free functions. Every
severed dependency carries an inline `// EXTRACTED: was …` seam comment at the
point it was cut.

Astromancer was **not modified**.

---

#### 1. What the algorithm actually is

Understanding the split below is easier with the pipeline in front of you:

1. **Ingest** — sources arrive with astrometry (RA/Dec), parallax distance,
   proper motion, and multi-band photometry. Photometry is cleaned (NaN and
   unknown filters dropped) and sorted by effective wavelength.
2. **Field star removal (FSR)** — an *elliptical* acceptance region in
   (pm_ra, pm_dec) intersected with a distance interval partitions sources into
   cluster members vs field.
3. **Isochrone matching** — for a chosen filter triple (blue, red, luminosity),
   members are plotted as colour `blue − red` against luminosity magnitude. The
   student varies four parameters — **age**, **metallicity**, **distance**,
   **reddening** — until a model isochrone overlays the main sequence. Distance
   and reddening enter as a rigid *offset* between the observed CM plane and the
   absolute HR plane; age and metallicity select which model track is fetched.
4. **Result** — the fitted distance plus member astrometry yield half-light
   radius, physical radius, galactic coordinates, velocity dispersion, and a
   virial mass.

The single most important function is
`isochrone-matching/isochrone-plot.util.ts::computePlotDelta`:

```
dx = A(red) − A(blue)                        colour excess
dy = −A(lum) − 5·log10(d_pc) + 5             distance modulus
```

with `A(λ)` from `cluster.util.ts::getExtinction` (Cardelli–Clayton–Mathis
parameterisation). HR mode shifts the *stars* by `+delta`; CM mode shifts the
*isochrone* by `−delta`. Same fit, opposite frame.

---

#### 2. Files copied

Line counts are of the **astromancer source file**; the "carried" column is how
much of it landed here.

| Destination | Source (under `/home/claude/astromancer/`) | Src lines | Carried |
|---|---|---|---|
| `cluster.util.ts` | `src/app/tools/cluster/cluster.util.ts` | 228 | 228 (verbatim) |
| `shared/angle.util.ts` | `src/app/tools/shared/data/utils.ts` | 278 | 24 (4 functions) |
| `storage/cluster-storage.service.util.ts` | `src/app/tools/cluster/storage/cluster-storage.service.util.ts` | 75 | 75 (verbatim) |
| `fsr/fsr.util.ts` | `src/app/tools/cluster/FSR/fsr.util.ts` | 22 | 22 (verbatim) + `range` |
| `fsr/fsr-histogram.util.ts` | `.../FSR/histogram-slider-input/histogram-slider-input.component.ts` | 467 | ~35 (2 functions) |
| `fsr/cmd-fsr.util.ts` | `.../FSR/cmd-fsr/cmd-fsr.component.ts` | 135 | ~45 (1 function) |
| `photometry/cluster-data.service.util.ts` | `src/app/tools/cluster/cluster-data.service.util.ts` | 133 | 133 (verbatim) |
| `photometry/cluster-data.service.ts` | `src/app/tools/cluster/cluster-data.service.ts` | 408 | ~180 |
| `isochrone-matching/cluster-isochrone.service.ts` | `.../isochrone-matching/cluster-isochrone.service.ts` | 121 | ~70 |
| `isochrone-matching/isochrone-plot.util.ts` | `.../isochrone-matching/plots/plot/plot.component.ts` | 447 | ~150 |
| ″ (`isValidFilterSelection`) | `.../control-panel/filter-selector/filter-selector.component.ts` | 53 | 3 |
| `result/result.utils.ts` | `src/app/tools/cluster/result/result.utils.ts` | 131 | 107 |
| `result/cluster-summary.ts` | `.../result/result-summary/result-summary.component.ts` | 275 | ~33 |
| ″ (`logAgeToMyr`) | `.../result/result-summary/result-summary.component.html` | 121 | 1 expression |
| `result/galaxy-projection.ts` | `.../result-graphics/galaxy-faceon/…component.ts` + `galaxy-edgeon/…component.ts` | 66 + 68 | ~20 |
| `result/mwsc-distributions.ts` | `.../result-graphics/{age,distance,metallicity,reddening,number-of-stars}/…component.ts` | 149+163+105+105+111 | ~50 |

`.spec.ts` files were not examined for content and none were copied.

##### Directory layout created

```
hrdiagram/
├── cluster.util.ts                 domain model, filter tables, extinction
├── shared/
│   └── angle.util.ts               rad, deg, d2HMS, d2DMS
├── storage/
│   └── cluster-storage.service.util.ts   ClusterMWSC, StarCounts, storage shapes
├── fsr/
│   ├── fsr.util.ts                 FsrParameters, range
│   ├── fsr-histogram.util.ts       Freedman–Diaconis binning, 2.5σ clip
│   └── cmd-fsr.util.ts             preview CMD construction
├── photometry/
│   ├── cluster-data.service.util.ts  the FSR membership cut, star counts
│   └── cluster-data.service.ts       in-memory source catalogue + projections
├── isochrone-matching/
│   ├── cluster-isochrone.service.ts  fitted-parameter store + defaults
│   └── isochrone-plot.util.ts        ★ the CM/HR transform
└── result/
    ├── result.utils.ts             half-light radius, galactic coords, mass
    ├── cluster-summary.ts          the terminal derivation chain
    ├── galaxy-projection.ts        (l, b, d) → galactic-plane position
    └── mwsc-distributions.ts       catalogue histogram prep + unit conversions
```

---

#### 3. What was left behind, and why

##### 3.1 Entire files excluded — pure Angular UI

Every `*.component.html`, `*.component.scss`, `*.component.spec.ts` and
`cluster.module.ts`, plus these `*.component.ts` files which contain **no**
computation at all:

`isochrone-matching.component.ts` (9 lines, empty shell), `result.component.ts`
(13, empty), `filter-controls.component.ts` (10, empty), `cluster.component.ts`,
`cluster-stepper.component.ts`, `cluster-plot-grid.component.ts` (grid arity from
`plotConfigs.length`), `plot-lists.component.ts` (CDK drag-reorder of plot
configs), `hrd-result.component.ts` (a `FormGroup` that builds one `PlotConfig`),
`result-graphics.component.ts` (fetches `/cluster/allMWSC`),
`archive-fetching-graphics.component.ts` (stacked column chart of star counts —
checked specifically, it only re-reads `getInterfaceStarCounts()`),
`field-star-removal.component.ts` (wires three histogram sliders to
`setFsrParams`), `pm-chart.component.ts`, `pie-chart.component.ts`,
`data-source/*` (file upload, drag-n-drop directive, name lookup, five modal
pop-ups), `archive-feetching/*` (fetch dialogs).

##### 3.2 Services excluded — framework state, not algorithm

- **`cluster.service.ts`** (101) — session state: cluster name, FSR params,
  tab index, loading flag, a registry of `Highcharts.Chart` handles, and six
  RxJS `Subject`s. The only thing downstream math needed from it was
  `getFsrParams()`, now a field on the extracted `ClusterDataService` and a
  parameter to `resetDistance()`.
- **`storage/cluster-storage.service.ts`** (194) — a `localStorage`
  get/set wrapper. **Its `init()` default block was preserved**, as
  `DEFAULT_ISOCHRONE_STORAGE` in `isochrone-matching/cluster-isochrone.service.ts`,
  because those are the algorithm's starting parameter values.
- **`data-source/cluster-data-source.service.ts`** (165) and
  **`.util.ts`** (77) — file upload/parse orchestration and
  `ClusterLookUpStackImpl`, an LRU stack of recent cluster-name searches. UI
  history. Left behind; `ClusterLookUpData` is aliased to `unknown` in
  `storage/cluster-storage.service.util.ts` with a seam comment.
- **`src/app/shared/job/job.ts`** — an `HttpClient` + `interval()` polling
  wrapper for async backend jobs. Network plumbing. `JobStorageObject` is
  likewise aliased to `unknown`.

##### 3.3 Functions deliberately dropped from files that were otherwise copied

| Dropped | From | Why |
|---|---|---|
| `drawStar(ctx, …)` | `result/result.utils.ts` | Canvas2D star-polygon rasteriser. Pure rendering. |
| `downloadCsv(cols, data, name)` | `result/result.utils.ts` | `Blob` + `<a download>` browser file save. Pure IO. |
| `lombScargle`, `lombScargleWithError`, `ArrMath`, `floatMod`, `UpdateSource` | `shared/data/utils.ts` | Periodogram / light-curve math, unreachable from the cluster tool. Already extracted under `algorithms/periodogram/core/` and `algorithms/lightcurve/shared/`. |
| `fetchCatalog`, `fetchFieldStarRemoval`, `getCatalogResults`, `getFSRResults`, `initValues`, `downloadSources` | `cluster-data.service.ts` | HTTP job submission/polling, response callbacks, localStorage job replay, CSV download. See §5 for the response contracts. |
| `setHighChart` / `getHighCharts` / `highCharts[]` | `cluster-isochrone.service.ts` | A registry of live chart handles used only for PNG export. |
| `downloadSummary`, `downloadData`, `downloadPlots`, `downloadFsrPlots`, `downloadPlotData`, `submitData` | `result-summary.component.ts` | Export handlers and an Astronomicon `POST`. `downloadPlotData` in particular reads points back out of the Highcharts series — it is a chart reader, not a producer. |

##### 3.4 Judgment calls on the UI-vs-algorithm boundary

The brief flagged `result/result-graphics/` as ambiguous. Findings, per file:

- **`galaxy-faceon` / `galaxy-edgeon`** — **contained real math; extracted.**
  Under the image blit and `drawStar` calls sits a genuine projection of
  (l, b, distance) into the galactic plane. Lifted to
  `result/galaxy-projection.ts`. The pixel scale factors (32, 16), the ±500
  clamp and the two canvas anchor points came along, because the returned
  offsets are meaningless without them — they are tagged as rendering constants.
- **`age`** — **contained a real conversion; extracted.** `10^age / 1e6`
  converts the catalogue's log10(years) to Gyr. Same expression appears in the
  summary template for Myr; both are in the extraction.
- **`distance`** — **contained a real conversion; extracted.** `distance/1000`
  is the *only* place the catalogue's parsecs meet the tool's kiloparsecs. Easy
  to lose, so it is called out explicitly in `mwsc-distributions.ts`.
- **`metallicity`, `reddening`, `number-of-stars`** — **borderline; extracted
  the clip, dropped everything else.** Each contributes only a domain filter
  (`−2.3 < Z < 0.8`, `0 ≤ E(B−V) ≤ 1`) or an outlier trim
  (`slice(0.0015·n, 0.99985·n)`). These match the charts' fixed axis bounds, but
  they function as catalogue-quality cuts that discard sentinel rows, so they
  were kept rather than discarded as styling.
- **`hrd-result`, `result-graphics`, `number-of-stars`'s marker update** — **no
  math; dropped.**

Three further calls worth recording:

- **`plot.component.ts` was the biggest judgment call.** It is a 448-line
  Highcharts component, and on a filename-only reading it would have been
  skipped as UI. It is in fact where the entire CM↔HR transform lives. Six
  private methods were lifted; the chart options, `setExtremes`/`setData`
  calls, the axis-title string building (with its `"prime"` → `'` prettifying
  and `<sub>0</sub>` markup) and the `try/catch` blocks — whose only purpose was
  "chart not built yet, write to the options literal instead" — were dropped.
- **`histogram-slider-input.component.ts`**: 467 lines of Material sliders and
  reactive forms wrapping ~35 lines of statistics. Only the statistics came.
- **`cluster-isochrone.service.ts` is mostly state plumbing**, not math. It was
  extracted anyway because it is the canonical definition of the algorithm's
  input surface (the four fitted parameters, the error cut, the plot configs)
  and the parameter defaults live there.

---

#### 4. Framework seams cut

Every one of these is marked inline with `// EXTRACTED: was …`.

| Seam | Where | Replacement |
|---|---|---|
| `@Injectable()` | `ClusterDataService`, `ClusterIsochroneService` | Plain classes, constructed directly. |
| `@Component` / `@Input` / `@ViewChild` | all lifted component methods | Free functions with explicit parameters. |
| RxJS `Subject`/`Observable` fan-out (`plotParams$`, `isochroneParams$`, `maxMagError$`, `plotConfig$`, `addPlotConfig$`, `resetPlotConfig$`, `sources$`, `clusterSources`) | both services | Removed. Setters mutate state; the host schedules recomputation. |
| `ClusterStorageService` (localStorage) | both services | Defaults inlined as `DEFAULT_ISOCHRONE_STORAGE`; `fsrParams` held as a field on `ClusterDataService` (`getFsrParams()` added). |
| `ClusterService.getFsrParams()` | `ClusterIsochroneService.resetDistance()` | Now an explicit `FsrParameters` parameter. |
| `ClusterService.reset$` | `ClusterIsochroneService` constructor | Call `init()` directly. |
| `HttpClient` + `environment.apiUrl` | `cluster-data.service.ts`, `plot.component.ts`, `result-graphics.component.ts` | Removed. Contracts documented in §5. `setUserPhotometry` / `setCluster` / `setStarCounts` were made public as the injection seam for what used to arrive in responses. |
| `Job` (async polling) | `cluster-data.service.ts` | Removed; `JobStorageObject` aliased to `unknown`. |
| `Highcharts` (options, `Chart` handles, `series[n].setData`, `axis.setExtremes`) | every chart component | Removed. Range computation retained as `getStandardViewRange` / `getDataRange`. |
| `@angular/forms` `ValidatorFn` | `filterValidator` | Kept as the plain predicate `isValidFilterSelection`. |
| `@angular/material` `MatSlider` `ViewChild` writes | `setExtremes` | Removed; `getHistogramExtremes` returns the range. |
| `@angular/cdk` `moveItemInArray` | `plot-lists.component.ts` | Whole component dropped. |
| DOM `Blob` / `document.createElement('a')` / `window.URL` | `downloadCsv` | Dropped. |
| Canvas2D `ctx` | `drawStar`, both galaxy `draw()` | Dropped; projection math retained. |
| `import {ClusterLookUpData}` | `cluster-storage.service.util.ts` | `type ClusterLookUpData = unknown` |

**No behaviour was silently dropped.** Where a cut removed a side effect (a
storage write, an observable emission, a chart update), the seam comment names
the exact statement removed.

---

#### 5. Data and asset dependencies

##### Isochrone model grids — **NOT PRESENT, and not copyable from this repo**

This is the most important dependency to flag. Astromancer ships **no** isochrone
data: no lookup tables, no model grids, nothing under `src/assets/` (which
contains only two font families and a `static/` folder). Verified by searching
the whole repo for `*isochrone*` — only the TypeScript files listed above match.

The model track is fetched per parameter change from a backend:

```
GET {environment.apiUrl}/cluster/isochrone
    ?age=<log10 yr>&metallicity=<solar>
    &blue_filter=<FILTER>&red_filter=<FILTER>&lum_filter=<FILTER>
→ { data: number[][], iSkip: number }
```

`data` arrives **already in `[colour, absolute magnitude]` pairs for the
requested filter triple** — i.e. the server does the grid interpolation and the
synthetic photometry. `iSkip` marks an index where the evolutionary track is
discontinuous and the polyline must be broken.

**Consequence:** `hrdiagram/` reproduces the client-side transform faithfully,
but a standalone system needs its own isochrone source (e.g. PARSEC / MIST
grids) plus the interpolation and bolometric-correction step that the
astromancer backend performs. That backend is not in this repository.

##### Other backend endpoints referenced (all cut)

| Endpoint | Was used for |
|---|---|
| `POST/GET {apiUrl}/cluster/catalog` | catalogue cone search; response supplies `output_sources`, `input_sources`, `cluster` (a `ClusterMWSC`), `star_counts` |
| `POST/GET {apiUrl}/cluster/fsr` | field-star-removal astrometry; response supplies `sources` and `FSR`, merged by `appendFSRResults` |
| `GET {apiUrl}/cluster/allMWSC` | the full Milky Way Star Cluster catalogue, `ClusterMWSC[]`, feeding `result/mwsc-distributions.ts` |
| `POST {astronomiconApiUrl}/submissions` | student result submission |

`environment.apiUrl` defaults to `http://127.0.0.1:5001` in dev.

##### Data tables that DID come along (embedded in source, not external files)

- `filterWavelength` — effective wavelength (µm) for 20 filters. Drives both
  extinction and the photometry sort order.
- `filterFramingValue` — per-filter `blue`/`red`/`faint`/`bright` extremes
  defining the "Standard View" axis window.
- `APASS_FILTERS`, `TWO_MASS_FILTERS`, `WISE_FILTERS`, `GAIA_FILTERS` — catalogue
  groupings used for per-survey star counts.
- The CCM extinction polynomial coefficients inside `getExtinction`.

##### Parameter domains (UI-enforced in astromancer, documented here only)

From `isochrone-plotting-controls.component.html`. The extracted code does **not**
enforce these — neither did astromancer's TypeScript.

| Parameter | Min | Max | Step | Default | Note |
|---|---|---|---|---|---|
| Distance (kpc) | 0.1 | 100 | 0.01 | 0.1 | log-scaled slider |
| log(Age (yrs)) | 6.60 | 10.20 | 0.05 | 6.60 | |
| Metallicity (solar) | −2.2 | 0.7 | 0.05 | −2.2 | |
| E(B−V) | 0 | 1 | — | 0 | |
| Max Error (mag) | 0 | 1 | — | 1 | photometric-error cut |

---

#### 6. External npm dependencies

**Required by the extracted code: none.** Every file here compiles against the
TypeScript standard library alone — no runtime imports outside `hrdiagram/`.

Dependencies of the *original* files, all severed:

| Package | Used for | Status |
|---|---|---|
| `@angular/core` | `@Injectable`, `@Component`, `@Input`, `@ViewChild` | cut |
| `@angular/common/http` | `HttpClient` | cut |
| `@angular/forms` | `FormGroup`, `FormControl`, `Validators`, `ValidatorFn` | cut |
| `@angular/material` | `MatSlider`, `MatDialog`, `mat-divider` | cut |
| `@angular/cdk` | `moveItemInArray`, drag-drop | cut |
| `rxjs` (~7.5) | `Subject`, `Observable`, `debounceTime`, `takeUntil`, `combineLatestWith`, … | cut |
| `highcharts` (^11.1) + `highcharts-angular` + `highcharts/modules/histogram-bellcurve` | every chart | cut |
| `piexif-ts` | EXIF stamping on exported PNGs | cut (never reached) |
| `chart.js` | `updateLine` in `shared/charts/utils.ts` | cut (never reached) |

`tslib` may be needed depending on the consuming project's `importHelpers`
setting; nothing here requires it directly.

---

#### 7. Preserved defects — do not "fix" these silently

Faithfulness was chosen over correctness. Each is flagged inline at its site.

1. **`getExtinction` ignores its own `rv` parameter in the leading term.**
   Returns `3.1 * reddening * (a + b / rv)` — the `3.1` is hard-coded even
   though `rv` is a parameter defaulting to `3.1`. Only matters for a non-3.1
   caller; there are none today. — `cluster.util.ts`
2. **`getStandardViewRange` mixes `lum` and `red` in the y-minimum.** The
   `y.min` expression subtracts `filterFramingValue[red].faint` where every
   sibling term uses `lum`. — `isochrone-matching/isochrone-plot.util.ts`
3. **Off-by-one in the isochrone break splice.** `slice(0, iSkip - 1)` drops one
   point before inserting the `[null, null]` gap. — `applyIsochroneTransform`
4. **Dead `else if (maxMagError === null)` branches** in `generateRawData`
   (three of them, one with an empty body). `maxMagError` is initialised to `0`
   and only ever assigned numbers, so these never fire.
5. **`getPmra` is applied to the pm_dec array** in the summary derivation
   (`result-summary.component.ts:108`). Harmless — `getPmra` and `getPmdec` have
   identical bodies — but it is not what it looks like. — `result/cluster-summary.ts`
6. **`d2DMS` computes a `sign` variable and never uses it.** Negative
   declinations therefore lose their sign in the DMS triple.
   — `shared/angle.util.ts`
7. **Asymmetric percentile bounds in `getVelocityDispersion`.** Low bound uses
   `(1 − p)/2`, high bound uses `(1 − p/2)` — not mirror images, so the retained
   band is not the intended central 68.3%. — `result/result.utils.ts`
8. **`updateClusterFieldSources` takes `sqrt` of a possibly negative value.**
   For a star outside the pm_ra semi-axis, `1 − ((pm_ra − c)/a)²` is negative and
   `decDiff` is `NaN`; the subsequent comparisons then yield `false`, which
   happens to be the correct rejection. Correct by accident.
   — `photometry/cluster-data.service.util.ts`

---

#### 8. Structural notes for a consumer

- **Circular type import, inherited.** `cluster.util.ts` imports `ClusterMWSC`
  from `storage/cluster-storage.service.util.ts`, which imports `PlotConfig`
  et al. back from `cluster.util.ts`. This cycle exists in astromancer and is
  type-only, so it erases at compile time. The `ClusterMWSC` import in
  `cluster.util.ts` is in fact **unused** — preserved to keep that file verbatim.
- **Sorting is a precondition, not an implementation detail.** `getDefaultBin`,
  `getHistogramExtremes`, `getPmra`, `getPmdec`, `getHalfLightRadius` and the
  `getClusterRa`/`getClusterDec` medians all assume ascending-sorted input. The
  `ClusterDataService` projections sort before returning; any replacement data
  path must do the same.
- **The cluster centre is an element-wise median** of member RA and Dec
  independently — not a spherical mean. Fine for compact clusters, wrong near
  the poles or across the RA=0 wrap.
- **No compiler was available in this environment** (`node`/`tsc` absent), so
  the extracted files have been reviewed by hand but not type-checked. Imports
  and paths were verified manually.

## Light Curve

_Former source: `algorithms/lightcurve/EXTRACTION.md`._

### Light Curve extraction from Astromancer

Algorithmic TypeScript for the **light curve** and **period folding** stages of
Astromancer's two light-curve tools, extracted into Kepler.

- **Source repo:** `/home/claude/astromancer` (Angular 16 / TypeScript). Read-only for this task; nothing there was modified.
- **Destination:** `/home/claude/Kepler/algorithms/lightcurve/`
- **Nature of the work:** extraction, not a port. Algorithms and comments are
  preserved verbatim. Angular decorators, DI, RxJS, `localStorage` and Highcharts
  handles were cut; every cut is marked in-file with an `// EXTRACTED:` comment.

---

#### 1. Structure created

```
lightcurve/
├── shared/
│   ├── numeric-utils.ts                     26 lines
│   └── data.interface.ts                    21 lines
├── pulsar/
│   ├── pulsar-lightcurve.types.ts          222 lines
│   ├── pulsar-lightcurve.algorithms.ts     392 lines
│   ├── pulsar-lightcurve.ingest.ts         445 lines
│   ├── pulsar-period-folding.types.ts      254 lines
│   └── pulsar-period-folding.algorithms.ts 169 lines
└── variable/
    ├── variable-lightcurve.types.ts        213 lines
    ├── variable-lightcurve.algorithms.ts   257 lines
    ├── variable-lightcurve.ingest.ts       127 lines
    ├── variable-period-folding.types.ts    182 lines
    └── variable-period-folding.algorithms.ts 46 lines
```

Total 2354 lines across 12 source files. Line counts include the provenance
header comments, which are a meaningful fraction of the smaller files.

The `pulsar/` and `variable/` split is deliberate and complete — no file mixes
the two tools, and nothing is shared between them except `shared/`.

---

#### 2. Exact source paths and what was copied

All paths below are relative to `/home/claude/astromancer/src/app/tools/`.

##### 2.1 Shared

| Source | Lines in source | Extracted | Destination |
|---|---|---|---|
| `shared/data/utils.ts` | 278 | `floatMod` (15-25) | `shared/numeric-utils.ts` |
| `shared/data/data.interface.ts` | 11 | `MyData` (all) | `shared/data.interface.ts` |

`floatMod` is the only helper in `utils.ts` that the light-curve path reaches;
both tools import it for period folding.

##### 2.2 Pulsar

| Source | Lines in source | Extracted symbols (source line ranges) | Destination |
|---|---|---|---|
| `pulsar/pulsar.service.util.ts` | 910 | `PulsarDataDict` 5-9, `errorMSE` 11-17, `PulsarStarOptions` 20-24, `PulsarInterface` 26-36, `PulsarInterfaceStorageObject` 38-42, `PulsarInterfaceImpl` 45-101, `PulsarData` 222-316 | `pulsar-lightcurve.types.ts` |
| `pulsar/pulsar.service.util.ts` | 910 | `PulsarDisplayPeriod` 524-527, `PulsarPeriodFoldingStorageObject` 530-543, `PulsarPeriodFoldingInterface` 546-580, `PulsarPeriodFolding` 583-760 | `pulsar-period-folding.types.ts` |
| `pulsar/pulsar.service.ts` | 1263 | `getPeriodFoldingChartData` 273-314, `getJdRange` 455-468, `getChartPulsarDataArray` 609-613, `getChartSourcesDataArray` 649-660, `median` 715-720, `backgroundSubtraction` 722-739, `binData` 850-886, `interpolateLinear` 1227-1240, `resampleLinear` 1250-1262 | `pulsar-lightcurve.algorithms.ts` |
| `pulsar/light-curve/pulsar-light-curve/pulsar-light-curve.component.ts` | 365 | `uploadHandler` 51-330, `processChartData` 332-358 | `pulsar-lightcurve.ingest.ts` |
| `pulsar/light-curve/pulsar-light-curve-form/pulsar-light-curve-form.component.ts` | 108 | `onBackScaleChange` 70-103 | `pulsar-lightcurve.ingest.ts` |
| `pulsar/period-folding/pulsar-period-folding-highchart/…component.ts` | 331 | `foldAndBin` 182-197, `duplicateIfNeeded` 199-203, difference/sum block 224-232, calibration map 218-220, single-source fold 249-264 | `pulsar-period-folding.algorithms.ts` |
| `pulsar/period-folding/pulsar-period-folding-form/…component.ts` | 307 | `getPeriodStep` 299-306 | `pulsar-period-folding.algorithms.ts` |

##### 2.3 Variable

| Source | Lines in source | Extracted symbols (source line ranges) | Destination |
|---|---|---|---|
| `variable/variable.service.util.ts` | 697 | `VariableDataDict` 5-12, `errorMSE` 14-20, `VariableData` 22-109, `VariableStarOptions` 112-116, `VariableInterface` 118-128, `VariableInterfaceStorageObject` 131-134, `VariableInterfaceImpl` 137-185 | `variable-lightcurve.types.ts` |
| `variable/variable.service.util.ts` | 697 | `VariableDisplayPeriod` 440-443, `VariablePeriodFoldingStorageObject` 446-454, `VariablePeriodFoldingInterface` 457-485, `VariablePeriodFolding` 488-598 | `variable-period-folding.types.ts` |
| `variable/variable.service.ts` | 536 | `getPeriodFoldingPeriod` 77-82, `getPeriodFoldingChartDataWithError` 162-194, `getJdRange` 285-289, `getChartVariableDataArray` 403-415, `getChartVariableErrorArray` 446-463 | `variable-lightcurve.algorithms.ts` |
| `variable/light-curve/variable-light-curve/variable-light-curve.component.ts` | 151 | the `fileParser.data$` handler body 38-113 → `mergeSourcesByMjd` | `variable-lightcurve.ingest.ts` |
| `variable/period-folding/variable-period-folding-form/…component.ts` | 129 | `getPeriodStep` 121-128 | `variable-period-folding.algorithms.ts` |

---

#### 3. A finding worth flagging up front

The task brief described `pulsar.service.util.ts` (910 lines) and
`variable.service.util.ts` (697 lines) as the files that "hold the math". They
mostly do not. Read in full, both are ~85% data models, chart-label carriers and
`localStorage` serialization. The only arithmetic in either is `errorMSE`, a
seven-line quadrature helper duplicated verbatim in both.

The actual light-curve algorithms live in three other places:

1. **`pulsar.service.ts` / `variable.service.ts`** — background subtraction,
   binning, period folding, differential photometry, JD-range.
2. **The `*.component.ts` files** — despite being nominally UI. The pulsar file
   ingest (Green Bank header parsing, time-axis rebasing, Nyquist derivation) is
   entirely inside `pulsar-light-curve.component.ts`'s `uploadHandler`, and the
   two-source MJD merge join is inside `variable-light-curve.component.ts`'s
   constructor. Both are real algorithms wearing component clothing.
3. **`pulsar-period-folding-highchart.component.ts`** — `foldAndBin` and the
   difference/sum computation are closures inside `updateData()`, surrounded by
   Highcharts series plumbing.

The blanket guidance "`*.component.ts` is UI, not the target" would therefore
have dropped the majority of the pulsar tool's algorithmic content. I extracted
from the components where the math genuinely lives, and documented each call in
§6 below.

---

#### 4. Framework seams cut

Every seam is marked in-file with `// EXTRACTED: was <original symbol>`.

| Seam | Where it appeared | How it was cut |
|---|---|---|
| `@Injectable()` + `@angular/core` | `PulsarService`, `VariableService` | Decorator and import removed; classes renamed `PulsarLightCurveAlgorithms` / `VariableLightCurveAlgorithms`. They still compose `PulsarData` / `PulsarInterfaceImpl` / `PulsarPeriodFolding` exactly as the services did, so no method body needed changing. |
| `@Component({...})` + template/style metadata | all light-curve and period-folding components | Removed. |
| Angular constructor DI | `PulsarLightCurveComponent`, `VariableLightCurveComponent`, both period-folding forms | Replaced by a plain constructor argument. For the pulsar ingest this is typed against a local `PulsarIngestHost` interface declaring exactly the 21 service members the verbatim body calls. |
| RxJS `BehaviorSubject` / `Subject` / `.next()` / `takeUntil` / `debounceTime` | ~14 subjects across both services, plus every component subscription | All emissions deleted. The in-memory mutation they announced is retained; only the notification is gone. |
| `localStorage` via `PulsarStorage` / `VariableStorage` | every setter in both services | `this.*Storage.save*()` calls deleted; the storage classes themselves were not extracted. |
| `Highcharts.Chart` handles | `setHighChartLightCurve` / `getHighChartPeriodogram` / `addSeries` / `setData` / `setExtremes` / `upsertSeries` | Not extracted. Where math was interleaved with series calls (pulsar period folding), the math was lifted into free functions. |
| Closure capture | `foldAndBin`, `duplicateIfNeeded`, `getPeriodStep` | These captured `period`, `phase`, `displayPeriod` and `this.service.binData` from their enclosing component. Those captures became explicit parameters. **This is the only place where a signature changed**; no body did. |
| `MatDialog` | chart-info edit dialogs | Not extracted. |
| `HonorCodePopupService` / `HonorCodeChartService` | `saveGraph()` in five components | Not extracted — chart PNG export behind an academic-honesty prompt. |
| `MyFileParser` / `FileType.CSV` | `VariableLightCurveComponent` | Not extracted. Generic CSV/TXT/FITS tokenizer shared by all Astromancer tools. `mergeSourcesByMjd` consumes its output shape (`{id, mjd, mag, mag_error}` rows), documented in-file. |
| `FileReader` | `PulsarLightCurveIngest.uploadHandler` | **Retained deliberately.** A browser API, not a framework dependency — and the whole ingest algorithm lives inside its `onload` callback. Keeping it means the body stays byte-identical. |

---

#### 5. Pulsar vs variable — the distinction, preserved

The two tools share a folder layout and a naming scheme, which makes them look
like variants of one implementation. They are not. Recorded here because the
similarity is misleading:

| | Pulsar | Variable |
|---|---|---|
| Sample record | `{jd, source1, source2}` — two polarizations, **no errors** | `{jd, source1, source2, error1, error2, errorMSE}` |
| Science signal | raw intensity with a **running-median background** removed | **differential photometry**: `target − comparison + referenceStarMagnitude` |
| Tuning parameter | `backScale` — background window width in seconds (default 3) | `referenceStarMagnitude` — photometric zero-point (default 0) |
| Background subtraction | yes (`backgroundSubtraction` + `median`) | none |
| Binning | yes (`binData`, default 100 bins/period) | none — plots individual points with error bars |
| Error propagation | none | throughout, via `errorMSE` |
| Period folding | phase and 2×-period duplication applied **after** binning, in the chart component | phase and duplication applied **inside** the fold, in the service |
| Folding params | `period, periodMin, periodMax, phase, cal, speed, bins, displayPeriod` | `period, phase, displayPeriod` only |
| Default period | `0.2` s, real value | `-1`, a sentinel meaning "use the full JD baseline" |
| Slider bounds | persisted on the model, seeded from the data's Nyquist limit at ingest | computed inline from `periodogramStartPeriod … jdRange` |
| Ingest | fixed-column instrument file, `#` metadata header, two flavours (cal / standard) | CSV with interleaved sources, needs a merge join to align |
| Default dataset | 100 synthetic rows | 14 synthetic rows |
| Sonification | yes | no |

Two smaller preserved discrepancies, both left as found:

- `getJdRange` is loop-based in pulsar (a deliberate fix — spread-arg
  `Math.max(...arr)` overflowed V8's stack on ~125k-sample files) but still
  spread-based in variable, whose datasets never got large enough to hit it.
- `getPeriodStep` is arithmetically identical in both tools, but only the
  variable copy carries the explanatory comment. Both copies kept.

---

#### 6. What was left behind, and why

##### Left behind as UI / rendering

- **All Highcharts components** — `pulsar-light-curve-highchart` (206),
  `variable-light-curve-highchart` (210), `variable-period-folding-highchart`
  (163), and the non-math ~80% of `pulsar-period-folding-highchart` (331).
  Series construction, boost-module config, marker symbols, tooltip formats.
- **`updateXAxisScale()`** (both period-folding highcharts) — a magnitude ladder
  (`delta` 0.15 → 0.000001) picking a rounded axis maximum, then
  `xAxis[0].setExtremes()`. Numeric, but it computes a chart viewport and
  nothing else. **Judgment call**; flagged in-file.
- **Both table components** — `pulsar-table` (179), `variable-table` (103).
  Handsontable grid adapters plus a `limitPrecision` display rounding helper.
- **Chart-info forms** — `pulsar-light-curve-chart-form` (62),
  `variable-light-curve-chart-form` (62), `variable-light-curve-form` (39).
  Pure `FormGroup` wiring for titles, axis labels and star selection.
- **All `*.component.html` / `*.component.scss`.**
- **All `*.component.spec.ts`** — 16 files, each a 21-23 line Angular TestBed
  stub with no assertions about the math.

##### Left behind as state / persistence

- **`PulsarStorage`** (`pulsar.service.util.ts` 763-911) and
  **`VariableStorage`** (`variable.service.util.ts` 601-697) — `localStorage`
  get/save/reset for ten and six keys respectively.
- **`PulsarChartInfo`** (104-218) and **`VariableChartInfo`** (188-295) — chart
  titles, axis labels, data labels.
- **`UpdateSource`** enum (`shared/data/utils.ts` 258-262) — an RxJS
  discriminator distinguishing init/reset/interface-driven form refreshes.

##### Left behind as out of scope

- **Sonification** — see §7.
- **Periodogram** — see §8.
- **`rad` / `deg` / `d2HMS` / `d2DMS`** (`shared/data/utils.ts` 1-12, 264-278) —
  celestial coordinate conversion. Verified by grep to be unused anywhere under
  `tools/pulsar/` or `tools/variable/`.
- **`Sonifier` class** (`shared/sonification/sonification.ts`, 173 lines) — a
  standalone audio class that no light-curve code imports; the pulsar tool has
  its own copy of this logic inlined in the service.

##### Retained despite a plausible case for exclusion

- **`interpolateLinear` / `resampleLinear`** (`pulsar.service.ts` 1227-1262).
  Their only callers in Astromancer are the sonifier. They are nonetheless pure,
  self-contained linear resampling with no audio or framework dependency and
  obvious utility on a binned light curve, so they were kept — with an in-file
  note recording that their sole in-app caller was out-of-scope audio code.
- **Chart-label fields on the period-folding models** (`title`, `xAxisLabel`,
  `yAxisLabel`, `dataLabel`). These are UI, but they are interleaved with the
  algorithm parameters inside `PulsarPeriodFolding` / `VariablePeriodFolding`.
  Stripping them would have meant rewriting the classes rather than copying
  them, so they were kept and flagged in-file.

---

#### 7. The sonifier — confirmed out of scope

`pulsar-light-curve-sonifier/` (88 lines) and the two large service methods it
drives, `PulsarService.sonification` (`pulsar.service.ts` 889-1053) and
`sonificationBrowser` (1056-1224), were **not extracted**.

Reviewed rather than assumed. Their content:

- WAV container construction — RIFF/fmt/data chunk headers written into a
  `DataView`, interleaved 16-bit PCM conversion, `Blob` + object-URL download.
- `AudioContext` / `AudioBufferSourceNode` playback, loop and stop handling.
- Two audio synthesis modes — amplitude-modulated white noise ("burst", TV-static
  style) below 4 kHz, and direct waveform playback above it.
- Audio-domain normalization to ±0.95 with a 0.7 gain.

The only genuinely reusable numerics inside are the global min/max normalization
and `interpolateLinear` — and `interpolateLinear` was extracted separately (§6).
The component itself (88 lines) is a button handler that clips the series to the
first 60 seconds before handing off. Everything else is audio rendering, which is
the same category as the Highcharts rendering excluded elsewhere.

`speed` and `cal` on `PulsarPeriodFolding` are retained even though `speed` is
consumed only by sonification — they are fields on an extracted model, not code.

---

#### 8. Overlap with the periodogram extraction

A separate agent extracted periodogram code into `/home/claude/Kepler/algorithms/periodogram/`
from three of the same source files. Nothing was written outside
`/home/claude/Kepler/algorithms/lightcurve/`. Their output landed before this document was
finalized, so the overlap below is **verified against their actual files**, not
predicted.

##### Shared source files, disjoint contents

- **`shared/data/utils.ts`** — I took only `floatMod` (15-25). The periodogram
  side owns `lombScargle` (81-125), `lombScargleWithError` (36-78) and the
  private `ArrMath` object (128-256), in `periodogram/core/lomb-scargle.ts`.
  No overlap in the *periodogram-specific* lines.
- **`pulsar.service.util.ts`** — I took the data/interface/period-folding models;
  they took `PulsarPeriodogram`, `PulsarPeriodogramStorageObject` and
  `PulsarPeriodogramInterface` (318-521). Disjoint.
- **`variable.service.util.ts`** — same split; `VariablePeriodogram` and friends
  (298-437) are theirs. Disjoint.

##### Genuinely duplicated symbols — confirmed

Each of these now exists in both `lightcurve/` and `periodogram/`. Per the
coordination note this duplication is expected and acceptable; it is listed so
that a future consolidation knows exactly what to reconcile.

| Symbol | My copy | Their copy |
|---|---|---|
| `floatMod` | `shared/numeric-utils.ts` | `core/lomb-scargle.ts:40` |
| `errorMSE` | both `*/…-lightcurve.types.ts` | `variable/variable-periodogram.model.ts:41` |
| `PulsarDataDict` | `pulsar/pulsar-lightcurve.types.ts` | `pulsar/pulsar-periodogram.compute.ts:30` |
| `VariableDataDict` | `variable/variable-lightcurve.types.ts` | `variable/variable-periodogram.model.ts:27` |
| `VariableStarOptions` | `variable/variable-lightcurve.types.ts` | `variable/variable-periodogram.compute.ts:22` |
| `getJdRange` | method on both algorithm classes | `pulsar/pulsar-periodogram.compute.ts:107` (free function) |
| `getChartPulsarDataArray` | method on `PulsarLightCurveAlgorithms` | `pulsar/pulsar-periodogram.compute.ts:37` (free function) |
| `getChartVariableDataArray` | method on `VariableLightCurveAlgorithms` | `variable/variable-periodogram.compute.ts:40` (free function) |
| `getPeriodStep` | both `*-period-folding.algorithms.ts` | `pulsar/pulsar-periodogram-folding-link.ts:54` |

Two notes on this table:

- `getChartVariableDataArray` is the **differential photometry** routine — the
  variable tool's core light-curve algorithm (§5). It appears on the periodogram
  side because the Lomb-Scargle input is the differential magnitude series, not
  the raw source columns. Both tools genuinely need it; neither claim is wrong.
- Their copies are free functions taking `data` as a parameter; mine are methods
  on a class that composes the data container, matching how `PulsarService` /
  `VariableService` held it. Same bodies, different call shape.

They also carried over `rad`, `deg`, `d2HMS`, `d2DMS` and `UpdateSource` from
`utils.ts` (they copied the file more wholesale); I deliberately dropped those as
unused-by-light-curve — see §6. Not a conflict, just a different cut line.

##### Coupling points — behaviour that spans both extractions

These are places where light-curve code legitimately writes periodogram state.
Neither extraction is complete without the other:

1. **Nyquist seeding** (`pulsar-light-curve.component.ts` 139-150 and 270-300).
   The light-curve ingest computes `avgDiff = 2 × mean sample interval` and
   writes it into **both** the period-folding bounds *and* the periodogram's
   start/end period, branching on `getPeriodogramMethod()` for
   frequency-vs-period mode. My `PulsarIngestHost` seam interface declares
   `getPeriodogramMethod`, `setPeriodogramStartPeriod` and
   `setPeriodogramEndPeriod` for exactly this reason, and flags them in-file.

   **This grid math is duplicated, deliberately, against coordinator guidance —
   flagging it explicitly.** The periodogram agent extracted the same lines as
   `nyquistPeriodogramRange` and `nyquistFoldingFloor`
   (`periodogram/pulsar/pulsar-periodogram-range.ts`) and the coordinator asked
   me not to duplicate them. I could not comply without breaking the extraction
   contract, for two reasons:

   - In the source these lines are **physically interleaved** with the file
     parsing inside a single `FileReader.onload` closure — the `avgDiff` loop
     sits between the column-mapping code and the background-subtraction call.
     Excising it would mean rewriting `uploadHandler` rather than copying it,
     which the task explicitly forbids ("preserve algorithms verbatim... do NOT
     redesign or reimplement").
   - The same `avgDiff` also drives `setPeriodFoldingPeriodMin/Max`, which is
     **period-folding state and therefore in my scope** per coordinator point 1.
     The block cannot be assigned wholly to either extraction.

   Resolution: `pulsar-lightcurve.ingest.ts` keeps `uploadHandler` byte-identical
   to the source, grid math included. Treat
   `periodogram/pulsar/pulsar-periodogram-range.ts` as the **canonical, reusable**
   form of that math — it is the same arithmetic, already factored into pure
   functions with `null` guards. My copy exists only as a side effect of keeping
   the surrounding ingest verbatim, and should not be maintained independently.
   If the two are ever reconciled, delete mine and have the ingest call theirs.
2. **Shared defaults.** `PulsarPeriodFolding.getDefaultStorageObject()` sets
   `periodMin: 0.1, periodMax: 3` with a preserved source comment stating these
   intentionally mirror the periodogram's `startPeriod`/`endPeriod` defaults.
   Changing one side silently desynchronizes the other.
3. **Periodogram → period folding.** `pulsar-period-folding-form.component.ts`
   157-183 recomputes the folding slider bounds from the periodogram's
   start/end period after each Compute, inverting them in frequency mode. Not
   extracted (it is RxJS + change-detection plumbing), but recorded here because
   it is the return leg of coupling point 1.

##### Not extracted here — periodogram-side, flagged for the other agent

- `PulsarService.getChartPeriodogramDataArray` (`pulsar.service.ts` 663-700)
- `VariableService.getChartPeriodogramDataArray` (`variable.service.ts` 465-473)
- `PulsarService.getLabels` (`pulsar.service.ts` 470-493) — period↔frequency axis
  relabeling that also inverts the periodogram bounds
- `PulsarService.compute` / `clearPeriodogramChart` / the
  `chartComputedPeriodogramDataArray` persistence path

---

#### 9. Preserved quirks — suspected bugs left intact

Per the extraction contract, nothing here was fixed. Each item is preserved
verbatim and flagged in-file; this list exists so the behaviour is not mistaken
for something the extraction introduced.

1. **Misaligned parallel filters in the variable period fold** — *most likely to
   bite.* `getPeriodFoldingChartDataWithError`
   (`variable-lightcurve.algorithms.ts`) builds `data` from
   `getChartVariableDataArray` and `error` from `getChartVariableErrorArray`,
   then indexes them in lockstep (`data[i]` / `error[i]`). But the two use
   **different filter predicates**: the error array additionally requires
   `row.errorMSE !== null`. Any row with a null `errorMSE` shortens `error`
   without shortening `data`, after which every subsequent pair is off by one and
   the tail throws on `error[i][1]!`. Rows only reach that state between a
   `mergeSourcesByMjd` result and the `VariableData.setData` call that populates
   `errorMSE`, which is why it rarely surfaces. *(The periodogram agent
   independently flagged the same two-pass pattern on its side.)*
2. **No empty-data guard on the variable fold.** The same method dereferences
   `data[0][0]!` with no length check and throws on an empty table. The pulsar
   equivalent (`getPeriodFoldingChartData`) had a guard added for exactly this —
   the fix was never mirrored across. Preserved as the asymmetry it is.
3. **Inverted `getIsLightCurveOptionValid` on the pulsar model.**
   `PulsarInterfaceImpl.getIsLightCurveOptionValid()` returns
   `!this.LightCurveOptionValid` — negated — while `PulsarService`'s method of
   the same name returns the flag un-negated. The two disagree for every input.
   Only the service version is reachable from the UI, so the model's copy is
   effectively dead code hiding a sign error. Both preserved.
4. **Descending sort immediately re-sorted ascending.** Both fold routines end
   with `sort((a, b) => b[0] - a[0])` (descending), and every caller then
   re-sorts ascending. Wasted work, not incorrect.
5. **`binData` divides by zero on a degenerate range.** If all x values are
   equal, `binSize` is 0 and every `binIndex` is `NaN`, yielding an empty result
   rather than an error. Unguarded in the source.
6. **Dead locals in the pulsar ingest.** `let type = "cal"` is assigned in both
   branches and never read; `let period: number | null = null` in the
   standard-file branch is shadowed by an inner `const period` and never read.
   Preserved so the body stays byte-identical.
7. **Index-based fold on single-source files.** `foldSingleSourceByIndex`
   spreads samples evenly across one period by array index
   (`item.frequency / initialData.length`), ignoring the true JD spacing that
   the dual-source path honours. Intentional-looking but undocumented in the
   source; preserved with a note.

#### 10. Source commit history — a caution

The Astromancer history is not a reliable guide to what changed. Verified
against actual diffs rather than messages:

- `226baed "Fix periodogram display bug"` touches only
  `pulsar-periodogram-highcharts.component.ts` and `.gitignore` — rendering
  only, no math, nothing in light-curve scope.
- `86bb5f9 "Minor formatting"` is **badly misnamed**. It carries real behavioural
  change into three files this extraction draws from: it adds
  `setTableType('subtracted')` to both `pulsar-light-curve.component.ts`'s
  upload handler and `PulsarService.resetData`, corrects a stale
  `10s` → `3s` comment on the Nyquist branch, and adds the
  `Promise.resolve().then(() => cdr.detectChanges())` NG0100 workaround to the
  period-folding form.

Both are ancestors of `HEAD` (`657b709`), and this extraction was taken from the
working tree at `HEAD`, so all of the above is already reflected. Recorded only
so that anyone diffing this extraction against an older Astromancer checkout
knows why those lines differ. Neither commit touched `shared/data/utils.ts`.

#### 11. External npm dependencies

**The extracted code has zero runtime npm dependencies.** Everything reduces to
plain TypeScript plus these browser globals:

| Global | Where | Note |
|---|---|---|
| `FileReader` | `pulsar-lightcurve.ingest.ts` | Retained deliberately (§4) |
| `alert`, `console` | `variable-lightcurve.ingest.ts` | Preserved verbatim from source |

Dependencies present in the originals and **removed** by this extraction, with the
versions declared in `/home/claude/astromancer/package.json`:

| Package | Version | Used for |
|---|---|---|
| `@angular/core` | ^16.2.0 | `@Injectable`, `@Component`, `ChangeDetectorRef` |
| `@angular/forms` | ^16.2.0 | `FormGroup`, `FormControl`, `Validators`, `FormBuilder` |
| `@angular/material` | ^16.2.0 | `MatDialog` |
| `rxjs` | ~7.5.0 | `BehaviorSubject`, `Subject`, `takeUntil`, `debounceTime`, `combineLatest`, `skip`, `first` |
| `highcharts` | ^11.1.0 | all chart rendering |
| `highcharts-angular` | ^3.1.2 | chart component wrapper |
| `handsontable` / `@handsontable/angular` | 13.0.0 | data tables |
| `chart.js` | ^4.2.1 | typing-only, via `shared/charts/chart.interface.ts` |

`localStorage` was also removed — a Web Storage global rather than a package, but
worth listing alongside these since it was the persistence layer for every model
class extracted here.

---

#### 12. Verification status

- Every extracted body was diffed by eye against its source; algorithms and
  comments are unchanged.
- The only signature changes are the closure-capture → parameter conversions
  listed in §4, each marked in-file.
- **Not type-checked.** No Node, npm or `tsc` is available in this environment
  (`/home/claude/astromancer/node_modules` has no `.bin/tsc`, and `node` is not
  on `PATH`). The files are self-consistent by inspection and the import graph is
  closed within `lightcurve/`, but they have not been fed to a compiler. Running
  `tsc --noEmit` over `lightcurve/` is the obvious next step once a toolchain is
  available.
- No test files were extracted; the 16 Astromancer spec files are TestBed stubs
  that assert only `expect(component).toBeTruthy()`.

## Periodogram

_Former source: `algorithms/periodogram/EXTRACTION.md`._

### Periodogram extraction

Algorithmic periodogram source lifted out of the Astromancer Angular app.

- **Source repo:** `/home/claude/astromancer` (read-only for this task; untouched)
- **Source commit:** `657b709` — *Merge pull request #73 from SkynetRTN/pulsar-bug-fix* (branch `main`, clean tree)
- **Extracted:** 2026-08-10

This is an **extraction, not a port**. Algorithms and comments are preserved
verbatim wherever the framework allowed it. Nothing was redesigned,
reimplemented, or translated. Where a framework dependency had to be severed,
the seam is marked in-file with an `// EXTRACTED:` comment.

---

#### Structure

```
periodogram/
├── core/
│   ├── lomb-scargle.ts                    ← the shared algorithmic heart
│   └── peak-detection.ts                  ← peak + false-alarm thresholds
├── pulsar/
│   ├── pulsar-periodogram.model.ts        ← input/output types, parameter block
│   ├── pulsar-periodogram.compute.ts      ← driver: column prep → lombScargle
│   ├── pulsar-periodogram-range.ts        ← Nyquist-derived default grid bounds
│   └── pulsar-periodogram-folding-link.ts ← periodogram output → folding input
├── variable/
│   ├── variable-periodogram.model.ts      ← input/output types (error-carrying)
│   └── variable-periodogram.compute.ts    ← driver: → lombScargleWithError
```

`core/` is deliberately central: both tools call the same transform, and both
tool folders import *upward* into `core/`. Nothing in `core/` imports from
`pulsar/` or `variable/`.

---

#### What was copied

| Destination | Source path (under `/home/claude/astromancer/`) | Source lines | Fidelity |
|---|---|---|---|
| `core/lomb-scargle.ts` | `src/app/tools/shared/data/utils.ts` | 1–278 (whole file) | **Byte-identical**, 20-line provenance header prepended |
| `core/peak-detection.ts` | `src/app/tools/pulsar/periodogram/pulsar-periodogram-highcharts/pulsar-periodogram-highcharts.component.ts` | 152–162, 234–247 | `findLocalMax` verbatim; confidence math lifted out of Highcharts calls |
| `pulsar/pulsar-periodogram.model.ts` | `src/app/tools/pulsar/pulsar.service.util.ts` | 5–9, 318–329, 332–368, 371–521 | Verbatim |
| `pulsar/pulsar-periodogram.compute.ts` | `src/app/tools/pulsar/pulsar.service.ts` | 442–445, 455–468, 470–493, 609–613, 663–700 | Bodies verbatim; `this.` reads → parameters |
| `pulsar/pulsar-periodogram-range.ts` | `src/app/tools/pulsar/light-curve/pulsar-light-curve/pulsar-light-curve.component.ts` | 139–150, 270–300 | Math + comments verbatim; lifted out of a FileReader handler |
| `pulsar/pulsar-periodogram-folding-link.ts` | `src/app/tools/pulsar/period-folding/pulsar-period-folding-form/pulsar-period-folding-form.component.ts` | 157–183, 299–306 | Verbatim; lifted out of an RxJS subscriber |
| `variable/variable-periodogram.model.ts` | `src/app/tools/variable/variable.service.util.ts` | 5–12, 14–20, 298–305, 308–336, 339–437 | Verbatim |
| `variable/variable-periodogram.compute.ts` | `src/app/tools/variable/variable.service.ts` + `variable.service.util.ts` | 403–415, 465–473 (+ util 112–116) | Bodies verbatim; `this.` reads → parameters; one local renamed (marked in-file) |

**`core/lomb-scargle.ts` is the highest-value artifact and is a byte-for-byte
copy** — verified with `diff` against the original after stripping the header.
It contains `lombScargleWithError`, `lombScargle`, the private `ArrMath`
vector helper object (`errorMean`, `errordot`, `weightedSum`, `dot`, `var`, …),
plus `rad`, `deg`, `floatMod`, `d2HMS`, `d2DMS`, and the `UpdateSource` enum.

---

#### The algorithm, briefly

Both tools evaluate Lomb-Scargle on a **logarithmically spaced** grid, not the
linear grid the loop header suggests. The loop iterates `xVal` linearly from
`start` to `stop`, but the value actually used is recomputed from the loop
counter:

```ts
let logXVal = Math.exp(Math.log(start) + (Math.log(stop) - Math.log(start)) * i / (steps))
```

The linear `xVal` is vestigial in `lombScargleWithError` and only used in
`lombScargle`'s `freqMode === true` branch, which overrides `logXVal` back to
the linear value. So **frequency mode samples linearly and period mode samples
logarithmically** — an asymmetry worth knowing before anyone "cleans up" that
loop. Both original in-code comments about this ("Huge MISTAKE was here…",
"Nyquist is not used here…") are preserved.

Error weighting (`lombScargleWithError` only) replaces the plain mean with
`ArrMath.errorMean` (inverse-variance weighted) and the plain dot product with
`ArrMath.errordot` (weights `1/σ²`, normalised by the weight sum).

The two functions also differ in **output shape**, which matters downstream:
`lombScargleWithError` returns `[x, y]` tuples; `lombScargle` returns
`{x, y}` objects. That difference is the direct cause of the recent bug fix
described below.

---

#### Pulsar vs. variable — the split

The two tools are genuinely different algorithms, not a copy-paste pair:

| | **pulsar** | **variable** |
|---|---|---|
| Transform | `lombScargle` (unweighted) | `lombScargleWithError` (inverse-variance weighted) |
| Input | `PulsarDataDict{jd, source1, source2}` — no errors | `VariableDataDict{jd, source1, source2, error1, error2, errorMSE}` |
| Input prep | raw sources, both polarisation channels independently | differential: target − reference + reference magnitude |
| Channels | **two** periodograms (XX / YY), second is optional | **one** periodogram |
| Grid steps | user-controlled `points` (default 1000) | hardcoded 2000 (`// Maximum points for html2canvas … is 2000`) |
| Period/frequency mode | yes — `method` flag → `freqMode` | no, period only |
| Default range | 0.1–3 s, overridden from data Nyquist on upload | 0.1–1, fixed |
| Peak detection | yes — global max marker + 3 confidence lines | none |
| Output shape | `{x, y}` objects | `[x, y]` tuples |

The pulsar tool is the more developed of the two. The variable tool has no
peak detection, no false-alarm thresholds, and no Nyquist-derived defaults —
so `core/peak-detection.ts` and `pulsar/pulsar-periodogram-range.ts` have no
variable counterpart. That absence is real, not an extraction gap.

---

#### Recent bug-fix findings

Checked `git log` / `git show` on all periodogram paths.

**`226baed` "Fix periodogram display bug" — display only. The Lomb-Scargle
math was not touched.** The commit modifies exactly one source file
(`pulsar-periodogram-highcharts.component.ts`, +25/−25) plus `.gitignore`. It
converts `lombScargle`'s `{x, y}` object output into `[x, y]` tuples before
handing it to Highcharts. The retained comment explains why:

> On Highcharts 11.1.0 (which is what production runs), line series given
> `{x, y}` object data on a logarithmic x-axis can fail to render their SVG
> path entirely for certain data shapes — the series group exists in the DOM
> but no path element is created.

It also replaced an `Object.entries(periodogramData)` iteration with an
explicit `[data1, data2]` array. That is a genuine behavioural fix but still
on the rendering side: `Object.entries` iterated the `{data1, data2}` return
object, so when `data2` was `undefined` the series indexing and the
"remove excess series" `slice(index)` could disagree.

**`86bb5f9` "Minor formatting"** — despite the name, this is where the
*reload* half of the fix landed (+27 in the same component): the `setData()`
guard against the `[[0], [0]]` storage placeholder, the same object→tuple
conversion on the persisted-data path, and recomputation of the "Global
Maxima" series on reload. Also +5 lines in `pulsar.service.ts`.

**`657b709`** is just the merge of those two (plus a gitignore commit).

**Net finding: the current periodogram numerics are identical to what they
were before the bug-fix branch. Nothing in `utils.ts` has changed in either
commit** — its last functional touch is much older (`52decba` "Change step
size", `840d003` "variable: periodogram is now logarithmically scaled").

Everything here reflects the **current fixed state** at `657b709`. The
tuple-conversion logic itself was *not* extracted — it is Highcharts
workaround code, documented here instead.

---

#### What was left behind, and why

**Angular UI / rendering (the bulk of both `periodogram/` folders):**

- `*.component.html`, `*.component.scss`, `*.component.spec.ts` — all of them.
- `pulsar-periodogram.component.ts` / `variable-periodogram.component.ts` —
  empty shell components (10 and ~10 lines, no logic at all).
- `pulsar-periodogram-form.component.ts` (160 lines) /
  `variable-periodogram-form.component.ts` (90 lines) — Angular
  `FormGroup`/`FormControl` wiring, debounce timings, honor-code save-graph
  hooks. The only non-UI content is the compute-button guard
  `if (start < end) service.compute()`, noted here rather than extracted.
- `pulsar-periodogram-highcharts.component.ts` (319 lines) /
  `variable-periodogram-highcharts.component.ts` (120 lines) — Highcharts
  options, series management, axis titles, zoom handling, and the
  object→tuple workaround above. Peak detection and the confidence-threshold
  formula were the only algorithmic content; both extracted to
  `core/peak-detection.ts`.

**State plumbing and persistence:**

- `PulsarStorage` / `VariableStorage` — `localStorage` get/save/reset.
- `PulsarData` / `VariableData` — light-curve data containers. `PulsarData`
  does hold `chartComputedPeriodogramDataArray`, but that is a persistence
  cache of this tool's output, not part of computing it.
- `PulsarChartInfo`, `VariableChartInfo`, `PulsarInterfaceImpl`,
  `VariableInterfaceImpl` — label/interface state.
- All RxJS `BehaviorSubject` / `Subject` / `takeUntil` / `debounceTime`
  plumbing, and the `Highcharts.Chart` handles held by the services.

**File parsing:** the pulsar upload handler's `P_topo` / `SRC_NAME` / `UTC` /
`DATE_OBS` header scraping and column mapping stays with the light curve. Only
the Nyquist bounds math was taken.

---

#### Period folding — judgment call

**Not extracted here** (beyond the interface seam), on the judgment that
folding is primarily light-curve territory: it phase-folds the light curve and
its output is a folded light curve. A separate agent owns `lightcurve/`, and
duplicating the folding transform would be the heavy kind of duplication worth
avoiding.

What *was* taken is only the coupling, in
`pulsar/pulsar-periodogram-folding-link.ts`:

- `foldingRangeFromPeriodogram()` — maps the periodogram's search window onto
  the folding slider bounds on Compute, including the frequency-mode
  inversion. This has to know the period/frequency mode flag, which is
  periodogram semantics.
- `getPeriodStep()` — folding step size, derived from `getJdRange()` which is
  extracted here.

**Left for the lightcurve extraction:** `PulsarService.getPeriodFoldingChartData()`
(pulsar.service.ts 273–314), `VariableService`'s folding equivalent
(variable.service.ts ~165–195), and the `PulsarPeriodFolding` /
`VariablePeriodFolding` model classes. Note that the actual folding transform
depends on **`floatMod`**, which lives in `core/lomb-scargle.ts` here —
whoever owns folding needs that helper, and it is expected to be duplicated.

Also note the coupling recorded in `pulsar.service.util.ts` (lines 617–619):
`PulsarPeriodFolding`'s `periodMin`/`periodMax` defaults (0.1 / 3)
intentionally mirror the periodogram's `startPeriod`/`endPeriod` defaults.
Changing one side silently desynchronises the other.

---

#### Overlap with the lightcurve extraction

Duplication is intentional and expected — these are copied, not shared:

| Symbol | Also needed by lightcurve | Where it is here |
|---|---|---|
| `floatMod` | **yes** — period folding depends on it | `core/lomb-scargle.ts` |
| `rad`, `deg`, `d2HMS`, `d2DMS` | probably (coordinate display) | `core/lomb-scargle.ts` |
| `UpdateSource` enum | yes — form reset plumbing | `core/lomb-scargle.ts` |
| `PulsarDataDict` | **yes** — shared row type | `pulsar/pulsar-periodogram.model.ts` |
| `VariableDataDict`, `errorMSE` | **yes** — shared row type | `variable/variable-periodogram.model.ts` |
| `VariableStarOptions` | **yes** | `variable/variable-periodogram.compute.ts` |
| `getChartVariableDataArray` | **yes** — it *is* the light curve | `variable/variable-periodogram.compute.ts` |
| `getChartPulsarDataArray` | **yes** | `pulsar/pulsar-periodogram.compute.ts` |
| `getJdRange` | likely | `pulsar/pulsar-periodogram.compute.ts` |
| Nyquist bounds math | shares its source function (the upload handler) | `pulsar/pulsar-periodogram-range.ts` |

Nothing under `/home/claude/Kepler/algorithms/lightcurve/` was read or written.

---

#### Framework seams cut

Every seam is marked in-file with `// EXTRACTED:`. Summary:

1. **`@Injectable` / Angular DI** — `PulsarService` and `VariableService` were
   root-provided singletons. Their periodogram methods are now free functions;
   every `this.<getter>()` read became an explicit parameter. Method bodies are
   otherwise unchanged.
2. **RxJS** — `BehaviorSubject` / `Subject` / `takeUntil` / `skip` /
   `debounceTime` all dropped. `PulsarService.compute()` was *only*
   `isComputingSubject.next(!getValue())` (an RxJS toggle telling the chart to
   recompute), so it is documented rather than reproduced.
3. **localStorage write-through** — `setChartComputedPeriodogramDataArray()`
   became an optional `onComputed` callback on the pulsar compute function, so
   the caching side effect stays visible without importing storage.
4. **Angular `@Component`** — `findLocalMax` and the confidence math were
   private methods of the Highcharts component; the surrounding
   `chartObject.addSeries(...)` / `setData(...)` calls are gone.
5. **`FileReader` handler** — the Nyquist bounds math was inline in an upload
   callback; it now takes a `number[]` and returns the bounds instead of
   pushing them through the service.
6. **`ChangeDetectorRef` / `InputSliderValue`** — Angular change-detection
   workarounds (the `Promise.resolve().then(() => cdr.detectChanges())`
   NG0100 dance) dropped entirely.
7. **Highcharts** — no import survives in this folder.

**One deliberate non-cut:** `lombScargle` and `lombScargleWithError` call the
DOM `alert()` on a `ts.length != ys.length` mismatch. That is original
behaviour inside the verbatim core, so it was left in place. A non-browser
host must shim `alert` or that path throws.

**One rename:** in `variable-periodogram.compute.ts` a local named `data`
became `filtered`, because `data` is now the parameter that replaced
`this.getData()`. Marked in-file.

---

#### External npm dependencies

**The extracted code has zero runtime npm dependencies.** It is plain
TypeScript over `Math`, arrays, and (in the two guard clauses) the DOM
`alert`. All imports are relative, within this folder.

Dependencies of the *original* files, all left behind:

| Package | Version in astromancer | Why it did not come along |
|---|---|---|
| `@angular/core` | `^16.2.0` | `@Injectable`, `@Component`, `ChangeDetectorRef` |
| `@angular/forms` | `^16.2.0` | `FormGroup` / `FormControl` in the form components |
| `highcharts` | `^11.1.0` | all rendering; also the subject of the recent bug fix |
| `rxjs` | `~7.5.0` | service subjects, debouncing |
| `typescript` | `~4.9.5` | build only |

Target language level: the code uses `**`, optional chaining, and
`Array.prototype.reduce` — ES2020 is sufficient.

---

#### Known limitations of this extraction

- **Not compiled or type-checked.** No Node/npm/tsc is available in this
  environment (`node`, `npm`, `npx`, `tsc` all absent; astromancer has no
  `node_modules`). The verbatim core was verified by `diff`; the
  parameter-threaded driver functions have been reviewed by eye but not
  compiled. Worth a `tsc --noEmit` pass on a machine with a toolchain.
- **No tests.** The astromancer `*.spec.ts` files are Angular TestBed
  scaffolding with no algorithmic assertions, so there was nothing to bring.
- The `AgentVault` shared memory at `/srv/agent-vault` referenced in the
  operating instructions was **not accessible** from this environment, so no
  vault notes were consulted or updated. The repo was treated as the source
  of truth.
