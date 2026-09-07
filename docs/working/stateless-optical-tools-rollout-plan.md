# Stateless Optical Tools Rollout Plan

**Status:** Approved; implementation pending on current `dev`

**Prerequisites:** Broken-links Phase 4, satisfied by PR #47 merged to `dev`.

**Unblocks:** The remaining [broken-links-remediation-plan.md](broken-links-remediation-plan.md) work and all [tui-harness-plan.md](tui-harness-plan.md) phases.

**Date:** 2026-09-07

**Architecture:** [stateless-optical-tools-architecture.md](stateless-optical-tools-architecture.md)

## Objective

Remove the remaining Skynet batch-processing architecture from Kepler's optical
path so an agent can invoke each capability as a tool with explicit inputs and
inspect an explicit result.

This is an orchestration refactor. The extracted astronomy algorithms are the
source of truth. Their mathematics, constants, ordering, thresholds, and known
parity behavior are not targets for improvement in this rollout.

## Delivery Shape

The work lands as one focused pull request from
`agent/remove-processing-run-architecture` to `dev`, separate from PR #47. The
implementation is divided into phases so each architectural boundary can be
reviewed and validated before the next one begins.

Each phase should be represented by one or more focused commits. The branch is
not merged partway through the rollout: intermediate APIs may exist while the
branch is under development, but the final PR must contain no compatibility
facade for the processing-run or batch architecture.

PR #47 was the prerequisite because its `solve_astrometry` tool must be migrated
to the stateless WCS result in the same follow-up PR. It is now merged. Update
the feature branch from current `dev` before implementation begins.

This rollout is the next implementation step for the shared optical surface. It
must merge before remaining broken-links work or any TUI phase starts. The TUI's
later photometry-pipeline rename therefore operates on the stateless pipeline;
it must not preserve, recreate, or rename the removed processing-run or batch
architecture.

## Governing Constraints

- Keep Python 3.14 and current dependency versions.
- Preserve the public tool response models unless a diagnostic field is needed
  to expose information that would otherwise be lost with mutable run state.
- Do not change source extraction, aperture or PSF photometry, plate-solver
  request construction, backend order, solution acceptance, source matching,
  reference-band selection, rejection, or zero-point math.
- Do not edit the numerical kernels in `algorithms/skylib_lite/`,
  `algorithms/fieldcal/solution.py`, or `algorithms/fieldcal/ref_mag.py`.
- Where orchestration and numerical work currently share a module, limit changes
  to imports, function boundaries, explicit input flow, typed result assembly,
  logging context, and removal of state mutation. Do not move or rewrite the
  mathematical blocks as part of this work.
- Do not replace `ProcessingRun` with a differently named context, request,
  session, stage, job, or progress object.
- Do not introduce a replacement batch command.
- Keep network access and FITS persistence in `tools/`; keep `algorithms/`
  focused on in-memory scientific values.
- Treat `file_id` as optional provenance. Callers without a meaningful numeric
  identifier pass `None`; they do not manufacture one from a path hash.
- Keep network and solver-data tests opt-in and deterministic by default.

## What Parity Means

Parity is equality of scientific behavior, not preservation of incidental ORM
or batch-run state. Existing recorded outputs and tolerances remain authoritative.

| Area | Behavior that must remain stable | Structural change allowed |
| --- | --- | --- |
| WCS | Backend order and attempts, request hints, acceptance decisions, returned WCS matrix, center, pixel scale, rotation, parity, pointing deltas, source count, FITS header updates, timeout and failure diagnostics | Replace mutation of a run-owned solution row with an immutable result |
| Source extraction | Detected rows and ordering, positions, fluxes, FWHM values, background and RMS arrays, saturation handling, optional `file_id` propagation | Remove adapters that read `file_id` from a run object |
| Photometry | Source identity, centroided positions, fluxes and errors, instrumental magnitudes and errors, aperture geometry, WCS-derived coordinates, header metadata | Make callers explicitly compose extraction and photometry |
| Field calibration | Variable-star exclusion, mutual nearest-neighbor matching, calibration photometry with aperture correction disabled, SNR and star selection, reference-band resolution, zero point, error, slop, limiting magnitude, rejection percentage, output rows, FITS calibration keywords | Supply WCS, reference rows, variable rows, and `file_id` directly |
| Public tools | Schemas, structured errors and warnings, offline replay, file protection, atomic writes, catalog selection behavior | Own all I/O, query, configuration, and orchestration work |

The following state is intentionally not a parity requirement:

- a `found_solution` flag separate from whether a returned WCS exists;
- mutation or clearing of a reusable ORM-shaped WCS record;
- timestamps or run IDs embedded in generated bookkeeping identifiers;
- stage, progress, retry-loop, or batch aggregation state; and
- the ability to reconstruct a WCS from a persisted processing-run row.

Two unit corrections are structural rather than mathematical: values currently
stored under `delta_ra_deg` and `delta_dec_deg` are already calculated in
arcseconds, so the explicit result names should state arcseconds without
changing the values.

## Rollout Sequence

### Phase 0: Baseline And Inventory

**Intent:** Establish the comparison point and confirm the branch contains the
complete merged Phase 4 tool surface.

**Scope:**

- Confirm the merged PR #47 is present on `dev` and update the feature branch
  from current `dev`.
- Run the complete default suite under Python 3.14 and record pass, skip, and
  warning counts.
- Inventory every current reference to processing runs, WCS solution state,
  field-calibration dependency wiring, path-derived IDs, and optical batch
  orchestration.
- Classify each match as current executable architecture, historical provenance,
  or an active planning reference.
- Identify mixed modules where plumbing can change but numerical blocks must
  remain untouched.

**Parity gate:** The branch starts green, and the inventory accounts for all
known artifacts before deletion begins.

**Exit criteria:** There is a reviewed removal list, a recorded test baseline,
and no ambiguity about which files contain source-of-truth math.

### Phase 1: Stateless WCS Results

**Intent:** Remove run-owned WCS state while retaining the solver's current
scientific and operational behavior.

**Scope:**

- Characterize successful, unsuccessful, and backend-failure solve outputs
  before changing the interface.
- Introduce the immutable WCS solve result and metadata contract described in
  the architecture document.
- Change WCS solving to accept header, image data, temporary storage,
  configuration, diagnostics channels, and optional `file_id` explicitly.
- Preserve in-memory header updates because later calculations in the same tool
  call depend on them.
- Migrate `tools.wcs.solve_astrometry` to consume the returned result while
  preserving its current error handling, backend reporting, fixture protection,
  concurrent-write guard, and atomic header persistence.
- Remove processing-run WCS reconstruction helpers and the WCS state module once
  all consumers use returned WCS values or header WCS values directly.

**Implementation latitude:** The executing agent chooses the smallest internal
refactor that produces the approved result contract. It must not alter backend
requests, fallback order, acceptance calculations, or FITS WCS write-back.

**Parity gate:** Characterization tests compare every scientific metadata field,
header effect, solver attempt, and failure diagnostic before and after the
interface change. The existing solver-data tests remain valid when local indexes
are available.

**Exit criteria:** WCS solving has no processing-run input or mutable persisted
state, and the Phase 4 tool behaves identically at its public boundary.

### Phase 2: Explicit Extraction And Photometry Composition

**Intent:** Make the already-stateless numerical entry points the only supported
algorithm APIs.

**Scope:**

- Migrate WCS, HR-diagram observation extraction, radio-source extraction, and
  any other consumers to call source extraction with an explicit `file_id`.
- Make callers explicitly pass the detected sources, WCS, background, and RMS
  values into photometry when they compose those stages.
- Pass `file_id=None` where there is no meaningful domain identifier.
- Remove both run-shaped source-extraction adapters and the combined
  run-shaped photometry adapter after their callers have migrated.
- Remove path hashing that exists only to populate a processing-run field.

**Implementation latitude:** Composition may live in the narrow consumer or in a
focused domain helper when more than one caller has the same responsibility.
It must not be moved back into a generic run-like abstraction.

**Parity gate:** Existing extraction and photometry suites continue to pin source
rows, background arrays, fluxes, magnitudes, errors, coordinates, and metadata.
Consumer tests verify the same results reach HR-diagram and radio workflows.

**Exit criteria:** `run_source_extraction` and `run_photometry` are the only
maintained algorithm entry points for these stages, and no caller synthesizes an
execution ID from a file path.

### Phase 3: Explicit Field-Calibration Inputs

**Intent:** Turn field calibration into deterministic computation over supplied
scientific data.

**Scope:**

- Strengthen characterization around the real-frame calibration path and the
  recorded Afterglow/Skynet parity fixtures before changing orchestration.
- Supply WCS, reference catalog rows, variable-star rows, optional detected
  sources, settings, and optional `file_id` directly.
- Replace the module-global dependency registry with ordinary imports of the
  deterministic extraction, coordinate, and photometry functions.
- Keep catalog-row normalization and generated IDs local to one call.
- Preserve variable-star rejection, matching order, the forced
  `apcorr_tol=0.0` calibration behavior, SNR selection, reference-magnitude
  resolution, `calc_solution`, and in-memory FITS keyword updates.
- Remove field calibration's ability to query catalogs or discover WCS state.

**Implementation latitude:** The executing agent may reorganize orchestration
helpers to clarify explicit data flow. It may not change the calculation order
or the content of matched and calibrated source rows except for removal of
run-derived bookkeeping values.

**Parity gate:** The end-to-end real-frame test, recorded zero-point cases,
Afterglow comparisons, variable-star exclusion tests, reference-band tests, and
solution tests all pass at their existing tolerances. A dedicated test proves
the algorithm performs no network query.

**Exit criteria:** Field calibration is callable with in-memory values alone and
has no process-global wiring, remote-service lookup, or processing-run input.

### Phase 4: Tool-Owned Catalog And File Orchestration

**Intent:** Put side effects at the public tool boundary where an agent can
observe and control them.

**Scope:**

- Move calibration catalog selection and queries into `tools.photometry`.
- Query VSX in the tool layer when variable-star rejection is enabled and pass
  those rows to the calibration algorithm.
- Keep recorded-source replay offline: supplied catalog rows must bypass every
  remote query, including VSX.
- Share only focused tool-layer preparation between the registered photometry
  tool and the standalone Claude compatibility path.
- Preserve current structured errors, fallbacks, comparisons, diagnostic
  payloads, and file-writing ownership.

**Implementation latitude:** The executing agent chooses the private tool helper
shape and exception translation, following established models in `tools/`.
There must be no mutable registry or configuration shared between calls.

**Parity gate:** Tests cover offline replay with zero network calls, live-query
orchestration through deterministic fakes, unchanged public schemas, and the
existing field-calibration failure modes.

**Exit criteria:** Tools own every network, environment, path, and persistence
decision; algorithms receive resolved values only.

### Phase 5: Remove Automated Batch Artifacts

**Intent:** Delete the remaining Skynet execution model rather than preserving
it under compatibility names.

**Scope:**

- Delete the automated WCS/photometry/zero-point batch exporter.
- Delete `ProcessingRunRef`, the field-calibration dependency registry, the WCS
  state classes, and obsolete exports after their consumers are gone.
- Audit for other retained optical automation patterns: implicit directory
  iteration, stage/progress state, broad "continue to next frame" exception
  handling, run-scoped persistence, CSV aggregation tied to a batch, and
  generated execution identifiers.
- Remove such artifacts when they exist solely to reproduce the upstream batch
  harness. Keep reusable scientific algorithms and public single-call tools.
- Add a repository-shape test that prevents current Python APIs from
  reintroducing the removed run and batch concepts.

**Implementation latitude:** The executing agent decides whether a discovered
helper is reusable computation or batch infrastructure using the architectural
boundary in the approved design. Uncertain cases should be surfaced in review
before deletion.

**Parity gate:** All scientific suites still pass. The removal audit has no
current executable matches, while historical provenance remains readable.

**Exit criteria:** No run-shaped facade, service locator, automated optical batch
driver, or renamed equivalent remains in current Python code.

### Phase 6: Documentation And Release Gate

**Intent:** Make the stateless tool boundary durable and leave the next broken-
links phase a clean base.

**Scope:**

- Update `docs/tool-architecture.md` to define one tool call as Kepler's unit of
  execution.
- Update `docs/repository-folders.md`, package documentation, and
  `tests/README.md` for the explicit APIs and new architecture coverage.
- Update `docs/extraction.md` without erasing provenance: upstream run and ORM
  names may remain where clearly historical, while current guidance must not
  instruct callers to recreate them.
- Review the complete branch diff specifically for accidental changes to
  numerical expressions, constants, thresholds, source ordering, and error
  semantics.
- Run the full repository checks on Python 3.14 and optional solver/network
  checks only when their external prerequisites are available.
- Open the separate PR to `dev` with parity evidence and a clear statement that
  this changes orchestration, not astronomy algorithms.

**Parity gate:**

```bash
uv run --python 3.14 pytest -q
uv run --python 3.14 python -m compileall tools algorithms
npm run typecheck
git diff --check
```

The PR also records focused optical-suite results, any optional solver-data run,
and a clean diff for the protected numerical-kernel files.

**Exit criteria:** Required CI is green, documentation matches the resulting
code, the working tree is clean, and the PR is reviewable phase by phase.

## Review Checkpoints

Review should occur at the following boundaries rather than waiting for the
entire refactor to accumulate:

1. WCS characterization and result contract.
2. WCS consumer migration and removal of state.
3. Extraction/photometry consumer migration and adapter removal.
4. Field-calibration characterization and explicit-input conversion.
5. Tool-layer query orchestration and offline replay.
6. Batch-artifact deletion, repository audit, and final documentation.

At every checkpoint, review the scientific diff separately from the API diff.
An interface can be structurally correct and still be rejected if it changes a
numerical expression or weakens a recorded parity assertion.

## Risk Controls

### Mixed algorithm and orchestration modules

Some extracted files contain both mathematical work and obsolete pipeline
plumbing. This is the highest-risk part of the rollout. Prefer narrow edits in
place, retain existing calculation order, and use characterization tests to
compare complete result structures rather than only success flags.

### Mutable-state removal

The old WCS state can retain stale values across solves. Stateless results remove
that possibility. Tests should distinguish an intentional absence of prior state
from a numerical regression in a fresh solve.

### Catalog-query relocation

Moving queries changes where failures are caught. Preserve user-visible tool
errors and the best-effort variable-star behavior while ensuring algorithm code
does not silently perform I/O.

### Bookkeeping identifiers

Timestamped, run-scoped, and path-hashed IDs are not scientific outputs, but they
can accidentally affect source joins. Verify matching and calibration row order
after replacing them with call-local IDs or `None`.

### Optional external systems

Astrometry indexes, UCAC catalogs, and live remote services are not default test
dependencies. Their gated tests supplement, but do not replace, deterministic
offline characterization.

## Completion Audit

Before the PR is declared ready, confirm all of the following:

- `ProcessingRun`, `ProcessingRunRef`, `ensure_wcs_solution`, processing-run WCS
  reconstruction, and field-calibration dependency wiring are absent from
  current Python APIs.
- The automated WCS/photometry/zero-point exporter and any equivalent retained
  batch harness are gone.
- No path hash is used as an optical `file_id`.
- Algorithm modules do not open caller-selected FITS paths or query catalogs.
- Public tools own configuration, I/O, network access, error translation, and
  requested persistence.
- Protected numerical-kernel files have no diff.
- Changes inside mixed modules are limited to the approved orchestration
  boundary and typed result construction.
- Default tests pass under Python 3.14 with no network requirement.
- The architecture and reference docs describe the code that will land.

## Next-Phase Readiness

This rollout is ready for implementation when Phase 0 is green on current `dev`.
It is ready to hand off to the next broken-links phase and the TUI only when the
completion audit passes and the follow-up PR merges to `dev`.

The resulting base will let later tools compose WCS, extraction, photometry, and
calibration through explicit values. Later phases should build on those public
tool contracts rather than adding shared execution state or restoring automated
batch behavior.
