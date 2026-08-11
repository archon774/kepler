# Field calibration — extraction record

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
| `solution.py` | 166 | `utils.py` | 468–603 (`_sigma_eq`, `calc_solution`) | **Byte-identical body** (verified by diff). |
| `ref_mag.py` | 217 | `utils.py` | 605–799 (`_SAFE_NAMES`, `_ALLOWED_TOKENS`, `_get_catalog_filter_lookup`, `_safe_eval_expr`, `_resolve_filter_lookup_candidate`, `_ref_mag_filter_token_candidates`, `resolve_ref_mag_for_filter`) | Verbatim (one blank line lost trailing whitespace). |
| `schemas.py` | 316 | `common/schemas.py` | field-cal subset of 331 | Verbatim per class; base model reduced (§4.1); catalog schemas re-exported from `algorithms/catalogs/` (§4.4). |
| `batch_wcs_photometry_zeropoint_export.py` | 195 | `OPD/batch_wcs_photometry_zeropoint_export.py` | 180 (all) | Verbatim except the repo-root discovery seam (§4.6). |
| `deps.py` | 130 | — | — | **New file.** Seam module only; contains no math. |
| `__init__.py` | 58 | — | — | **New file.** Public API surface. |

### Catalog metadata — MOVED OUT

`fieldcal` no longer owns catalogs. What was `fieldcal/catalogs/` (13 files) and
`fieldcal/catalog_plugins.py` now lives in `algorithms/catalogs/`, and what was
`fieldcal/catalog_query.py` is `algorithms/query/selection.py`,
`algorithms/query/geometry.py` and `algorithms/query/runner.py`. Provenance for
all of it moved to `algorithms/catalogs/EXTRACTION.md` and
`algorithms/query/EXTRACTION.md`.

The catalog *backends* severed by this extraction — the VizieR engine, SDSS's
SkyServer SQL, the SkyMapper constraint override, the astroquery cache layer —
have since been extracted into `algorithms/query/`, so the network path
described in §4.4 is no longer inert.

Field calibration now reads catalog metadata by importing `algorithms.catalogs`
directly (pure data, no network stack) and reaches the network through
`deps.query_catalogs`.

### Vendored skylib subset (`algorithms/skylib_lite/`)

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

## 3. What was left behind, and why

| Left in Skynet | Why |
|---|---|
| `skynet_db.models.ObservationAssetProcessingRun` | SQLAlchemy ORM row. Field calibration reads exactly two attributes off it. |
| `skynet_db.models.File`, S3 asset download (`_download_to_path`), `write_image_product_fits`, `get_worker_tmp_file_path` (`utils.py`) | Object storage / temp-file plumbing. Never reached from field calibration. |
| `skynet_sdk.schemas.SkynetBaseModel` registry (`model_registry`, `register_union`, `rebuild_all_models`) | FastAPI/SDK schema-generation infrastructure. |
| The other ~700 lines of `utils.py` (header parsing, pixel-scale estimation, RA/Dec guessing, trig helpers, DB session use) | Not field calibration. Only `calc_solution` and `resolve_ref_mag_for_filter` are reached. Its VizieR cache pruning, `query_catalogs_for_image` and WCS box helpers went to `algorithms/query/` — see `algorithms/query/EXTRACTION.md`. |
| `OPD/photometry.py`, `OPD/source_extraction.py` | Photometry / SEP extraction — `algorithms/photometry/`. Reached via `deps`. |
| `OPD/wcs.py` (astrometry.net / ATLAS plate solving, 36 KB) | Plate solving — `algorithms/wcs/`. Reached via `deps`. |
| `OPD/catalogs/*`, the SDSS SQL backend | Catalogs and their query backends — now `algorithms/catalogs/` and `algorithms/query/`. See §6. |
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

Two sites: `field_cal.perform_field_calibration` and
`field_cal._filter_variable_stars`.

Only `.id` (source-ID prefix + logging) and `.observation_asset_id` (used as
`file_id`) are read. `schemas.ProcessingRunRef` is a concrete stand-in for
standalone callers. The third upstream site was the catalog query entry point,
which never read the parameter at all; `algorithms/query/runner.py` drops it (§4.4).

### 4.3 Cross-domain callables → `algorithms/fieldcal/deps.py`

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

### 4.4 Catalog ownership → `algorithms/catalogs/` and `algorithms/query/`

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

### 4.5 `skylib` absolute imports → shared `skylib_lite` imports

`from skylib.util.{stats,angle,fits} import ...` →
`from algorithms.skylib_lite.util.{stats,angle,fits} import ...`. Mirrors the
pattern used by `algorithms/photometry/` and `algorithms/wcs/`.

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
   now live in `algorithms/catalogs/`; see `algorithms/catalogs/EXTRACTION.md`
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
   documented in `algorithms/catalogs/EXTRACTION.md` §5.4.

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

## 6. Catalog-backend code — now extracted

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

## 7. External dependencies

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
