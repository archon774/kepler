# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Kepler is a **staging area for extracted astronomy algorithms**, not yet a coherent
package. It holds four things:

1. `database_tools.py` — a prototype Anthropic tool runner over `astroquery`/`psrqpy`/`ads`.
2. `tools/` — plain Python tool wrappers and shared tool-facing models.
3. `algorithms/` — extracted algorithm folders (`wcs/`, `photometry/`,
   `fieldcal/`, `catalogs/`, `query/`, `lightcurve/`, `periodogram/`,
   `hrdiagram/`) plus the shared `skylib_lite/` subset.
4. `docs/tool-architecture.md` — the master architecture for the tool collection.

The top-level `tools/` and `algorithms/` folders are intentionally separate.
`tools/` is the public tool surface; `algorithms/` holds lower-level extracted
code that tool wrappers may call. `README.md`, `docs/repository-folders.md`, and
`docs/tool-architecture.md` describe the current architecture.

## The extraction contract (most important thing to know)

The Python folders were extracted from Skynet (`/home/claude/skynet`) and the TypeScript
folders from Astromancer (`/home/claude/astromancer`). Both were **extractions, not
rewrites**: algorithms, constants, comments, and known bugs are byte-preserved. Two rules
follow from this:

- **Every severed upstream dependency is marked inline** with `# EXTRACTED: was <symbol>`
  (Python) or `// EXTRACTED: was …` (TypeScript). These markers are the index of what was
  cut and why. Preserve them; add one whenever you cut another dependency.
- **Documented parity quirks are deliberate.** Example: `algorithms/wcs/state.py` is a non-`slots`
  dataclass *specifically* so `_clear_wcs_solution_fields()` reproduces upstream's silent
  no-op on unmapped attribute names (`algorithms/wcs/EXTRACTION.md` §5.2).
  `algorithms/hrdiagram/` preserves several flagged upstream bugs. Do not "fix"
  these unless the task is explicitly to diverge from Skynet/Astromancer.

Each domain folder has an `EXTRACTION.md` with exact provenance (source path, line ranges,
per-file diff fidelity), the list of seams, dependency requirements, and what verification
was actually performed. **Read the relevant `EXTRACTION.md` before touching a domain
folder** — it is the only place the upstream mapping is recorded.

## Commands

```bash
uv sync                                  # create .venv and install pinned deps
python3 -m py_compile database_tools.py  # the only Python check CI runs
python3 -m compileall tools algorithms   # local package syntax/import smoke
git diff --check                         # whitespace check
```

There is **no test suite, linter, or type-checker configured** in this repository. Do not
claim tests pass; there are none to run. CI (`.github/workflows/ci.yml`) runs only the
`py_compile` above plus a `repository-shape` job asserting that `README.md`,
`pyproject.toml`, `uv.lock`, `database_tools.py`, and `docs/tool-architecture.md`
exist. Note that CI never imports or compiles the extracted algorithm packages.

Other workflows: `secret-scan.yml` (gitleaks over tree and full history) and
`workflow-safety.yml` (actionlint + zizmor). The `.gitleaks.toml` allowlist for env-var
names is **path-scoped** — referencing `ADS_DEV_KEY`/`ANTHROPIC_API_KEY`/`NASA_API_KEY`
from a file outside that path list may need a new allowlist entry.

`pyproject.toml` pins every dependency with `==`. Adding one means editing the pin and
re-running `uv lock`.

The TypeScript folders have **no `package.json`, `tsconfig.json`, or build step**. They are
source modules awaiting a future TS package; there is currently no way to compile or test
them in-repo.

## Python domain boundaries

`algorithms/wcs/`, `algorithms/photometry/` and `algorithms/fieldcal/`
deliberately do not import each other directly. `algorithms/catalogs/` and
`algorithms/query/` are shared layers that `algorithms/fieldcal/` may import —
see below. Ownership is strict:

- `algorithms/wcs/` owns plate solving only — `algorithms.wcs.wcs.solve_wcs`. Extracts sources, tries the
  astrometry.net `solve-field` subprocess backend, falls back to the in-process ATLAS
  triangle solver against local UCAC4/UCAC5, validates against parity/pointing hints,
  writes the accepted solution into the FITS header.
- `algorithms/photometry/` owns SEP source extraction and aperture photometry —
  `algorithms.photometry.pipeline.photometry.{run_photometry, perform_photometry}` and
  `algorithms.photometry.pipeline.source_extraction.run_source_extraction`.
- `algorithms/fieldcal/` owns the photometric zero-point solve —
  `perform_field_calibration` and `calc_solution`. It does **not** own catalogs.
- `algorithms/catalogs/` owns photometric catalog declarations — band tables, colour
  transforms, column mappings, VizieR IDs, and the SIMBAD object-type table for
  eleven catalogs. Declaration only: nothing here imports `astroquery` or opens a
  socket.
- `algorithms/query/` owns remote catalog access — the VizieR engine, SDSS SkyServer SQL,
  SIMBAD resolution, the astroquery cache layer, filter-aware catalog selection,
  WCS-footprint geometry, and the query orchestration entry points.

`algorithms/query/` imports `algorithms/catalogs/`; never the reverse. That direction is what keeps
filter matching and the whole zero-point solve runnable with no network stack
installed. Backends are attached to declarations by `algorithms/query/binding.py`, which
subclasses `(Declaration, Backend)` so that the three plugins overriding
`table_to_sources` reach the engine implementation through `super()` — the same
MRO position upstream's single-class arrangement gave them. Do not replace that
with composition.

Two catalog registries exist and disagree deliberately: `CATALOGS` (11 catalogs)
and `CATALOG_OPTIONS` (APASS + PanSTARRS, read only by reference-magnitude
resolution). Merging them silently changes which reference band a narrowband or
unfiltered image calibrates against. See `algorithms/catalogs/EXTRACTION.md` §4.

`algorithms.fieldcal` needs WCS, source extraction, and photometry but does not own them. The seam is
`algorithms/fieldcal/deps.py`: module-level names that default to stubs raising
`FieldCalDependencyError`. A caller wires them by assignment before use:

```python
from algorithms.fieldcal import deps
deps.run_photometry = ...                # from algorithms/photometry/
deps.run_source_extraction = ...         # from algorithms/photometry/
deps.get_source_radec = ...              # from algorithms/photometry/
deps.build_wcs_for_processing_run = ...  # from algorithms/wcs/
```

`deps.query_catalogs` is the one entry with a working default — it lazily imports
`algorithms.query.runner.query_catalogs`, so catalog fetching needs no wiring and
`import algorithms.fieldcal` still costs no astroquery. Override it to route
queries elsewhere.

Call sites in `field_cal.py` deliberately use `deps.<name>(...)` rather than a
`from .deps import <name>` binding, so late injection works. Preserve that pattern.

### Vendored `skylib` is consolidated

The WCS, photometry, and field-calibration extractions originally carried
overlapping `skylib/` subsets. They now share `algorithms/skylib_lite/`, which
contains the astrometry, extraction, calibration, aperture-photometry, FITS,
angle, overlap, and statistics files needed by those algorithms. Update the
single shared copy deliberately when touching a vendored Skylib routine, and
preserve extraction-parity notes.

### Configuration seams

Upstream Dynaconf/ORM/S3 plumbing was replaced with duck-typed stand-ins:

- `algorithms/wcs/config.py` — `SolverSettings` reads `ANET_INDEX_PATH`, `ATLAS_CATALOG_ROOT`,
  `ATLAS_CATALOG` (default `ucac5`), `ATLAS_TIMEOUT_S` from the environment. Callers with
  their own config pass any object exposing those four attributes to
  `build_anet_config` / `build_atlas_config`, or reassign `wcs.settings`.
- `algorithms/wcs/state.py` — plain dataclasses replacing SQLAlchemy rows; persistence dropped.
- `algorithms/query/config.py` — `QuerySettings` reads `VIZIER_SERVER`, `VIZIER_CACHE_ENABLED`
  and `VIZIER_CACHE_AGE_DAYS` from the environment, replacing Afterglow's Flask
  `current_app.config` reads and Skynet's five-line literal module. Callers with
  their own configuration assign `query.config.settings`. Note that enabling the
  cache snaps query regions to a fixed grid, which is observable near a field
  edge (`algorithms/query/EXTRACTION.md` §5.1).

### Runtime dependencies that are not optional

`numba` and `sep` are **hard import-time** requirements of
`algorithms/skylib_lite` (`@njit` on `util/angle.py` and
`extraction/centroiding.py`); there is no non-numba fallback. `scipy`, `astropy`,
and Pydantic v2 are likewise required.

End-to-end runs additionally need data that is not in this repo: astrometry.net index files
plus a `solve-field` binary on `PATH` (or the `SKYLIB_*` overrides documented in
`algorithms/wcs/EXTRACTION.md`), and/or a local UCAC4/UCAC5 catalog. Both WCS backends degrade to
"unavailable" rather than failing, so imports succeed and solves simply return no solution
when the data is absent. This is why full parity has never been validated here.

## TypeScript domain boundaries

Angular, RxJS, HTTP job polling, Highcharts, canvas rendering, and browser export handlers
were removed. Ownership is likewise strict and cross-cutting:

- `algorithms/periodogram/core/` is the shared Lomb-Scargle heart. `pulsar/` and `variable/` import
  *upward* into `core/`; nothing in `core/` imports from either.
- Period **folding** belongs to `algorithms/lightcurve/`, not
  `algorithms/periodogram/` —
  `algorithms/periodogram/pulsar/pulsar-periodogram-folding-link.ts` is only the coupling between them.
- `algorithms/lightcurve/pulsar/` and `algorithms/lightcurve/variable/` share nothing but `shared/`; no file mixes
  the two tools.
- `algorithms/hrdiagram/` pipeline: ingest -> field-star removal (`fsr/`) -> isochrone matching -> result
  summaries. The load-bearing function is
  `isochrone-matching/isochrone-plot.util.ts::computePlotDelta`.

## Conventions

- Target `dev`, not `main`, unless a maintainer says otherwise. `.github/CODEOWNERS` marks
  the repo maintainer-owned.
- Keep PRs narrow; separate documentation, workflow, dependency, and behavior changes.
- Keep live remote astronomy service calls out of default checks — gate them explicitly.
  Default checks must stay deterministic and bounded.
- Do not commit downloaded FITS products, generated plots, caches, or large datasets
  (`.gitignore` already covers `fits_downloads/`, `artifacts/`, `data/`, etc.).
- `database_tools.py` requires `ADS_DEV_KEY` for ADS queries and `ANTHROPIC_API_KEY` for its
  interactive runner. It is prototype code; `docs/tool-architecture.md` plans to move
  its logic into `tools/` and `services/` modules with `ToolResult` envelopes, keeping the
  module temporarily as a compatibility wrapper.
