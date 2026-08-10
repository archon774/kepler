# Catalogs — extraction record

## 1. What this package is

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

## 2. Files copied — exact provenance

Upstream carried **two parallel catalog plugin packages** that had drifted apart.
Both are reproduced, because the drift is load-bearing (§4).

### Primary registry — `CATALOGS`

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

### Secondary registry — `CATALOG_OPTIONS`

`catalog_options.py` merges four files from
`skynet/packages/py/skynet-db/skynet_db/runners/common/catalog_plugins/`:
`catalog.py` (45), `apass_catalog.py` (37), `panstarrs_catalog.py` (43),
`__init__.py` (49). Colour transforms and `NARROWBAND_FILTER_LOOKUP` verbatim.

### Schemas and vocabulary

| Kepler file | Upstream | Notes |
|---|---|---|
| `schemas.py` | `skynet_db/runners/common/schemas.py` (331) — catalog subset | Field names, aliases and the NaN-stripping serializer preserved |
| `simbad.py` | `skynet/apps/public-api/public_api/services/target_search.py` lines 27–234 | 206-entry otype table, verbatim |

Afterglow's `afterglow_core/models/catalogs.py` and
`afterglow_core/resources/catalog_plugins/*` are the common ancestor of the
Skynet copies. Where the two disagreed, Kepler takes Skynet's — it is the
de-Flasked, more recently maintained fork — except where noted in
`query/EXTRACTION.md` §3.

## 3. What was renamed, and why

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

## 4. The two registries are not redundant

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

## 5. Deliberate behaviours preserved (do not "fix")

### 5.1 `CatalogSource` silently drops four VSX fields

`VSXCatalog.table_to_sources` constructs sources with `name`, `type`,
`amplitude` and `period`. `CatalogSource` declares none of them, and Pydantic's
default `extra='ignore'` drops them. Upstream behaves identically. Field
calibration uses VSX only for positional variable-star rejection, so nothing
reads those fields — but adding them would change what downstream consumers see.

### 5.2 Landolt's U-magnitude error uses the wrong colour index

`landolt_catalog.py` computes the uncertainty on U as
`hypot(B_err, V_R_err)` where the colour algebra calls for `U_B`. The U
*magnitudes* are correct; only their reported uncertainty is wrong. Preserved as
upstream wrote it, and flagged inline.

### 5.3 Two VSX defects were fixed upstream, and the fixes are kept

`vsx_catalog.py` carries inline notes on both: the `OID` integer is coerced to
`str` because `CatalogSource.id` is typed as a string, and the passband
assignment is wrapped in a `try`. Without either, a Pydantic validation error
propagates into `fieldcal.field_cal._filter_variable_stars`, which swallows it —
silently disabling variable-star rejection rather than failing. Regressing
these produces wrong zero points with no error.

### 5.4 `catalog_options.py` mutates class-level dicts

Its `_MutatingCatalog.__init__` updates the *class* `filter_lookup` in place,
where `catalog.Catalog` rebinds an instance-level copy. Both upstreams did it
their respective ways. The merged content is identical for the two
single-instantiation classes involved; the aliasing difference is preserved
rather than normalized, and the classes are private to that module.

### 5.5 `filter_lookup` may be absent entirely

`Catalog` annotates `filter_lookup` without assigning it, so a plugin declaring
no transforms (USNO-B1, Stetson) has no such attribute at all — not an empty
dict. Every reader uses `getattr(..., {})`. Upstream had the same shape.

## 6. Dependencies

`pydantic` v2 only. Deliberately no `astroquery`, no `astropy` except
`astropy.table.Table` as a type hint on three `table_to_sources` overrides.

## 7. Verification performed

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

Not verified: any live VizieR or SkyServer response. See `query/EXTRACTION.md` §6.
