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
  pulsar.py           # 4-stage pulsar pipeline: light curve, periodogram, fold, sonify
  ads.py              # ADS literature search/review tools
  mast.py             # MAST archive/product tools
  mpc.py              # Minor Planet Center observation tools
  casda.py            # CASDA archive tools
  resolve.py          # SIMBAD-backed target resolution
  registry.py         # optional agent/tool schema registry
  runner.py           # optional Anthropic agent loop
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

Tools are the public surface. They should stay thin:

- accept normal Python values, file paths, or small Pydantic models;
- normalize and validate inputs locally;
- call an existing algorithm package rather than reimplementing astronomy math;
- return compact summaries, warnings/errors, and artifact metadata;
- write large arrays, tables, generated FITS files, and plots to disk instead
  of embedding them in inline results.

The first local, no-network tools are:

- `tools.astrometry.describe_image_wcs(path)`
- `tools.catalogs.list_photometric_catalogs()`
- `tools.catalogs.resolve_reference_band(catalog, image_filter)`
- `tools.calibration.solve_zeropoint_from_measurements(measurements, catalog_sources)`
- `tools.pulsar.load_pulsar_lightcurve(path, ...)`
- `tools.pulsar.compute_pulsar_periodogram(path, ...)`
- `tools.pulsar.fold_pulsar_lightcurve(path, period_s, ...)`
- `tools.pulsar.sonify_pulsar(path, period_s=None, ...)`
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

Next Python tools should follow the same pattern before adding new layers:

- `solve_astrometry(path, settings=None)`
- `extract_sources(path, settings=None)`
- `measure_photometry(path, sources, settings=None)`
- `calibrate_zeropoint(path, settings=None)`
- `search_catalog(catalog, region, limit=50)`
- `search_catalogs_for_image(path, limit=50)`

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
