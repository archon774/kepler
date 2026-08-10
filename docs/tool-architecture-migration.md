# Kepler Tool Architecture — Migration Plan

Date: 2026-08-10
Status: proposed
Companion to [`tool-architecture.md`](tool-architecture.md), which specifies the
target design. This document covers *how to get there*: the file-by-file move,
the phase order, what CI must gain at each step, and what breaks.

---

## 1. Target layout

```text
kepler/
  __init__.py
  contracts/
    __init__.py
    envelope.py         # ToolResult, ToolError, Warning, Provenance
    errors.py           # the closed error-code set
    refs.py             # ImageRef, TableRef, Artifact
    imaging.py          # WcsSolution, SourceRow, Measurement, ZeroPoint (JSON-safe)
    timeseries.py       # Series, PeriodogramResult, FoldResult
    cluster.py          # ClusterSummary, IsochroneFit
  runtime/
    __init__.py
    config.py           # one settings object; supersedes the per-domain env reads
    artifacts.py        # content-addressed store, allowlisted roots
    limits.py           # row/byte/radius/runtime caps
    registry.py         # tool specs, profiles, deferred loading, schema export
    node_bridge.py      # subprocess transport for the TypeScript kernels
    serve_mcp.py        # kepler-mcp entry point
    logging.py          # structured, credential-redacting
  adapters/
    __init__.py
    catalogs.py  query.py  wcs.py  photometry.py  fieldcal.py
    timeseries.py  cluster.py      # both go through node_bridge
  tools/
    __init__.py
    catalogs.py  query.py  astrometry.py  photometry.py  calibration.py
    timeseries.py  cluster.py  workspace.py
  kernels/
    __init__.py
    wcs/  photometry/  fieldcal/  catalogs/  query/    # moved verbatim in Phase 1

packages/ts/
  package.json  tsconfig.json
  src/
    lightcurve/  periodogram/  hrdiagram/              # moved verbatim in Phase 4
    bridge/cli.ts                                       # the only new TS file

tests/
  contract/   # envelope + schema snapshots, every tool
  layering/   # import-direction, marker counts, kernel manifest
  unit/       # adapter logic on tiny fixtures
  fixtures/
database_tools.py                                       # stays at root (see §4)
```

---

## 2. File mapping

### Python kernels — pure moves, import rewiring only

| Today | Target | Change |
|---|---|---|
| `wcs/*.py` (7 modules) | `kepler/kernels/wcs/` | relative-import rewiring only |
| `wcs/skylib/**` (34 modules) | `kepler/kernels/wcs/skylib/` | unchanged |
| `photometry/pipeline/*.py` (4 modules) | `kepler/kernels/photometry/pipeline/` | unchanged |
| `photometry/skylib/**` (15 modules) | `kepler/kernels/photometry/skylib/` | unchanged |
| `fieldcal/*.py` (7 modules) | `kepler/kernels/fieldcal/` | unchanged, **including `deps.py`** |
| `fieldcal/skylib/**` (5 modules) | `kepler/kernels/fieldcal/skylib/` | unchanged |
| `catalogs/*.py` (16 modules) | `kepler/kernels/catalogs/` | unchanged |
| `query/*.py` (12 modules) | `kepler/kernels/query/` | unchanged |
| every `EXTRACTION.md` | moves with its folder | header note added: new path, provenance unchanged |

`deps.py` moves as-is, and the composition root wraps it (design §6). Replacing
it outright means rewriting the `deps.<name>(...)` call sites in `field_cal.py` —
worth doing, but not in the same commit that relocates the file, or the move diff
stops being reviewable. Sequenced immediately after Phase 1.

`wcs/config.py` and `query/config.py` also move as-is. `kepler/runtime/config.py`
becomes the single place that *constructs* the objects they expect and assigns
`query.config.settings` / `wcs.settings` — which is exactly the seam those
modules were written to accept, so no kernel edit is needed to unify
configuration.

### TypeScript kernels — pure moves plus a build

| Today | Target |
|---|---|
| `lightcurve/**` (12 modules) | `packages/ts/src/lightcurve/` |
| `periodogram/**` (8 modules) | `packages/ts/src/periodogram/` |
| `hrdiagram/**` (14 modules) | `packages/ts/src/hrdiagram/` |
| — | `packages/ts/src/bridge/cli.ts` (new) |
| — | `packages/ts/{package.json,tsconfig.json}` (new) |

The cross-package import direction is preserved as-is: `pulsar/` and `variable/`
import *upward* into `periodogram/core/`, nothing in `core/` imports from either,
and no file mixes the two light-curve tools.

### New code

Everything under `kepler/contracts/`, `kepler/runtime/`, `kepler/adapters/`,
`kepler/tools/`, `tests/`, and `packages/ts/src/bridge/`. Nothing else is new.

---

## 3. Phases

Each phase is one PR targeting `dev`, sized to stay reviewable and to keep CI
green throughout. The ordering is chosen so that the guardrails exist *before*
the algorithm code moves, and so that the numeric regression harness exists
before any algorithm is corrected.

### Phase 0 — Scaffolding and guardrails (no kernel changes)

- Create `kepler/` with `contracts/` and `runtime/` populated; `adapters/`,
  `tools/`, `kernels/` empty.
- Land `ToolResult`, the closed error-code set, `Artifact`/`ImageRef`, the
  artifact store, `limits.py`, and the empty registry.
- Land the layering tests (import-direction, `EXTRACTED:` marker baseline,
  kernel SHA-256 manifest — initially covering the folders in their *current*
  locations).
- CI gains: `compileall` over `kepler/`, contract tests, layering tests.

Nothing under the eight domain folders is touched. This phase is pure addition,
which makes the marker/manifest baselines trustworthy for every later phase.

### Phase 1 — Move the Python kernels

- `git mv` the five Python folders under `kepler/kernels/`, rewiring imports to
  relative form only.
- Regenerate the SHA-256 manifest; the diff must show **path changes and import
  lines only**. That review step is the whole point of doing the move as its own
  PR.
- Update `pyproject.toml`: `[tool.setuptools.packages.find] include = ["kepler*"]`,
  and move the `wcs.skylib.astrometry.anet` → `kepler.kernels.wcs...` package-data
  entry for `ngc2000.dat`.
- Update `README.md` entry points and `docs/repository-folders.md`.

**This is the breaking commit.** `from wcs.wcs import solve_wcs` stops working.

### Phase 2 — Offline tool slice

Adapters and tools for everything that needs no network, no solver data, no
numba, and no Node:

- `list_photometric_catalogs`, `resolve_reference_band`
- `solve_zeropoint_from_measurements`
- `describe_image_wcs`
- `list_artifacts`, `describe_artifact`

Chosen deliberately as the first slice: it exercises the whole stack — schema,
envelope, artifact store, registry, error mapping — and it is fully testable in
CI with no fixtures beyond a tiny FITS header. It needs no network, no solver
data, no numba and no Node, so it is the earliest point at which the tool
contract can be proven end to end.

### Phase 3 — Imaging and catalog-query tools

- `resolve_target`, `search_catalog`, `search_catalogs_for_image`
- `solve_astrometry`, `extract_sources`, `measure_photometry`
- `calibrate_zeropoint` with the `wired_fieldcal()` composition root
- Backend probing so `backend_unavailable` is distinguishable from `no_solution`
- Live-provider tests gated behind `KEPLER_LIVE_TESTS=1`, off by default

Heaviest phase; splittable at the query/imaging line if review load demands.

### Phase 4 — TypeScript bridge

- `packages/ts/` with `package.json`, `tsconfig.json`, and the three kernel
  folders moved verbatim
- `bridge/cli.ts` plus `kepler/runtime/node_bridge.py`
- `compute_periodogram`, `find_periodogram_peaks`, `fold_lightcurve`,
  `reduce_lightcurve`, `build_color_magnitude_diagram`, `remove_field_stars`,
  `fit_isochrone`, `summarize_cluster`
- CI gains `tsc --noEmit` and a bridge round-trip smoke test

First phase where `tsc` runs against the TypeScript at all. Expect it to surface
type errors that were invisible at extraction time; fixing *type* errors without
changing *runtime behaviour* is in scope, and anything that would change
behaviour stops and becomes a decision.

### Phase 5 — Serving surfaces and prototype absorption

- `kepler-mcp` entry point; `tool_runner`-ready callables; schema export
- Profiles and `defer_loading` wiring
- `database_tools.py` logic moves into `kepler/tools/retrieval.py` and
  `kepler/tools/literature.py` on the same envelope, per the brainstorm; the root
  module stays as a thin compatibility wrapper

### Phase 6 — Gated: vendored `skylib` consolidation

Not part of this refactor. `wcs/skylib/`, `photometry/skylib/`, and
`fieldcal/skylib/` remain three independent copies. Consolidation is a
pre-existing open repo-level decision and, if taken, should be its own PR with a
byte-diff gate proving the merged file is identical to all three inputs — never
folded into a structural change.

---

## 4. What breaks, and what it costs

| Break | Who it affects | Handling |
|---|---|---|
| `from wcs.wcs import solve_wcs` and every other top-level domain import | `README.md`, `docs/repository-folders.md`, any local notebook | Update docs in Phase 1. No compatibility shims: the repo is explicitly a staging area, `.github/CODEOWNERS` marks it maintainer-owned, and there are no external consumers. Shims would create a second import path to keep working forever. |
| `pyproject.toml` package discovery | packaging | Phase 1 |
| `.gitleaks.toml` path-scoped allowlist for `ADS_DEV_KEY` / `ANTHROPIC_API_KEY` / `NASA_API_KEY` | secret-scan CI | Any new module referencing those names outside the current path list needs an allowlist entry. Phase 5 is where this bites, when `database_tools.py` logic moves under `kepler/tools/`. |
| `database_tools.py` at repo root | CI `repository-shape` job asserts it exists | Keep the file. Phase 5 hollows it into a wrapper rather than deleting it. Same for `README.md`, `pyproject.toml`, `uv.lock`, `docs/architecture-brainstorm.md`. |
| Node enters the toolchain | contributors, CI | Phase 4. Optional at runtime (`backend_unavailable` degrade), required for the TS tools. |
| Field calibration is single-flight per process | concurrent callers | Documented in the tool description; see design §6. |

---

## 5. CI evolution

Today: `python -m py_compile database_tools.py`, a repository-shape file check,
`git diff --check`, gitleaks, actionlint + zizmor. The extracted packages are
never imported or compiled.

| Phase | Added |
|---|---|
| 0 | `compileall kepler/`; contract tests; layering tests; marker baseline; kernel manifest |
| 1 | manifest regenerated and diffed in review; `import kepler` smoke test |
| 2 | schema snapshots for the offline tools; envelope tests |
| 3 | `import kepler.kernels.query` guarded (needs astroquery); live tests gated behind `KEPLER_LIVE_TESTS=1` |
| 4 | `tsc --noEmit`; `npm ci` + build; bridge round-trip |
| 5 | MCP server start/stop smoke test; full schema snapshot |

Everything stays deterministic and bounded by default. No live remote astronomy
call runs in a default check — the existing repository convention, unchanged.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| A kernel edit slips in during the move | SHA-256 manifest + `EXTRACTED:` marker count in CI from Phase 0, i.e. before any move happens |
| Adapters accumulate business logic and become a second kernel | Adapters may only translate, wire, classify errors, and surface residual uncertainty. Anything numeric belongs in a kernel, where it gets a ledger entry and a fixture — an adapter is never the place to quietly adjust a number |
| Tool surface grows past what an agent can select from | Profiles + deferred loading from Phase 5; a hard budget for the `core` profile |
| `tsc` surfaces errors that need behaviour changes to fix | Type-only fixes are in scope for Phase 4. A type error that is really a *numeric* bug is a remediation finding: log it, keep the phase moving with `// @ts-expect-error` plus a comment naming the finding ID, and fix it on the remediation track where it gets a fixture |
| Numeric behaviour still unvalidated after all this | Out of scope here by design — the remediation track owns it. The tool layer's contribution is structural: one call site per kernel entry point, a manifest that flags algorithm changes, and `backend_unavailable` making missing deployment data legible |
| Six phases stall halfway | Every phase is independently useful. Phases 0–2 alone deliver a working, fully offline tool package with no deployment data required |

---

## 7. Definition of done, per phase

A phase is done when: CI is green; the kernel manifest diff shows only intended
changes; every new tool has a schema snapshot and a contract test; every
documented quirk it touches has a warning code and a test asserting the warning
fires; and the relevant `EXTRACTION.md` and AgentVault notes record the new
paths.
