# Kepler

Kepler is an early-stage astronomy tooling repository. Its current state is a
small installable Python tool collection, extracted astronomy algorithms, a
prototype database-query tool, and an architecture document for turning those
pieces into a coherent tool surface.

## Current Contents

| Path | Status | What it contains |
|---|---|---|
| `database_tools.py` | Prototype | A Claude/Anthropic tool runner around `astroquery`, `psrqpy`, and `ads` for SIMBAD, NED, VizieR, ATNF, ADS, MAST, and MPC queries. |
| `tools/` | Python tools | First plain Python tool wrappers for WCS description, catalog metadata, reference-band resolution, zero-point solving, and local artifact inspection. |
| `algorithms/wcs/` | Extracted Python algorithm | Skynet WCS calibration: source extraction, FITS-header hinting, astrometry.net `solve-field`, ATLAS triangle solving, solution validation, and FITS-header write-back. |
| `algorithms/photometry/` | Extracted Python algorithm | Skynet source extraction and aperture photometry using the shared `algorithms/skylib_lite/` Skylib subset. |
| `algorithms/fieldcal/` | Extracted Python algorithm | Skynet photometric zero-point calibration: catalog-source matching, variable-star filtering, reference-magnitude resolution, and weighted zero-point solving. |
| `algorithms/skylib_lite/` | Shared Python support | Consolidated local Skylib subset used by WCS, photometry, and field calibration: astrometry, SEP extraction, background estimation, aperture photometry, FITS helpers, angle math, and statistics. |
| `algorithms/catalogs/` | Extracted Python algorithm | Skynet and Afterglow photometric catalog declarations: band tables, filter/colour transforms, column mappings, and the SIMBAD object-type vocabulary for eleven catalogs. Declaration only — no network code. |
| `algorithms/query/` | Extracted Python algorithm | Skynet and Afterglow remote catalog access: the VizieR engine, SDSS SkyServer SQL, SIMBAD identifier resolution, astroquery cache handling, filter-aware catalog selection, and WCS-footprint query orchestration. |
| `algorithms/lightcurve/` | Extracted TypeScript algorithm | Astromancer pulsar and variable-star light-curve ingestion, transformation, and period-folding logic with Angular/RxJS/Highcharts removed. |
| `algorithms/periodogram/` | Extracted TypeScript algorithm | Astromancer Lomb-Scargle periodogram logic, peak/confidence helpers, pulsar range defaults, and periodogram-to-folding coupling. |
| `algorithms/hrdiagram/` | Extracted TypeScript algorithm | Astromancer cluster/HR-diagram logic: field-star removal, isochrone matching, extinction offsets, cluster summaries, and result projections. |
| `docs/tool-architecture.md` | Architecture | Master package architecture: public tools, algorithm ownership, future services, runtime policy, and `skylib_lite` consolidation. |

Each extracted domain folder has an `EXTRACTION.md` file with provenance,
severed framework dependencies, known parity behaviors, dependency notes, and
verification already performed.

## Repository Shape

```text
Kepler/
  database_tools.py              # current astronomy database prototype
  pyproject.toml                 # Python package metadata and dependencies
  uv.lock                        # uv lockfile for reproducible installs
  docs/
    tool-architecture.md         # master package architecture
  tools/                         # first plain Python tool wrappers and shared models
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
dependencies needed by the database prototype and extracted algorithm modules.
`uv.lock` records the resolved dependency set.

Some extracted runtime paths also require non-Python solver data called out in
the relevant `EXTRACTION.md` files, including astrometry.net index files and
local UCAC4/UCAC5 catalogs.

## Python Entry Points

The database prototype can be called directly:

```python
from database_tools import AstroQueryTool

tool = AstroQueryTool()
result = tool.execute({
    "database": "SIMBAD",
    "query_type": "object_name",
    "target": "M31",
})
```

ADS queries require `ADS_DEV_KEY`. The interactive Anthropic runner in
`database_tools.py` requires `ANTHROPIC_API_KEY` and is still prototype code.

The first plain Python tools live under `tools`:

```python
from tools.astrometry import describe_image_wcs
from tools.catalogs import list_photometric_catalogs, resolve_reference_band
from tools.calibration import solve_zeropoint_from_measurements
from tools.workspace import describe_artifact, list_artifacts
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
`algorithms.catalogs` for band tables and colour transforms — it is pure data and
pulls in no network stack. Import `algorithms.query.registry` when you need to
actually fetch sources.

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
framework-free TypeScript source extracted from Astromancer. There is currently no
`package.json`, `tsconfig.json`, build command, or generated bundle in this
repository. Treat these folders as algorithm source modules ready to be wired
into a future TypeScript package or application.

## Validation

Current CI is intentionally small:

```bash
python3 -m py_compile database_tools.py
python3 -m compileall tools algorithms
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
