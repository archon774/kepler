# Kepler

Kepler is an early-stage astronomy tooling repository. Its current state is a
set of extracted astronomy algorithms, a prototype database-query tool, and a
planning document for turning those pieces into a coherent package.

This is not yet a single installable Python or TypeScript package. The top-level
folders are intentionally independent while the extraction work settles.

## Current Contents

| Path | Status | What it contains |
|---|---|---|
| `kepler/` | Tool package | One thin tool per astronomy database (SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS) built on `astroquery`/`psrqpy`, following `docs/tool-architecture.md`. Every tool writes its full result to disk and returns a bounded summary — no hardcoded row caps. |
| `wcs/` | Extracted Python algorithm | Skynet WCS calibration: source extraction, FITS-header hinting, astrometry.net `solve-field`, ATLAS triangle solving, solution validation, and FITS-header write-back. |
| `photometry/` | Extracted Python algorithm | Skynet source extraction and aperture photometry, with vendored `skylib` routines for SEP extraction, centroiding, background estimation, aperture sums, and statistics. |
| `fieldcal/` | Extracted Python algorithm | Skynet photometric zero-point calibration: catalog-source matching, variable-star filtering, reference-magnitude resolution, and weighted zero-point solving. |
| `catalogs/` | Extracted Python algorithm | Skynet and Afterglow photometric catalog declarations: band tables, filter/colour transforms, column mappings, and the SIMBAD object-type vocabulary for eleven catalogs. Declaration only — no network code. |
| `query/` | Extracted Python algorithm | Skynet and Afterglow remote catalog access: the VizieR engine, SDSS SkyServer SQL, SIMBAD identifier resolution, astroquery cache handling, filter-aware catalog selection, and WCS-footprint query orchestration. |
| `lightcurve/` | Extracted TypeScript algorithm | Astromancer pulsar and variable-star light-curve ingestion, transformation, and period-folding logic with Angular/RxJS/Highcharts removed. |
| `periodogram/` | Extracted TypeScript algorithm | Astromancer Lomb-Scargle periodogram logic, peak/confidence helpers, pulsar range defaults, and periodogram-to-folding coupling. |
| `hrdiagram/` | Extracted TypeScript algorithm | Astromancer cluster/HR-diagram logic: field-star removal, isochrone matching, extinction offsets, cluster summaries, and result projections. |
| `docs/architecture-brainstorm.md` | Planning | Proposed direction for a future package with public tool contracts, services, Pydantic models, provenance, artifacts, and bounded remote calls. |

Each extracted domain folder has an `EXTRACTION.md` file with provenance,
severed framework dependencies, known parity behaviors, dependency notes, and
verification already performed.

## Repository Shape

```text
Kepler/
  kepler/                        # per-database astronomy tools (see docs/tool-architecture.md)
    tools/                       # simbad.py, ned.py, vizier.py, atnf.py, mast.py, mpc.py, casda.py
  pyproject.toml                 # Python package metadata and dependencies
  uv.lock                        # uv lockfile for reproducible installs
  docs/
    architecture-brainstorm.md   # future package architecture notes
    tool-architecture.md         # the tool-package shape kepler/ follows
  wcs/                           # Python WCS extraction from Skynet
  photometry/                    # Python photometry extraction from Skynet
  fieldcal/                      # Python zero-point calibration extraction
  catalogs/                      # Python catalog declarations (no network code)
  query/                         # Python remote catalog access (VizieR/SDSS/SIMBAD)
  lightcurve/                    # TypeScript light-curve extraction
  periodogram/                   # TypeScript periodogram extraction
  hrdiagram/                     # TypeScript HR-diagram extraction
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

Each database has its own tool function, callable directly with no server or
agent runtime required:

```python
from kepler.tools.simbad import search_simbad
from kepler.tools.vizier import search_vizier
from kepler.tools.ned import search_ned

search_simbad("M31")
search_vizier("Cas A", category="radio")   # any VizieR spectrum, any catalog
search_ned("Cas A", table="photometry")    # NED's full historical flux table
```

Every tool returns a bounded `kepler.models.ToolResult`: a short inline
preview plus, when a result is larger than that, a path to the complete
table written under `artifacts/`. See `docs/tool-architecture.md` for the
full tool list and design rules.

Literature search, citation lookup, and literature-review generation are
available via `kepler.tools.ads` (`search_ads`, `get_citing_papers`,
`get_referenced_papers`, `build_literature_review`), built on
`astroquery.nasa_ads` rather than the standalone `ads` package
`database_tools.py` used. Requires an API token in `ADS_DEV_KEY` — get one
from https://ui.adsabs.harvard.edu/user/settings/token.
`build_literature_review` writes a Markdown review with full citations and
abstracts to `artifacts/ads/`.

An optional agentic runner is available for wiring these tools into an
Anthropic tool-use loop:

```bash
ANTHROPIC_API_KEY=... uv run kepler-astro-query "all historical radio data on Cassiopeia A"
```

The extracted Python domains expose callable algorithm entry points:

```python
from wcs.wcs import solve_wcs
from photometry.pipeline.photometry import run_photometry, perform_photometry
from photometry.pipeline.source_extraction import run_source_extraction
from fieldcal import perform_field_calibration, calc_solution
from query.runner import query_catalogs
from query.simbad import resolve_simbad
```

`fieldcal` deliberately does not own WCS, photometry, or catalogs. Before using
`perform_field_calibration`, wire the cross-domain callables in `fieldcal.deps`
to the implementations from `wcs/` and `photometry/`. Catalogs are the
exception: `fieldcal.deps.query_catalogs` already defaults to `query/`.

Catalog metadata and catalog access are separate on purpose. Import `catalogs`
for band tables and colour transforms — it is pure data and pulls in no network
stack. Import `query.registry` when you need to actually fetch sources.

## Catalog Query Configuration

The remote catalog backends read settings from environment variables:

- `VIZIER_SERVER`: VizieR mirror hostname, defaulting to `vizier.cds.unistra.fr`.
- `VIZIER_CACHE_ENABLED`: whether astroquery caches responses on disk (default on).
- `VIZIER_CACHE_AGE_DAYS`: cache retention, defaulting to 30.

With the cache enabled, query regions are snapped to a fixed grid so that
near-identical fields share a cache entry. This is observable near a field edge —
see `query/EXTRACTION.md` §5.1.

## WCS Configuration

The WCS solver reads backend settings from environment variables:

- `ANET_INDEX_PATH`: astrometry.net index directory or `os.pathsep`-separated directories.
- `ATLAS_CATALOG_ROOT`: local UCAC4/UCAC5 catalog root for the ATLAS fallback.
- `ATLAS_CATALOG`: catalog name, defaulting to `ucac5`.
- `ATLAS_TIMEOUT_S`: ATLAS matcher timeout in seconds.

The astrometry.net backend also needs a `solve-field` binary on `PATH` or via
the supported `SKYLIB_*` environment overrides documented in `wcs/EXTRACTION.md`.
If neither backend is configured, the package can still import, but end-to-end
plate solving will not produce a solution.

## TypeScript Extracts

`lightcurve/`, `periodogram/`, and `hrdiagram/` contain framework-free
TypeScript source extracted from Astromancer. There is currently no
`package.json`, `tsconfig.json`, build command, or generated bundle in this
repository. Treat these folders as algorithm source modules ready to be wired
into a future TypeScript package or application.

## Validation

Current CI is intentionally small:

```bash
python3 -m compileall kepler catalogs
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
