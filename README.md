# Kepler

Kepler is an early-stage astronomy tooling repository. Its current state is a
set of extracted astronomy algorithms, a prototype database-query tool, and a
planning document for turning those pieces into a coherent package.

This is not yet a single installable Python or TypeScript package. The top-level
folders are intentionally independent while the extraction work settles.

## Current Contents

| Path | Status | What it contains |
|---|---|---|
| `database_tools.py` | Prototype | A Claude/Anthropic tool runner around `astroquery`, `psrqpy`, and `ads` for SIMBAD, NED, VizieR, ATNF, ADS, MAST, and MPC queries. |
| `wcs/` | Extracted Python algorithm | Skynet WCS calibration: source extraction, FITS-header hinting, astrometry.net `solve-field`, ATLAS triangle solving, solution validation, and FITS-header write-back. |
| `photometry/` | Extracted Python algorithm | Skynet source extraction and aperture photometry, with vendored `skylib` routines for SEP extraction, centroiding, background estimation, aperture sums, and statistics. |
| `fieldcal/` | Extracted Python algorithm | Skynet photometric zero-point calibration: catalog-source matching, variable-star filtering, reference-magnitude resolution, and weighted zero-point solving. |
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
  database_tools.py              # current astronomy database prototype
  pyproject.toml                 # Python package metadata and dependencies
  requirements.txt               # pinned Python dependencies for the current repo
  docs/
    architecture-brainstorm.md   # future package architecture notes
  wcs/                           # Python WCS extraction from Skynet
  photometry/                    # Python photometry extraction from Skynet
  fieldcal/                      # Python zero-point calibration extraction
  lightcurve/                    # TypeScript light-curve extraction
  periodogram/                   # TypeScript periodogram extraction
  hrdiagram/                     # TypeScript HR-diagram extraction
```

## Python Setup

Use a virtual environment and install the Python package with its dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

`pyproject.toml` is the installable package metadata and includes the Python
dependencies needed by the database prototype and extracted algorithm modules.
`requirements.txt` remains as the pinned dependency snapshot that existed before
packaging metadata was added.

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

The extracted Python domains expose callable algorithm entry points:

```python
from wcs.wcs import solve_wcs
from photometry.pipeline.photometry import run_photometry, perform_photometry
from photometry.pipeline.source_extraction import run_source_extraction
from fieldcal import perform_field_calibration, calc_solution
```

`fieldcal` deliberately does not own WCS or photometry. Before using
`perform_field_calibration`, wire the cross-domain callables in `fieldcal.deps`
to the implementations from `wcs/` and `photometry/`.

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
python3 -m py_compile database_tools.py
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
