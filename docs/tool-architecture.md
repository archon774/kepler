# Kepler Tool Architecture

Date: 2026-08-10
Status: proposed
Scope: **file organisation and tool wiring** for the eight extracted domain
folders — `wcs/`, `photometry/`, `fieldcal/`, `catalogs/`, `query/` (Python) and
`lightcurve/`, `periodogram/`, `hrdiagram/` (TypeScript).

Kepler's purpose is to take the hard-core algorithms Skynet and Astromancer
shipped for production and make them callable as tools by any LLM, script, or
notebook. This document covers how the code is laid out and how a service-shaped
call becomes a tool-shaped call.

**Out of scope — deliberately.** Algorithmic correctness, astronomical accuracy,
and the bug-fix rollout are a separate track with their own document, driven by
the algorithm review. Nothing here asserts that any algorithm is correct. Where
the two tracks touch — the error taxonomy, the layering that makes numeric
changes reviewable — this document says only what structure is required, never
what should be fixed.

Companion documents:
- [`tool-architecture-migration.md`](tool-architecture-migration.md) — the
  file-by-file move plan and phasing.
- [`architecture-brainstorm.md`](architecture-brainstorm.md) — the greenfield
  tool families Kepler should grow later (retrieval, literature, plotting).

---

## 1. The shape gap

Skynet's pipeline stages are **service** code. A stage takes an ORM row
(`processing_run`), mutates it in place, reads configuration from ambient global
state, raises exceptions as control flow, returns unbounded in-memory numpy
arrays, and assumes a caller that already holds an open FITS file and a wired
dependency graph. Astromancer's TypeScript is **UI** code: functions that assume
an Angular component owns the state and a Highcharts instance owns the output.

A tool call is the opposite on every axis: a stateless JSON request against a
declared schema, returning bounded JSON plus file handles, where failure is a
value rather than a stack trace, and where the caller holds nothing but strings.

Closing that gap is the whole job. It is not one transformation — it is eight
recurring ones, and naming them is what turns this from a rewrite into a
mechanical exercise.

---

## 2. The eight rewiring patterns

Every service-shaped construct in these folders reduces to one of these. Each row
gives the pattern, the tool-shaped replacement, and where it actually occurs.

| # | Service shape | Tool shape | Where it occurs in Kepler |
|---|---|---|---|
| **P1** | An ORM row is threaded through the call and **mutated** as the output channel | Adapter builds an **ephemeral run context** per call; the tool reads results from **return values**, never from the mutated object | `solve_wcs(processing_run, …)`, `perform_field_calibration(processing_run, …)`, `perform_source_extraction(processing_run, …)`. Stand-ins already exist in `wcs/state.py` and `fieldcal/schemas.py` |
| **P2** | A FITS header is **written in place** and the caller is expected to persist it | Write to a **copy**, register it in the artifact store, return the handle. The input file is never modified | `_write_wcs_to_header` (WCS keywords); the `PHOT_M0` / `PHOT_M0E` / `PHOT_CAL` writes in field calibration |
| **P3** | **Module-global dependency injection** — a host assigns names before use | A **composition root** binds implementations for the duration of one call (§6) | `fieldcal/deps.py`: `run_photometry`, `run_source_extraction`, `get_source_radec`, `build_wcs_for_processing_run` |
| **P4** | Configuration read from **ambient environment** at call time | Settings resolved **once** into an explicit object at startup; the runtime assigns the seams the kernels already expose | `wcs/config.py::SolverSettings` (`ANET_INDEX_PATH`, `ATLAS_*`), `query/config.py::QuerySettings` (`VIZIER_*`) |
| **P5** | **Exceptions as control flow**, plus degraded returns that conflate distinct causes | A **closed error-code taxonomy**; every distinguishable failure gets its own code (§5) | `raise ValueError('wcs_settings.ra_hours', 'RA not within range', 422)`; both WCS backends "degrade to unavailable rather than failing", so a missing index set and an unsolvable frame return the same thing |
| **P6** | **Unbounded in-memory returns** — full source lists, whole arrays | **Bounded summary inline + full result as an artifact** (§5) | `run_source_extraction` → `list[SourceExtractionData]`; `query_catalogs` → `list[CatalogSource]`; both can run to thousands of rows |
| **P7** | **Rich domain objects** as the interface | JSON-safe models at the boundary; domain objects stay below the adapter line | `CatalogSource`, `PhotometryData`, `astropy.wcs.WCS`, `fits.Header`, `np.ndarray` |
| **P8** | **Framework-owned state** — the Angular component holds the data, Highcharts holds the output | A pure call with explicit inputs and one JSON response per invocation | `lightcurve/`, `hrdiagram/` — the service and component classes retained from Astromancer |

The rest of this document is the machinery that makes those eight applyable
uniformly rather than case by case.

---

## 3. Layering

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
│ kepler.adapters.*     applies P1–P8. Opens FITS, builds │
│                       run contexts, wires deps,         │
│                       classifies failures, bounds       │
│                       output. Knows kernel shapes.      │
├─────────────────────────────────────────────────────────┤
│ kepler.kernels.*      the algorithms, as shipped.       │
│   wcs/ photometry/ fieldcal/ catalogs/ query/           │
│   + ts/ reached through the Node bridge                 │
└─────────────────────────────────────────────────────────┘
       kepler.contracts.*   Pydantic models, error codes, envelope
       kepler.runtime.*     artifact store, config, limits, registry, serving
```

### Four rules

**R1 — Algorithm code lives only in kernels.** Adapters translate; they never
adjust a number. If a computation has nowhere to live but an adapter, that is a
signal it belongs in a kernel — not an invitation to put it in the adapter.

**R2 — Tools never import kernels.** A tool module imports `kepler.contracts` and
exactly one adapter. Mechanically checkable (§10). This keeps the tool layer thin
and keeps every kernel call site in one reviewable place.

**R3 — No science objects cross the tool boundary.** Pattern P7, enforced.
`np.ndarray`, `fits.Header`, `astropy.wcs.WCS`, `CatalogSource` and
`PhotometryData` live below the adapter line and never above it.

**R4 — Failure is data.** Pattern P5, enforced. Kernels raise; adapters catch and
classify; tools return `status: "error"` with a stable code. An unhandled
exception escaping a tool is an adapter bug.

### Why not just decorate the existing entry points?

Because they cannot satisfy R3 or R4 without a translation layer somewhere.
`solve_wcs` takes an ORM stand-in, a mutable header, a raw float32 array and a
scratch directory — four arguments an agent cannot construct — and
`perform_field_calibration` will not run at all until four module globals are
assigned. Decorating those signatures produces a schema an agent cannot fill in
and a result it cannot interpret. The adapter layer is where P1–P8 get applied;
the only real question is whether it is a named layer or scattered through the
tools.

---

## 4. File organisation

```text
kepler/
  contracts/          envelope.py errors.py refs.py imaging.py timeseries.py cluster.py
  runtime/            config.py artifacts.py limits.py registry.py
                      node_bridge.py serve_mcp.py logging.py
  adapters/           catalogs.py query.py wcs.py photometry.py fieldcal.py
                      timeseries.py cluster.py
  tools/              catalogs.py query.py astrometry.py photometry.py calibration.py
                      timeseries.py cluster.py workspace.py
  kernels/            wcs/ photometry/ fieldcal/ catalogs/ query/
packages/ts/          package.json tsconfig.json src/{lightcurve,periodogram,hrdiagram,bridge}
tests/                contract/ layering/ unit/ fixtures/
```

Three organising decisions, each with a reason:

**One module per domain, at every layer.** `tools/photometry.py` →
`adapters/photometry.py` → `kernels/photometry/`. A vertical slice is readable in
three files, and the mapping is guessable rather than memorised.

**Existing domain boundaries are preserved, not flattened.** The extraction
established ownership rules that are load-bearing and survive the move unchanged:

- `wcs/`, `photometry/`, `fieldcal/` do not import each other. Cross-domain needs
  go through `fieldcal/deps.py` (P3) — which is exactly why that seam exists.
- `query/` imports `catalogs/`, never the reverse. That direction is what keeps
  filter matching and the zero-point solve runnable with **no network stack
  installed** — worth protecting, because it is what makes an offline tool slice
  possible at all.
- In TypeScript, `pulsar/` and `variable/` import *upward* into
  `periodogram/core/`; nothing in `core/` imports from either; period folding
  belongs to `lightcurve/`, not `periodogram/`.

Collapsing any of these trades a real capability for a shorter import path.

**Kernels keep their internal structure.** `kepler/kernels/wcs/skylib/…` stays
laid out as extracted, including the three vendored `skylib` copies. Consolidating
them is a content change and a known open decision; folding it into a structural
move makes both unreviewable.

---

## 5. The calling contract

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

`status` is chosen to drive the caller's next move, not to describe internals:

| status | meaning | next move |
|---|---|---|
| `ok` | complete result | continue |
| `partial` | ran, but a provider failed or a cap was hit | continue, or narrow and retry |
| `empty` | ran correctly, found nothing | change the region or threshold — don't retry |
| `error` | did not run | read `code` |

### Error taxonomy (pattern P5)

A closed set. Anything unmapped is `internal_error` and is a bug.

`invalid_input` · `not_found` · `ambiguous_target` · `no_solution` ·
`insufficient_sources` · `backend_unavailable` · `dependency_missing` ·
`provider_unavailable` · `rate_limited` · `timeout` · `too_many_results` ·
`artifact_too_large` · `unsupported_format` · `internal_error`

The set is sized by one rule: **two failures get different codes when they imply
different actions.** The clearest case here is `backend_unavailable` vs
`no_solution`. Today both WCS backends degrade to "unavailable", so a deployment
missing its astrometry.net index files is indistinguishable from a genuinely
unsolvable frame — one is fixed by installing data, the other by taking a better
exposure. The adapter probes backend configuration before the solve and returns
the distinguishing code, naming the missing environment variable. The same rule
separates `dependency_missing` (a wiring fault) from `insufficient_sources` (a
data fault).

### Bounded output (pattern P6)

Every table-returning tool takes `limit` (default 50, hard cap 500) and returns:

```json
{ "row_count": 4312, "returned": 50, "truncated": true,
  "columns": [...], "rows": [...],
  "artifacts": [{"id": "art_...", "kind": "source_table", "mime": "text/x-ecsv"}] }
```

The inline rows are a **sample for reasoning**; the artifact is the dataset.
Column metadata (name, unit, description) always ships with the sample so the
caller can interpret it without a second call.

---

## 6. State, artifacts, and the composition root

### Artifacts replace `processing_run` (patterns P1, P2)

```text
kepler.runtime.artifacts.ArtifactStore
  put(path|bytes, kind, produced_by) -> Artifact
  resolve(ref) -> local path
```

- `Artifact` = `{id, kind, mime, path, bytes, sha256, created_at, produced_by,
  parent_ids}`, with `id = art_<sha256[:16]>` — registering the same file twice
  yields the same artifact.
- Data-bearing inputs take an **`ImageRef`**: `art_...`, or a local path under an
  allowlisted root (`KEPLER_DATA_ROOTS`). No URLs, no recursive scans, no bare
  relative paths.
- Producing tools set `parent_ids`, which yields a provenance DAG across a session
  for free.
- `list_artifacts` / `describe_artifact` let a caller recover dropped handles.

Chains like solve → extract → measure → calibrate pass handles, not arrays. The
adapter builds a throwaway run-context object per call, lets the kernel populate
it, and reads what it needs — but results come from return values (P1) and header
writes go to a copy (P2), so no tool result depends on mutated state.

### Composition root for `fieldcal.deps` (pattern P3)

`fieldcal/deps.py` holds process-global names, with call sites written as
`deps.<name>(...)` so late injection works. The adapter binds them per call:

```python
# kepler/adapters/fieldcal.py
_WIRING_LOCK = threading.Lock()

@contextmanager
def wired_fieldcal():
    with _WIRING_LOCK:
        saved = {n: getattr(deps, n) for n in _WIRED}
        deps.run_photometry = ...                # from kernels.photometry
        deps.run_source_extraction = ...
        deps.get_source_radec = ...
        deps.build_wcs_for_processing_run = ...  # from kernels.wcs
        try:
            yield
        finally:
            for n, v in saved.items():
                setattr(deps, n, v)
```

`deps.query_catalogs` keeps its lazy default, so `import fieldcal` still costs no
astroquery.

**Interim constraint with a known exit.** Module globals make this single-flight
per process; the tool description says `concurrency: serialised`. The proper fix
is a `Deps` dataclass threaded through `field_cal.py` — ordinary work, sequenced
after the move only because rewriting call sites in the file being relocated
makes the move diff unreviewable. Lock first, refactor second, drop the lock
third.

---

## 7. Tool catalogue

Verb-first, stable names. Real descriptions must be prescriptive about *when* to
call the tool — that is what drives correct selection.

**Catalog declarations** (pure, offline, no deployment data)
`list_photometric_catalogs` · `resolve_reference_band`

First-class rather than internal helpers: instant, deterministic, need nothing
installed, and they answer what callers ask first ("can I calibrate this filter
against APASS at all?").

**Remote catalog access**
`resolve_target` · `search_catalog` · `search_catalogs_for_image`

**Astrometry**
`solve_astrometry` (→ solution + FITS artifact) · `describe_image_wcs`
(header read only, no solve, no backend required)

**Photometry**
`extract_sources` · `measure_photometry`

**Field calibration**
`calibrate_zeropoint` · `solve_zeropoint_from_measurements`

Splitting `calc_solution` out as its own tool is worth it: it is the one piece of
the chain a caller can invoke on data already in hand — no FITS, no network, no
wiring.

**Time series** (TypeScript kernels via the bridge)
`compute_periodogram` · `find_periodogram_peaks` · `fold_lightcurve` ·
`reduce_lightcurve`

**Cluster / HR diagram** (TypeScript kernels via the bridge)
`build_color_magnitude_diagram` · `remove_field_stars` · `fit_isochrone` ·
`summarize_cluster`

`fit_isochrone` needs a caller-supplied `isochrone_grid` artifact — Astromancer
fetched model tracks from a server endpoint that is not in the repository, so
there is no grid to ship. Without one it returns `dependency_missing`.

**Workspace**
`list_artifacts` · `describe_artifact`

### Granularity and surface size

Two rules decide where to cut:

- **One tool per operation a caller would name.** `solve_astrometry` and
  `extract_sources` stay separate even though the solve extracts sources
  internally, because a caller asks for them separately.
- **Split where the dependency profile changes.** `describe_image_wcs` is split
  from `solve_astrometry` precisely because one needs 40 GB of index files and the
  other needs only a header. A caller with no deployment data still gets half the
  domain.

That is ~20 tools before the brainstorm's retrieval and literature families land,
and a flat 30-tool surface degrades selection. Two mechanisms:

- **Profiles.** `registry.tool_specs(profile=...)` — `core` (11: catalogs, query,
  astrometry, photometry, calibration), `timeseries`, `cluster`, `all`. The two
  workspace tools appear in every profile, since handles are how any profile
  passes data along.
- **Deferred loading.** Non-core tools ship `defer_loading: true` alongside a
  `tool_search_tool_bm25_20251119` entry, so schemas load on demand and are
  *appended* rather than swapped — which preserves the prompt cache. At least one
  tool must stay non-deferred.

---

## 8. Serving

`kepler.runtime.registry` is the single source of tool definitions. Input schemas
come from the Pydantic input models via `model_json_schema()`, with
`additionalProperties: false` and a complete `required` list, so tools can be
declared `strict: true` and inputs validate exactly.

Three surfaces, one registry:

1. **In-process** — callables usable directly with
   `client.beta.messages.tool_runner(...)`, which drives the call loop and still
   allows per-turn approval gates for anything that writes files.
2. **MCP server** — a `kepler-mcp` console script over the same registry.
3. **Plain Python** — `from kepler.tools.photometry import extract_sources` in a
   notebook, returning the same `ToolResult`. No agent required.

Two constraints the registry must honour:

- **Deterministic ordering.** Tool definitions render first in a request, ahead of
  system and messages; any byte change there invalidates the whole prompt cache.
  Emit sorted by name with deterministic JSON, and choose profiles once per
  session rather than per request.
- **No tool names in prose.** Descriptions never cross-reference sibling tools by
  name, so enabling or disabling a profile never leaves a dangling reference.

### Chaining without context blowup

Running `measure_photometry` across 50 frames should not put 50 envelopes in the
context window. The iteration-heavy tools — `measure_photometry`,
`extract_sources`, `search_catalog` — declare
`allowed_callers: ["code_execution_20260120"]`, so the loop runs in the
code-execution container and only the aggregate returns.

**Stated tradeoff:** programmatic tool calling is incompatible with
`strict: true`. Those three ship non-strict and their adapters do the validation
the schema would otherwise guarantee. Every other tool is strict. A per-tool
decision recorded in the registry, not a blanket setting.

---

## 9. The TypeScript bridge

`lightcurve/`, `periodogram/` and `hrdiagram/` have no `package.json`, no
`tsconfig.json` and no build — they cannot currently be compiled or run at all.

**Decision: a Node sidecar, not a Python port.**

```text
packages/ts/
  package.json          # first build config in the repo; zero runtime deps
  tsconfig.json
  src/
    lightcurve/  periodogram/  hrdiagram/     # kernels, moved as-is
    bridge/cli.ts                             # the only new TS file
  dist/
```

`bridge/cli.ts` reads one JSON request on stdin, dispatches to a named kernel
function, writes one JSON response on stdout, exits. No file I/O, no sockets — it
is pattern P8 applied once, centrally, instead of per function.
`kepler/runtime/node_bridge.py` spawns it with a wall-clock timeout, a
max-stdout-bytes cap and a clean `backend_unavailable` when `node` is absent, so
`import kepler` and every Python tool still work with no Node installed.

**Rejected: porting to Python.** One runtime and no subprocess would be nicer, but
a port rewrites numerics that currently have no test coverage and no compiler —
unverifiable in both directions at once. If a Python implementation is ever
wanted it should be an *additional* kernel validated against the TypeScript one,
not a replacement.

**Consequence to accept:** the repo gains a Node toolchain and `tsc --noEmit`
enters CI. That is the first time the TypeScript is checked by anything.

---

## 10. Enforcing the layering

The rules in §3 are only real if something checks them:

1. **Import direction.** Walk the AST under `kepler/tools/`; fail on any
   `kepler.kernels` import. Same for kernels importing adapters or tools.
2. **Envelope contract.** Every registered tool, given deliberately invalid input,
   returns `status: "error"` with a code from the closed set — and does not raise.
3. **Schema snapshots.** Committed JSON Schema per tool; a diff becomes a
   reviewable API change rather than a silent one.
4. **Kernel manifest.** Committed per-file SHA-256 under `kepler/kernels/`. During
   the move this proves the move changed nothing. Afterwards it makes any commit
   touching algorithm code visible in review and routes it to the remediation
   track, rather than letting it pass as a structural change.
5. **Compile/import.** `compileall` over `kepler/`, plus `tsc --noEmit` for
   `packages/ts/`. CI today compiles one file and never imports the extracted
   packages at all.

---

## 11. Non-goals

- **Algorithmic correctness.** Not addressed here, by design. No claim in this
  document asserts an algorithm is right. The structures above exist partly to
  make numeric fixes reviewable — one call site per kernel entry point, a manifest
  that flags algorithm changes — but the fixes themselves belong to the
  remediation track.
- **Consolidating the three vendored `skylib` copies.** A content change; keep it
  out of a structural move.
- **Orchestration, planning, or a chat runtime.** Kepler exposes tools; deciding
  when to call them is the caller's job.
- **End-to-end validation.** Still requires reference FITS, solver binaries and
  local catalog data not in this repo. The tool layer changes none of that — it
  makes the absence *legible* (`backend_unavailable`) instead of silent.

---

## 12. Open decisions

1. **Node in the default install** — hard dependency, or optional extra that
   degrades to `backend_unavailable`? The design assumes optional.
2. **`fit_isochrone` grid** — PARSEC or MIST, vendored subset or caller-supplied
   artifact? Blocks the `hrdiagram/` chain end to end.
3. **Default profile membership** — are 11 core tools the right cut, or does
   `solve_astrometry` belong in an `imaging` profile given its data requirements?
4. **Artifact lifetime** — session-scoped temp dir, or a persistent cache with a
   TTL? Determines whether handles survive across sessions.
5. **`database_tools.py` landing** — the brainstorm's retrieval and literature
   tools should adopt this envelope and registry; that merge is the natural
   Phase 5.
