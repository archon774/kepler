# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Kepler is a **staging area for extracted astronomy algorithms**, not yet a coherent
package. It holds four things:

1. `tools/` — plain Python tool wrappers, split database/archive tools, an optional runner,
   and shared tool-facing models.
2. `algorithms/` — extracted algorithm folders (`wcs/`, `photometry/`,
   `fieldcal/`, `catalogs/`, `query/`, `lightcurve/`, `periodogram/`,
   `hrdiagram/`) plus the shared `skylib_lite/` subset.
3. `docs/tool-architecture.md` — the master architecture for the tool collection.

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
- **Documented parity quirks are deliberate.** Example: `algorithms/catalogs/`
  ships two registries that disagree on purpose — `CATALOGS` (11 catalogs) and
  `CATALOG_OPTIONS` (APASS + PanSTARRS, read only by reference-magnitude
  resolution). Merging them silently changes which reference band a narrowband
  or unfiltered image calibrates against (`docs/extraction.md`, Catalogs §4).
  `algorithms/hrdiagram/` preserves several flagged upstream bugs. Do not "fix"
  these unless the task is explicitly to diverge from Skynet/Astromancer.

  The quirk that used to head this list is gone rather than preserved:
  `algorithms/wcs/state.py` was a non-`slots` dataclass specifically so
  `_clear_wcs_solution_fields()` reproduced upstream's silent no-op on unmapped
  attribute names, and the stateless rollout (S0–S6) deleted the module along
  with the processing-run objects it stood in for. `_clear_wcs_solution_fields`
  is now on `tests/test_repository_shape.py`'s forbidden-API list.

`docs/extraction.md` carries one section per domain with exact provenance (source path,
line ranges, per-file diff fidelity), the list of seams, dependency requirements, and what
verification was actually performed. It consolidates what used to be a per-folder
`EXTRACTION.md`; those files are gone, and references to them elsewhere are stale.
**Read the relevant section before touching a domain folder** — it is the only place the
upstream mapping is recorded.

One folder is an exception to the contract above. `algorithms/pulsar/` is a **port** of
Astromancer TypeScript into Python, not an extraction, because the upstream sonifier is
welded to browser APIs and cannot run headless. It is marked `# PORTED:` rather than
`# EXTRACTED:` so the extraction-marker index stays meaningful, and its divergences are
enumerated in `docs/extraction.md` (Pulsar Sonification §6).

## Commands

```bash
uv sync                                  # create .venv and install pinned deps
uv run pytest                            # the test suite (no network by default)
python3 -m compileall tools algorithms   # local package syntax smoke
npm install                              # once; node_modules/ is not in a fresh checkout
npm run typecheck                        # tsc --noEmit over the TypeScript folders
git diff --check                         # whitespace check
```

`npm run typecheck` needs `npm install` first — `node_modules/` is absent from
a fresh checkout and `tsc` is not on `PATH` without it. Nothing installs it for
you: the typecheck is not a CI job, so this is the only thing that runs it
(BL-12).

CI (`.github/workflows/ci.yml`) gates three jobs: `compileall` over `tools algorithms
tests`, `uv run --locked pytest`, and a `repository-shape` job asserting that
`README.md`, `pyproject.toml`, `uv.lock`, `tools/registry.py`, `tools/runner.py`, and
`docs/tool-architecture.md` exist. **The TypeScript typecheck is not a CI job** — run it
by hand when touching a `.ts` file.

The suite is algorithm-preservation testing, not correctness testing: it pins bit-exact
parity against recorded Skynet output and pins known bugs rather than fixing them. See
`tests/README.md`. Nothing in it opens a socket unless marked `network`, which also
requires `KEPLER_TEST_NETWORK=1`.

There is **no linter or formatter configured**. Match the surrounding file's style.

Other workflows: `secret-scan.yml` (gitleaks over tree and full history) and
`workflow-safety.yml` (actionlint + zizmor). The `.gitleaks.toml` allowlist for env-var
names is **path-scoped to exact files** (never directory wildcards) — referencing
`ADS_DEV_KEY`/`ANTHROPIC_API_KEY`/`NASA_API_KEY`/`OPENAI_API_KEY`/`GEMINI_API_KEY`
from a file outside that list needs a new allowlist entry. A `paths` entry
disables secret detection for the whole file, so keep each one specific.

`pyproject.toml` pins every dependency with `==`. Adding one means editing the pin and
re-running `uv lock`.

The TypeScript folders have a root `package.json` and `tsconfig.json` carrying a
`typecheck` script (`tsc --noEmit`, `lib: ["ES2022", "DOM"]`) but **no build, bundle, or
test step**, and no runtime — nothing executes the TypeScript. They are source modules
plus a syntax and type gate. A tool that needs TypeScript behaviour at runtime today has
to go through a Python port; `algorithms/pulsar/` is the one instance, and
`docs/extraction.md` (Pulsar Sonification §5) records why that was allowed there and why
it is not a general licence.

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
  `algorithms.photometry.photometry.run_photometry` and
  `algorithms.photometry.source_extraction.{run_source_extraction, get_source_xy,
  get_source_radec, build_wcs_from_header}`.
- `algorithms/fieldcal/` owns the photometric zero-point solve —
  `perform_field_calibration` and `calc_solution`. It does **not** own catalogs.
- `algorithms/catalogs/` owns photometric catalog declarations plus provider
  lookup tables for ADS, NED, and ATNF. Declaration only: nothing here imports
  `astroquery`, `psrqpy`, or opens a socket.
- `algorithms/query/` owns remote catalog access — the VizieR engine, SDSS SkyServer SQL,
  SIMBAD resolution, the astroquery cache layer, filter-aware catalog selection,
  WCS-footprint geometry, and the query orchestration entry points.
- `algorithms/pulsar/` owns the whole radio-pulsar chain, one module per stage:
  `ingest.py` (read + background subtraction), `periodogram.py` (Lomb-Scargle +
  peak + confidence), `folding.py` (phase fold + bin), `sonification.py`
  (synthesis + WAV). It imports nothing from the other algorithm folders and is
  imported only by `tools/pulsar.py`.

  **The stage order is a dependency, not a convention:** light curve ->
  periodogram -> period -> fold -> sonify. Only the periodogram produces a
  period, and folding at a wrong period returns a *flat profile, not an error*.
  That silent failure is why each stage reports a quality number
  (`peak_confidence`, `pulse_snr`) and why the tools are four rather than one.
  See `docs/pulsar-tool-pipeline.md`.

  Never read a period off rendered audio: the synthesis ignores sample
  timestamps (`docs/extraction.md`, Pulsar Sonification §7.2). Catalogued
  periods come from `tools.atnf.search_atnf` and beat anything a 60-second scan
  measures.

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
unfiltered image calibrates against. See `docs/extraction.md`, Catalogs §4.

`algorithms.fieldcal` needs WCS, source extraction, and photometry but does not
own them. **There is no dependency-injection seam.** The stateless rollout
(S0–S6, PR #52) deleted `algorithms/fieldcal/deps.py` along with the
processing-run objects it existed to service; callers pass everything in:

```python
from algorithms.fieldcal import perform_field_calibration

zero_point, result = perform_field_calibration(
    header,
    data,                        # the image array
    wcs=wcs,                     # built by the caller, e.g. build_wcs_from_header
    catalog_sources=rows,        # fetched by the caller — see below
    variable_sources=vsx_rows,   # optional; omit and the VSX check is skipped
    extraction_settings=...,     # or pass detected_sources= directly
    photometry_settings=...,
    field_cal_settings=...,
)
```

**The catalog query moved out of the algorithm package entirely.** There is no
`deps.query_catalogs` and no lazy import of `algorithms.query` — `algorithms/fieldcal/`
opens no socket at all, and fetching the rows is the caller's job. In this repo
that caller is the tool layer: `tools.photometry.calibrate_zeropoint` does the
query, and passing it `catalog_sources=` (from
`tools.fieldcal_reference.replay_catalog_sources`) makes the whole solve offline.

One public tool call is Kepler's execution boundary: no run, stage, or session
state is retained between calls, and no tool writes state another tool reads.

### The agent loop and the model port

`tools/agent/` owns the headless agent loop and nothing else: `run_session()`
(an iterator of events, with a `Decision` flowing back through an approver),
the ten event dataclasses in `events.py`, and `SYSTEM_PROMPT` (moved verbatim
from `tools/runner.py` — `runner.py` re-exports it). It imports no UI toolkit.
`tools/runner.py` is now a thin console shim over it.

`tools/llm/` owns the provider-neutral **model port** and nothing else:
neutral types, the `ModelBackend` protocol (`complete()` is the only required
method), schema translation (`schema.py`), pre-dispatch argument validation
(`validation.py`, S8), the `provider/model` spec factory (`factory.py`), and
the four adapters. Its rules:

- **Adapters never import `tools/registry.py`.** Translating the registry
  schemas into a backend's dialect is the caller's job (the engine does it
  once before the turn loop); the same holds for validation.
- **Nothing under `algorithms/` imports `tools/llm/` or `tools/agent/`.** The
  dependency runs one way: tools/agent → tools/llm → tools/registry.
- Zero new third-party dependencies: the `anthropic` SDK is reused, the other
  three adapters are raw `httpx`. Never disable TLS verification, never follow
  redirects, always an explicit timeout; header auth only, no key in a URL.
- The integer/number-or-null union is never downgraded to a plain scalar to
  make a weak model's life easier (`schema.py`); the string `"None"` is never
  coerced to `None` (`validation.py`).

`docs/working/model-backends.md` is the full design; `docs/tool-architecture.md`
section 10 is the summary.

### Vendored `skylib` is consolidated

The WCS, photometry, and field-calibration extractions originally carried
overlapping `skylib/` subsets. They now share `algorithms/skylib_lite/`, which
contains the astrometry, extraction, calibration, aperture-photometry, FITS,
angle, overlap, and statistics files needed by those algorithms. Update the
single shared copy deliberately when touching a vendored Skylib routine, and
preserve extraction-parity notes.

### Configuration seams

Upstream Dynaconf/ORM/S3 plumbing was replaced with duck-typed stand-ins:

- `algorithms/wcs/config.py` — `SolverSettings` reads `ANET_INDEX_PATH`,
  `ANET_TIMEOUT_S`, `ATLAS_CATALOG_ROOT`, `ATLAS_CATALOG` (default `ucac5`), and
  `ATLAS_TIMEOUT_S` from the environment. `solve_wcs(..., solver_settings=...)`
  accepts a per-call settings object; callers using the builders directly can
  likewise pass any object exposing the relevant attributes.
- `algorithms/wcs/results.py` — solve output as two *frozen* dataclasses,
  `WcsSolveMetadata` and `WcsSolveResult`. This replaced `state.py`, which held
  plain-dataclass stand-ins for the Skynet ORM rows; the stateless rollout
  (S0–S6) deleted it and dropped persistence with it.
- `algorithms/query/config.py` — `QuerySettings` reads `VIZIER_SERVER`, `VIZIER_CACHE_ENABLED`
  and `VIZIER_CACHE_AGE_DAYS` from the environment, replacing Afterglow's Flask
  `current_app.config` reads and Skynet's five-line literal module. Callers with
  their own configuration assign `query.config.settings`. Note that enabling the
  cache snaps query regions to a fixed grid, which is observable near a field
  edge (`docs/extraction.md`, Query §5.1).
- `tools/config.py` — `KEPLER_DATA_DIR` (default `<repo>/data`) is the data
  root: the fixture frames, the recorded reference solves, and the archive
  download root `KEPLER_FITS_DOWNLOAD_DIR` (default `<data root>/fits_downloads`)
  that `tools/mast.py` and `tools/casda.py` write into.

  It is also a **boundary**. `tools/optical.py` walks the download root
  recursively — astroquery nests MAST products under
  `mastDownload/<mission>/<obs_id>/` — and only does so while that root
  resolves *inside* the data root; outside it the directory is searched flat
  and the listing carries a `download_root_outside_data_dir` warning.
  Containment is decided on the resolved path, so a symlink out of the tree
  does not buy a walk of wherever it lands. Overriding `KEPLER_DATA_DIR` moves
  the download root and the boundary, not the bundled frame library — that has
  its own override, `KEPLER_OPTICAL_DATA_DIR`.

  `KEPLER_MAX_FRAMES` (default 200, must be ≥ 1) bounds how many frames one
  `list_optical_frames` call reads headers for and returns **per root**; over
  the cap the listing carries a `listing_truncated` warning naming the total.
  Per root, not overall, because roots are ordered primary-first and an
  operator archive larger than the cap would otherwise make every archive
  download invisible. It is not a tool parameter, so raising it is an
  operator decision, not a model's. `list_photometry_targets` is an
  inventory of filenames, not a header listing, and is never capped.

  `tools/wcs.py` refuses to write a solved header back into a bundled fixture.
  That guard names the four tracked fixture subtrees (`afterglow/`,
  `fieldcal/`, `optical/`, `pulsar/`) — pinned to this repository, reading no
  setting — so a downloaded product under `data/fits_downloads/` stays
  writable and no environment variable can switch the guard off. A new
  fixture subtree has to be added to `_FIXTURE_SUBTREES`; a test asserts the
  tuple matches the directories present.

### Runtime dependencies that are not optional

`numba` and `sep` are **hard import-time** requirements of
`algorithms/skylib_lite` (`@njit` on `util/angle.py` and
`extraction/centroiding.py`); there is no non-numba fallback. `scipy`, `astropy`,
and Pydantic v2 are likewise required.

End-to-end runs additionally need data that is not in this repo. On the
development host, `solve-field` is `/usr/bin/solve-field`, astrometry.net
indexes 4107-4119 are under `/usr/share/astrometry/data`, and UCAC5 data is
under `/srv/agents/catalogs/ATLAS/UCAC5`; none is selected by the repository's
default environment. Set `ANET_INDEX_PATH` and/or `ATLAS_CATALOG_ROOT` to opt
in. The packaged astrometry.net indexes start at a wider scale than the
~10-arcminute fixture, and the all-sky 0.1-60 arcsec/pixel search has reached
the backend without producing a solution. The `solver_data`-marked tests gate
this path. The solver is wired and exercised; successful solve parity has not
been validated. Both backends still degrade to "unavailable" when unconfigured.

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
  (`.gitignore` covers `fits_downloads/`, `artifacts/`, `cache/`, `work/`, etc.).
  **`data/` itself is tracked** — it is the fixture tree, ~175 MB of it — so
  there is deliberately no `data/` pattern in `.gitignore`, and adding one back
  would ignore every fixture. The untracked part is `data/fits_downloads/`,
  matched by the depth-independent `fits_downloads/` pattern.
- ADS-backed tools require `ADS_DEV_KEY`; the optional `tools.runner` agent loop
  requires a model backend — `ANTHROPIC_API_KEY` by default, or
  `KEPLER_MODEL_BACKEND=provider/model` plus that provider's key. Remote
  astronomy service calls stay out of default checks and should return bounded
  previews plus artifact paths for complete results.
