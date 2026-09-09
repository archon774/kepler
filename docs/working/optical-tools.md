# Optical Tools: Broken Links and Stateless Architecture

**Status:** Baseline phases merged; stateless rollout merged as PR #52;
remaining broken-links phases are unblocked and retain their independent scope.
**Date:** 2026-09-04 (findings), 2026-09-07 (stateless design, sequencing,
consolidation)
**Prerequisites:** None outstanding. The stateless rollout's prerequisite —
broken-links Phase 4 — merged as PR #47.
**Unblocks:** The remaining broken-links phases below, and every phase of
[tui-harness.md](tui-harness.md).
**Merged at:** `dev` commit `33617a4adaf89aadd006ec8be11fe6678f19d0cd` (PR #52,
"Refactor optical processing to stateless S0–S6 contracts").
**Scope:** the seam between the public `tools/` surface and the local data in
`test_data/`, and the execution architecture behind that seam. **Not** algorithm
correctness — that is
[`../analysis/algorithm-remediation-plan.md`](../analysis/algorithm-remediation-plan.md) —
and not file organization, which is [`../tool-architecture.md`](../tool-architecture.md).

This document is architecture and sequencing. It contains no implementation
code. An agent working a phase reads the contracts here, then writes the code
that satisfies them.

## Two coupled problems, one surface

**The links are broken.** Tools that should run against the data bundled in this
repository do not reach it, and the recorded ground truth in
`test_data/afterglow/` and `test_data/fieldcal/` is readable only as a pytest
fixture, never as a tool result. Twelve findings, section 1.

**The architecture underneath is the wrong shape.** Kepler exposes astronomy
capabilities as tools an agent invokes one call at a time. It is not the
automated Skynet batch pipeline several optical algorithms were extracted from.
The remaining `ProcessingRun` types, ORM-shaped state, module-global dependency
wiring, and batch exporter force tool callers to emulate a job system Kepler
neither owns nor needs. Section 3.

They are coupled because the second blocks the first. Every remaining broken-link
fix would otherwise have to be written twice — once against the processing-run
boundary and again against the stateless one — so **the stateless rollout merges
first** and the remaining broken-links phases build on its contracts.

The governing pattern for both halves already exists in this repository.
`tools/pulsar.py` solves the discovery problem correctly for radio scans: a
Stage 0 pair (`list_pulsar_scans` / `resolve_pulsar_scan`) backed by an
environment-overridable data directory, returning typed models that carry
`ToolError`s instead of raising. Every fix below generalizes that pattern to the
other data classes this repository ships — optical frames, recorded zero-point
solves, and the Afterglow cross-check — and then registers the result so an
agent loop can reach it.

---

## 1. Findings

Twelve broken links, each verified against a working tree with the commands
shown; none is inferred from documentation. The investigation was first carried
out against `main`, then **re-verified in a `dev` checkout** before being
recorded, and the status column has been updated again after the baseline phases
merged.

### Severity summary

Status is **as of 2026-09-07 on `dev`**, after PRs #43, #44, #45, and #47.

| # | Broken link | Status | Severity |
|---|---|---|---|
| BL-1 | `describe_image_wcs` raised `TypeError` on 38 of 39 bundled frames | **closed** — fixed on `dev` before Phase 1; the parametrized sweep landed with it | — |
| BL-2 | The agent registry omitted the local no-network tools | **closed** — Phase 1 registered `astrometry`, `calibration`, `catalogs`, `workspace` | was High |
| BL-3 | No optical-frame lookup registry (the HR-diagram example) | **closed** — Phase 2 added `tools/optical.py` | was Medium |
| BL-4 | No tool read `test_data/afterglow/` or `test_data/fieldcal/` | **closed** — Phase 3 added `tools/fieldcal_reference.py` and `tools/photometry.py` | was High |
| BL-5 | `ZeropointSolution.zero_point_corr` held an absolute zero point | **closed** — Phase 1 renamed it to `zero_point` | was High |
| BL-6 | `ocl_filter_report.json` no longer joined to any bundled frame | **closed** — Phase 3 added `test_data/frame_provenance.json` | was Medium |
| BL-7 | `solve_wcs` unreachable; its index data present but unconfigured | **closed as far as wiring goes** — Phase 4 added `tools/wcs.py`. Convergence remains open, section 6.1 | was Medium |
| BL-8 | Curated pulsar periods unreachable from the tool layer | **stands** — no `test_data/pulsar/curated_periods.json`; Phase 5 below | Medium |
| BL-9 | HR diagram: no offline path | **stands, narrowed** — `dev` has a Python runtime and seven registered tools; the gap is offline operation, section 5 | Medium (deferred) |
| BL-10 | Variable-star light curve / periodogram: TypeScript only, no data | **stands** | Medium (deferred) |
| BL-11 | Archive downloads dead-end — no tool consumes a downloaded FITS path | **stands** — `tools/optical.py` still searches one root; Phase 6 below | Medium |
| BL-12 | `npm run typecheck` cannot run from a fresh checkout | **stands** — `CLAUDE.md` still omits `npm install`; Phase 6 below | Low |

### BL-1 — `describe_image_wcs` raised on almost every bundled frame

`tools/astrometry.py` sliced `wcs.wcs.ctype`, which is an astropy `StrListProxy`
and does not implement slicing under astropy 8.0.1 — it raises
`TypeError: sequence index must be integer, not 'slice'`. A sweep over the
fixture directory returned 1 ok, 38 failed. The single success was
`m15_globular_open_000.fits`, which returns early at the no-celestial-WCS branch
because it carries no WCS keywords at all. **Every frame that actually had a WCS
raised.** This was the only local FITS tool in `tools/`, so the local image
surface was not merely thin — it was nonfunctional.

Nothing caught it because **no test imported `tools.astrometry`**. The tool-layer
importers under `tests/` covered pulsar plots, the runner session, photometry
smoke, and sonification; `tools.astrometry`, `tools.calibration`,
`tools.catalogs` and `tools.workspace` appeared in none of them.
`tests/test_wcs_headers.py` covers `algorithms.wcs`, not the wrapper.

The fix materializes the proxy before slicing, with a comment naming the cause.
The lasting remedy is the parametrized sweep across all 39 frames — the test
whose absence hid the bug.

### BL-2 — the agent registry exposed no local-data tool except pulsar

`tools/registry.py` mapped 23 tools drawn from 10 modules. Sixteen were remote
database queries; the remaining seven were the pulsar chain. So an agent driven
by `tools/runner.py` could query eight archives and sonify a pulsar, but
**could not open, measure, calibrate, or even describe any of the 39 FITS frames
this repository ships**, and could not list an artifact it produced.

`docs/tool-architecture.md` section 2 named `describe_image_wcs`,
`list_photometric_catalogs`, `resolve_reference_band`,
`solve_zeropoint_from_measurements`, `list_artifacts` and `describe_artifact` as
"the first local, no-network tools". None of them was registered.

### BL-3 — no optical-frame lookup registry

The pulsar chain's Stage 0 has: a listing function, a resolver that returns
either a match or the candidate list, a data directory overridable through
`KEPLER_PULSAR_DATA_DIR`, name matching that normalizes punctuation (so `PSR
B0329+54` and `psr_b0329_54` are the same source), and ambiguity or miss
handling that returns `ToolError`s rather than raising.

The optical equivalent existed only inside a CLI script — the photometry tool's
private path resolver and target lister. It was not registered, not importable as
a documented tool, returned a bare mapping of lists, **raised `FileNotFoundError`
instead of returning a `ToolError`**, had no environment override, and reported
no header metadata — so a caller could not ask "which frames are in B?" or
"which frames have a WCS?" without opening all 39 files.
`docs/pulsar-tool-pipeline.md` already cited the photometry script as the model
the pulsar tools should follow; both halves converge on one pattern.

### BL-4 — no tool read `test_data/afterglow/` or `test_data/fieldcal/`

Grepping `test_data` across `tools/` and `algorithms/` returned hits in exactly
two files: the pulsar scan directory and the photometry script's frame search
roots. **Nothing in the tool layer read the recorded ground truth.**

What was sitting there unused:

| Fixture | Contents |
|---|---|
| `test_data/fieldcal/zp_solutions/<field>/fit_data.csv` | every photometered source, with `used_for_calibration` marking the exact rows handed to `calc_solution` |
| `…/fit_summary.json` | the five numbers `calc_solution` returned, plus Afterglow's own result and the declared tolerance |
| `test_data/afterglow/fieldcal/ngc_5128_test_vals.json` | the complete Afterglow field-calibration API response |
| `test_data/afterglow/photometry/afterglow_photometry_ngc5128_b.csv` | 303 sources with `zero_point`, `zero_point_correction`, `calibrated_zero_point` |
| `test_data/afterglow/afterglow_web_values_master.csv` | published zero points for 73 subjects |

The capability was there; only the tool in front of it was missing. Driving the
zero-point solver by hand from the recorded rows reproduces the recorded solve
exactly — `21.147659857998637` from 35 sources, matching `fit_summary.json` once
Afterglow's fixed base of 20 is added.

Two things stood between that and a tool call. First, the zero-point solver
takes already-measured sources, and nothing produced them from a local frame.
Second, the one path that did produce them —
`claude_photometry_haiku_tool.compute_field_cal_zero_point` — queried VizieR
over the network, and **field calibration is on by default**; the flag is the
negative `--no-field-cal`. Offline, the default bundled-target run printed a
warning to stderr and silently fell back to instrumental magnitudes — for
`ngc5128_galaxy_b_001.fits`, whose true zero point is recorded three different
ways in this repository.

**A limitation to state up front.** Offline replay is feasible because
`fit_data.csv` carries the matched catalog rows — but only the 35 *matched* rows
were recorded, not the full cone-search response. A replay provider therefore
validates photometry → matching → reference-magnitude resolution → solve, but
cannot reproduce `fit_summary.json`'s `num_not_selected_by_field_cal: 263`,
because the rows that failed to match were never written down. This is stated in
the tool's docstring and in the test; a partial replay must not be mistaken for a
full one.

Note also that the existing end-to-end field-calibration test **synthesizes**
catalog sources at detected positions with a known offset. That is a good test of
the wiring, but it is a self-consistency check: it recovers a constant it
planted. The recorded APASS rows make a real cross-implementation check possible.

### BL-5 — `zero_point_corr` held an absolute zero point

The public model field named `zero_point_corr` was populated from
`calc_solution`'s `m0`, which is the **absolute** zero point —
`21.147659857998637` where the recorded correction is `1.1476598579986392`.
Afterglow fixes `zero_point = 20` and reports a correction; Kepler computes the
absolute value. `test_data/README.md` warns in bold that mixing the two
conventions "lands 20 magnitudes off in a way that looks entirely plausible" —
and the public model name was on the wrong side of exactly that trap. Afterglow's
own `field_cal_zero_point_corr` key keeps its name; it genuinely is a correction.

### BL-6 — the OCL report no longer joined to any bundled frame

`test_data/fieldcal/ocl_filter_report.json` records a full WCS → photometry →
field-calibration sweep over ten Open/Clear/Lum frames, keyed by upstream
filename. The bundled frames were renamed to `m15_globular_lum_000.fits` and
`m15_globular_open_000.fits`, and the report carries no observation
date, no exposure time, and no other identifier — only the input filename — so
**the join key was lost in the rename** and the ground truth was stranded.

The mapping was recoverable only from outside this repository, from the upstream
rename script at `/home/claude/skynet-data/pipeline_data/reorganize.py`. One row
corroborates it independently: all three trial filters for the Open frame failed
with "no WCS solution found in FITS header", and `m15_globular_open_000.fits` is
precisely the one bundled frame with no WCS keywords. The mapping was certain;
it just was not written down here. It now is, as
`test_data/frame_provenance.json`.

Worth noting for BL-7: upstream's OCL sweep only *read* the header WCS — it did
not plate-solve. A working plate-solving tool takes that frame further than the
recorded pipeline did.

### BL-7 — `solve_wcs` was unreachable, and its data dependency present but unconfigured

Three gaps stacked here.

1. **No tool.** `docs/tool-architecture.md` listed `solve_astrometry` under
   "next Python tools". It was never built, and the algorithm was reachable only
   by importing the algorithm package directly.
2. **A state object with no factory.** `solve_wcs` called a method on a
   processing run. A bare stand-in fails with an attribute error;
   `algorithms.wcs.state.ProcessingRun` was the intended duck-type and worked,
   but nothing in `tools/` constructed it and no document said a caller must.
   **Section 3 removes this requirement outright** rather than documenting it.
3. **The index data was on this machine and nothing pointed at it.**
   `/usr/bin/solve-field` and thirteen astrometry.net index files (4107–4119,
   ~350 MB) under `/usr/share/astrometry/data`, with both `ANET_INDEX_PATH` and
   `ATLAS_CATALOG_ROOT` unset. `CLAUDE.md` explained that both WCS backends
   "degrade to *unavailable* rather than failing … This is why full parity has
   never been validated here." Sound in general and **wrong on this host**:
   astrometry.net is installed, and the solver had simply never been pointed at
   it.

Pointed at the indexes, the solve reached the backend and ran for real: 100
sources on a 1056×1027 frame, RA/Dec hints correctly derived from the frame's own
header, one index directory accepted, 670 seconds, no solution. The wiring works.
What the log shows is *why* it found nothing: a search radius of 180 degrees and
a 0.1–60 arcsec/px scale window — an all-sky search across a 600× pixel-scale
window, on a frame whose header states `SECPIX = 0.5864922312362758`.

**That is deliberate upstream behaviour, not a bug**, and it constrains what a
tool wrapper may do. `solve_wcs` constructs a `WcsCalibrationSettings()` fresh
and exposes only two of its fields through `PlateSolveSettings`, under an explicit
rationale:

> Only the two knobs that shape the *written* WCS are exposed — SIP order and
> where the reference pixel sits. Search radii, scale windows and source caps
> stay internal: they are accuracy tuning, not a product choice, and an observer
> narrowing the search would silently cause misses.
> — `algorithms/wcs/wcs.py`

And `pixel_scale_hint_arcsec` does **not** narrow the astrometry.net search.
`anet_min_scale` and `anet_max_scale` are assigned straight from the
`WcsCalibrationSettings` defaults, under a comment recording that a radius of
180 is a true all-sky search. The hint feeds only the acceptance threshold
`max_sep_deg` and the *ATLAS* backend's scale narrowing — and no UCAC4/UCAC5
data exists on this host, so ATLAS is unavailable and that narrowing never runs.

**Consequence, and it survived into the landed tool:** a wrapper cannot make this
solve fast through the public signature. It can only (a) bound it with a timeout
and report non-convergence as a warning, or (b) reassign the calibration-settings
defaults — which diverges from upstream and is a maintainer decision, not a
tool-layer one. Phase 4 took route (a) and route (b) remains open (section 6.1).

An earlier draft of that phase told the implementer to pass the pixel-scale hint
to speed the solve up. Reading the algorithm after the real run showed the hint
never reaches the astrometry.net scale window. The correction is recorded here so
it is not re-made.

### BL-8 — the curated pulsar periods are unreachable from the tool layer

`PulsarScan` carries path, source name, observation date, receiver, observing
frequency, coordinates, duration, and size — and no period. The periods live in
two places, neither of which is a tool:

- `test_data/pulsar/Curated pulsars.docx` — the reference `test_data/README.md`
  calls "the verification reference … **This document, not ATNF, is the reference
  the tests compare against**".
- A literal dictionary in `tests/conftest.py`, transcribed from that document's
  literature-period column. A pytest module; not importable as a tool.

Meanwhile the system prompt tells the agent that for a catalogued source, the
ATNF search gives a period more accurate than a short scan can measure, and to
prefer it when the two disagree. `search_atnf` is `psrqpy` over the network.
Offline the agent must blind-search — and the sonification suite pins that this
works for **one of the five** bundled scans; the other four peak on 60 Hz mains
interference or red noise while still reporting "99.73% Confidence". So the
documented recovery path is exactly the one unreachable without a socket, and the
local data that would fix it sits in the same directory as the scans.

### BL-9 — HR diagram: the remaining gap is offline operation

Written against `main`, this finding said there was no runtime, no data, and one
genuinely external dependency. **Two thirds of that is now wrong**, and the
correction matters more than the original.

`dev` carries `algorithms/hrdiagram_py/` (`hrfit`, `isochrones`, `literature`,
`matching`, `membership`, `observations`) with seven registered tools in
`tools/hr_diagram.py`, including a full catalog-driven pipeline. The isochrone
dependency originally called "the one item wiring cannot fix" **was fixed**:
`algorithms/hrdiagram_py/isochrones.py::fetch_parsec_isochrone_grid` pulls PARSEC
grids from the CMD service at `stev.oapd.inaf.it` and caches them under
`isochrone_cache/`.

What survives is narrower and squarely this document's topic: **the HR-diagram
chain cannot run offline.** The isochrone grid is a live HTTP fetch, Gaia
photometry is a live VizieR query, and there is no cluster fixture anywhere in
`test_data/` — so nothing in the chain has a bundled-data path, and the
repository's "default checks stay deterministic and bounded" constraint means
none of it can be covered by the default suite. The fix is a recorded fixture
(one cluster's Gaia rows plus one PARSEC grid), not a runtime or a data-licensing
decision.

For the record of what was severed: `docs/extraction.md` section 3 lists four
backend endpoints. Three — cluster catalog cone search (returning
`output_sources`, `input_sources`, the cluster, and `star_counts`),
field-star-removal astrometry (whose cut lives in `fsr/fsr.util.ts` and
`cluster-data.service.util.ts`; only the data delivery was severed), and the
Milky Way Star Cluster catalogue — are catalog work this repository can already
do through `algorithms/query`. The fourth returned
isochrone data **already interpolated into colour and absolute-magnitude pairs
for the requested filter triple**; the server did the grid interpolation and the
synthetic photometry. Astromancer ships no grid (verified: its assets are two
font families and a static folder) and neither does Kepler, which is what the
PARSEC fetch now supplies at the cost of a network call.

### BL-10 — variable-star light curve and periodogram

`algorithms/lightcurve/variable/` and `algorithms/periodogram/variable/` are
TypeScript with no runtime, and there is no fixture data anywhere in
`test_data/`. Astromancer ships no sample light curves. Unlike BL-9 there is no
external-data blocker — a variable-star light curve is an ordinary time series
and VizieR, ASAS-SN, or ZTF can supply one — but it needs the same runtime
decision. Deferred with BL-9; section 5.

### BL-11 — archive downloads dead-end

`tools/mast.py` creates `FITS_DOWNLOAD_DIR` and downloads products into it when
`download=True`. Nothing can then be done with them: `tools/optical.py` still
reports a single `search_root` and searches only the optical data directory, so
a downloaded frame is invisible to the frame registry that every other optical
tool resolves through. The chain **find data → measure → calibrate → compare**
is still severed at its first joint.

### BL-12 — `npm run typecheck` cannot run from a fresh checkout

`CLAUDE.md` lists `npm run typecheck` in Commands. `node_modules/` is absent and
`tsc` is not on `PATH`; the command needs `npm install` first, which `CLAUDE.md`
does not mention (`README.md` does), and it is not a CI job so nothing else runs
it. One-line documentation fix.

---

## 2. The baseline already landed

Phases 1–4 merged to `dev` as PRs #43, #44, #45, and #47. Their task-level
narrative is in git history; what matters going forward is the surface they
established, because everything below builds on it.

| Phase | PR | What it established |
| --- | --- | --- |
| 1 — local tools work and are reachable | #43 | The `StrListProxy` fix plus a parametrized sweep over all 39 frames; `astrometry`, `calibration`, `catalogs` and `workspace` registered; `ZeropointSolution.zero_point` renamed to say it holds an absolute zero point; a registry-coverage test that pins every public tool module as represented. |
| 2 — the optical frame registry | #44 | `tools/optical.py` — `list_optical_frames` and `resolve_optical_frame`, header summary only with no pixel reads, backed by `KEPLER_OPTICAL_DATA_DIR`, returning `OpticalFrame`/`OpticalFrameList` with filter, telescope, WCS presence, field centre, pixel scale and size. Both registered; the photometry CLI's private resolver delegates to it. |
| 3 — the field-calibration reference comparison | #45 | `tools/fieldcal_reference.py` — listing, loading, solving from, and comparing against the recorded solves, plus `replay_catalog_sources` for offline replay; `tools/photometry.py`'s `calibrate_zeropoint`; `test_data/frame_provenance.json` restoring the OCL join key. |
| 4 — plate solving as a tool | #47 | `tools/wcs.py`'s `solve_astrometry`, with a timeout bound, backend-attempt reporting, fixture protection, a concurrent-file-change check, and an atomic WCS header write. Behind a `solver` marker by default. |

**Names later phases depend on:** `list_optical_frames`,
`resolve_optical_frame`, `OPTICAL_DATA_DIR_ENV` (`KEPLER_OPTICAL_DATA_DIR`);
`list_zeropoint_references`, `load_zeropoint_reference`,
`solve_zeropoint_from_reference`, `solve_zeropoint_from_recorded_solve`,
`compare_zeropoint_to_reference`, `load_ocl_reference`,
`replay_catalog_sources`, `FIELDCAL_DATA_DIR_ENV` (`KEPLER_FIELDCAL_DATA_DIR`);
`calibrate_zeropoint`; `solve_astrometry`, returning a `WcsSummary`; and
`ZeropointSolution.zero_point`. The result models are
`OpticalFrame`/`OpticalFrameList`, `ZeropointReference`, and
`ZeropointComparison`.

`TOOL_FUNCTIONS` is **49** on `dev` as of 2026-09-07, up from 23 when the
findings were written.

Two conventions those phases set, which the remaining work keeps:

- **The `slow` and `solver` markers** keep the two expensive additions —
  pixel-level field calibration, and a real plate solve — out of the default run,
  per the repository's deterministic-and-bounded constraint.
- **A recorded-input replay and a from-pixels measurement are different claims,
  and the tests say which is which.** The bit-exact claim belongs to replay; the
  end-to-end number re-measures photometry from pixels and is asserted to 0.1 mag.

---

## 3. Stateless optical tools architecture

The remaining `ProcessingRun` types, ORM-shaped state, module-global dependency
wiring, and batch exporter are removed while preserving the numerical behaviour
of source extraction, plate solving, photometry, and field calibration.
Algorithm functions receive explicit scientific inputs and return explicit
results. Public tools own filesystem access, remote catalog access,
configuration, timeouts, error translation, and artifact persistence.

### 3.1 Scope

**In scope:**

- remove `algorithms.wcs.state.ProcessingRun` and the ORM-shaped mutable
  `WcsSolution` record;
- remove `algorithms.fieldcal.schemas.ProcessingRunRef`;
- remove source-extraction and photometry adapters whose only purpose is reading
  `processing_run.observation_asset_id`;
- replace WCS mutation with a typed return value;
- replace field calibration's process-global `deps` service locator with explicit
  inputs and ordinary imports of deterministic algorithm functions;
- move catalog-query orchestration to `tools.photometry`;
- update every tool and algorithm consumer to pass `file_id` and WCS explicitly;
- delete the retained Skynet batch WCS/photometry/zero-point exporter; and
- update extraction and repository documentation to describe the agentic tool
  architecture rather than instructing callers to recreate a processing run.

**Explicitly out of scope:**

- changing Python 3.14 or dependency versions;
- changing plate-solver search order, acceptance thresholds, or timeout
  behaviour;
- changing source extraction, aperture or PSF photometry, matching,
  reference-band selection, or zero-point mathematics;
- introducing a replacement run, request-context, session, stage, progress, or
  job object **under any name**;
- introducing a new batch CLI, or preserving the legacy batch exporter behind a
  compatibility alias; or
- changing the public tool response models, except where an additional
  diagnostic is required to preserve information currently hidden in mutable run
  state.

This is an orchestration refactor. The extracted astronomy algorithms are the
source of truth; their mathematics, constants, ordering, thresholds, and known
parity behaviour are not targets for improvement here.

### 3.2 The architectural boundary

**Algorithm layer.** Modules under `algorithms/` operate on in-memory scientific
values. They may use Astropy, NumPy, SciPy, SEP, and other algorithm
dependencies, but they do not: open caller-selected FITS paths; query remote
catalogs; read tool configuration from environment variables; mutate module-level
dependency slots; persist job, stage, or progress state; or create identifiers
from a pipeline run.

An optional `file_id` remains valid as provenance attached to source rows. It is
data, not execution state. Callers pass it directly; callers without a meaningful
numeric identifier pass nothing, and **do not hash a path to manufacture one**.

**Tool layer.** Modules under `tools/` resolve files, read FITS data, choose
local or remote services, invoke algorithms, write requested artifacts, and
convert failures into the established `ToolError` and `ToolWarning` models. **A
tool call is the unit of execution. No state survives solely to connect one tool
call to another.**

### 3.3 WCS contract

`algorithms/wcs/state.py` is deleted. A focused result module defines immutable
solve output in two frozen dataclasses, `WcsSolveMetadata` and `WcsSolveResult`:

- **`WcsSolveMetadata`** carrying, all optional: `science_hdu_index`; `ra_deg`
  and `dec_deg`; `crpix1`/`crpix2`; `crval1`/`crval2`; `cdelt1`/`cdelt2`; the four
  CD elements `cd11`, `cd12`, `cd21`, `cd22`; `crota2`; `width_px` and
  `height_px`; `rotation_deg`; `pixel_scale_arcsec_per_px`; `mirrored`;
  `date_solved`; `pointing_error_arcsec`; `delta_ra_arcsec` and
  `delta_dec_arcsec` **in arcseconds**; and `n_field`, the field-source count,
  which defaults to zero.
- **`WcsSolveResult`** carrying the WCS itself (or nothing, when no solution was
  accepted), the `CatalogSource` rows as a tuple, and that metadata.

`solve_wcs` takes the FITS header, the image data, a temporary directory, and —
all keyword-only and optional — `file_id`, `pixel_scale_hint_arcsec`,
`extraction_settings` (a `SourceExtractionSettings`), `solve_settings` (a
`PlateSolveSettings`), `solver_settings` (a `SolverSettings`), and the two
diagnostic channels `solver_attempts` and `solver_failures`. It returns the
`WcsSolveResult`.

The solve continues updating the caller-provided **in-memory** FITS header with
an accepted WCS, because downstream calculations in the same call depend on it.
It does not write a file. Failure and no-solution results carry dimensions and
detected-source count without pretending a persisted solution row exists. **The
historical stale-field clearing bug disappears with the mutable reusable state**
— there is no previous result to clear.

`build_wcs_from_processing_run_solution` and `build_wcs_for_processing_run` are
deleted. Consumers use the returned WCS directly, or call `build_wcs_from_header`
when the WCS is already in a FITS header.

`tools.wcs.solve_astrometry` consumes the `WcsSolveResult`. Its existing error
codes, backend-attempt reporting, fixture protection, concurrent-file-change
check, and atomic WCS-header write are unchanged.

**Two unit corrections are structural, not mathematical.** The values stored under
`delta_ra_deg` and `delta_dec_deg` are already calculated in arcseconds, so the
explicit result names become `delta_ra_arcsec` and `delta_dec_arcsec` without
changing the values.

### 3.4 Source extraction and photometry contracts

Both source-extraction packages already expose deterministic functions that
accept `file_id` explicitly. Those become the only supported entry points:
`run_source_extraction`, taking data, header, `settings` and an optional
`file_id`; and `run_photometry`, taking data, header, sources and settings, plus
an optional `wcs`, `background`, and `background_rms`.

The two run-shaped `perform_source_extraction` adapters and the run-shaped
`perform_photometry` adapter are deleted. Callers that need the old combined flow
call source extraction, build the WCS from the header, then call photometry. That
composition lives in the calling tool or a focused domain adapter, where its
inputs are visible — **never back inside a generic run-like abstraction.**

`algorithms.hrdiagram_py.observations` and `tools.radio_sources` stop generating
process-random path hashes. They pass no `file_id`; neither public result exposes
the internal source-row file identifier.

### 3.5 Field calibration contract

`algorithms.fieldcal.deps` and the wiring function are deleted. Field
calibration has **no process-global callable registry**.
`perform_field_calibration` receives all externally acquired data explicitly:
header, image data, and — keyword-only — `wcs`, `catalog_sources`,
`variable_sources` (defaulting to none), `file_id`, the three settings objects
`field_cal_settings` (a `PhotometricCalibrationSettings`), `photometry_settings`
(a `PhotometrySettings`) and `extraction_settings` (a
`SourceExtractionSettings`), optional pre-detected `detected_sources`
(`SourceExtractionData` rows), and `use_provided_photometry`. It returns the
zero point and a `FieldCalResult`.

It normalizes and matches the provided catalog data, optionally filters it
against the provided variable-star rows, runs deterministic extraction and
photometry through ordinary imports, and calculates the same solution. **It never
queries a catalog.** Absent reference sources raise the existing missing-input
error; a missing WCS where matching requires one raises the existing missing-WCS
error.

Unique generated source ids use a call-local prefix and are collision-free only
within the supplied rows. They no longer include a timestamp or a processing-run
id. These ids are bookkeeping; they do not participate in matching or numerical
results.

`tools.photometry.calibrate_zeropoint` performs catalog selection and calls
`algorithms.query.runner.query_catalogs`. When variable-star rejection is
enabled, the tool also queries VSX and passes those results in. **Offline
recorded-source replay makes no network calls at all, VSX included.** Shared
tool-layer preparation is a private helper in `tools.photometry`; the standalone
compatibility module calls that helper rather than wiring global state.

The calibration algorithm may continue writing `PHOT_M0`, `PHOT_M0E`, and
`PHOT_CAL` to its in-memory header, because those are explicit scientific outputs
consumed during the same tool call. The tool remains responsible for any
filesystem write.

### 3.6 Batch artifact removal

`algorithms/fieldcal/batch_wcs_photometry_zeropoint_export.py` is **deleted, not
ported**. It is an automated directory runner with modes, implicit iteration, CSV
aggregation, broad exception swallowing, and mutable FITS writes. Those are
Skynet harness responsibilities, not reusable field-calibration algorithms.

No replacement batch command is introduced. An agent enumerates known inputs and
invokes `solve_astrometry` or `calibrate_zeropoint` deliberately, inspecting a
structured result after each call.

Before completion, the implementation audits Python and documentation for
remaining optical-pipeline artifacts. In this scope the **forbidden retained
concepts** are: `ProcessingRun`, `ProcessingRunRef`, `ensure_wcs_solution`,
`build_wcs_for_processing_run`, `wire_fieldcal_deps`, mutable `fieldcal.deps`
assignments, and the WCS/photometry/zero-point batch driver. Historical prose in
`docs/extraction.md` may name upstream Skynet types **only** when clearly
describing provenance, never as a current Kepler API.

### 3.7 Error handling

- Invalid explicit inputs continue to raise `ValueError` at the algorithm layer.
- A valid solve that finds no acceptable WCS returns a result whose WCS is
  absent — not an exception, and not a separate found-solution flag.
- Backend execution failures remain recorded through the existing solver-failure
  diagnostic channel, so the tool can distinguish a failure from an ordinary miss.
- Remote query failures are handled in the tool layer and translated into the
  current structured tool errors and warnings.
- The field-calibration algorithm does not catch dependency or I/O failures,
  because it performs neither dependency lookup nor I/O.
- **No broad exception handling is added** to preserve batch-style
  "continue with the next frame" behaviour.

### 3.8 What parity means

Parity is equality of scientific behaviour, not preservation of incidental ORM or
batch-run state. Existing recorded outputs and tolerances remain authoritative.

| Area | Behaviour that must remain stable | Structural change allowed |
| --- | --- | --- |
| WCS | Backend order and attempts, request hints, acceptance decisions, returned WCS matrix, centre, pixel scale, rotation, parity, pointing deltas, source count, FITS header updates, timeout and failure diagnostics | Replace mutation of a run-owned solution row with an immutable result |
| Source extraction | Detected rows and ordering, positions, fluxes, FWHM values, background and RMS arrays, saturation handling, optional `file_id` propagation | Remove adapters that read `file_id` from a run object |
| Photometry | Source identity, centroided positions, fluxes and errors, instrumental magnitudes and errors, aperture geometry, WCS-derived coordinates, header metadata | Make callers explicitly compose extraction and photometry |
| Field calibration | Variable-star exclusion, mutual nearest-neighbour matching, calibration photometry with aperture correction disabled, SNR and star selection, reference-band resolution, zero point, error, slop, limiting magnitude, rejection percentage, output rows, FITS calibration keywords | Supply WCS, reference rows, variable rows, and `file_id` directly |
| Public tools | Schemas, structured errors and warnings, offline replay, file protection, atomic writes, catalog selection behaviour | Own all I/O, query, configuration, and orchestration work |

**Deliberately not parity requirements:** a `found_solution` flag separate from
whether a returned WCS exists; mutation or clearing of a reusable ORM-shaped WCS
record; timestamps or run ids embedded in generated bookkeeping identifiers;
stage, progress, retry-loop, or batch aggregation state; and the ability to
reconstruct a WCS from a persisted processing-run row.

### 3.9 Documentation outcome

`docs/tool-architecture.md` states that a tool call is Kepler's execution
boundary. `docs/repository-folders.md` and package documentation reference
explicit algorithm inputs rather than dependency wiring. `docs/extraction.md`
retains provenance and parity notes while marking ORM and job-runner adapters and
the batch driver as deliberately removed from the maintained architecture.

---

## 4. Rollout

**The rollout is complete.** The stateless rollout (phases S0–S6) merged as one
focused PR before broken-links Phase 5 or 6 begins, and before any
[tui-harness.md](tui-harness.md) phase. The TUI's later photometry-pipeline
rename therefore operates on the stateless pipeline; it must not preserve,
recreate, or rename the removed processing-run or batch architecture.

### Rollout outcome

PR #52 delivered the stateless boundaries: WCS solving now returns immutable
results, extraction and photometry receive explicit inputs, field calibration is
deterministic over supplied data, and tools own catalog queries, configuration,
file I/O, error translation, and persistence. The processing-run state,
dependency registry, and automated optical batch exporter were removed, and the
architecture, extraction, repository-layout, package, and test documentation
was updated accordingly.

The remaining broken-links phases are now unblocked by this merge, but their
scope is independent: Phase 5 still adds curated pulsar-period data and Phase 6
still closes the archive-download loop and documents the TypeScript typecheck
prerequisite. The deferred TypeScript-backed tools and the maintainer/data
decisions in sections 5 and 6 remain out of this rollout.

PR #52's GitHub CI checks, including `python tests`, succeeded. This completion
record does not claim that optional local solver-data or live-network checks ran;
those remain gated by their prerequisites, with CI as the authoritative full-suite
gate.

### Global constraints

Every phase inherits these, from `CLAUDE.md` and `docs/tool-architecture.md`.

- **The extraction contract holds.** `algorithms/` is byte-preserved from
  Skynet/Astromancer. No phase here edits algorithm numerics. Where a change
  touches `algorithms/`, it adds a caller-facing seam, never a changed
  expression. Every newly severed dependency gets an `# EXTRACTED: was <symbol>`
  marker.
- **Known bugs stay pinned.** Documented parity quirks are deliberate. If a test
  reveals one, pin it and say so in capitals.
- **Do not edit the numerical kernels** in `algorithms/skylib_lite/`,
  `algorithms/fieldcal/solution.py`, or `algorithms/fieldcal/ref_mag.py`. These
  files must show no diff at the end.
- **Where orchestration and numerical work share a module**, limit changes to
  imports, function boundaries, explicit input flow, typed result assembly,
  logging context, and removal of state mutation. Do not move or rewrite the
  mathematical blocks.
- **Do not replace `ProcessingRun` with a differently named context, request,
  session, stage, job, or progress object**, and do not introduce a replacement
  batch command.
- **Default checks stay offline and deterministic.** Nothing added here opens a
  socket unless marked `network`, which also requires `KEPLER_TEST_NETWORK=1`.
  Keep solver-data and live-query tests opt-in.
- **No generated files in the repository.** Artifacts go to
  `KEPLER_ARTIFACT_DIR` (default `artifacts/`, gitignored). Do not add FITS,
  plots, or caches to `test_data/`; the one new fixture the remaining phases add
  is a small JSON map.
- **Keep Python 3.14 and current dependency versions.** Dependencies are pinned
  with `==`; no phase here needs a new one.
- **No linter or formatter is configured.** Match the surrounding file's style.
- **Target `dev`, not `main`.** Keep PRs narrow; separate documentation,
  workflow, dependency, and behaviour changes.
- **Result contract:** public tools return typed models carrying warnings and
  errors. Failures are returned, not raised.
- **`file_id` is optional provenance.** Callers without a meaningful numeric
  identifier pass nothing; they do not manufacture one from a path hash.
- **Keep network access and FITS persistence in `tools/`**; keep `algorithms/`
  focused on in-memory scientific values.

### Verification commands

```bash
uv run --python 3.14 pytest -q            # default no-network suite
uv run --python 3.14 python -m compileall tools algorithms
npm run typecheck                         # only when touching a .ts file
git diff --check
```

After a plate-solving change, additionally, with the local indexes available:

```bash
ANET_INDEX_PATH=/usr/share/astrometry/data uv run pytest -m solver
```

### Delivery shape for the stateless rollout

One focused pull request from `agent/remove-processing-run-architecture` to
`dev`, separate from PR #47, divided into phases so each architectural boundary
can be reviewed and validated before the next begins. Each phase is one or more
focused commits. **The branch is not merged partway through.** Intermediate APIs
may exist while the branch is under development, but the final PR contains no
compatibility facade for the processing-run or batch architecture.

Each phase must leave its focused tests passing. Temporary compatibility code is
allowed only inside an uncommitted red-green-refactor cycle.

### Phase S0 — Baseline and inventory

**Intent:** establish the comparison point and confirm the branch carries the
complete merged Phase 4 tool surface.

- [x] Confirm PR #47 is present on `dev` and update the feature branch from
      current `dev`.
- [x] Run the complete default suite under Python 3.14 and record pass, skip, and
      warning counts.
- [x] Inventory every current reference to processing runs, WCS solution state,
      field-calibration dependency wiring, path-derived ids, and optical batch
      orchestration.
- [x] Classify each match as current executable architecture, historical
      provenance, or an active planning reference.
- [x] Identify mixed modules where plumbing may change but numerical blocks must
      remain untouched.

**Parity gate:** the branch starts green, and the inventory accounts for all
known artifacts before deletion begins.
**Exit:** a reviewed removal list, a recorded test baseline, and no ambiguity
about which files hold source-of-truth mathematics.

### Phase S1 — Stateless WCS results

**Intent:** remove run-owned WCS state while retaining the solver's current
scientific and operational behaviour.

- [x] Characterize successful, unsuccessful, and backend-failure solve outputs
      **before** changing the interface.
- [x] Introduce the immutable result and metadata contract of section 3.3.
- [x] Change WCS solving to accept header, image data, temporary storage,
      configuration, diagnostic channels, and an optional `file_id` explicitly.
- [x] Preserve in-memory header updates — later calculations in the same tool
      call depend on them.
- [x] Migrate `tools.wcs.solve_astrometry` to consume the returned result while
      preserving its error handling, backend reporting, fixture protection,
      concurrent-write guard, and atomic header persistence.
- [x] Remove the processing-run WCS reconstruction helpers and the WCS state
      module once all consumers use returned or header WCS values directly.

**Latitude:** choose the smallest internal refactor that produces the approved
result contract. Do not alter backend requests, fallback order, acceptance
calculations, or FITS WCS write-back.
**Parity gate:** characterization tests compare every scientific metadata field,
header effect, solver attempt, and failure diagnostic before and after. The
existing solver-data tests remain valid when local indexes are available.
**Exit:** WCS solving has no processing-run input and no mutable persisted state,
and the Phase 4 tool behaves identically at its public boundary.

### Phase S2 — Explicit extraction and photometry composition

**Intent:** make the already-stateless numerical entry points the only supported
algorithm APIs.

- [x] Migrate WCS, HR-diagram observation extraction, radio-source extraction,
      and any other consumers to call source extraction with an explicit
      `file_id`.
- [x] Make callers explicitly pass detected sources, WCS, background, and RMS
      into photometry when they compose those stages.
- [x] Pass no `file_id` where there is no meaningful domain identifier.
- [x] Remove both run-shaped source-extraction adapters and the combined
      run-shaped photometry adapter **after** their callers have migrated.
- [x] Remove path hashing that exists only to populate a processing-run field.

**Latitude:** composition may live in the narrow consumer or in a focused domain
helper when more than one caller shares the responsibility. It must not move back
into a generic run-like abstraction.
**Parity gate:** existing extraction and photometry suites continue to pin source
rows, background arrays, fluxes, magnitudes, errors, coordinates, and metadata.
Consumer tests verify the same results reach HR-diagram and radio workflows.
**Exit:** `run_source_extraction` and `run_photometry` are the only maintained
algorithm entry points for these stages, and no caller synthesizes an execution
id from a file path.

### Phase S3 — Explicit field-calibration inputs

**Intent:** turn field calibration into deterministic computation over supplied
scientific data.

- [x] Strengthen characterization around the real-frame calibration path and the
      recorded Afterglow/Skynet parity fixtures **before** changing
      orchestration.
- [x] Supply WCS, reference catalog rows, variable-star rows, optional detected
      sources, settings, and an optional `file_id` directly.
- [x] Replace the module-global dependency registry with ordinary imports of the
      deterministic extraction, coordinate, and photometry functions.
- [x] Keep catalog-row normalization and generated ids local to one call.
- [x] Preserve variable-star rejection, matching order, the forced
      `apcorr_tol=0.0` calibration behaviour, SNR selection, reference-magnitude
      resolution, `calc_solution`, and in-memory FITS keyword updates.
- [x] Remove field calibration's ability to query catalogs or discover WCS state.

**Latitude:** orchestration helpers may be reorganized to clarify explicit data
flow. Calculation order and the content of matched and calibrated source rows may
not change, except for removal of run-derived bookkeeping values.
**Parity gate:** the end-to-end real-frame test, recorded zero-point cases,
Afterglow comparisons, variable-star exclusion tests, reference-band tests, and
solution tests all pass at their existing tolerances. **A dedicated test proves
the algorithm performs no network query.**
**Exit:** field calibration is callable with in-memory values alone, with no
process-global wiring, remote-service lookup, or processing-run input.

### Phase S4 — Tool-owned catalog and file orchestration

**Intent:** put side effects at the public tool boundary where an agent can
observe and control them.

- [x] Move calibration catalog selection and queries into `tools.photometry`.
- [x] Query VSX in the tool layer when variable-star rejection is enabled, and
      pass those rows to the calibration algorithm.
- [x] Keep recorded-source replay offline: supplied catalog rows bypass every
      remote query, VSX included.
- [x] Share only focused tool-layer preparation between the registered photometry
      tool and the standalone compatibility path.
- [x] Preserve current structured errors, fallbacks, comparisons, diagnostic
      payloads, and file-writing ownership.

**Latitude:** choose the private helper shape and exception translation, following
established models in `tools/`. **No mutable registry or configuration shared
between calls.**
**Parity gate:** tests cover offline replay with zero network calls, live-query
orchestration through deterministic fakes, unchanged public schemas, and the
existing field-calibration failure modes.
**Exit:** tools own every network, environment, path, and persistence decision;
algorithms receive resolved values only.

### Phase S5 — Remove automated batch artifacts

**Intent:** delete the remaining Skynet execution model rather than preserving it
under compatibility names.

- [x] Delete the automated WCS/photometry/zero-point batch exporter.
- [x] Delete `ProcessingRunRef`, the field-calibration dependency registry, the
      WCS state classes, and obsolete exports **after** their consumers are gone.
- [x] Audit for other retained optical automation patterns: implicit directory
      iteration, stage or progress state, broad continue-to-next-frame exception
      handling, run-scoped persistence, CSV aggregation tied to a batch, and
      generated execution identifiers.
- [x] Remove such artifacts when they exist solely to reproduce the upstream
      batch harness. Keep reusable scientific algorithms and public single-call
      tools.
- [x] Add a repository-shape test that prevents current Python APIs from
      reintroducing the removed run and batch concepts.

**Latitude:** decide whether a discovered helper is reusable computation or batch
infrastructure using the boundary in section 3.2. **Surface uncertain cases in
review before deleting them.**
**Parity gate:** all scientific suites still pass; the removal audit has no
current executable matches, while historical provenance remains readable.
**Exit:** no run-shaped facade, service locator, automated optical batch driver,
or renamed equivalent remains in current Python code.

### Phase S6 — Documentation and release gate

**Intent:** make the stateless tool boundary durable and leave the next
broken-links phase a clean base.

- [x] Update `docs/tool-architecture.md` to define one tool call as Kepler's unit
      of execution.
- [x] Update `docs/repository-folders.md`, package documentation, and
      `tests/README.md` for the explicit APIs and the new architecture coverage.
- [x] Update `docs/extraction.md` **without erasing provenance**: upstream run and
      ORM names may remain where clearly historical, while current guidance must
      not instruct callers to recreate them.
- [x] Review the complete branch diff specifically for accidental changes to
      numerical expressions, constants, thresholds, source ordering, and error
      semantics.
- [x] Run the full repository checks on Python 3.14, and the optional
      solver and network checks only when their prerequisites are available.
- [x] Open and merge the PR to `dev` with parity evidence and a clear statement that this
      changes orchestration, not astronomy algorithms. Record focused
      optical-suite results, any optional solver-data run, and a clean diff for
      the protected numerical-kernel files.

**Exit:** required CI green, documentation matching the resulting code, a clean
working tree, and a PR reviewable phase by phase.

### Review checkpoints

Review at these boundaries rather than letting the whole refactor accumulate:

1. WCS characterization and result contract.
2. WCS consumer migration and removal of state.
3. Extraction and photometry consumer migration, and adapter removal.
4. Field-calibration characterization and explicit-input conversion.
5. Tool-layer query orchestration and offline replay.
6. Batch-artifact deletion, repository audit, and final documentation.

At every checkpoint, **review the scientific diff separately from the API diff**.
An interface can be structurally correct and still be rejected if it changes a
numerical expression or weakens a recorded parity assertion.

### Risk controls

**Mixed algorithm and orchestration modules.** Some extracted files contain both
mathematical work and obsolete pipeline plumbing. This is the highest-risk part
of the rollout. Prefer narrow edits in place, retain existing calculation order,
and use characterization tests that compare complete result structures rather
than only success flags.

**Mutable-state removal.** The old WCS state can retain stale values across
solves; stateless results remove that possibility. Tests must distinguish an
intentional absence of prior state from a numerical regression in a fresh solve.

**Catalog-query relocation.** Moving queries changes where failures are caught.
Preserve user-visible tool errors and the best-effort variable-star behaviour
while ensuring algorithm code does not silently perform I/O.

**Bookkeeping identifiers.** Timestamped, run-scoped, and path-hashed ids are not
scientific outputs, but they can accidentally affect source joins. Verify
matching and calibration row order after replacing them with call-local ids or
nothing.

**Optional external systems.** Astrometry indexes, UCAC catalogs, and live remote
services are not default test dependencies. Their gated tests supplement, but do
not replace, deterministic offline characterization.

### Completion audit for the stateless rollout (recorded outcome)

PR #52's review and successful GitHub CI gate confirm the following:

- `ProcessingRun`, `ProcessingRunRef`, `ensure_wcs_solution`, processing-run WCS
  reconstruction, and field-calibration dependency wiring are absent from current
  Python APIs.
- The automated WCS/photometry/zero-point exporter and any equivalent retained
  batch harness are gone.
- No path hash is used as an optical `file_id`.
- Algorithm modules do not open caller-selected FITS paths or query catalogs.
- Public tools own configuration, I/O, network access, error translation, and
  requested persistence.
- Protected numerical-kernel files have no diff.
- Changes inside mixed modules are limited to the approved orchestration boundary
  and typed result construction.
- Default tests pass under Python 3.14 with no network requirement.
- The architecture and reference docs describe the code that will land.

### Phase 5 — The curated pulsar periods (BL-8)

**Now unblocked by the stateless rollout merge. The phase retains its
independent scope.**

- [ ] Create `test_data/pulsar/curated_periods.json`, transcribed from
      `tests/conftest.py`'s `PULSAR_PERIODS_S`, `PULSAR_ATNF` and
      `PULSAR_DIFFICULTY` tables — themselves the literature-period column of
      `Curated pulsars.docx`. The file carries a comment recording that **that
      document, not ATNF, is the reference the tests compare against**, and that
      the scan files carry no topocentric-period header, so the period always
      comes from outside the data.
- [ ] Add three optional fields to `PulsarScan`: `curated_period_s`,
      `curated_difficulty`, and `period_source`.
- [ ] Load the fixture once at module level in `tools/pulsar.py`, guarded so a
      missing file is a warning rather than an import error, and match a scan to a
      key using the existing `_normalize_pulsar_name` — the keys are already in
      normalized form (`b0329`), so a containment test against the normalized
      source name is the lookup.
- [ ] Repoint `tests/conftest.py`'s `PULSAR_PERIODS_S` at the fixture so the
      number lives in one place. **Keep the surrounding comment block** — it
      explains why the document and not ATNF is the arbiter, and that reasoning
      is not in the JSON.
- [ ] Amend the system prompt so the offline path is stated first: the scan
      resolver reports a curated literature period for every bundled scan, and
      it is preferred over the blind search, which succeeds on only one of the
      five. **Locate the prompt before editing it** — it moves to
      `tools/agent/prompt.py` in [model-backends.md](model-backends.md) Phase 0c
      and `tools/runner.py` re-exports it while the shim exists. Edit whichever
      file holds it; the prompt text and the reason for the edit are the same
      either way.

**Do not fix anything else in `tools/pulsar.py` while here.**
`docs/analysis/pulsar-pipeline-review.md` tracks a set of open tool-correctness
bugs in that file — the periodogram chart hard-coding "Polarization XX" while the
default channel is `sum`, frequency-mode periodograms inheriting period-mode axis
semantics, `lomb_scargle()` raising `ZeroDivisionError` on a constant light curve,
`top_peaks` being ambiguous between seconds and hertz, `fold_lightcurve()` having
no guard against a tiny period, and Stage 0 still able to raise `OSError` on an
unreadable file. Every one is a tool-correctness bug rather than a local-data
link. Fixing one in passing would put a behaviour change in a
documentation-and-plumbing PR.

`docs/pulsar-tool-pipeline.md` section 7 was stale and has been corrected; keep
it in step when Stage 0 gains the curated period.

### Phase 6 — Close the archive-to-analysis loop and the documentation (BL-11, BL-12)

**Now unblocked by the stateless rollout merge. The phase retains its
independent scope.**

- [ ] Make the optical data directory resolve to a **list** of roots: the
      `KEPLER_OPTICAL_DATA_DIR` override or the default optical directory, plus
      `tools.config.FITS_DOWNLOAD_DIR` when it exists. Both the lister and the
      resolver walk all of them.
- [ ] Keep the existing `search_root` field reporting the primary root, and add a
      `search_roots` list to `OpticalFrameList` so a caller can see both. An
      explicit `directory` argument still means exactly that one directory.
- [ ] Extend the archive tools' existing download warning so it names the next
      step — that the downloaded files are now resolvable through the frame
      registry.
- [ ] `README.md`: the photometry-tool section says the target listing covers
      targets it can run against with no live archive query. True of *resolution*,
      but field calibration is on by default and queries VizieR. State that the
      zero point needs either `--no-field-cal`, a `--zero-point` override, or the
      offline `compare_to` path.
- [ ] `README.md` and `docs/tool-architecture.md` section 2: add the tools the
      baseline phases landed to the local-tool lists, and strike
      `solve_astrometry` from "next tools" now that it exists.
- [ ] `CLAUDE.md` Commands: note that `npm run typecheck` needs `npm install`
      first — `node_modules/` is not present in a fresh checkout and the typecheck
      is not a CI job (BL-12). `README.md` already says so; `CLAUDE.md` does not.

---

## 5. Deferred: the TypeScript-backed tools (BL-9, BL-10)

**A separate subsystem needing its own plan.** Deferred deliberately, not
overlooked: the HR diagram and the variable-star tools share a runtime decision
this document cannot make for them.

| | HR diagram | Variable star |
|---|---|---|
| Runtime | **now exists** on `dev` — `algorithms/hrdiagram_py/` plus seven registered tools | none — nothing executes the TypeScript |
| Input data | none in `test_data/` | none in `test_data/` |
| Catalog access | solvable — `algorithms/query` already queries VizieR for Gaia, 2MASS, APASS, WISE and MWSC | solvable — VizieR, ASAS-SN, ZTF |
| Model grids | **fetched live** from the PARSEC CMD service, with no recorded fixture | not applicable |

**The runtime decision, still open for BL-10.** `CLAUDE.md` is explicit that a
Python port is not a general licence: `algorithms/pulsar/` is the one instance,
and `docs/extraction.md` (Pulsar Sonification §5) records why it was allowed
there and why it is not general. That port was justified because the upstream
sonifier was welded to browser APIs and could not run headless. The variable-star
code is not — it is plain arithmetic on plain arrays — so the precedent does not
extend on its own. The choice between a Node subprocess seam (mirroring the
`solve-field` subprocess pattern `algorithms/wcs/` already uses, at the cost of
adding Node to the runtime dependency set when `package.json` has no build step),
a Python port marked `# PORTED:` with its divergences enumerated, and leaving it
as typechecked source is a real architectural decision. **It requires
brainstorming with the maintainer — do not pick one from a plan document.**
For the HR diagram this is settled: `dev` took the port.

**What the follow-on plan needs, in order:**

1. **Decide the runtime** for the variable-star half.
2. **Decide the isochrone-grid policy.** PARSEC and MIST both publish
   downloadable grids. This is a licensing and repository-size question as much
   as a technical one: `test_data/` is already 175 MB and `.gitignore` excludes
   `data/`. The `ANET_INDEX_PATH` precedent — the operator supplies the bulk
   data, the repository carries only the pointer — is the obvious model, but it is
   the maintainer's call. `dev`'s live fetch plus local cache is a third answer
   that works and has no offline story.
3. **Build cluster ingest on `algorithms/query`.** A cone search returning Gaia
   astrometry plus multi-band photometry is what the query runner already does;
   the HR-diagram source shape is a normalization of it.
4. **Record a cluster fixture in `test_data/`** — one well-studied open cluster
   (M67 is the conventional choice: old enough for a clean turnoff, well covered
   by Gaia and 2MASS) as a recorded VizieR response, plus one PARSEC grid, so the
   field-star cut and the plot-delta computation get an offline test the way the
   zero-point solution has one.
5. **Then, and only then, a lookup registry** — `list_clusters` and
   `resolve_cluster` over that fixture, mirroring the optical frame registry.

Step 4 is the one that makes the original request literally true for the HR
diagram, and it is fourth because the steps above it are its prerequisites.

---

## 6. What this document cannot fix

Everything below surfaced during the investigation and **no phase above closes
it**. Each needs something this work does not have: a maintainer's decision, data
that is not in this repository, a fixture nobody recorded, or a different topic
entirely. Grouping them by *why* they are stuck is the point — that is what tells
you who unblocks each one.

### 6.1 Needs a maintainer decision, deliberately not made here

**The astrometry.net search window (BL-7).** The one that stops plate solving
from being useful on the only frame that needs it. `solve_wcs` constructs
`WcsCalibrationSettings()` internally and exposes just two of its fields, under
the explicit rationale quoted in BL-7: search radii, scale windows and source
caps stay internal because an observer narrowing the search would silently cause
misses. So astrometry.net always gets a 180-degree radius and a 0.1–60 arcsec/px
window. On `m15_globular_open_000.fits` that ran 670 seconds and returned
nothing, on a frame whose own header states `SECPIX = 0.5864922312362758`.
Narrowing the window to the header value would very probably make the solve
tractable — and would be precisely the failure mode that comment warns about.
**Phase 4 therefore bounded the run with a timeout and narrowed nothing.** Until
this is decided, `solve_astrometry` is a tool that reaches the backend correctly
and reports an honest non-result. Deciding it changes extracted behaviour and
belongs in its own PR under the extraction contract.

**The TypeScript runtime for the variable-star tools (BL-10).** Section 5.

**Whether Kepler carries, fetches, or requires an isochrone grid.** Section 5,
item 2. `dev` currently fetches, which answers the capability question and not
the offline one.

### 6.2 Needs data that is not in this repository

**Cluster photometry and variable-star light curves.** There is none in
`test_data/`. On `dev` this bites harder than it did on `main`, because the
HR-diagram chain exists and still cannot be exercised offline: the Gaia
crossmatch is a live VizieR query and the isochrone grid is a live HTTP fetch, so
no part of `tools/hr_diagram.py` can be covered by the default deterministic
suite. A lookup registry for HR-diagram or variable-star inputs likewise has
nothing to look up until a fixture is recorded.

**UCAC4/UCAC5 catalog data.** Absent from this host entirely. The ATLAS triangle
solver is therefore unreachable, and **no test the baseline phases added
exercises that backend at all** — including its pixel-scale narrowing, which is
the one place the pixel-scale hint actually does something. Half of
`algorithms/wcs/`'s solver surface stays unvalidated, and no phase here changes
that.

**The B-band frames behind three of the four recorded zero-point solves.** Three
of them — `ngc5286_b_000`, `_001` and `_002` — describe NGC 5286 exposures in B;
the only NGC 5286 frame bundled is `ngc5286_globular_v_000.fits`, a V frame. So
all four solves are checked bit-exactly at the solution level, but **only NGC
5128 B can be driven end-to-end from pixels**. Three quarters of the recorded
ground truth is reachable as numbers and not as a pipeline.

### 6.3 Needs a fixture nobody recorded upstream

**The unmatched catalog rows (BL-4).** `fit_data.csv` recorded the 35 APASS rows
that *matched* a detection. The cone-search rows that did not match were never
written down, so the recorded count of sources not selected by field calibration
(`num_not_selected_by_field_cal: 263`) is unreproducible from the shipped
fixture, and the replay validates photometry → matching → reference magnitude →
solve but not catalog selection. Closing this needs a live VizieR cone search
re-recorded as a new fixture — a network operation producing a new artifact,
against two of this document's own constraints. The tool docstring and the test
say so, rather than letting a partial replay pass for a full one.

**The 36 frames above the 9 MB cut-off.** The Afterglow web table covers 73
subjects (~1.5 GB); `test_data/optical/` carries the 37 under 9 MB plus the two
OCL frames. Widening coverage means adding large incompressible binaries to plain
git, permanently. `test_data/README.md` already names Git LFS as the answer; that
is an infrastructure change, not a broken link.

### 6.4 Real problems, different topic

Tracked elsewhere; this document must not quietly absorb them.

**`docs/analysis/pulsar-pipeline-review.md` — open pulsar tool bugs.** Enumerated
under Phase 5 above, where the constraint bites. All are tool-correctness bugs,
not local-data links.

**`docs/analysis/algorithm-remediation-plan.md`'s 109 findings and 7 blockers.**
Algorithm correctness, untouched here by design. The extraction contract holds
throughout: no phase moves a numeric expression.

### 6.5 What "all phases complete" will not mean

**Not full Skynet parity.** This work validates the *tool seam* — that a tool can
find local data, run the real code path against it, and return a number
comparable to recorded ground truth. It does not validate that Kepler's whole
pipeline reproduces Skynet's.

**Not a working plate solve.** Phase 4 demonstrated that the solver is wired,
configured, and exercised. Whether it *converges* on the one frame that needs it
is unresolved and, per section 6.1, may stay unresolved until the search-window
question is answered.

---

## 7. References

* [`../tool-architecture.md`](../tool-architecture.md) — the master architecture
  this work sits under, and the document Phase S6 amends to define a tool call as
  the unit of execution.
* [`../extraction.md`](../extraction.md) — per-domain provenance; the WCS, HR
  Diagram, and Catalogs sections are the ones this work touches.
* [`../pulsar-tool-pipeline.md`](../pulsar-tool-pipeline.md) — the Stage 0
  pattern every registry here generalizes, and the document Phase 5 keeps in step.
* [`../analysis/pulsar-pipeline-review.md`](../analysis/pulsar-pipeline-review.md)
  — the open pulsar tool bugs Phase 5 must leave alone.
* [`../analysis/algorithm-remediation-plan.md`](../analysis/algorithm-remediation-plan.md)
  — algorithm correctness, deliberately out of scope.
* `test_data/README.md` — the zero-point convention warning behind BL-5, and the
  Git LFS note behind section 6.3.
* [tui-harness.md](tui-harness.md) — blocked on the stateless rollout, and the
  owner of the photometry-pipeline rename that must operate on its result.
* [model-backends.md](model-backends.md) — owner of the system-prompt move that
  this document's Phase 5 must account for.
