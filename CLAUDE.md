# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Kepler is a **staging area for extracted astronomy algorithms**, not yet a coherent
package. It holds four things:

1. `tools/` — plain Python tool wrappers, split database/archive tools, the
   optional agent loop and the `kepler` console over it, and shared
   tool-facing models.
2. `algorithms/` — extracted algorithm folders (`wcs/`, `photometry/`,
   `fieldcal/`, `catalogs/`, `query/`, `lightcurve/`, `periodogram/`,
   `hrdiagram/`) plus the shared `skylib_lite/` subset.
3. `docs/tool-architecture.md` — the master architecture for the tool collection.

The top-level `tools/` and `algorithms/` folders are intentionally separate.
`tools/` is the public tool surface; `algorithms/` holds lower-level extracted
code that tool wrappers may call. `README.md`, `docs/repository-folders.md`, and
`docs/tool-architecture.md` describe the current architecture.

Using the tools, as opposed to working on this repository, is taught by the agent
skill in `skills/kepler-tools/`, rendered from its one source in `tools/skill/source/`:
edit the source, then run `uv run python -m tools.skill`.

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

CI (`.github/workflows/ci.yml`) runs on **Python 3.13** -- the newest Python
every dependency ships wheels for (`sep` has none for 3.14; see
`docs/installing.md`); `pyproject.toml` keeps
3.12 as the floor, so code still has to work there (`Path.resolve()` raises
`RuntimeError` rather than `OSError` on a symlink loop under 3.12 — use
`tools.config.within`/`safe_resolve`). It gates three jobs: `compileall` over
`tools algorithms tests`, `uv run --locked --extra mcp pytest` (after the MCP
tests alone without the extra), and a `repository-shape` job asserting that
`README.md`, `pyproject.toml`, `uv.lock`, `tools/registry.py`,
`tools/agent/engine.py`, `tools/tui/app.py`, and `docs/tool-architecture.md`
exist. **The TypeScript typecheck is not a CI job** — run it
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
  timestamps (`docs/extraction.md`, Pulsar Sonification §7.2).

  **A catalogued period is a check on a measured one, never an input.** The
  bundled scans carry `curated_period_s` (from `data/pulsar/curated_periods.json`,
  reported by `resolve_pulsar_scan`/`list_pulsar_scans` with a `period_source`);
  `tools.atnf.search_atnf` covers sources the curation does not. Neither is
  where a period comes from. A fold at a *measured* period is a detection; a
  fold at a *literature* period is a fit to a known answer, and the two must
  never be reported as each other. The order is fixed: **measure** with
  `compute_pulsar_periodogram` (read `peak_fold_snr`, not `peak_confidence` —
  the confidence threshold assumes white noise and mains interference reads
  "99.73%" while folding to nothing) → **compare** against the curated or
  ATNF value → on disagreement **retune** (`back_scale`, `start`/`stop`,
  `steps`; 0.016665 s is 60 Hz mains, a 2.1–2.2 s peak is baseline red noise)
  → only then **fall back** to folding at the reference, and say so — that
  fold's `pulse_snr` is not an independent detection. A blind search succeeds
  on one of the five bundled scans, so reaching the fallback on the faint ones
  is an ordinary outcome to report, not a failure to hide. This reversed P1's
  original checkbox wording at the maintainer's direction; the shipped prompt
  in `tools/agent/prompt.py` ("PERIOD SOURCING") is the authoritative text.

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
query, and passing it `catalog_fixture=` (or `catalog_sources=` from
`tools.fieldcal_reference.replay_catalog_sources`) makes the whole solve offline.
`"full_response"` replays the recorded APASS response for the whole field
**together with the recorded VSX rows** -- the recorded selection filtered
variables out before matching, and does not reproduce without them.

One public tool call is Kepler's execution boundary: no run, stage, or session
state is retained between calls, and no tool writes state another tool reads.

### The agent loop and the model port

`tools/agent/` owns the headless agent loop and nothing else: `run_session()`
(an iterator of events, with a `Decision` flowing back through an approver),
the twelve event dataclasses in `events.py`, and `SYSTEM_PROMPT` (moved
verbatim from the retired `tools/runner.py`). It imports no UI toolkit.
`tools/tui/` is the console over it, and the repository's only model-driven
entry point: `kepler`. The `tools/runner.py` shim and its
`kepler-astro-query` script were deleted once the console replaced them.

`run_session()` also takes three optional callables for an interactive caller,
and behaves exactly as before without them: `on_delta` (receives `TextDelta`
and `ThinkingDelta` live **instead of** their being emitted afterwards — a
delta is delivered exactly once either way), `pending_input` (drained each turn
and merged into the trailing user message, so a note typed mid-run arrives with
the tool results), and `should_stop` (ends the session with outcome
`interrupted`, refusing any pending tool call with a `tool_result` rather than
leaving a `tool_use` unanswered).

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
- **Revealed reasoning is never merged into assistant text.** `ThinkingBlock`
  is a neutral block and `on_thinking` is its streaming hook, parallel to
  `on_text`. Anthropic's is signed and must be replayed on the turn whose tool
  calls are being answered — hence for the **last** assistant message only, and
  never unsigned. Asking for a thinking budget costs `temperature`, which the
  provider refuses alongside it, so thinking is **off by default** everywhere
  but the console (`docs/archive/model-backends.md` 4.8).

`tools/bench/` owns the model benchmark harness and nothing else: the tool
plane (`plane.py`), the fixture store (`fixtures.py`), the task loader
(`tasks.py`), the run loop (`harness.py`), the four graders, the report, and
the `kepler-bench` CLI. Its rules:

- **It owns no tool and adds nothing to the tool surface.** It reads
  `tools/registry.py`'s schemas and substitutes `run_session`'s
  `tool_functions=` mapping, and it reads the session manifest the engine
  already writes. It is in `NOT_TOOL_MODULES`.
- **Nothing under `algorithms/` or `tools/llm/` imports it.** The dependency
  runs one way: tools/bench → tools/agent → tools/llm → tools/registry.
- **The tool plane is closed.** All 55 registered tools are classified local
  (26, run live), remote (22, always replayed) or mixed (7, decided per call
  from the arguments). An unclassified tool raises rather than defaulting, and
  a test asserts the plane covers the registry — so **a new registry tool must
  be classified in the same commit that adds it**. Without that, the first new
  remote tool would run live, against a real service, inside a run that
  believes it is offline.
- The classification is **per tool, never per module**:
  `get_literature_cluster_params` looks local and reaches VizieR;
  `tools.hr_diagram` spans all three classes.
- Class-L tools are **not** replayed. Replaying `compute_pulsar_periodogram`
  would replace the measurement with a guess about the measurement.
- Zero new dependencies; nothing here opens a socket under a plain
  `uv run pytest`, and that is a test (B2), not a convention.

`tools/mcp/` owns the MCP server (`kepler-mcp`) and nothing else: a fourth
consumer of the registry, served over stdio to a coding agent's console on a
machine with no checkout. Its rules:

- **The dependency runs `tools/mcp → tools/registry`**, plus `tools/mcp/groups
  → tools/bench/plane` (import-light by design, for `TOOL_CLASSES`).
  **`tools/mcp/` imports nothing from `tools/agent/` or `tools/llm/`**, and
  nothing under `algorithms/` imports it. `tests/test_mcp_surface.py` asserts
  both.
- **The `mcp` SDK is optional** (`uv sync --extra mcp`). Only
  `tools/mcp/server.py` imports it to serve, and `tools/mcp/selftest.py` to
  act as a client of that server; nothing else under `tools/mcp/` may. CI
  runs the MCP tests **first without it**, then the whole suite with it
  (`--extra mcp`), so every test that drives the SDK must call
  `pytest.importorskip("mcp")` *before* any SDK import, or CI fails.
- **The registry is read, never edited, to serve it.** What only the server
  knows (the pinned artifact root, a sentence the server makes false) is
  added or replaced at serve time in `tools/mcp/surface.py`, and a test pins
  each registry original.
- **Undeclared arguments never reach a tool.** The server validates each call
  against a copy of the registry schema with `additionalProperties: false`,
  and with `integer` excluding floats, matching the agent loop's validator.
  Several tools take keywords their schema omits on purpose (`subdir`,
  `output_dir`, …), and a model must not reach them. The agent loop agrees:
  a schema whose `properties` is declared empty takes no arguments, whatever
  the function's signature accepts.
- **`.env` is loaded first.** `tools/dotenv.py` resolves nothing at import;
  `kepler-mcp` loads `.env` before pinning roots or importing `tools.config`,
  whose settings are fixed at import, and so does the `kepler` console
  (`tools.tui:launch`). `tools.config` re-exports the loader.
- **Instructions stay under `tools.skill.BRIEF_LIMIT`** (1,900 characters,
  worst case, tested). Claude Code truncates a server's instructions at
  about 2,000. Everything longer is a `kepler://skill/...` resource.
- **The skill has one source**, `tools/skill/source/`. Edit it and run
  `uv run python -m tools.skill`; `skills/kepler-tools/` is generated.

**Bundled data and the Kepler home.** Tools read bundled fixtures only through
`config.BUNDLED_DATA_DIR`, which is `tools/_data`: a committed symlink to
`data/` in a checkout (or, in a clone made without symlink support, where the
link arrives as a text file, the checkout's `data/` directly), and in a wheel
the core data (`pulsar/`, `fieldcal/`, `afterglow/`, `variable_star/`) that
package-data ships. Never add a path of the form
`Path(__file__).parents[1] / "data"`: under a wheel it names a directory that
does not exist. An installed Kepler writes only under the per-user Kepler
home (`tools/paths.py`; `KEPLER_HOME`):

- `artifacts/`, the default for the MCP server and an installed console;
- `fits_downloads/`;
- `numba-cache/`, numba's compiled-function cache (`NUMBA_CACHE_DIR`,
  set by both entry points on an install);
- `bundles/<name>/`, the optional `optical` and `isochrones` bundles that
  `kepler-mcp fetch-data` installs, pinned by size and SHA-256 in
  `tools/mcp/bundles.json`.

A changed bundle is a new, content-addressed asset on the standing `data`
release, never a replaced one (`docs/releasing.md`).

`docs/archive/model-backends.md` is the port's full design and
`docs/benchmarking/harness.md` the harness's; `docs/tool-architecture.md`
sections 10 and 10.1 are the summaries, and 10.3 is the MCP server's.

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
  `fieldcal/`, `optical/`, `pulsar/`) — pinned to the package's own bundled
  data (`tools/_data`, a symlink to `data/` in a checkout), reading no
  setting — so a downloaded product under `data/fits_downloads/` stays
  writable and no environment variable can switch the guard off. It also
  covers fetched data bundles (`<kepler home>/bundles/`). A new fixture
  subtree has to be added to `_FIXTURE_SUBTREES`; a test asserts the tuple
  matches the directories present. An installed wheel re-anchors the data
  and download roots; see `docs/installing.md`.

### Runtime dependencies that are not optional

`numba` and `sep` are **hard import-time** requirements of
`algorithms/skylib_lite` (`@njit` on `util/angle.py` and
`extraction/centroiding.py`); there is no non-numba fallback. `scipy`, `astropy`,
and Pydantic v2 are likewise required.

End-to-end runs additionally need data that is not in this repo. On the
development host, `solve-field` is `/usr/bin/solve-field`, astrometry.net
indexes 4107-4119 are under `/usr/share/astrometry/data`, three further
index sets (2MASS 4200-series, TYCHO2, UCAC5) are under
`/srv/agents/catalogs/astrometry/{2MASS_ANET/4200,TYCHO2/indices,UCAC5}`, and
UCAC5 catalogue data is under `/srv/agents/catalogs/ATLAS/UCAC5`; none is
selected by the repository's default environment. Set `ANET_INDEX_PATH` and/or
`ATLAS_CATALOG_ROOT` to opt in. `ANET_INDEX_PATH` must name directories that
hold index files *directly* (`os.pathsep`-join the three leaf directories
above; the `astrometry/` root alone is rejected as holding no index files).
The packaged 4107-4119 indexes start at a wider scale than the ~10-arcminute
fixture, and the default all-sky 0.1-60 arcsec/pixel search has reached the
backend without producing a solution. With the 4200-series set the M15
fixture solves: in ~14 s with explicit bounds (`solve_astrometry(...,
search_radius_deg=1, min_scale_arcsec=0.4, max_scale_arcsec=0.8)`, P6) and in
~285 s all-sky, to the same solution. The bounds are opt-in; the default
stays the extracted all-sky search. The
`solver_data`-marked tests gate this path. The ATLAS backend has not been
validated (P9). Both backends still degrade to "unavailable" when unconfigured.

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
- ADS-backed tools require `ADS_DEV_KEY`; the optional agent loop — the
  `kepler` console and `tools/agent/` under it — requires a model backend.
  `ANTHROPIC_API_KEY` by default, or `KEPLER_MODEL_BACKEND=provider/model`
  plus that provider's key, or a local Ollama daemon, which needs none. The
  backend is selectable inside the session with `/backend`, so an unset
  variable is a question of which one it opens on, not whether it runs. Remote
  astronomy service calls stay out of default checks and should return bounded
  previews plus artifact paths for complete results.
