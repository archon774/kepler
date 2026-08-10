# Query — extraction record

## 1. What this package is

`query/` is Kepler's remote catalog access layer. It owns every network call in
the catalog path: the VizieR engine, SDSS's SkyServer SQL backend, SIMBAD
identifier resolution, the astroquery response cache, and the orchestration that
turns "these catalogs, this field, this filter" into a list of `CatalogSource`.

It sits above `catalogs/`, which declares what each catalog contains and imports
nothing network-related. `query/` imports `catalogs/`; never the reverse.

## 2. Files copied — exact provenance

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

## 3. Where the two upstreams disagreed

Afterglow and Skynet's copies had drifted. Per file, Kepler took:

| Piece | Taken from | Why |
|---|---|---|
| VizieR engine | Afterglow | Superset — Skynet dropped the configurable server and the custom-catalog factory, both restored here |
| `SDSS._args_to_payload` signature | Skynet | Afterglow passed `radius=None` to `super()`, which newer astroquery rejects |
| `mags` value type | Skynet | Lists, not tuples — Afterglow's tuples were a Marshmallow artifact |
| USNO-B1 `B`/`R` band columns | Skynet | Afterglow declared them as empty tuples, so B and R were never read |
| SDSS narrowband aliases | Skynet | Afterglow had no `Halpha`/`OIII`/`SII` entries |
| Default VizieR mirror | Skynet | `vizier.cds.unistra.fr`, replacing `vizier.cfa.harvard.edu` |

## 4. Every seam cut

### 4.1 Flask `current_app.config` → `query/config.py`

Afterglow read `VIZIER_SERVER`, `VIZIER_CACHE` and `VIZIER_CACHE_AGE` from Flask
config, which made importing the catalog plugins require an application context.
Kepler reads the environment. Defaults reproduce upstream values. No effect on
query results.

### 4.2 Import-time monkey-patch → explicit call

Afterglow patched `astroquery.query.to_cache` and `AstroQuery` as a bare side
effect of module import. Kepler moves it to
`cache.install_cache_error_suppression()`, which `vizier.py` calls on import —
so the default behaviour is unchanged, but the patch is greppable and a caller
can opt out. Patching a third-party module's globals should not be invisible.

### 4.3 `CUSTOM_VIZIER_CATALOGS` loop → `build_custom_vizier_catalog()`

Afterglow built custom catalog classes in an import-time `for` loop over Flask
config, wrapped in `try/except Exception` that logged and continued. Kepler
exposes the same class construction as a function that raises. A misconfigured
catalog should be visible where it is registered, not absent at query time.

### 4.4 `processing_run` parameter dropped

`query_catalogs_for_processing_run` took an `ObservationAssetProcessingRun`
SQLAlchemy row as its first argument and never read it — it was there for
call-site symmetry. Kepler's `query_catalogs` omits it rather than carry a
duck-typed placeholder. `fieldcal` call sites updated.

### 4.5 SIMBAD resolver: local-database branches severed

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

### 4.6 `AfterglowError` → `UnknownCatalogError(ValueError)`

`afterglow_core/errors/catalog.py` defined `UnknownCatalogError` as an
HTTP-404-carrying `AfterglowError`. Kepler is a library here, so it subclasses
`ValueError` — which keeps the `raise ValueError('Unknown catalog "…"')` that the
query runner used catchable the same way. Callers needing a 404 map it at their
edge.

### 4.7 Job wrapper not extracted

`afterglow_core/.../job_plugins/catalog_query_job.py` (347 lines) is the same
orchestration wrapped as a Marshmallow job class reading images from a data-file
store. Its algorithmic content — the FOV geometry and the combined-FOV bounding
box — is in `geometry.py`. The `Job`/`JobResult`/`get_data_file_fits` wrapper is
service infrastructure and was left behind.

### 4.8 Class renames

`AfterglowSDSS` → `KeplerSDSS`. Generated SQL unchanged. See
`catalogs/EXTRACTION.md` §3 for the rest.

## 5. Deliberate behaviours preserved (do not "fix")

### 5.1 Cache rounding is observable

With the cache enabled, `query_box` and `query_circ` snap the region centre to
10 arcsec and round sizes *up* to 0.2 arcmin, so near-identical fields share a
cache entry. This means a cached query returns rows for a slightly larger,
grid-aligned region than asked for. The WCS path clips afterwards; a caller
using `query_circ` directly does not. Turning the cache off changes results near
a field edge.

### 5.2 `_derive_columns` requests columns named `int` and `float`

The identifier filter skips NumPy exports and `str` methods but not Python
builtins, so Landolt's sexagesimal-parsing expressions contribute `'int'` and
`'float'` as VizieR column names. VizieR ignores unknown columns, so the query
still returns correct data — which is why it survived upstream unnoticed.
Left as-is: filtering builtins changes the request Kepler sends and needs
validation against a live VizieR.

### 5.3 `build_custom_vizier_catalog`'s character class is wrong

`[^a-zA-z0-9_]` — lowercase `z` — additionally admits ``[ \ ] ^ _ ` ``. Cosmetic;
the generated name is never parsed. Preserved.

### 5.4 Rows with no magnitudes are dropped

`table_to_sources` appends a source only `if source.mags`. A source Kepler cannot
photometer is not useful, and field calibration depends on the filtering.
`len(table)` and `len(sources)` differ routinely.

### 5.5 A magnitude of 99 or more means "not measured"

VizieR's null convention in several tables. Applied before a `Mag` is built.

### 5.6 `skip_failed` never skips the last catalog

In WCS mode, a failing catalog is skipped only while another remains to try. The
last one always raises — otherwise a total provider outage would be
indistinguishable from an empty field.

### 5.7 `SkyMapperQueryBackend.query_region` mutates the caller's dict

It calls `constraints.setdefault('flags', '0')` on the dict it was handed. A
caller reusing one dict across catalogs finds `flags` added after querying
SkyMapper. Upstream did the same; Kepler's runner passes a fresh dict per call.

### 5.8 SDSS ignores `constraints`

Accepted on all three SDSS query methods and never used — the SQL applies its own
quality predicates and upstream never wired column filters through. A caller
passing constraints to SDSS gets unfiltered results, silently. Documented on the
class rather than changed, because raising would break existing call sites that
pass a shared constraints dict to a catalog list including SDSS.

### 5.9 `combined_bounding_box` is disabled upstream

Afterglow guarded the call with `if False:` and fell through to querying each
field separately. The reason was never recorded. Kepler keeps it as a working,
tested function that nothing calls. Enabling it is a behaviour change needing its
own validation.

### 5.10 Two footprint implementations, both kept

`boxes_from_wcs` projects the four corners with `CRVAL` moved to (0,0), which
handles rotation and the cos(dec) narrowing. `image_boxes_from_wcs` multiplies
pixel scale by axis length, which is blind to both but works without
`array_shape`. Upstream had both; they return different widths for the same WCS
(verified: 1.02297° vs 1.02400° on a 1024² TAN field). Prefer the former.

## 6. External dependencies

`astroquery==0.4.11` (already pinned in `pyproject.toml`; no change required),
`astropy`, `numpy`, and `catalogs/`.

Network access is required only at query time. No module makes a network call at
import time.

## 7. Verification performed

Offline only — no live VizieR, SkyServer or SIMBAD calls were made.

* All backends bind with the intended MRO:
  `SDSSCatalogQueryable → SDSSCatalog → SDSSQueryBackend → VizierCatalog → Catalog`,
  so plugin `table_to_sources` overrides reach the engine's implementation via
  `super()` exactly as upstream's single-class arrangement did.
* Registry `filter_lookup` overlays survive binding.
* Column derivation for APASS, Landolt, VSX, Tycho, USNO — including §5.2.
* Row mapping and all three photometric transforms against synthetic astropy
  tables; see `catalogs/EXTRACTION.md` §7.
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
