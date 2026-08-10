# Kepler Tool Architecture

Date: 2026-08-10
Status: proposed
Scope: the eight extracted domain folders — `wcs/`, `photometry/`, `fieldcal/`,
`catalogs/`, `query/` (Python) and `lightcurve/`, `periodogram/`, `hrdiagram/`
(TypeScript).

This document specifies the target architecture for turning those folders into a
collection of tools any LLM can call. It is the companion to
[`architecture-brainstorm.md`](architecture-brainstorm.md), which sketches the
*greenfield* tool families Kepler should eventually grow (retrieval, literature,
plotting). This document covers the harder half: the ~22,400 lines of algorithm
code that already exist and were extracted from a service, not designed as tools.
The file-by-file move plan lives in
[`tool-architecture-migration.md`](tool-architecture-migration.md).

---

## 1. The problem in one paragraph

Skynet's pipeline stages are *service* code: a stage takes an ORM row
(`processing_run`), mutates it in place, reads configuration from ambient global
state, raises exceptions as control flow, returns unbounded in-memory numpy
arrays, and assumes a caller who already holds an open FITS file and a wired
dependency graph. Astromancer's TypeScript is *UI* code: functions that assume an
Angular component owns the state and a Highcharts instance owns the output. An
LLM tool call is the opposite on every axis: a stateless JSON request against a
declared schema, returning bounded JSON plus file handles, where failure is a
value and not a stack trace. The gap between those two shapes is what this
architecture has to bridge — **without editing the algorithms**, because the
extraction contract (`CLAUDE.md`, each `EXTRACTION.md`) makes byte-preservation
and documented parity quirks load-bearing.

The resolution is that the algorithms **do not move up** into the tool layer.
They stay frozen at the bottom, and two thin new layers are built on top.

---

## 2. Layering

```text
   LLM / agent / notebook / CLI
              │  JSON tool call, declared schema
              ▼
┌─────────────────────────────────────────────────────────┐
│ kepler.tools.*        one function per tool.            │
│                       Validates input, calls exactly    │
│                       one adapter, returns ToolResult.  │
│                       Imports NO kernel. No astronomy.  │
├─────────────────────────────────────────────────────────┤
│ kepler.adapters.*     the only layer that knows kernel  │
│                       quirks. Opens FITS, wires deps,   │
│                       builds run-state stand-ins,       │
│                       contains preserved bugs, maps     │
│                       exceptions to error codes.        │
├─────────────────────────────────────────────────────────┤
│ kepler.kernels.*      FROZEN extracted code.            │
│   wcs/ photometry/ fieldcal/ catalogs/ query/           │
│   + ts/ reached through the Node bridge                 │
└─────────────────────────────────────────────────────────┘
       kepler.contracts.*   Pydantic models, error codes, envelope
       kepler.runtime.*     artifact store, config, limits, registry, serving
```

### The four rules that make this work

**R1 — Kernels are frozen.** No file under `kepler/kernels/` is edited except for
import rewiring during the move. Every `# EXTRACTED: was <symbol>` marker
survives verbatim. Behaviour changes happen in adapters or not at all.

**R2 — Tools never import kernels.** A tool module imports `kepler.contracts` and
exactly one adapter. This is mechanically checkable (see §10) and it is what
keeps the frozen layer frozen: there is no path by which a tool author can
"just tweak" `field_cal.py`.

**R3 — No science objects cross the tool boundary.** Tool inputs are scalars,
strings, and artifact handles. Tool outputs are JSON-safe models plus artifact
handles. `np.ndarray`, `fits.Header`, `astropy.wcs.WCS`, `CatalogSource`, and
`PhotometryData` live below the adapter line and never above it.

**R4 — Failure is data.** Kernels raise (`ValueError`, `FieldCalDependencyError`,
astroquery transport errors). Adapters catch and classify. Tools return
`status: "error"` with a stable code. An unhandled exception escaping a tool is a
bug in the adapter, not an expected outcome.

### Why not just add `@tool` decorators to the existing entry points?

Because the existing entry points cannot satisfy R3 or R4. `solve_wcs` takes
`(processing_run, header, data, tmpdir, ...)` — an ORM stand-in, a mutable FITS
header it writes into, a raw float32 array, and a scratch directory — and it
signals "no solution" the same way it signals "you never configured a backend."
`perform_field_calibration` requires four module-global callables to be assigned
before it will run at all. Decorating those signatures produces a tool schema an
agent cannot fill in and a result an agent cannot interpret. The adapter layer is
where that translation has to happen, and putting it anywhere else means editing
frozen code.

---

## 3. State, handles, and the workspace

Astronomy tool chains are not stateless in practice: solve → extract → measure →
calibrate all operate on the same frame, and passing a 4096×4096 float array
through a JSON tool call is not an option. The architecture uses a **content-
addressed artifact store** as the only shared state.

```text
kepler.runtime.artifacts.ArtifactStore
  put(path|bytes, kind, produced_by) -> Artifact
  resolve(ref) -> local path
```

- An `Artifact` is `{id, kind, mime, path, bytes, sha256, created_at,
  produced_by, parent_ids}`. `id` is `art_<sha256[:16]>`, so the same input file
  registered twice is the same artifact.
- Tool inputs that name data take an **`ImageRef`**: either `art_...` or a local
  path under an allowlisted root (`KEPLER_DATA_ROOTS`). Nothing else resolves —
  no URLs, no recursive directory scans, no bare relative paths.
- Tools that produce files (a WCS-written FITS, a source table, a folded curve)
  register them and return handles with `parent_ids` set, which gives a free
  provenance DAG across a whole agent session.
- `list_artifacts` / `describe_artifact` let an agent recover handles it dropped
  from context.

This is what replaces `processing_run`. The adapter builds a throwaway
`ProcessingRunRef`/`WcsSolution` dataclass per call (the stand-ins already exist
in `wcs/state.py` and `fieldcal/schemas.py`), lets the kernel mutate it, and then
reads what it needs — but see §6, because *which* fields the adapter is allowed
to trust is a preserved-bug question.

---

## 4. The tool contract

### Envelope

```python
class ToolResult(BaseModel):
    schema_version: Literal["kepler.tool.v1"]
    status: Literal["ok", "partial", "empty", "error"]
    data: BaseModel | None                 # per-tool typed payload
    artifacts: list[Artifact] = []
    warnings: list[Warning] = []           # {code, message, detail}
    errors: list[ToolError] = []           # {code, message, field?, retriable}
    provenance: Provenance                 # tool, version, inputs, timing, packages
```

`status` distinctions matter to an agent's next move and are chosen for that:

| status | meaning | agent's next move |
|---|---|---|
| `ok` | complete result | continue |
| `partial` | some sources returned, one provider failed / row cap hit | continue, or narrow and retry |
| `empty` | ran correctly, found nothing | change the region/threshold, don't retry |
| `error` | did not run | read `code` |

### Error codes

Stable, closed set. Anything unmapped becomes `internal_error` and is a bug.

`invalid_input` · `not_found` · `ambiguous_target` · `no_solution` ·
`insufficient_sources` · `backend_unavailable` · `dependency_missing` ·
`provider_unavailable` · `rate_limited` · `timeout` · `too_many_results` ·
`artifact_too_large` · `unsupported_format` · `internal_error`

Two of these earn their place specifically from this codebase:

- **`backend_unavailable` vs `no_solution`.** Today both WCS backends "degrade to
  unavailable rather than failing," so a solve with no astrometry.net indexes and
  no UCAC catalog returns exactly what a genuinely unsolvable frame returns. An
  agent cannot tell "your data is bad" from "your deployment is missing 40 GB of
  index files." The adapter probes `build_anet_config` / `build_atlas_config`
  first and returns `backend_unavailable` with the missing environment variable
  named. This is the single highest-value thing the tool layer adds to `wcs/`.
- **`dependency_missing`.** `FieldCalDependencyError` becomes this, naming the
  unwired seam — but under the composition root of §5 it should be unreachable,
  so seeing it is a wiring bug.

### Bounded output

Source tables run to thousands of rows; a tool result that dumps them is
unusable. Every table-returning tool takes `limit` (default 50, hard cap 500) and
returns:

```json
{ "row_count": 4312, "returned": 50, "truncated": true,
  "columns": [...], "rows": [...],
  "artifacts": [{"id": "art_...", "kind": "source_table", "mime": "text/x-ecsv"}] }
```

The full table always goes to an artifact. The inline rows are a *sample for
reasoning*, not the dataset. Column metadata (name, unit, description) is always
present so the agent can interpret the sample without a second call.

---

## 5. Composition root — replacing `fieldcal.deps`

`fieldcal/deps.py` is the service-era seam: module-level names a host application
assigns before use, with call sites written as `deps.run_photometry(...)`
precisely so late injection works. `CLAUDE.md` requires that pattern be
preserved, and it must be — but module globals are process-wide, so two
concurrent `calibrate_zeropoint` calls would race.

The adapter owns this, not the tool:

```python
# kepler/adapters/fieldcal.py
_WIRING_LOCK = threading.Lock()

@contextmanager
def wired_fieldcal():
    """Bind fieldcal's severed seams to Kepler's own kernels for one call.

    SEAM: fieldcal.deps holds process-global names by design (see
    fieldcal/EXTRACTION.md). Serialised rather than refactored, because
    rewriting the deps.<name>(...) call sites would edit frozen kernel code.
    """
    with _WIRING_LOCK:
        saved = {n: getattr(deps, n) for n in _WIRED}
        deps.run_photometry = photometry.pipeline.photometry.run_photometry
        deps.run_source_extraction = ...
        deps.get_source_radec = ...
        deps.build_wcs_for_processing_run = ...
        try:
            yield
        finally:
            for n, v in saved.items():
                setattr(deps, n, v)
```

`deps.query_catalogs` is left at its lazy default so `import fieldcal` still
costs no astroquery.

**Accepted constraint:** field calibration is single-flight per process. It is
documented in the tool description (`concurrency: serialised`), and the honest
scaling answer is a worker process per call, not a refactor of the kernel. If
that becomes a real bottleneck, the fix is a `Deps` dataclass threaded through
`field_cal.py` — a deliberate divergence from Skynet, requiring its own decision
record, not an incidental change.

---

## 6. Containing preserved bugs at the adapter

This is the part of the design that is specific to Kepler rather than generic
tool architecture, and it is the strongest argument for the adapter layer
existing at all. The extraction deliberately preserved ~20 upstream defects. A
tool must not fix them — and must not *propagate* them into a result an agent
will reason over. Containment, not repair.

| Kernel behaviour (preserved) | Failure it would cause in a tool result | Adapter containment |
|---|---|---|
| `_clear_wcs_solution_fields()` clears `ra`/`dec`/`pixel_scale`/`rotation`, but the solve writes `ra_deg`/`dec_deg`/… — so **stale values survive a failed solve** (`wcs/EXTRACTION.md` §5.2) | Agent reads last run's pointing as this run's answer | Build the result **only** from `solve_wcs`'s return value, never from the mutated state object; allocate a fresh `WcsSolution` per call so there is nothing stale to inherit. Emit warning `stale_solution_fields_not_cleared` when a solve fails on a run that carried a prior solution. |
| APASS `H_alpha` → `rprime`, `Halpha` → Lupton R: two spellings of one filter give different reference magnitudes | Zero point silently depends on header spelling | `resolve_reference_band` resolves **every** known spelling and returns them all; warns `narrowband_alias_divergence` with both values when they disagree. Never picks one. |
| `CATALOGS` (11) and `CATALOG_OPTIONS` (2) disagree deliberately (`catalogs/EXTRACTION.md` §4) | Merging changes which band a narrowband/unfiltered image calibrates against | `list_photometric_catalogs` returns them as two named registries with a note on which code path reads which. No tool merges them. |
| `apcorr_tol=0` set in `field_cal.py` but gating aperture correction in `skylib/aperture.py`; "no centroiding" realised as `centroid_radius=0.0` + `if r_cent > 0` | Caller who sets photometry settings by hand silently breaks Afterglow parity | Adapter exposes `parity_mode: "afterglow" \| "explicit"`. `afterglow` (default) sets the paired values together and refuses to let either be overridden individually. |
| VizieR cache snaps regions to a fixed grid (`query/EXTRACTION.md` §5.1) | Sources returned for a slightly different footprint than requested, visible at a field edge | `search_catalog` echoes the **effective** region in `provenance.query`, and warns `region_snapped_to_cache_grid` when it differs from the requested one. |
| Variable-tool two-pass misalignment: `data` and `error` built under different predicates, then indexed in lockstep — one null `errorMSE` misaligns everything after it and the tail throws | Bridge subprocess dies mid-call, or worse, returns silently misaligned science | Bridge validates series lengths and null-density **before** dispatch; returns `invalid_input` / `inconsistent_series_lengths` with the offending index. Kernel untouched. |
| Isochrone break-splice off-by-one; `getExtinction` ignoring its own `rv` in the leading term | Wrong numbers presented as authoritative | `fit_isochrone` result carries `known_deviations: ["isochrone_splice_offset", "extinction_rv_leading_term"]`, so the agent can caveat its own report. |

The general rule: **the adapter never reads mutated kernel state when a return
value is available, and every documented deviation ships as a machine-readable
warning on the result that it affects.** Preserved bugs stop being invisible
without becoming un-preserved.

---

## 7. Tool catalogue

Names are verb-first and stable. Descriptions in the real implementation must be
prescriptive about *when* to call the tool, not just what it does — 3–4 sentences
minimum — because that is what drives correct tool selection.

### Catalog declarations — pure, offline, cheap

| Tool | Kernel | Notes |
|---|---|---|
| `list_photometric_catalogs` | `catalogs/` | Both registries, bands, VizieR IDs. No network. |
| `resolve_reference_band` | `fieldcal/ref_mag.py`, `query/selection.py` | Filter → reference band or colour expression, per catalog. Surfaces alias divergence (§6). |

These two are deliberately first-class rather than internal helpers: they are
instant, deterministic, need no deployment data, and answer the question agents
actually ask first ("can I calibrate an H-alpha frame against APASS?").

### Remote catalog access

| Tool | Kernel |
|---|---|
| `resolve_target` | `query/simbad.py` — returns *all* matches with an `ambiguous_target` warning; never first-match |
| `search_catalog` | `query/runner.py::query_catalogs` |
| `search_catalogs_for_image` | `query/runner.py::query_catalogs_for_image` + `query/geometry.py` |

### Astrometry

| Tool | Kernel |
|---|---|
| `solve_astrometry` | `wcs/wcs.py::solve_wcs` — returns solution summary + FITS artifact with the header written |
| `describe_image_wcs` | `photometry/pipeline/source_extraction.py::build_wcs_from_header`, `wcs/header_utils.py` — header read only, no solve, no backend needed |

### Photometry

| Tool | Kernel |
|---|---|
| `extract_sources` | `photometry/pipeline/source_extraction.py::run_source_extraction` |
| `measure_photometry` | `photometry/pipeline/photometry.py::run_photometry` |

### Field calibration

| Tool | Kernel |
|---|---|
| `calibrate_zeropoint` | `fieldcal/field_cal.py::perform_field_calibration` (wired per §5) |
| `solve_zeropoint_from_measurements` | `fieldcal/solution.py::calc_solution` — pure, takes a measurement table, no I/O |

Splitting `calc_solution` out is worth it: it is the one piece of the calibration
chain an agent can call on data it already holds, with no FITS file, no network,
and no wiring.

### Time series — TypeScript kernels via the bridge

| Tool | Kernel |
|---|---|
| `compute_periodogram` | `periodogram/core/lomb-scargle.ts` |
| `find_periodogram_peaks` | `periodogram/core/peak-detection.ts`, `periodogram/pulsar/pulsar-periodogram-range.ts` |
| `fold_lightcurve` | `lightcurve/*/period-folding.algorithms.ts` |
| `reduce_lightcurve` | `lightcurve/pulsar/*` (background, bin, calibrate) or `lightcurve/variable/*` (differential photometry), selected by `mode` |

Folding stays in `lightcurve/` and the periodogram→folding coupling stays in
`periodogram/pulsar/pulsar-periodogram-folding-link.ts` — the ownership rule from
`CLAUDE.md` is reproduced in the tool split rather than flattened.

### Cluster / HR diagram — TypeScript kernels via the bridge

| Tool | Kernel |
|---|---|
| `build_color_magnitude_diagram` | `hrdiagram/fsr/cmd-fsr.util.ts`, `hrdiagram/photometry/` |
| `remove_field_stars` | `hrdiagram/fsr/` |
| `fit_isochrone` | `hrdiagram/isochrone-matching/isochrone-plot.util.ts::computePlotDelta` |
| `summarize_cluster` | `hrdiagram/result/` |

**Known gap:** Astromancer ships no isochrone grids — model tracks were fetched
per parameter change from a server-side endpoint that is not in the repository.
`fit_isochrone` therefore requires an injected grid (`isochrone_grid` artifact)
and returns `dependency_missing` without one. This is a data gap, not a design
gap, and it is the largest single blocker to `hrdiagram/` being usable as a tool.

### Workspace

`list_artifacts`, `describe_artifact`.

### Sizing the surface

That is ~20 tools before `database_tools.py`'s retrieval/literature families
land, and a flat 30-tool surface degrades selection quality. Two mechanisms:

- **Profiles.** `kepler.runtime.registry.tool_specs(profile=...)` — `core`
  (11: the catalog, query, astrometry, photometry, and calibration tools),
  `timeseries`, `cluster`, `all`. The two workspace tools are present in every
  profile, since artifact handles are how any profile passes data along.
- **Deferred loading.** Non-core tools ship with `defer_loading: true` alongside
  a `tool_search_tool_bm25_20251119` entry, so schemas load on demand and are
  *appended* rather than swapped — which preserves the prompt cache. At least one
  tool must stay non-deferred.

---

## 8. Serving the tools

`kepler.runtime.registry` is the single source of tool definitions. Input schemas
are generated from the Pydantic input models via `model_json_schema()`, with
`additionalProperties: false` and a full `required` list, so tools can be
declared `strict: true` and inputs validate exactly.

Three surfaces, one registry:

1. **In-process (Anthropic SDK).** Tool callables usable directly with
   `client.beta.messages.tool_runner(...)`, which drives the call loop and still
   allows per-turn approval gates for anything that writes files.
2. **MCP server.** A `kepler-mcp` console script exposing the same registry over
   MCP, for editors and agent hosts that speak it.
3. **Plain Python.** `from kepler.tools.photometry import extract_sources` works
   in a notebook and returns the same `ToolResult`. No agent required.

Two constraints the registry must honour:

- **Deterministic ordering.** Tool definitions render *first* in a request, ahead
  of system and messages; any byte change there invalidates the entire prompt
  cache. The registry emits tools sorted by name with deterministic JSON
  serialisation, and profiles are chosen once per session, not per request.
- **No tool names in prose.** Descriptions describe the tool; they never
  cross-reference sibling tools by name. Enabling or disabling a profile then
  never leaves a dangling reference.

### Chaining without context blowup

Running `measure_photometry` across 50 frames should not put 50 result envelopes
in the context window. Tools whose main use is iteration —
`measure_photometry`, `extract_sources`, `search_catalog` — declare
`allowed_callers: ["code_execution_20260120"]`, so Claude can drive them from a
script in the code-execution container, and only the aggregate returns.

**Tradeoff, stated:** programmatic tool calling is not compatible with
`strict: true`. Those three tools therefore ship non-strict, and their adapters
do the validation the schema would otherwise guarantee. Every other tool is
strict. This is a deliberate per-tool decision recorded in the registry, not a
blanket setting.

---

## 9. The TypeScript bridge

`lightcurve/`, `periodogram/`, and `hrdiagram/` have no `package.json`, no
`tsconfig.json`, and no build. They also contain byte-identical upstream
numerics whose behaviour (including the preserved defects in §6) must not drift.

**Decision: a Node sidecar, not a Python port.**

```text
packages/ts/
  package.json          # first build config in the repo; zero runtime deps
  tsconfig.json
  src/
    lightcurve/  periodogram/  hrdiagram/     # kernels, moved verbatim
    bridge/cli.ts                             # the only new TS file
  dist/
```

`bridge/cli.ts` reads one JSON request on stdin, dispatches to a named kernel
function, writes one JSON response on stdout, exits. It performs no file I/O and
opens no sockets. On the Python side, `kepler/runtime/node_bridge.py` spawns it
with a wall-clock timeout, a max-stdout-bytes cap, and a clean
`backend_unavailable` error when `node` is absent — so `import kepler` and every
Python tool still work on a machine with no Node installed.

**Rejected alternative:** reimplementing Lomb-Scargle, folding, and isochrone
matching in Python. It would give one runtime and no subprocess, but
`periodogram/core/lomb-scargle.ts` is byte-identical to Astromancer and the
preserved defects are the point of the extraction. A port makes every future
divergence undetectable. If a Python implementation is ever wanted it should be
an *additional* kernel validated against the TS one, not a replacement.

**Consequence to accept:** the repo gains a Node toolchain, `tsc --noEmit` and a
build step enter CI, and the TS folders finally become compilable — which they
are not today, and which is why `tsc --noEmit` was left outstanding at extraction
time.

---

## 10. Enforcing the layering

The rules in §2 are only real if something checks them. Add to CI:

1. **Import-direction test.** Walk the AST of every module under
   `kepler/tools/`; fail if any imports `kepler.kernels`. Same check for
   `kepler.kernels` importing `kepler.adapters` or `kepler.tools`.
2. **Marker preservation.** Count `# EXTRACTED:` / `// EXTRACTED:` markers per
   kernel file against a committed baseline; fail on a decrease. Cheap, and it
   catches the exact kind of well-meaning cleanup the extraction contract
   forbids.
3. **Kernel byte-diff.** A committed manifest of per-file SHA-256 for
   `kepler/kernels/`. Any change requires updating the manifest in the same
   commit, which makes an accidental kernel edit visible in review.
4. **Envelope contract tests.** Every registered tool, called with a
   deliberately invalid input, returns `status: "error"` with a code from the
   closed set — and does not raise.
5. **Schema snapshot.** Committed JSON Schema per tool; a diff is a reviewable
   API change, not a silent one.
6. **Compile/import.** `python -m compileall` over `kepler/`, plus `tsc --noEmit`
   for `packages/ts/`. CI today compiles only `database_tools.py` and never
   imports the extracted packages at all.

Note (2) and (3) are what let this refactor be aggressive about *structure* while
being provably conservative about *content*.

---

## 11. What this architecture does not do

- It does not consolidate the three vendored `skylib/` copies. That is a known
  open repo-level decision (`CLAUDE.md`), and doing it inside a tool refactor
  would mix a large content change into a large structural one. §12 of the
  migration doc proposes it as a separate, gated phase.
- It does not fix any preserved defect. §6 contains them; it does not repair
  them. Repairs are deliberate divergences from Skynet/Astromancer and each needs
  its own decision.
- It does not add orchestration, planning, or a chat runtime. Kepler exposes
  tools; deciding when to call them is the caller's job.
- It does not make end-to-end parity claims. Full WCS/photometry/calibration
  parity has never been validated in this repo and still requires reference FITS,
  solver binaries, and local catalog data that are not here. The tool layer
  changes none of that — it just makes the missing pieces report themselves
  (`backend_unavailable`) instead of looking like a null result.

---

## 12. Open decisions

1. **`fit_isochrone` grid source.** PARSEC or MIST, vendored subset or injected
   artifact? Blocks `hrdiagram/` end-to-end.
2. **Node in the default install.** Hard dependency (simplest contract) or
   optional extra with a `backend_unavailable` degrade (smaller install)? The
   design assumes the latter.
3. **Default profile membership.** Are 12 core tools the right cut, or should
   `solve_astrometry` move to an `imaging` profile given its deployment-data
   requirements?
4. **Artifact lifetime.** Session-scoped temp dir, or a persistent cache with a
   TTL? Affects whether handles survive across agent sessions.
5. **Concurrency for `calibrate_zeropoint`.** Accept single-flight per process
   indefinitely, or plan the `Deps`-dataclass divergence from Skynet?
6. **`database_tools.py` landing.** The brainstorm's `tools/retrieval.py` and
   `tools/literature.py` should adopt this same envelope and registry; that
   merge is the natural Phase 5.
