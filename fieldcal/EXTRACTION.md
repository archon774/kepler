# Field calibration — extraction record

Photometric zero-point calibration, extracted from the Skynet optical
data-processing pipeline (`/home/claude/skynet`) into `Kepler/fieldcal/`.

This was an **extraction, not a rewrite**. Algorithms, numeric constants,
ordering and comments are verbatim. Every place a Skynet dependency was cut is
marked in-code with an `# EXTRACTED:` comment; this document is the index of
those seams.

---

## 1. What field calibration does

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

## 2. Files copied — exact provenance

All source paths are relative to
`/home/claude/skynet/packages/py/skynet-db/skynet_db/runners/`
unless noted. `OPD/` abbreviates
`observation_asset_processing/optical_data_processing/`.

### Core algorithm

| Kepler file | Lines | Source | Source lines | Fidelity |
|---|---|---|---|---|
| `field_cal.py` | 735 | `OPD/field_cal.py` | 701 (all) | Verbatim. Diff vs original is imports + 4 `deps.` call seams + 2 type annotations + the added parity annotation at the `apcorr_tol` line. No logic touched. |
| `catalog_query.py` | 451 | `OPD/catalog_query.py` | 436 (all) | Verbatim. Diff vs original is imports + 1 type annotation. |
| `solution.py` | 166 | `utils.py` | 468–603 (`_sigma_eq`, `calc_solution`) | **Byte-identical body** (verified by diff). |
| `ref_mag.py` | 217 | `utils.py` | 605–799 (`_SAFE_NAMES`, `_ALLOWED_TOKENS`, `_get_catalog_filter_lookup`, `_safe_eval_expr`, `_resolve_filter_lookup_candidate`, `_ref_mag_filter_token_candidates`, `resolve_ref_mag_for_filter`) | Verbatim (one blank line lost trailing whitespace). |
| `schemas.py` | 367 | `common/schemas.py` | field-cal subset of 331 | Verbatim per class; base model reduced (see §4.1). |
| `batch_wcs_photometry_zeropoint_export.py` | 195 | `OPD/batch_wcs_photometry_zeropoint_export.py` | 180 (all) | Verbatim except the repo-root discovery seam (§4.6). |
| `deps.py` | 97 | — | — | **New file.** Seam module only; contains no math. |
| `__init__.py` | 64 | — | — | **New file.** Public API surface. |

### Catalog metadata (`catalogs/`)

Metadata only — band tables and filter/colour transforms. Query backends
severed; see §6.

| Kepler file | Lines | Source (`OPD/catalogs/`) | Source lines |
|---|---|---|---|
| `catalogs/__init__.py` | 104 | `__init__.py` | 87 |
| `catalogs/catalog.py` | 69 | `catalog.py` | 45 |
| `catalogs/apass_catalog.py` | 40 | `apass_catalog.py` | 37 |
| `catalogs/panstarrs_catalog.py` | 44 | `panstarrs_catalog.py` | 43 |
| `catalogs/twomass_catalog.py` | 41 | `twomass_catalog.py` | 40 |
| `catalogs/tycho_catalog.py` | 28 | `tycho_catalog.py` | 27 |
| `catalogs/ucac_catalog.py` | 31 | `ucac_catalog.py` | 30 |
| `catalogs/stetson_globs_catalog.py` | 37 | `stetson_globs_catalog.py` | 36 |
| `catalogs/skymapper_catalog.py` | 48 | `skymapper_catalog.py` | 58 |
| `catalogs/sdss_catalog.py` | 55 | `sdss_catalog.py` | 213 |
| `catalogs/usno_catalog.py` | 71 | `usno_catalog.py` | 63 |
| `catalogs/landolt_catalog.py` | 91 | `landolt_catalog.py` | 83 |
| `catalogs/vsx_catalog.py` | 113 | `vsx_catalog.py` | 105 |
| `catalog_plugins.py` | 194 | `common/catalog_plugins/{__init__,catalog,apass_catalog,panstarrs_catalog}.py` | 49+45+37+43 |

A diff against every original confirms **zero changes** to any `mags`,
`filter_lookup`, `col_mapping`, `sort` or `row_limit` value. The only removed
lines are the severed backend methods and the rewritten imports.

### Vendored skylib subset (`skylib/`)

Byte-for-byte copies from `/home/claude/skynet/packages/py/skylib/skylib/`,
directory layout preserved so nothing depends on an installed `skylib`.

| Kepler file | Lines | Source |
|---|---|---|
| `skylib/util/stats.py` | 772 | `skylib/util/stats.py` (`chauvenet` — the rejection kernel) |
| `skylib/util/angle.py` | 60 | `skylib/util/angle.py` (`angdist`) |
| `skylib/util/fits.py` | 211 | `skylib/util/fits.py` (`get_fits_time`) |
| `skylib/util/__init__.py` | 8 | verbatim |
| `skylib/__init__.py` | 16 | rewritten header; `from ._version import __version__` dropped |

All three modules are self-contained (numpy / numba / astropy only, no
intra-skylib imports), so they were copied whole rather than sliced.

**Known duplication:** `Kepler/photometry/skylib/` vendors a larger subset of the
same library, including identical copies of `util/stats.py`, `util/angle.py` and
`util/fits.py`. This duplication is deliberate and agreed across the extraction
agents — each domain folder stands alone and none reaches into another.
Consolidating the three `skylib/` copies into one shared location is a
repo-level decision, deliberately not made here.

---

## 3. What was left behind, and why

| Left in Skynet | Why |
|---|---|
| `skynet_db.models.ObservationAssetProcessingRun` | SQLAlchemy ORM row. Field calibration reads exactly two attributes off it. |
| `skynet_db.models.File`, S3 asset download (`_download_to_path`), `write_image_product_fits`, `get_worker_tmp_file_path` (`utils.py`) | Object storage / temp-file plumbing. Never reached from field calibration. |
| `skynet_sdk.schemas.SkynetBaseModel` registry (`model_registry`, `register_union`, `rebuild_all_models`) | FastAPI/SDK schema-generation infrastructure. |
| The other ~700 lines of `utils.py` (header parsing, pixel-scale estimation, RA/Dec guessing, trig helpers, VizieR cache pruning, `query_catalogs_for_image`, WCS box helpers, DB session use) | Not field calibration. Only `calc_solution` and `resolve_ref_mag_for_filter` are reached. |
| `OPD/photometry.py`, `OPD/source_extraction.py` | Photometry / SEP extraction — `Kepler/photometry/`. Reached via `deps`. |
| `OPD/wcs.py` (astrometry.net / ATLAS plate solving, 36 KB) | Plate solving — `Kepler/wcs/`. Reached via `deps`. |
| `OPD/catalogs/vizier_catalogs.py` (352 lines), `OPD/catalogs/config.py`, the SDSS SQL backend, `catalogs/local/` | Catalog query backends — see §6. |
| `common/schemas.py`: `WcsCalibrationSettings`, `Photometry`, `ImageProperties` | Not field-cal settings or results. |
| `skylib` beyond `util/{stats,angle,fits}.py` | Not reached from field calibration. |

---

## 4. Every seam cut

Each is greppable in-code: `grep -rn "EXTRACTED" fieldcal/`.

### 4.1 `SkynetBaseModel` → reduced base (`schemas.py`)

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

### 4.2 `ObservationAssetProcessingRun` → duck-typed `Any`

Three sites: `field_cal.perform_field_calibration`,
`field_cal._filter_variable_stars`, `catalog_query.query_catalogs_for_processing_run`.

Only `.id` (source-ID prefix + logging) and `.observation_asset_id` (used as
`file_id`) are read. In `catalog_query` the parameter is never read at all — it
is retained purely for call-signature parity. `schemas.ProcessingRunRef` is a
concrete stand-in for standalone callers.

### 4.3 Cross-domain callables → `fieldcal/deps.py`

| `deps` name | Was | Belongs in |
|---|---|---|
| `run_photometry` | `from .photometry import run_photometry` | `Kepler/photometry/` |
| `run_source_extraction` | `from .source_extraction import run_source_extraction` | `Kepler/photometry/` |
| `get_source_radec` | `from .source_extraction import get_source_radec` | `Kepler/photometry/` |
| `build_wcs_for_processing_run` | `from .wcs import build_wcs_for_processing_run` | `Kepler/wcs/` |
| `solve_wcs` | `from .wcs import solve_wcs` (batch driver only) | `Kepler/wcs/` |

Unassigned, each raises `FieldCalDependencyError` naming the original symbol.
Call sites use `deps.<name>(...)` rather than a `from .deps import <name>`
binding so late assignment works.

One behavioural note on `build_wcs_for_processing_run`: the Skynet original is
`build_wcs_from_header(header) or build_wcs_from_processing_run_solution(processing_run)`.
The second branch reconstructs a WCS from persisted DB rows and is ORM
persistence — it is not reproduced. A header-only implementation gives the
behaviour field calibration actually depends on.

### 4.4 Catalog query backends → `NotImplementedError`

`catalogs/*.py` classes no longer subclass `VizierCatalog`; they subclass the
local metadata-only `Catalog`, whose `query_box` / `query_circ` /
`query_objects` / `table_to_sources` raise. Consequence: the
`query_catalogs_for_processing_run` *network* path is inert until Kepler
supplies backends. **Everything else works**, including filter-aware catalog
selection, reference-magnitude resolution, matching and the full zero-point
solve, provided sources arrive via `catalog_sources` / `detected_sources`.

Two backend overrides that contain real magnitude math were **kept rather than
dropped**, and now call a raising `super()`:

- `LandoltCatalog.table_to_sources` — colour-index → UBVRI conversion with
  error propagation.
- `USNOB1Catalog.table_to_sources` — B/R synthesis from B1/B2, R1/R2.

They become live the moment a `table_to_sources` backend is supplied.
`VSXCatalog.table_to_sources` does not call `super()` and is fully functional
as-is.

### 4.5 `skylib` absolute imports → vendored relative imports

`from skylib.util.{stats,angle,fits} import ...` →
`from .skylib.util.{stats,angle,fits} import ...` (and `..` from `solution.py`'s
perspective, `.` from the package root). Mirrors the pattern used by
`Kepler/photometry/`.

### 4.6 Repo-root discovery (batch driver)

`_find_repo_root()` walked ancestors looking for `packages/py/skynet-db`, then
derived `../skynet-data/pipeline_data`. That marker cannot exist in Kepler, so
the walk was replaced with `$KEPLER_PIPELINE_DATA_DIR` (default
`./pipeline_data`). Only *where the driver looks for data* changed; the batch
logic and every calibration setting literal are untouched.

---

## 5. Deliberate parity behaviours preserved (do not "fix")

1. **`apcorr_tol` forced to 0** — `field_cal.py:612` (`:645` here):
   `phot_settings.model_copy(update={"apcorr_tol": 0.0})`. This is what disables
   aperture correction during calibration photometry; the aperture kernel in
   `Kepler/photometry/` gates its correction pass on `apcorr_tol > 0`
   (`skylib/photometry/aperture.py:426`). Restoring the caller's default
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

5. **Two divergent catalog registries** — `catalogs/CATALOGS` (11 catalogs) and
   `catalog_plugins/CATALOG_OPTIONS` (APASS + PanSTARRS). They are *not*
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

6. **Two divergent `Catalog.__init__` merge semantics** —
   `catalogs/catalog.py` rebinds an instance-level copy
   (`self.filter_lookup = {**class_level, **arg}`); `catalog_plugins.Catalog`
   mutates the class-level dict in place (`self.filter_lookup.update(arg)`), so
   constructing that plugin permanently rewrites its class attribute. Effective
   merged content is the same. Both are preserved as written rather than
   normalised.

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

## 6. Catalog-backend code for `Kepler/catalogs/` — NOT copied here

Per scope, none of this was moved into `Kepler/catalogs/`. Flagging only.

| Skynet source | Size | What it is |
|---|---|---|
| `OPD/catalogs/vizier_catalogs.py` | 352 lines | `VizierCatalog` base: astroquery `Vizier` box/circle/object queries, `table_to_sources` row mapper (evaluates `col_mapping` expressions, builds `Mag` objects), `_columns` derivation from `col_mapping`+`mags`+`sort`, cache-granularity rounding of RA/Dec/size, and a module-import-time monkey-patch of `astroquery.query.to_cache` / `AstroQuery` to swallow cache errors. |
| `OPD/catalogs/config.py` | 5 lines | `VIZIER_SERVER`, `VIZIER_CACHE_ENABLED`, `VIZIER_CACHE_AGE_DAYS`. |
| `OPD/catalogs/sdss_catalog.py` | ~110 of 213 lines | `AfterglowSDSS(SDSSClass)` — bespoke SDSS SQL generation for rect/circular regions incl. pole and RA-wrap handling — plus the `query_objects` / `query_box` / `query_circ` overrides driving it. |
| `OPD/catalogs/skymapper_catalog.py` | ~20 of 58 lines | `query_region` override that defaults the `flags=0` column constraint. The full original body is reproduced in a comment in `fieldcal/catalogs/skymapper_catalog.py` so the behaviour is not lost. |
| `OPD/catalogs/local/` | untracked | A local catalog backend present **only as `__pycache__`** (`backend`, `config`, `engine`, `errors`, `health`, `normalize`, `routing`). No `.py` sources on disk and nothing in git. Not imported by `catalogs/__init__.py`. Someone should establish whether the sources still exist anywhere. |
| `utils.py::prune_vizier_cache` | ~27 lines | VizieR cache maintenance. |
| `utils.py::query_catalogs_for_image` + `_infer_image_shape`, `_wcs_boxes_from_image_wcs` | ~105 lines | A second, image-oriented catalog query entry point parallel to `catalog_query.query_catalogs_for_processing_run`. Not reached by field calibration. |
| `common/catalog_plugins/vizier_catalogs.py` etc. | ~13 KB | Near-duplicate of the above under the second plugin package. |

**Recommended contract** when `Kepler/catalogs/` lands: provide
`table_to_sources(table)`, `query_box(ra_hours, dec_degs, width_arcmins, height_arcmins, constraints, limit=None)`,
`query_circ(ra_hours, dec_degs, radius_arcmins, constraints, limit=None)` and
`query_objects(names)`. `fieldcal/catalogs/` can then be reduced to metadata
mixins over those backends. Until then `fieldcal` is fully usable by passing
catalog sources in directly.

---

## 7. External dependencies

Required:

- `numpy`
- `scipy` — `scipy.spatial.cKDTree` (source matching), `scipy.optimize.brenth`
  (intrinsic-scatter solve)
- `astropy` — `astropy.wcs.WCS`, `astropy.io.fits` (batch driver),
  `astropy.table.Table` (type hints on preserved `table_to_sources` overrides)
- `pydantic` v2 — `pydantic.alias_generators.to_camel`
- **`numba`** — *hard* import-time dependency of the vendored
  `skylib/util/{stats,angle}.py`. There is no non-numba fallback path;
  `chauvenet` and `angdist` are `@njit`-decorated at import.

Removed: `sqlalchemy`, `skynet_db`, `skynet_sdk`, `boto3`/S3, `astroquery`
(left with the catalog backends).

---

## 8. Verification performed

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
