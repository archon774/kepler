# Kepler

Kepler is an early-stage astronomy tooling repository. Its current state is a
small installable Python tool collection, extracted astronomy algorithms, a
split database-query tool surface, and an architecture document for turning
those pieces into a coherent tool surface.

## Current Contents

| Path | Status | What it contains |
|---|---|---|
| `tools/` | Python tools | Plain Python wrappers for WCS description, catalog metadata, reference-band resolution, zero-point solving, local artifact inspection, and remote database/archive queries. |
| `algorithms/wcs/` | Extracted Python algorithm | Skynet WCS calibration: source extraction, FITS-header hinting, astrometry.net `solve-field`, ATLAS triangle solving, solution validation, and FITS-header write-back. |
| `algorithms/photometry/` | Extracted Python algorithm | Skynet source extraction and aperture photometry using the shared `algorithms/skylib_lite/` Skylib subset. |
| `algorithms/fieldcal/` | Extracted Python algorithm | Skynet photometric zero-point calibration: catalog-source matching, variable-star filtering, reference-magnitude resolution, and weighted zero-point solving. |
| `algorithms/skylib_lite/` | Shared Python support | Consolidated local Skylib subset used by WCS, photometry, and field calibration: astrometry, SEP extraction, background estimation, aperture photometry, FITS helpers, angle math, and statistics. |
| `algorithms/catalogs/` | Extracted Python algorithm | Skynet and Afterglow photometric catalog declarations, SIMBAD object-type vocabulary, and provider lookup tables used by ADS/NED/ATNF tools. Declaration only — no network code. |
| `algorithms/query/` | Extracted Python algorithm | Skynet and Afterglow remote catalog access: the VizieR engine, SDSS SkyServer SQL, SIMBAD identifier resolution, astroquery cache handling, filter-aware catalog selection, and WCS-footprint query orchestration. |
| `algorithms/lightcurve/` | Extracted TypeScript algorithm | Astromancer pulsar and variable-star light-curve ingestion, transformation, and period-folding logic with Angular/RxJS/Highcharts removed. |
| `algorithms/periodogram/` | Extracted TypeScript algorithm | Astromancer Lomb-Scargle periodogram logic, peak/confidence helpers, pulsar range defaults, and periodogram-to-folding coupling. |
| `algorithms/hrdiagram/` | Extracted TypeScript algorithm | Astromancer cluster/HR-diagram logic: field-star removal, isochrone matching, extinction offsets, cluster summaries, and result projections. |
| `package.json` / `tsconfig.json` | TypeScript tooling | Private npm metadata and compiler configuration for the extracted TypeScript algorithm modules. |
| `docs/tool-architecture.md` | Architecture | Master package architecture: public tools, algorithm ownership, future services, runtime policy, and `skylib_lite` consolidation. |

Each extracted domain folder has an `EXTRACTION.md` file with provenance,
severed framework dependencies, known parity behaviors, dependency notes, and
verification already performed.

## Repository Shape

```text
Kepler/
  pyproject.toml                 # Python package metadata and dependencies
  uv.lock                        # uv lockfile for reproducible installs
  package.json                   # TypeScript toolchain metadata
  tsconfig.json                  # TypeScript compiler smoke-check config
  docs/
    tool-architecture.md         # master package architecture
  tools/                         # public Python tool wrappers, runner, shared models
  algorithms/
    wcs/                         # Python WCS extraction from Skynet
    photometry/                  # Python photometry extraction from Skynet
    fieldcal/                    # Python zero-point calibration extraction
    skylib_lite/                 # shared vendored Skylib subset
    catalogs/                    # Python catalog declarations (no network code)
    query/                       # Python remote catalog access (VizieR/SDSS/SIMBAD)
    lightcurve/                  # TypeScript light-curve extraction
    periodogram/                 # TypeScript periodogram extraction
    hrdiagram/                   # TypeScript HR-diagram extraction
```

## Python Setup

Use `uv` to create the virtual environment and install the Python package with
its dependencies:

```bash
uv sync
```

`pyproject.toml` is the installable package metadata and includes the Python
dependencies needed by the split database tools and extracted algorithm modules.
`uv.lock` records the resolved dependency set.

Some extracted runtime paths also require non-Python solver data called out in
the relevant `EXTRACTION.md` files, including astrometry.net index files and
local UCAC4/UCAC5 catalogs.

## Python Entry Points

ADS queries require `ADS_DEV_KEY`. The optional Anthropic runner exposed by
`tools.runner` requires `ANTHROPIC_API_KEY`.

The plain Python tools live under `tools`:

```python
from tools.astrometry import describe_image_wcs
from tools.catalogs import list_photometric_catalogs, resolve_reference_band
from tools.calibration import solve_zeropoint_from_measurements
from tools.simbad import search_simbad
from tools.vizier import search_vizier
from tools.ned import search_ned
from tools.ads import search_ads, build_literature_review
from tools.mast import search_mast
from tools.mpc import search_mpc
from tools.atnf import search_atnf
from tools.casda import search_casda
from tools.workspace import describe_artifact, list_artifacts
```

An optional agentic runner is available for wiring these tools into an
Anthropic tool-use loop:

```bash
ANTHROPIC_API_KEY=... uv run kepler-astro-query "all historical radio data on Cassiopeia A"
```

Advanced callers can still import the extracted algorithm packages directly:

```python
from algorithms.wcs.wcs import solve_wcs
from algorithms.photometry.pipeline.photometry import run_photometry, perform_photometry
from algorithms.photometry.pipeline.source_extraction import run_source_extraction
from algorithms.fieldcal import perform_field_calibration, calc_solution
from algorithms.query.runner import query_catalogs
from algorithms.query.simbad import resolve_simbad
```

`fieldcal` deliberately does not own WCS, photometry, or catalogs. Before using
`perform_field_calibration`, wire the cross-domain callables in
`algorithms.fieldcal.deps` to the implementations from `algorithms.wcs` and
`algorithms.photometry`. Catalogs are the exception:
`algorithms.fieldcal.deps.query_catalogs` already defaults to `algorithms.query`.

Catalog metadata and catalog access are separate on purpose. Import
`algorithms.catalogs` for band tables, colour transforms, and provider
vocabularies; it is pure data and pulls in no network stack. Import
`algorithms.query.registry` when you need to actually fetch sources.

## Catalog Query Configuration

The remote catalog backends read settings from environment variables:

- `VIZIER_SERVER`: VizieR mirror hostname, defaulting to `vizier.cds.unistra.fr`.
- `VIZIER_CACHE_ENABLED`: whether astroquery caches responses on disk (default on).
- `VIZIER_CACHE_AGE_DAYS`: cache retention, defaulting to 30.

With the cache enabled, query regions are snapped to a fixed grid so that
near-identical fields share a cache entry. This is observable near a field edge —
see `algorithms/query/EXTRACTION.md` §5.1.

## WCS Configuration

The WCS solver reads backend settings from environment variables:

- `ANET_INDEX_PATH`: astrometry.net index directory or `os.pathsep`-separated directories.
- `ATLAS_CATALOG_ROOT`: local UCAC4/UCAC5 catalog root for the ATLAS fallback.
- `ATLAS_CATALOG`: catalog name, defaulting to `ucac5`.
- `ATLAS_TIMEOUT_S`: ATLAS matcher timeout in seconds.

The astrometry.net backend also needs a `solve-field` binary on `PATH` or via
the supported `SKYLIB_*` environment overrides documented in
`algorithms/wcs/EXTRACTION.md`.
If neither backend is configured, the package can still import, but end-to-end
plate solving will not produce a solution.

## TypeScript Extracts

`algorithms/lightcurve/`, `algorithms/periodogram/`, and `algorithms/hrdiagram/` contain
framework-free TypeScript source extracted from Astromancer. The root
`package.json` and `tsconfig.json` provide a compiler-only setup for these
modules; there are no runtime npm dependencies.

Install the TypeScript toolchain with npm:

```bash
npm install
```

Run the TypeScript smoke check:

```bash
npm run typecheck
```

The compiler target is ES2022 and includes the DOM library because the preserved
light-curve ingest path still uses browser globals such as `FileReader`.

## Validation

Current CI is intentionally small:

```bash
python3 -m compileall tools algorithms
npm run typecheck
git diff --check
```

The extraction notes record broader one-off checks such as compile/import smoke
tests, source diffs, and selected behavior checks. Full end-to-end WCS,
photometry, and calibration parity still requires a real astronomy runtime:
reference FITS data, native dependencies, solver binaries, and local catalog
data.

## Development Notes

- Keep changes narrow and target `dev` unless a maintainer asks otherwise.
- Do not commit API keys, local environment files, downloaded FITS products,
  generated plots, caches, or large astronomy datasets.
- Keep live remote astronomy service calls gated; default checks should remain
  deterministic and bounded.
- Preserve documented legacy-parity behavior in extracted code unless a change
  is explicitly intended to diverge from Skynet or Astromancer.

See `CONTRIBUTING.md` for the current contribution guidance.
