# Kepler Tool Collection Architecture

Date: 2026-08-10
Status: active architecture

Kepler is an astronomy tool collection for Python callers, scripts, notebooks,
agents, and future CLI/application surfaces. It is not an orchestration
framework. The public tool layer should expose small, ordinary Python functions
that prepare inputs, call the extracted algorithms, and return compact typed
results or local artifact paths.

The working design rule is:

> Astropy-native inside, JSON-and-artifact-native outside.

Algorithm packages can use Astropy, NumPy, SciPy, Pydantic, FITS/WCS objects,
tables, local solver data, and astronomy-specific containers. Public tools
should summarize those objects into small Pydantic models, warnings/errors, and
artifacts with enough metadata to reproduce the operation.

---

## 1. Current Repository Shape

```text
tools/
  __init__.py
  astrometry.py       # WCS/header summary tools
  calibration.py      # zero-point tools
  catalogs.py         # catalog declarations and band helpers
  simbad.py           # SIMBAD object, measurement, and bibliography tools
  ned.py              # NED historical table tools
  vizier.py           # broad VizieR catalog search tools
  atnf.py             # ATNF pulsar catalog tools
  pulsar.py           # pulsar pipeline: scan resolution, light curve, periodogram, fold, sonify, plot
  photometry.py       # local aperture photometry over the bundled FITS library
  hr_diagram.py       # FITS-to-HR-diagram pipeline orchestration (plus a catalog-only entry point)
  radio_sources.py    # radio FITS -> catalog-identified sources -> labeled SED plot
  ads.py              # ADS literature search/review tools
  mast.py             # MAST archive/product tools
  mpc.py              # Minor Planet Center observation tools
  casda.py            # CASDA archive tools
  resolve.py          # SIMBAD-backed target resolution
  registry.py         # optional agent/tool schema registry
  runner.py           # thin console shim over tools/agent/ (kept for kepler-astro-query)
  sessions.py         # per-run session manifest recording + the loop's cache-key helper
  agent/              # headless agent loop: run_session, events, the moved SYSTEM_PROMPT
  llm/                # provider-neutral model port -- see section 10
  workspace.py        # local artifact helpers
  models.py           # shared result, warning/error, WCS, catalog, artifact models
  config.py           # small environment-backed settings helpers
  artifacts.py        # local artifact path and file metadata helpers

algorithms/
  __init__.py
  wcs/                  # Python WCS algorithms
  photometry/           # Python source extraction and aperture photometry
  fieldcal/             # Python zero-point field calibration
  skylib_lite/          # shared vendored Skylib subset
  catalogs/             # Python catalog/provider declarations, no network calls
  query/                # Python remote catalog access
  hrdiagram_py/         # Python HR-diagram pipeline: parity port + optimizer, not an extraction
  radio/                # Python radio spectral-index fitting + catalog cross-matching, new capability

  pulsar/               # Python pulsar pipeline: ingest, periodogram, folding,
                        #   sonification (a PORT, not an extraction)

  lightcurve/           # TypeScript light-curve algorithms
  periodogram/          # TypeScript periodogram algorithms
  hrdiagram/            # TypeScript HR-diagram algorithms
docs/
```

The Python distribution discovers the `tools*` and `algorithms*` packages;
package data such as
`ngc2000.dat` belongs to the corresponding `algorithms.skylib_lite.*` package path.

---

## 2. Public Tool Layer

**One public tool call is Kepler's execution boundary.** No run, stage, session,
or batch object spans two calls; no tool writes state another tool reads. A
caller that needs a value from an earlier step passes it in, or passes the
artifact path the earlier call returned. The processing-run architecture that
used to carry that state was removed by the stateless rollout (S0–S6), along
with `algorithms/fieldcal/deps.py` — cross-domain values are explicit function
arguments now, not injected module-level names.

Tools are the public surface. They should stay thin:

- accept normal Python values, file paths, or small Pydantic models;
- normalize and validate inputs locally;
- call an existing algorithm package rather than reimplementing astronomy math;
- return compact summaries, warnings/errors, and artifact metadata;
- write large arrays, tables, generated FITS files, and plots to disk instead
  of embedding them in inline results.

The first local, no-network tools are:

- `tools.optical.list_optical_frames(directory=None, image_filter=None)` /
  `tools.optical.resolve_optical_frame(name, directory=None)` -- Stage 0 for
  image work. Searches the primary optical root *and* the archive download
  root, so a product fetched by `tools.mast`/`tools.casda` resolves by name
  through the same registry every image tool already takes a path from.
  Both bounds on that search are operator settings rather than tool
  parameters: the download root is walked recursively only while it resolves
  inside `KEPLER_DATA_DIR` (outside it, searched flat with a
  `download_root_outside_data_dir` warning), and `KEPLER_MAX_FRAMES`
  (default 200) caps how many frames one listing reads headers for from each
  root, with a `listing_truncated` warning naming the total when it bites.
  `search_mast(download=true)` reports the directories products landed in, so
  `directory=` can reach a specific product past the cap.
- `tools.astrometry.describe_image_wcs(path)`
- `tools.catalogs.list_photometric_catalogs()`
- `tools.catalogs.resolve_reference_band(catalog, image_filter)`
- `tools.calibration.solve_zeropoint_from_measurements(measurements, catalog_sources)`
- `tools.photometry.calibrate_zeropoint(path, catalog_sources=None, catalog_fixture=None, catalogs=None, compare_to=None)`
  -- extraction -> photometry -> catalog match -> reference magnitude ->
  `calc_solution`. Local only when `catalog_sources` is injected or
  `catalog_fixture` names a recorded input (`"selected_rows"`, the matched
  APASS rows; `"full_response"`, the recorded response for the whole field
  plus its VSX filter); without either the calibration-input helper queries
  a reference catalog over the network.
- `tools.fieldcal_reference.list_zeropoint_references()` /
  `load_zeropoint_reference(field)` / `compare_zeropoint_to_reference(...)` /
  `replay_field_calibration(field)` -- the four recorded Skynet zero-point
  solves, the offline replay inputs (`replay_catalog_sources`,
  `replay_variable_sources`) that drive a real solve against them, and the
  end-to-end selection replay that re-chooses NGC 5128 B's 35 calibration
  stars from the recorded 132-row APASS response and reproduces the recorded
  solve bit for bit.
- `tools.pulsar.list_pulsar_scans(...)` / `tools.pulsar.resolve_pulsar_scan(...)`
- `tools.pulsar.load_pulsar_lightcurve(path, ...)`
- `tools.pulsar.compute_pulsar_periodogram(path, ...)`
- `tools.pulsar.fold_pulsar_lightcurve(path, period_s, ...)`
- `tools.pulsar.sonify_pulsar(path, period_s=None, ...)`
- `tools.pulsar.plot_pulsar(...)`
- `tools.photometry.list_photometry_targets()`
- `tools.photometry.run_photometry_on_target(target, ...)`
- `tools.workspace.list_artifacts(directory=None)`
- `tools.workspace.describe_artifact(path)`

The split remote database/archive tools follow the same boundary: bounded
inline previews, complete result artifacts, provider warnings/errors, and no
live calls in default validation:

- `tools.resolve.resolve_target(name)`
- `tools.simbad.search_simbad(name)`
- `tools.simbad.search_simbad_measurements(name, table="flux")`
- `tools.simbad.search_simbad_bibliography(name)`
- `tools.ned.search_ned(name, table="photometry")`
- `tools.vizier.list_vizier_catalogs(keywords)`
- `tools.vizier.search_vizier(...)`
- `tools.atnf.search_atnf(name)`
- `tools.ads.search_ads(...)`
- `tools.ads.build_literature_review(...)`
- `tools.mast.search_mast(name, ...)`
- `tools.mpc.search_mpc(designation)`
- `tools.casda.search_casda(...)`

`tools.hr_diagram` composes several of the above (`tools.vizier.search_vizier`
for both Gaia DR3 and cluster-literature lookups) with the pure
`algorithms.hrdiagram_py` package rather than adding a new query layer:

- `tools.hr_diagram.extract_photometry_from_fits(fits_path)`
- `tools.hr_diagram.crossmatch_gaia(csv_path, ...)`
- `tools.hr_diagram.crossmatch_gaia_by_position(cluster_name, ...)` -- no FITS frame; fetches
  Gaia DR3 directly around the cluster's own resolved position
- `tools.hr_diagram.get_literature_cluster_params(cluster_name)`
- `tools.hr_diagram.select_cluster_members(csv_path, cluster_name, ...)`
- `tools.hr_diagram.fit_and_compare_hr_diagram(members_csv_path, cluster_name, ...)`
- `tools.hr_diagram.run_full_hr_pipeline(fits_path, cluster_name, ...)`
- `tools.hr_diagram.run_full_hr_pipeline_from_catalog(cluster_name, ...)` -- the
  `run_full_hr_pipeline` composite with `extract_photometry_from_fits` +
  `crossmatch_gaia` swapped for `crossmatch_gaia_by_position`, so a plain "HR
  diagram for cluster X" request needs no FITS file at all

`tools.photometry` is a thin wrapper reusing `tools.claude_photometry_haiku_tool`'s
already-tested pipeline directly (not a reimplementation), so a tool-use call
produces exactly what the standalone CLI script produces. It intentionally
does not share extraction settings with `tools.hr_diagram.extract_photometry_from_fits`:
the two need different things from `algorithms.photometry` (a calibrated
zero point and fixed apertures here; cheap "auto" Kron-like apertures and no
zero point there, since the HR-diagram pipeline discards the frame's own
magnitude once Gaia's is fetched). `run_photometry_on_target(...,
write_source_table=True)` writes a CSV in the `ra_deg`/`dec_deg` column shape
`tools.hr_diagram.crossmatch_gaia` expects, as the one deliberate bridge
between the two.

`tools.radio_sources` composes `algorithms.photometry` (source extraction, its
own settings again -- neither a Gaia handoff nor an optical zero point apply
to a radio map), `algorithms.radio` (spectral fitting, catalog cross-match),
`tools.vizier.search_vizier(category="radio")`, and `tools.ned.search_ned`:

- `tools.radio_sources.plot_field_sed(fits_path, ...)` -- the main entry point:
  identify sources in a radio FITS frame against VizieR's radio catalogs, then
  plot every identified source's spectral energy distribution (from NED)
  together on one labeled plot, each with its own fitted spectral index.
- `tools.radio_sources.identify_radio_sources(fits_path, ...)` -- the spatial
  half alone: detected sources cross-matched against radio catalogs by
  position, with no plot.
- `tools.radio_sources.analyze_source_spectrum(name=..., csv_path=..., frequencies_hz=..., fluxes_jy=...)`
  -- the spectral half alone, for one already-identified/named source.

`tools.wcs.solve_astrometry(path, *, index_path=None, write_header=False,
timeout_s=None, force=False, search_radius_deg=None, min_scale_arcsec=None,
max_scale_arcsec=None)` wraps the extracted plate solver with its required
per-call backend configuration, structured unavailable and no-solution outcomes,
attempted-backend reporting, and guarded FITS-header persistence. A single tool
call is Kepler's execution boundary: no run or stage state is retained between
calls.

The three search bounds are opt-in (P6). Unset, the solve is the extracted
all-sky search over 0.1–60 arcsec/px; set, they are validated at the tool
boundary (`invalid_search_bounds`), reach the algorithm as one
`algorithms.wcs.config.WcsSearchBounds`, and the result's `search` reports the
radius, scale window, and pointing centre astrometry.net was asked to search,
with `explicit` naming which bounds the caller set and, when the ATLAS
backend ran, the narrower window it was given (`atlas_*`; ATLAS takes no
radius). A radius below 180
is centred on the frame's own pointing hint; a frame that yields none gets
`search_radius_without_hint`, not a silent all-sky search. On the development
host, against its 4200-series indexes, the M15 fixture solves in ~14 s at
`search_radius_deg=1, min_scale_arcsec=0.4, max_scale_arcsec=0.8` and in
~285 s all-sky, to the same solution.

Next Python tools should follow the same pattern before adding new layers:

- `extract_sources(path, settings=None)`
- `measure_photometry(path, sources, settings=None)`
- `search_catalog(catalog, region, limit=50)`
- `search_catalogs_for_image(path, limit=50)`

`calibrate_zeropoint` and `solve_astrometry` were on this list and have since
landed; both are above.

TypeScript-backed tools should come after the TypeScript package/runtime story
is explicit. Their first wrapper should be simple: JSON in, existing algorithm
execution, compact JSON/artifact summary out.

---

## 3. Algorithm Packages

The algorithm packages are the source of truth for scientific behavior. Tool
and architecture work should not silently change numerical behavior or fix
algorithm bugs. Structural moves such as `algorithms.skylib_lite` must be mechanical
import/package rewiring. Bug fixes belong in focused remediation PRs with the
smallest targeted tests that prove the affected behavior.

Current algorithm ownership:

| Package | Owns | Notes |
| --- | --- | --- |
| `algorithms.wcs` | FITS-header WCS construction, astrometry.net solving, ATLAS solving, WCS validation, FITS header write-back | Requires solver binaries/indexes or local UCAC data for end-to-end solving. |
| `algorithms.photometry` | Source extraction and aperture photometry | Uses `algorithms.skylib_lite` extraction, calibration, photometry, and utility code. |
| `algorithms.fieldcal` | Catalog-source matching, reference-magnitude resolution, zero-point solving | Uses dependency seams for photometry/WCS and defaults catalog queries to `algorithms.query`. |
| `algorithms.catalogs` | Catalog/provider declarations, band tables, filter mappings, SIMBAD vocabulary, ADS field metadata, NED table names, ATNF parameter vocabulary | Declaration only; importing it should not perform network work. |
| `algorithms.query` | VizieR, SDSS, SIMBAD, cache policy, WCS-footprint query orchestration | Owns remote catalog calls; live calls stay out of default checks. |
| `algorithms.hrdiagram_py` | Star-cluster CMD/HR-diagram fitting: CM<->HR transform, extinction, isochrone loading, distance/E(B-V)/age optimizer, field-star removal, geometric matching | A parity **port** of `algorithms.hrdiagram` (TypeScript) plus a new optimizer, not a byte-preserving extraction -- deliberately not named `hrdiagram` since that folder is TypeScript-owned. Performs no *catalog* network I/O -- Gaia/VizieR catalog fetching lives in `tools.hr_diagram` via `tools.vizier.search_vizier`. Its `isochrones.py` still calls the PARSEC isochrone service (stev.oapd.inaf.it) directly; no existing tool wraps it. |
| `algorithms.radio` | Radio spectral-index/log-parabola fitting (`spectral_fitting.py`) and generic RA/Dec-column-guessing catalog cross-match (`matching.py`) | New first-party capability, no upstream Skynet/Astromancer equivalent. Performs no network I/O -- VizieR/NED fetching lives in `tools.radio_sources`. |
| `algorithms.pulsar` | Pulsar file ingest, background subtraction, Lomb-Scargle periodogram, phase folding/binning, and audio synthesis | The one **port** rather than extraction under `algorithms/`; marked `# PORTED:`. Stage order is a dependency chain — see `docs/pulsar-tool-pipeline.md`. |
| `algorithms.lightcurve` | Framework-free TypeScript light-curve ingestion, transforms, period folding, and pulsar sonification | Typechecked by the root `tsconfig.json`. |
| `algorithms.periodogram` | Framework-free TypeScript Lomb-Scargle periodogram and period helpers | No runtime wrapper yet. |
| `algorithms.hrdiagram` | Framework-free TypeScript cluster/HR-diagram transforms | No runtime wrapper yet. |

---

## 4. Shared Models And Artifacts

Keep shared Python models small until a tool needs more:

- warning/error records;
- file and artifact metadata;
- runner session manifests;
- table summaries;
- WCS summaries;
- catalog summaries;
- reference-band and zero-point results.

Future result envelopes can grow toward a richer `ToolResult` shape when
retrieval, provenance, pagination, and remote provider warnings require it:

```python
class ToolResult(BaseModel):
    status: Literal["ok", "partial", "not_found", "error"]
    data: dict | list[dict] | None
    warnings: list[ToolWarning]
    errors: list[ToolError]
    artifacts: list[Artifact]
    provenance: list[Source]
    query: QueryTrace | None
    pagination: Pagination | None
```

Important modeling rules:

- Coordinates serialize as decimal degrees plus frame.
- Quantities serialize with value, unit, and uncertainty when known.
- Times serialize as ISO strings plus scale where known.
- Tables expose column metadata rather than dumping huge payloads.
- Measurements preserve uncertainty, method, calibration assumptions, and source.
- Artifacts include local path, MIME type, size, created time, and producing tool.
- Agent-loop artifacts are session-scoped under
  `artifacts/sessions/<session_id>/...`; the runner writes
  `session_manifest.json` in that directory with the ordered tool-call trace,
  cache hits, warning/error summaries, and artifact paths, but not full tool
  payloads.

---

## 5. Extracted Skylib Inventory

Several Python algorithms originally vendored overlapping pieces of Skynet's
`skylib`. They are consolidated into `algorithms.skylib_lite` so every extracted
Skylib call uses one local implementation without depending on an external
`skylib` installation.

Originally extracted package-local skylib subsets:

| Algorithm extraction | Extracted skylib subset |
| --- | --- |
| WCS | `astrometry/` including `anet/`, `atlas/`, solver types, and `ngc2000.dat`; `calibration/background.py`; `extraction/main.py`; `extraction/centroiding.py`; `io/fits_compression.py`; `util/angle.py`; `util/fits.py`. |
| Photometry | `calibration/background.py`; `extraction/main.py`; `extraction/centroiding.py`; `photometry/aperture.py`; `photometry/aperture_numba.py`; `photometry/exposure.py`; `util/angle.py`; `util/fits.py`; `util/overlap.py`; `util/stats.py`. |
| Field calibration | `util/angle.py`; `util/fits.py`; `util/stats.py`. |

Consolidation target:

```text
algorithms/skylib_lite/
  __init__.py
  astrometry/
  calibration/
  extraction/
  io/
  photometry/
  util/
```

Consolidation rules:

- Move extracted files mechanically and update imports to
  `algorithms.skylib_lite.*`.
- Preserve numerical code, constants, comments, and data files.
- Remove package-local `skylib` copies only after every import path is updated.
- Do not combine this with algorithm bug fixes or helper rewrites.

---

## 6. Future Services

Services are internal building blocks, not public API commitments. Add them only
when multiple tools need the same careful behavior.

Likely service areas:

- target resolution;
- catalog search and row normalization;
- archive discovery and product fetching;
- local FITS/table/product inspection;
- image, photometry, time-series, and spectrum workflows;
- plot and artifact creation;
- table normalization, joins, and crossmatch;
- ADS/literature search and citation metadata;
- provenance, cache, and limits.

Do not turn every dependency into an architecture layer. `astropy`, `astroquery`,
`pyvo`, `photutils`, `ads`, `numpy`, `scipy`, and related packages are
implementation dependencies selected by tool capability. Higher-order scientific
dependencies are allowed when the tool or algorithm needs them; the architecture
should bound public inputs and outputs, not remove valid science dependencies.

---

## 7. Runtime Policy

Configuration should come from environment variables, optional config files, and
direct constructor/function arguments. Keep settings explicit and small at the
tool boundary.

Runtime behavior should be bounded:

- conservative defaults for row counts, radius, byte size, and timeouts;
- no live remote calls in default validation;
- partial results when one provider in a multi-provider tool fails;
- credentials redacted from logs and outputs;
- recursive local file scans avoided by default;
- large payloads returned as artifacts plus summaries.
- `tools.runner` persists a session manifest when it starts, after each tool
  call, and at terminal states (`end_turn`, `max_turns`, or an exception), so
  another caller can inspect the exact session context without re-running
  remote queries.

Serving is optional. A Python caller must be able to import and call every tool
without running a server. If a serving surface is added later, generate it from
the same tool functions and models rather than designing the package around a
server.

---

## 8. Validation Policy

Default checks stay lightweight and deterministic:

- `python3 -m compileall tools algorithms`
- smoke imports for `tools.*` and `algorithms.*`
- `git diff --check`

End-to-end WCS, photometry, catalog-query, and field-calibration validation
requires FITS data, solver binaries, local catalog data, and native astronomy
dependencies. Those checks should be targeted to the PR that changes the
behavior and should not become a broad architecture gate.

TypeScript algorithms currently have no build manifest. Add `package.json` and
`tsconfig.json` only when the TypeScript package/runtime shape is being defined.

---

## 9. Non-Goals

- No orchestration framework.
- No mandatory serving framework.
- No broad numerical remediation in architecture PRs.
- No remote-provider live tests in default checks.
- No large model tree before public tools need it.
- No TypeScript runtime redesign before TypeScript-backed tools are in scope.

---

## 10. The Agent Loop and Model Port

Serving/agent-loop code stays optional (section 7): every tool is callable
from plain Python without any of this. When an agent loop *is* wanted, it is
built in two layers.

`tools/agent/` is the headless loop. `run_session()` drives a model backend
over the tool registry and yields a stream of events (`SessionStarted`,
`TurnStarted`, `TextDelta`, `ToolCallProposed`/`Started`/`Finished`/`Denied`,
`ProtocolFault`, `TurnFinished`, `SessionFinished`); a `Decision` flows back in
through an approver callable. It imports no UI toolkit. `SYSTEM_PROMPT` lives
in `tools/agent/prompt.py`. `tools/runner.py` is now a thin shim that iterates
`run_session()` and prints, kept so the `kepler-astro-query` console script and
its output are unchanged.

`tools/llm/` is the provider-neutral **model port**. Two rules govern it:

> The core owns the loop; adapters own the dialect.
>
> Replay the tools, never the model.

- A backend is named by a `provider/model` spec, split on the **first slash
  only** (`ollama/llama3.1:8b`, `openai/meta-llama/Llama-3-8b`). Recognized
  providers: `anthropic`, `openai`, `ollama`, `gemini`. `build_backend(spec)`
  constructs one; `spec` defaults to `KEPLER_MODEL_BACKEND`.
- Environment: `KEPLER_MODEL_BACKEND` (default spec), `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY` / `OPENAI_BASE_URL`, `GEMINI_API_KEY`, `OLLAMA_BASE_URL`. A
  provider key from the environment reaches only that provider's default host;
  a non-default base URL needs a key passed explicitly with it.
- `complete()` is the **only required method** of a `ModelBackend`, and it is
  non-streaming. Streaming is a capability flag with a one-shot fallback.
  Schema translation into a backend's dialect and pre-dispatch argument
  validation are the caller's job (`tools/llm/schema.py`,
  `tools/llm/validation.py`), so adapters never import `tools/registry.py`.
- Zero new third-party dependencies: the `anthropic` SDK is reused; the OpenAI,
  Ollama, and Gemini adapters are raw `httpx`.
