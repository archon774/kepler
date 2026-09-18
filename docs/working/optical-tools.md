# Optical Tools: Broken Links and Stateless Architecture

**Status:** Baseline phases 1–4 and stateless phases S0–S6 are complete on
`dev`, as are closure phases P1–P9. The rollout is complete.
**Date:** 2026-09-04 (findings), 2026-09-07 (stateless design, sequencing,
consolidation), 2026-09-09 (completion audit and approved closure rollout),
2026-09-11 (P4 completion), 2026-09-12 (P5 and P6 completion), 2026-09-13
(P7 and P9 completion), 2026-09-16 (P8 completion)
**Prerequisites:** No architectural prerequisite remains. The stateless rollout's
prerequisite — broken-links Phase 4 — merged as PR #47. P8 has a separate
maintainer-supplied asset gate.
**Unblocks:** The stateless boundary required by every phase of
the TUI track is complete. The remaining phases close
local-data and solver-convergence gaps.
**Merged at:** `dev` commit `33617a4adaf89aadd006ec8be11fe6678f19d0cd` (PR #52,
"Refactor optical processing to stateless S0–S6 contracts").
**Scope:** the seam between the public `tools/` surface and the local data in
`data/`, the execution architecture behind that seam, and the Python
runtime ports needed to make the locally shipped TypeScript algorithms callable.
The ports preserve TypeScript numerical behavior; separate correctness
remediation remains
[`../analysis/algorithm-remediation-plan.md`](../analysis/algorithm-remediation-plan.md).
This is not a general file-organization plan; see
[`../tool-architecture.md`](../tool-architecture.md).

This document is architecture and sequencing. It contains no implementation
code. An agent working a phase reads the contracts here, then writes the code
that satisfies them.

## Two coupled problems, one surface

**The links are broken.** Tools that should run against the data bundled in this
repository do not reach it, and the recorded ground truth in
`data/afterglow/` and `data/fieldcal/` is readable only as a pytest
fixture, never as a tool result. The original twelve findings are supplemented
by the reference-document drift found in the post-rollout audit, section 1.

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

### Status summary

Status is **as of 2026-09-13**, after PRs #43, #44, #45, #47, #52, #59, #60,
#62 and #63 on `dev`, plus #64 (P7) once it merges.

| # | Broken link | Status | Severity |
|---|---|---|---|
| BL-1 | `describe_image_wcs` raised `TypeError` on 38 of 39 bundled frames | **closed** — fixed on `dev` before Phase 1; the parametrized sweep landed with it | — |
| BL-2 | The agent registry omitted the local no-network tools | **closed** — Phase 1 registered `astrometry`, `calibration`, `catalogs`, `workspace` | was High |
| BL-3 | No optical-frame lookup registry (the HR-diagram example) | **closed** — Phase 2 added `tools/optical.py` | was Medium |
| BL-4 | No tool read `data/afterglow/` or `data/fieldcal/` | **closed** — Phase 3 added `tools/fieldcal_reference.py` and `tools/photometry.py`; Phase P7 recorded the field's APASS and VSX responses and added the end-to-end selection replay, which re-chooses the recorded 35 calibration stars from the recorded 132-row cone (45 candidates on the frame) and reproduces the solve bit for bit offline | was High |
| BL-5 | `ZeropointSolution.zero_point_corr` held an absolute zero point | **closed** — Phase 1 renamed it to `zero_point` | was High |
| BL-6 | `ocl_filter_report.json` no longer joined to any bundled frame | **closed** — Phase 3 added `data/frame_provenance.json` | was Medium |
| BL-7 | `solve_wcs` unreachable; its index data present but unconfigured | **closed** — Phase P6 added explicit opt-in search bounds while retaining the parity default; against the host's 4200-series indexes the M15 fixture solves in ~14 s bounded and ~285 s all-sky, to the same solution | was Medium |
| BL-8 | Curated pulsar periods unreachable from the tool layer | **closed** — Phase P1 added the curated-period map and the measure-first sourcing order | was Medium |
| BL-9 | HR diagram: no offline path and an incomplete Python port | **closed** — Phase P5 provides a configured operator-local Girardi grid and ports the remaining computational TypeScript surface | was Medium |
| BL-10 | Variable-star light curve / periodogram: TypeScript only, no data | **closed** — PR #60 added the exact-parity Python runtime and compact fixture | Medium |
| BL-11 | Archive downloads dead-end — no tool consumes a downloaded FITS path | **closed** — Phase P2 made the archive download directory a second, recursive frame-registry root | was Medium |
| BL-12 | `npm run typecheck` cannot run from a fresh checkout | **closed** — Phase P2 recorded the `npm install` prerequisite in `CLAUDE.md` | was Low |
| BL-13 | Reference documentation still instructs callers to use removed stateless-rollout APIs | **closed** — Phase P3 reconciled `CLAUDE.md`, `README.md`, the reference docs and the working index with the landed architecture | was Medium |

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

### BL-4 — no tool read `data/afterglow/` or `data/fieldcal/`

Grepping `data` across `tools/` and `algorithms/` returned hits in exactly
two files: the pulsar scan directory and the photometry script's frame search
roots. **Nothing in the tool layer read the recorded ground truth.**

What was sitting there unused:

| Fixture | Contents |
|---|---|
| `data/fieldcal/zp_solutions/<field>/fit_data.csv` | every photometered source, with `used_for_calibration` marking the exact rows handed to `calc_solution` |
| `…/fit_summary.json` | the five numbers `calc_solution` returned, plus Afterglow's own result and the declared tolerance |
| `data/afterglow/fieldcal/ngc_5128_test_vals.json` | the complete Afterglow field-calibration API response |
| `data/afterglow/photometry/afterglow_photometry_ngc5128_b.csv` | 303 sources with `zero_point`, `zero_point_correction`, `calibrated_zero_point` |
| `data/afterglow/afterglow_web_values_master.csv` | published zero points for 73 subjects |

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
full one. **P7 closed this** by recording the field's APASS *and* VSX responses
and adding the end-to-end selection replay — the VSX rows turned out to be part
of the recorded selection (the P7 record has the star).

Note also that the existing end-to-end field-calibration test **synthesizes**
catalog sources at detected positions with a known offset. That is a good test of
the wiring, but it is a self-consistency check: it recovers a constant it
planted. The recorded APASS rows make a real cross-implementation check possible.

### BL-5 — `zero_point_corr` held an absolute zero point

The public model field named `zero_point_corr` was populated from
`calc_solution`'s `m0`, which is the **absolute** zero point —
`21.147659857998637` where the recorded correction is `1.1476598579986392`.
Afterglow fixes `zero_point = 20` and reports a correction; Kepler computes the
absolute value. `data/README.md` warns in bold that mixing the two
conventions "lands 20 magnitudes off in a way that looks entirely plausible" —
and the public model name was on the wrong side of exactly that trap. Afterglow's
own `field_cal_zero_point_corr` key keeps its name; it genuinely is a correction.

### BL-6 — the OCL report no longer joined to any bundled frame

`data/fieldcal/ocl_filter_report.json` records a full WCS → photometry →
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
`data/frame_provenance.json`.

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
solve fast through the public signature. Phase 4 bounded it with a timeout and
reported non-convergence as a warning. P6 resolved the remaining public-control
gap by adding explicit opt-in search-radius and scale bounds while preserving the
default all-sky 0.1–60 arcsec/px behavior; see its completion record for the
bounded solve that closed this.

An earlier draft of that phase told the implementer to pass the pixel-scale hint
to speed the solve up. Reading the algorithm after the real run showed the hint
never reaches the astrometry.net scale window. The correction is recorded here so
it is not re-made.

### BL-8 — the curated pulsar periods are unreachable from the tool layer

`PulsarScan` carries path, source name, observation date, receiver, observing
frequency, coordinates, duration, and size — and no period. The periods live in
two places, neither of which is a tool:

- `data/pulsar/Curated pulsars.docx` — the reference `data/README.md`
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
`data/` — so nothing in the chain has a bundled-data path, and the
repository's "default checks stay deterministic and bounded" constraint means
none of it can be covered by the default suite. The fix is a recorded fixture
(one cluster's Gaia rows plus one PARSEC grid), not a runtime or a data-licensing
decision. Phase P5 now expands the Python port to every remaining
computational HR-diagram algorithm and adds an explicit local-grid execution
path; M67 is a test fixture only, never a public registry entry.

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

`algorithms/lightcurve/variable/` and `algorithms/periodogram/variable/` remain
the TypeScript provenance for the variable-star algorithms. P4 added their
exact-parity Python runtime in `algorithms/variable_star/`, its public tools,
and a compact paired-source fixture in `data/variable_star/` (PR #60).
Astromancer ships no sample light curves. Unlike BL-9 there is no external-data
blocker — a variable-star light curve is an ordinary time series and VizieR,
ASAS-SN, or ZTF can supply one.

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

### BL-13 — reference documents describe deleted architecture

The stateless code removed `algorithms.fieldcal.deps`, processing-run state,
and run-shaped photometry adapters, but `CLAUDE.md`, `README.md`, and parts of
the reference architecture still tell callers to use them or omit the landed
local optical tools. This is a broken link between the public documentation and
the maintained API. Phase P3 reconciles those current-state documents while
preserving clearly labelled upstream provenance in `docs/extraction.md`.

---

## 2. The baseline already landed

Phases 1–4 merged to `dev` as PRs #43, #44, #45, and #47. Their task-level
narrative is in git history; what matters going forward is the surface they
established, because everything below builds on it.

| Phase | PR | What it established |
| --- | --- | --- |
| 1 — local tools work and are reachable | #43 | The `StrListProxy` fix plus a parametrized sweep over all 39 frames; `astrometry`, `calibration`, `catalogs` and `workspace` registered; `ZeropointSolution.zero_point` renamed to say it holds an absolute zero point; a registry-coverage test that pins every public tool module as represented. |
| 2 — the optical frame registry | #44 | `tools/optical.py` — `list_optical_frames` and `resolve_optical_frame`, header summary only with no pixel reads, backed by `KEPLER_OPTICAL_DATA_DIR`, returning `OpticalFrame`/`OpticalFrameList` with filter, telescope, WCS presence, field centre, pixel scale and size. Both registered; the photometry CLI's private resolver delegates to it. |
| 3 — the field-calibration reference comparison | #45 | `tools/fieldcal_reference.py` — listing, loading, solving from, and comparing against the recorded solves, plus `replay_catalog_sources` for offline replay; `tools/photometry.py`'s `calibrate_zeropoint`; `data/frame_provenance.json` restoring the OCL join key. |
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
focused PR before implementation of the remaining P1–P9 phases began, and before any
TUI phase. The TUI's later photometry-pipeline
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

The remaining broken-links phases were unblocked by this merge and received an
approved, independent P1–P9 rollout below. P5 and P9 have since completed;
P8 begins when its maintainer-supplied assets arrive.

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
  plots, or caches to `data/`; the one new fixture the remaining phases add
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

### Phase S0 — Baseline and inventory — Complete

**Intent:** establish the comparison point and confirm the branch carries the
complete merged Phase 4 tool surface.

- Confirm PR #47 is present on `dev` and update the feature branch from
      current `dev`.
- Run the complete default suite under Python 3.14.
- Inventory every current reference to processing runs, WCS solution state,
      field-calibration dependency wiring, path-derived ids, and optical batch
      orchestration.
- Classify each match as current executable architecture, historical
      provenance, or an active planning reference.
- Identify mixed modules where plumbing may change but numerical blocks must
      remain untouched.

**Parity gate:** the branch starts green, and the inventory accounts for all
known artifacts before deletion begins.
**Exit:** a reviewed removal list, a completed test baseline, and no ambiguity
about which files hold source-of-truth mathematics.

### Phase S1 — Stateless WCS results — Complete

**Intent:** remove run-owned WCS state while retaining the solver's current
scientific and operational behaviour.

- Characterize successful, unsuccessful, and backend-failure solve outputs
      **before** changing the interface.
- Introduce the immutable result and metadata contract of section 3.3.
- Change WCS solving to accept header, image data, temporary storage,
      configuration, diagnostic channels, and an optional `file_id` explicitly.
- Preserve in-memory header updates — later calculations in the same tool
      call depend on them.
- Migrate `tools.wcs.solve_astrometry` to consume the returned result while
      preserving its error handling, backend reporting, fixture protection,
      concurrent-write guard, and atomic header persistence.
- Remove the processing-run WCS reconstruction helpers and the WCS state
      module once all consumers use returned or header WCS values directly.

**Latitude:** choose the smallest internal refactor that produces the approved
result contract. Do not alter backend requests, fallback order, acceptance
calculations, or FITS WCS write-back.
**Parity gate:** characterization tests compare every scientific metadata field,
header effect, solver attempt, and failure diagnostic before and after. The
existing solver-data tests remain valid when local indexes are available.
**Exit:** WCS solving has no processing-run input and no mutable persisted state,
and the Phase 4 tool behaves identically at its public boundary.

### Phase S2 — Explicit extraction and photometry composition — Complete

**Intent:** make the already-stateless numerical entry points the only supported
algorithm APIs.

- Migrate WCS, HR-diagram observation extraction, radio-source extraction,
      and any other consumers to call source extraction with an explicit
      `file_id`.
- Make callers explicitly pass detected sources, WCS, background, and RMS
      into photometry when they compose those stages.
- Pass no `file_id` where there is no meaningful domain identifier.
- Remove both run-shaped source-extraction adapters and the combined
      run-shaped photometry adapter **after** their callers have migrated.
- Remove path hashing that exists only to populate a processing-run field.

**Latitude:** composition may live in the narrow consumer or in a focused domain
helper when more than one caller shares the responsibility. It must not move back
into a generic run-like abstraction.
**Parity gate:** existing extraction and photometry suites continue to pin source
rows, background arrays, fluxes, magnitudes, errors, coordinates, and metadata.
Consumer tests verify the same results reach HR-diagram and radio workflows.
**Exit:** `run_source_extraction` and `run_photometry` are the only maintained
algorithm entry points for these stages, and no caller synthesizes an execution
id from a file path.

### Phase S3 — Explicit field-calibration inputs — Complete

**Intent:** turn field calibration into deterministic computation over supplied
scientific data.

- Strengthen characterization around the real-frame calibration path and the
      recorded Afterglow/Skynet parity fixtures **before** changing
      orchestration.
- Supply WCS, reference catalog rows, variable-star rows, optional detected
      sources, settings, and an optional `file_id` directly.
- Replace the module-global dependency registry with ordinary imports of the
      deterministic extraction, coordinate, and photometry functions.
- Keep catalog-row normalization and generated ids local to one call.
- Preserve variable-star rejection, matching order, the forced
      `apcorr_tol=0.0` calibration behaviour, SNR selection, reference-magnitude
      resolution, `calc_solution`, and in-memory FITS keyword updates.
- Remove field calibration's ability to query catalogs or discover WCS state.

**Latitude:** orchestration helpers may be reorganized to clarify explicit data
flow. Calculation order and the content of matched and calibrated source rows may
not change, except for removal of run-derived bookkeeping values.
**Parity gate:** the end-to-end real-frame test, recorded zero-point cases,
Afterglow comparisons, variable-star exclusion tests, reference-band tests, and
solution tests all pass at their existing tolerances. **A dedicated test proves
the algorithm performs no network query.**
**Exit:** field calibration is callable with in-memory values alone, with no
process-global wiring, remote-service lookup, or processing-run input.

### Phase S4 — Tool-owned catalog and file orchestration — Complete

**Intent:** put side effects at the public tool boundary where an agent can
observe and control them.

- Move calibration catalog selection and queries into `tools.photometry`.
- Query VSX in the tool layer when variable-star rejection is enabled, and
      pass those rows to the calibration algorithm.
- Keep recorded-source replay offline: supplied catalog rows bypass every
      remote query, VSX included.
- Share only focused tool-layer preparation between the registered photometry
      tool and the standalone compatibility path.
- Preserve current structured errors, fallbacks, comparisons, diagnostic
      payloads, and file-writing ownership.

**Latitude:** choose the private helper shape and exception translation, following
established models in `tools/`. **No mutable registry or configuration shared
between calls.**
**Parity gate:** tests cover offline replay with zero network calls, live-query
orchestration through deterministic fakes, unchanged public schemas, and the
existing field-calibration failure modes.
**Exit:** tools own every network, environment, path, and persistence decision;
algorithms receive resolved values only.

### Phase S5 — Remove automated batch artifacts — Complete

**Intent:** delete the remaining Skynet execution model rather than preserving it
under compatibility names.

- Delete the automated WCS/photometry/zero-point batch exporter.
- Delete `ProcessingRunRef`, the field-calibration dependency registry, the
      WCS state classes, and obsolete exports **after** their consumers are gone.
- Audit for other retained optical automation patterns: implicit directory
      iteration, stage or progress state, broad continue-to-next-frame exception
      handling, run-scoped persistence, CSV aggregation tied to a batch, and
      generated execution identifiers.
- Remove such artifacts when they exist solely to reproduce the upstream
      batch harness. Keep reusable scientific algorithms and public single-call
      tools.
- Add a repository-shape test that prevents current Python APIs from
      reintroducing the removed run and batch concepts.

**Latitude:** decide whether a discovered helper is reusable computation or batch
infrastructure using the boundary in section 3.2. **Surface uncertain cases in
review before deleting them.**
**Parity gate:** all scientific suites still pass; the removal audit has no
current executable matches, while historical provenance remains readable.
**Exit:** no run-shaped facade, service locator, automated optical batch driver,
or renamed equivalent remains in current Python code.

### Phase S6 — Documentation and release gate — Complete

**Intent:** make the stateless tool boundary durable and leave the next
broken-links phase a clean base.

- Update `docs/tool-architecture.md` to define one tool call as Kepler's unit
      of execution.
- Update `docs/repository-folders.md`, package documentation, and
      `tests/README.md` for the explicit APIs and the new architecture coverage.
- Update `docs/extraction.md` **without erasing provenance**: upstream run and
      ORM names may remain where clearly historical, while current guidance must
      not instruct callers to recreate them.
- Review the complete branch diff specifically for accidental changes to
      numerical expressions, constants, thresholds, source ordering, and error
      semantics.
- Run the required repository checks on Python 3.14. Optional solver and
      network validation are explicit follow-on phases with their required data.
- Open and merge the PR to `dev` with parity evidence and a clear statement
      that this changes orchestration, not astronomy algorithms.
- Complete the focused optical and protected-kernel audits. Optional
      solver-data and live-network evidence belongs to the dedicated closure
      phases below, not to the completed stateless rollout.

**Exit:** required CI green, the stateless architecture documented at the
public boundary, and a PR reviewable phase by phase. Phase P3 reconciles
reference-document drift discovered after the merge.

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

### Completed stateless rollout

PR #52 completed S0–S6. P3 corrects the remaining stale reference prose, while
P6 and P9 separately cover solver convergence controls and optional operator
data; neither reopens the completed stateless boundary.

### Phase P1 — Curated pulsar periods (BL-8) — Complete

- [x] Create `data/pulsar/curated_periods.json`, transcribed from
      `tests/conftest.py`'s `PULSAR_PERIODS_S`, `PULSAR_ATNF` and
      `PULSAR_DIFFICULTY` tables — themselves the literature-period column of
      `Curated pulsars.docx`. The file carries a comment recording that **that
      document, not ATNF, is the reference the tests compare against**, and that
      the scan files carry no topocentric-period header, so the period always
      comes from outside the data.
- [x] Add three optional fields to `PulsarScan`: `curated_period_s`,
      `curated_difficulty`, and `period_source`.
- [x] Load the fixture once at module level in `tools/pulsar.py`, guarded so a
      missing file is a warning rather than an import error, and match a scan to a
      key using the existing `_normalize_pulsar_name` — the keys are already in
      normalized form (`b0329`), so a containment test against the normalized
      source name is the lookup.
- [x] Repoint `tests/conftest.py`'s `PULSAR_PERIODS_S` at the fixture so the
      number lives in one place. **Keep the surrounding comment block** — it
      explains why the document and not ATNF is the arbiter, and that reasoning
      is not in the JSON.
- [x] Amend the system prompt so the offline path is stated first: the scan
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

**Outcome.** Delivered as PR #57 (`feat/pulsar-curated-periods` -> `dev`), three
commits: the tool change, its documentation, and a policy correction made during
review.

`data/pulsar/curated_periods.json` is the single copy of the curated
periods, difficulty ratings and ATNF cross-check; `tests/conftest.py`'s
`PULSAR_PERIODS_S`, `PULSAR_ATNF` and `PULSAR_DIFFICULTY` read it rather than
restating it, with their comment blocks kept. `PulsarScan` gained
`curated_period_s`, `curated_difficulty`, `period_source` and a `warnings` list,
filled by a `_normalize_pulsar_name` containment match. All five bundled scans
resolve with their literature period, including the B2021+51 scan whose
`SRC_NAME` is its observing programme.

**Two divergences from the checkboxes above**, both deliberate.

*The curated period is a check, not an input.* P1 specified that it be
"preferred over the blind search". It is not: the system prompt, the four
affected registry tool descriptions and the tool docstrings state the sourcing
order as measure, compare, retune, and only then fall back to the reference.
Folding at a literature period produces a fit to a known answer rather than a
detection, and `data/README.md` leans on that distinction — the scans carry
no period in-file precisely so that a successful fold is independent evidence.
Preferring the reference by default would convert every `pulse_snr` in the
pipeline from evidence into a restatement of its own input. The recovery path
the checkbox was reaching for survives as step 4, with a reporting obligation
attached. Changed at the maintainer's direction during review.
`docs/pulsar-tool-pipeline.md` gains a "Measure first, check second" section.

*The map is read from beside the scans, not from a fixed repository path.* P1
said "load the fixture once at module level". It is loaded once per scan
directory instead, because `KEPLER_PULSAR_DATA_DIR` points the tools at another
archive: a hardcoded path would name-match these five periods onto an operator's
own files and stamp them with a `period_source` naming a document that describes
different observations. The bundled case is unchanged — the map is in the
bundled directory — and `tools/` still imports with no `data/` present.

**Review.** A `high`-effort code review and a security review both ran against
the PR diff. The security review returned no findings: the PR adds no privilege
boundary, no new external input reaching a sensitive sink, and no change to
path, subprocess, network, crypto or secret-handling code; the new parse is
`json.loads` of a repo-controlled file whose path derives from `__file__`, and
the untrusted `SRC_NAME` a scan header carries is only ever the haystack of a
containment test against repo-controlled keys. The code review's substantive
findings were fixed rather than deferred:

- `_load_curated_periods` validated only the envelope, so a row that was not a
  dict raised `AttributeError` out of `list_pulsar_scans` and a non-numeric
  `period_s` raised a pydantic `ValidationError` — both contradicting the
  function's own "a missing or unreadable map costs the curated period, not the
  pipeline". Rows are now validated individually and unusable ones dropped, so a
  row without a numeric `period_s` can no longer yield a `period_source` citing
  a curation for a number it lacks.
- The `curated_periods_unavailable` warning existed only on `PulsarScanList`, so
  `resolve_pulsar_scan` — the tool the prompt names first — dropped it on both
  single-match returns, leaving "this archive has no curation" indistinguishable
  from "this source is not curated". `PulsarScan` now carries `warnings`, as
  `OpticalFrame` already does.
- The warning asserted the file was absent when it may be present-but-malformed,
  and named a repo path even for a caller-supplied directory. It now names the
  directory searched and claims nothing about the cause.
- `tests/conftest.py` read the fixture unguarded at import, so a missing or
  malformed file would uncollect the entire suite rather than skip the pulsar
  tests. Guarded like `_discover_frames`/`_require`, with a
  `requires_curated_periods` skip marker for the tests that read the tables
  directly.
- The listing test compared a *set* of periods, so a regression permuting the
  scan-to-period assignment would still have passed. It compares a filename ->
  period mapping now.
- The bias test ran two full-default periodograms and asserted only determinism.
  It now plants a deliberately wrong curated period beside a copied scan, so a
  leak would move the answer rather than merely confirm it, over a narrowed grid.

Findings dismissed with reasons: `data/` not being packaged makes
`curated_period_s` null in an installed copy, but the scans are not packaged
either and `_pulsar_data_dir()` already defaults inside `data/`, so an
installed copy has no scans to attach a period to — a pre-existing repository
property, not one this phase introduced. The "programme SRC_NAME collides"
scenario does not hold: `3_Pulsar_Team_B2021+51_ERIRA` embeds its own target
designation, so a different target under the same programme carries a different
`SRC_NAME` and matches nothing. Renaming `period_source` to
`curated_period_source` was declined: the plan names the field, and `PulsarScan`
is a Stage 0 object that never holds a measured period. The `observation` number
is provenance from the curation's own archival records, not a join key to these
files, and is deliberately unread.

**Still open, by maintainer decision:** `CLAUDE.md`'s pulsar section still says
catalogued periods "beat anything a 60-second scan measures", and P1's checkbox
above still reads "preferred over the blind search". Both now contradict the
shipped prompt and tool descriptions; the code review flagged the `CLAUDE.md`
line independently as the cheapest way to stop the contradiction propagating.
**P3 deliberately did not touch either** — the standing decision was to leave
them, and reconciling stale documentation is not licence to reverse a
maintainer's explicit call. Reverse it by asking, not by tidying.

**Verified:** default no-network suite **1653 passed, 41 skipped**;
`compileall` over `tools algorithms tests`; `git diff --check`; all seven GitHub
CI checks green on the pre-review commit. `tests/test_pulsar_registry.py` pins
the phase in **23 cases**. No `.ts` file was touched, so `npm run typecheck` did
not apply. The four LLM schema goldens were regenerated; the diff is four
description strings per dialect with no schema shape change. The open
tool-correctness bugs listed above were left alone.

### Phase P2 — Archive-to-analysis loop and fresh-checkout documentation (BL-11, BL-12) — Complete

- [x] Make the optical data directory resolve to a **list** of roots: the
      `KEPLER_OPTICAL_DATA_DIR` override or the default optical directory, plus
      `tools.config.FITS_DOWNLOAD_DIR` when it exists. Both the lister and the
      resolver inspect every root; the download root is recursive because MAST
      stores products below its `mastDownload/` directory.
- [x] Keep the existing `search_root` field reporting the primary root, and add a
      `search_roots` list to `OpticalFrameList` so a caller can see both. An
      explicit `directory` argument still means exactly that one directory.
- [x] Extend the archive tools' existing download warning so it names the next
      step — that the downloaded files are now resolvable through the frame
      registry.
- [x] `README.md`: the photometry-tool section says the target listing covers
      targets it can run against with no live archive query. True of *resolution*,
      but field calibration is on by default and queries VizieR. State that the
      zero point needs either `--no-field-cal`, a `--zero-point` override, or the
      offline `compare_to` path.
- [x] `README.md` and `docs/tool-architecture.md` section 2: add the tools the
      baseline phases landed to the local-tool lists, and strike
      `solve_astrometry` from "next tools" now that it exists.
- [x] `CLAUDE.md` Commands: note that `npm run typecheck` needs `npm install`
      first — `node_modules/` is not present in a fresh checkout and the typecheck
      is not a CI job (BL-12). `README.md` already says so; `CLAUDE.md` does not.


**Outcome.** Delivered on `feat/archive-frame-registry` -> `dev`, three
commits: the tool change, the documentation corrections, and this record.

`tools/optical.py` resolves a **list** of roots. The primary root is unchanged
and `search_root` still reports it, present or not; `OpticalFrameList` gains
`search_roots`, every root actually inspected, so a caller can tell "nothing
downloaded yet" from "the primary root is gone". The archive download root is
appended when it exists and searched recursively; the primary root stays flat.
`directory_not_found` now fires only when no root exists and names each root it
tried. A file reachable through two roots is listed once, keyed on the resolved
path, because nothing stops an operator pointing both env vars at one place.
An explicit `directory` argument still means exactly that one directory.

**Three divergences from the checkboxes above.**

*`solve_astrometry` was already struck.* P2 asked for it to come off the "next
tools" list in `docs/tool-architecture.md` section 2. It had already been
removed when it landed, and has its own paragraph there. The entry that was
actually stale was `calibrate_zeropoint`, which exists as
`tools.photometry.calibrate_zeropoint`; that is what was struck, with a line
recording that both have landed.

*`tools/casda.py` was fixed, not just its warning.* Checkbox 3 asks the archive
tools' download warning to name the next step. For CASDA that statement would
have been false: `download_files` was passed a literal `savedir="fits_downloads"`
rather than `FITS_DOWNLOAD_DIR`, so an operator who set
`KEPLER_FITS_DOWNLOAD_DIR` got downloads in one directory and a frame registry
searching another. It uses `FITS_DOWNLOAD_DIR` now. This is a behaviour change
in a phase that is otherwise plumbing and documentation; it is here because the
warning cannot be made true without it.

*The registry descriptions and the system prompt were amended.* Not in the
checkboxes, but `list_optical_frames`'s `directory` parameter documented one
default root and now has two, and the prompt's LOCAL OPTICAL FRAMES paragraph
told the model "there is no archive behind them" with no hint that
`search_mast(download=true)` can put a frame within reach — which is the whole
point of the phase. The four LLM schema goldens were regenerated: two
description strings per dialect, no schema shape change.

**Scope deliberately not taken.** The glob stays `*.fits`. Astroquery can
deliver gzipped products, and a `.fits.gz` under the download root is still
invisible to the registry. Nothing in this repository exercises that path, the
checkbox does not mention extensions, and widening the glob touches `_summary`'s
`<object>_<category>_<filter>_<seq>` stem parse (`Path("x.fits.gz").stem` is
`"x.fits"`), so it is recorded here rather than guessed at. A phase that wants
the loop to close for every MAST mission should start there.

**Review.** A `high`-effort code review and a security review both ran against
the PR diff. The security review returned no findings: the phase adds no
privilege boundary, no subprocess, no new network call, no deserialization and
no secret handling; the path handling it does add reaches nothing that
`resolve_optical_frame`'s pre-existing "explicit path" contract did not already
reach, and `KEPLER_FITS_DOWNLOAD_DIR` is a trusted operator input. One new data
flow was noted rather than flagged: `list_optical_frames()` now parses FITS
headers from archive-fetched files automatically, and those header strings
reach the model. That is the same trust level as every existing remote tool
result, but it is the first time an archive download joins it.

The code review's six substantive findings were fixed rather than deferred:

- **The documented override only moved half the loop.** `tools/optical.py`
  reads `config.FITS_DOWNLOAD_DIR` through the module, but `tools/mast.py` and
  `tools/casda.py` bound it with a `from`-import. A host application that
  reassigned it downloaded to one directory while the registry searched another
  — BL-11 again, with the new warning actively claiming otherwise. The env-var
  path worked for both, which is why nothing caught it. Both archive tools read
  it late now.
- **A downloaded frame could not be resolved by its filename.** The `root /
  name` probe is flat and cannot reach a nested download; normalized matching
  turns `"x.fits"` into `"xfits"`, which is not a substring of the stem `"x"`.
  The docstring and the registry schema both advertise "filename", and a
  filename is exactly what a caller copies out of an archive manifest. The
  original test missed it by writing its frame flat in the download root.
- **`list_photometry_targets` began advertising downloads as bundled targets**,
  contradicting its own registry description ("no live image archive behind
  photometry … a small, fixed set of bundled test frames"), `list_bundled_targets`'s
  docstring, and `PhotometryTargetLibrary`'s. A CASDA radio cube in an optical
  photometry target list is simply wrong. Scoped to the primary root through a
  new public `primary_optical_data_dir()`.
- **`FITS_DOWNLOAD_DIR` was never resolved**, unlike `ARTIFACT_DIR`, whose
  comment explains precisely why a bare relative path is a hazard for something
  handed to another caller. Now that these paths *are* the frame paths the
  image tools take, resolved at import like its neighbour.
- **Duplicate roots were reported twice** in `search_roots`. Collapsed, with
  recursion **OR-ed** rather than taken from the first entry — inheriting the
  primary root's flat search would have silently stopped finding nested
  downloads.
- **The isolation fixture was module-scoped**, so `test_fieldcal_reference` and
  `test_photometry_tool_smoke` still resolved frames against whatever untracked
  `fits_downloads/` the developer had. Moved to `tests/conftest.py`.

A seventh finding is **recorded, not fixed**: `rglob` over the download root is
unbounded, and the whole `OpticalFrameList` is serialized into the model's
context by `tools/agent/engine.py`. After a bulk `download=True` — and
`search_mast`'s own docstring records 121,515 products for Cas A — one
`list_optical_frames()` call reads thousands of headers and emits a payload
that can exhaust the context window. The exposure is real and this phase
created it, but the fix is a `limit`/`max_frames` parameter with a truncation
warning, mirroring `max_observations`; that changes a public tool schema and is
a maintainer's call, not a review cleanup. **It should be the first item of
whichever phase touches this tool next.**

> **Closed** by the data-root phase below (§5, "Data root and bounded frame
> discovery"). The maintainer chose a boundary over a parameter: recursion is
> confined to the data directory and the cap is an operator setting
> (`KEPLER_MAX_FRAMES`), so the public tool schema is unchanged.

One earlier self-audit finding, fixed before review: `_resolve_roots` tested
`directory is not None` where the single-root code it replaced tested `if
directory`. `Path("")` is `Path(".")`, so an empty string — an ordinary thing
for a model to send for an optional parameter — went from "use the defaults" to
"search the working directory", returning an empty listing with `search_root`
`"."`.

**Verified:** default no-network suite **1672 passed, 41 skipped** (19 new
cases in `tests/test_optical_registry.py`); `compileall` over `tools algorithms
tests`; `git diff --check`. No `.ts` file was touched, so `npm run typecheck`
did not apply — though BL-12's claim was confirmed directly while documenting
it: with no `node_modules/`, the command fails with `tsc: command not found`.

The new tests use an autouse fixture that points the download root at an empty
tmp path. `fits_downloads/` is gitignored but real, and now that it is a genuine
second search root a developer who had ever run `search_mast(..., download=True)`
would otherwise see the bundled-frame counts move under them.

**Not touched:** the BL-8 row in the status summary above still reads
"planned — Phase P1" although P1 is complete. It belongs to that phase's
record, not this one. *(Corrected during P3, at the maintainer's direction.)*

---

## 5. Approved remaining closure rollout

The decisions in this section replace the earlier deferred-work framing. Every
phase has a testable exit. Phases P1, P4, P6, P7, P8, and P9 have no code
dependency on one another; P2 and P3 both edit reference documentation and
should be coordinated or landed serially. P5 begins once the maintainer has
supplied the PARSEC grid described in its asset gate.

### Phase P3 — Reconcile reference documentation (BL-13) — Complete

**Intent:** make the reference documents describe the stateless architecture
that is already in `dev`, rather than telling callers to recreate deleted
processing-run and dependency-injection APIs.

**Files:** `CLAUDE.md`, `README.md`, `docs/tool-architecture.md`,
`docs/repository-folders.md`, `docs/extraction.md`, `tests/README.md`, and
`docs/working/README.md`.

- [x] Replace the `algorithms.fieldcal.deps` wiring examples with the explicit
      `perform_field_calibration` inputs and tool-owned query boundary.
- [x] Remove references to deleted run-shaped photometry adapters and WCS
      reconstruction helpers; retain upstream names only in clearly historical
      provenance text.
- [x] State that one public tool call is Kepler's execution boundary and list
      the landed `optical`, `fieldcal_reference`, `photometry`, and `wcs` tools.
- [x] Correct the photometry documentation: target resolution is offline, but
      default field calibration can query VizieR unless callers use the
      documented offline/replay or no-field-calibration routes.
- [x] Update the working-document index to show S0–S6 complete and list these
      remaining independently deliverable closure phases.

**Validation:** `rg` finds no current instruction to import
`algorithms.fieldcal.deps`, create `ProcessingRun`, or call a deleted adapter;
`uv run --python 3.14 pytest tests/test_repository_shape.py -q`; and
`git diff --check`.

**Exit:** current-state documents agree with the public code and the working
index no longer describes the completed stateless rollout as pending.

**Outcome.** Landed with P2 in PR #59, at the maintainer's direction — the phase
table said P2 and P3 "should be coordinated or landed serially", and P2 had
already completed two of P3's five checkboxes (the photometry offline/VizieR
correction outright, and part of the landed-tool listing), so coordinating them
into one PR discharged the constraint rather than deferring it.

`algorithms/fieldcal/deps.py` is **gone** — verified against the tree, not
inferred: `algorithms/fieldcal/` is now `field_cal.py`, `ref_mag.py`,
`schemas.py`, `solution.py`, `__init__.py`. The `deps` wiring example in
`CLAUDE.md` and the two paragraphs in `README.md` are replaced by the real
signature: `perform_field_calibration(header, data, *, wcs=, catalog_sources=,
variable_sources=, extraction_settings=|detected_sources=, photometry_settings=,
field_cal_settings=)`. The catalog query did not move behind a different seam —
it left the package. There is no `deps.query_catalogs` and no lazy import of
`algorithms.query`; `algorithms/fieldcal/` opens no socket, and the tool layer
(`tools.photometry.calibrate_zeropoint`) is the caller that queries.

Two stale symbol claims were found while checking the rest:
`algorithms.photometry.photometry.perform_photometry` does not exist —
`run_photometry` is the module's entire `__all__` — and
`build_wcs_for_processing_run` does not exist, `build_wcs_from_header` does.
Both were named in `CLAUDE.md` as current API. `get_source_radec` and
`run_source_extraction`, also named in the deleted `deps` block, do still exist
and are now listed against the module that owns them.

`docs/extraction.md` needed one current-state correction (a "now reaches the
network through `deps.query_catalogs`" claim) and two severed-dependency rows
reworded so "reached via `deps`" reads as what was true at extraction time
rather than as current structure. The upstream Skynet names in that document are
untouched — that is the provenance record.

The execution-boundary statement (checkbox 3) is now in `CLAUDE.md`,
`README.md`'s domain-ownership highlight, and `docs/tool-architecture.md`
section 2, not only in the `solve_astrometry` paragraph where it originally
appeared.

**Deliberately not touched.** `CLAUDE.md`'s pulsar section still says catalogued
periods "beat anything a 60-second scan measures", contradicting the shipped
prompt. P1's outcome records that as left open **by maintainer decision**.
Reconciling stale documentation is not licence to reverse an explicit call, so
it stands; see the note in P1 above.

**Verified:** `rg` finds no instruction to import `algorithms.fieldcal.deps`,
construct a `ProcessingRun`, or call a deleted adapter outside clearly
historical provenance text; `uv run --python 3.14 pytest -q`;
`python3 -m compileall tools algorithms tests`; `git diff --check`.

**Audited afterwards, and it missed one.** Re-running P3's check in a
generalised form — import every dotted `algorithms.*`/`tools.*` symbol the
top-level documents name, and stat every in-repo path they reference — found
`algorithms/wcs/state.py`, which the stateless rollout deleted alongside
`algorithms/fieldcal/deps.py`. P3 chased the second and never looked for the
first. It was cited in three current-state places, the worst being `CLAUDE.md`'s
extraction contract, where it was the **flagship example** of a parity quirk not
to "fix" — and the function it named, `_clear_wcs_solution_fields`, is on
`tests/test_repository_shape.py`'s forbidden-API list. Corrected, with a live
example substituted (the two deliberately disagreeing catalog registries) and
the dead one kept as a record of a quirk that is gone rather than preserved.
`docs/repository-folders.md` listed `state.py` among `algorithms/wcs/`'s current
files and omitted `results.py`, so that list was wrong in both directions. A
`deps.query_catalogs` mention also survived in `tools/photometry.py`'s
docstring: P3 swept the documentation tree and not tool docstrings. The lesson
for later phases is in the method — a reconciliation that greps for the symbol
it already knows about will only ever find that symbol.

### Data root and bounded frame discovery — Complete

**Not a numbered phase.** This closes the finding P2 recorded and deferred (see
the block quote in §4), on the maintainer's instruction to bind the recursive
walk to the data directory, and renames that directory in the same breath.

`test_data/` is now `data/`: it holds the archive download root, so naming it
after the test suite had stopped being true. The rename carried a trap worth
recording. `.gitignore` already contained a bare `data/` for local scratch, so
renaming into it would have made git ignore the whole ~175 MB fixture tree —
and because files already tracked stay tracked, nothing would have looked wrong
until someone added a fixture that silently never got committed.
`tests/test_repository_shape.py` now asserts no such pattern exists, and
`.gitignore` carries a comment saying why.

The bound is two settings, both operator-level rather than tool parameters:

- **`KEPLER_DATA_DIR`** (default `<repo>/data`) is the data root *and* the
  recursion boundary. `KEPLER_FITS_DOWNLOAD_DIR` defaults inside it, rather
  than to a working-directory-relative `fits_downloads` that moved with
  whatever directory the process started in. `tools/optical.py` walks the
  download root recursively only while it resolves inside the data root;
  outside it the directory is still *searched*, but flat, with a
  `download_root_outside_data_dir` warning. Downgrading rather than refusing is
  deliberate: CASDA's `download_files` writes flat, so a refusal would lose
  those products. Containment is decided on the resolved path, so a symlink out
  of the tree does not buy a walk of wherever it lands.
- **`KEPLER_MAX_FRAMES`** (default 200, rejected below 1) caps how many frames
  one listing reads headers for and returns **per root**, with a
  `listing_truncated` warning naming the total. It is applied *before*
  `_summary`, so it bounds the FITS header reads rather than trimming the
  result after paying for them. A lone match resolved out of a truncated
  listing carries a `resolved_from_truncated_listing` warning — it was found
  among the frames that were read, not the frames that exist, and uncapped the
  name might have been ambiguous.

Keeping both out of the tool schema is what let the four LLM schema goldens stay
structurally unchanged; only two description strings moved.

**One consequence the plan did not anticipate.** `tools/wcs.py` refuses to write
a solved header back into a bundled fixture, and that guard was the entire
`test_data/` tree. With the download root moving *inside* `data/`, it would have
begun refusing writes to downloaded frames — reporting an archive product as a
bundled fixture, and closing the archive → analysis loop BL-11 exists to open.
The guard now names the four tracked fixture subtrees and reads no setting —
see the review record below for why the first draft's "data minus the download
root" was not good enough.

**Review record.** A security review found nothing and empirically exercised
the write guard against `..` traversal and a symlink planted inside the
download root. A code review returned fifteen findings; thirteen were fixed,
one was a docstring correction, and one is a process point left to the
maintainer. The ones that changed behaviour:

- **The write guard could be switched off by one environment variable.** The
  first draft exempted whatever `FITS_DOWNLOAD_DIR` named, so
  `KEPLER_FITS_DOWNLOAD_DIR=<repo>/data` — a plausible misconfiguration —
  disabled it for every fixture. The reviewer proposed requiring the download
  root to be strictly inside and disjoint from the fixtures; naming the four
  subtrees directly is simpler and cannot be misconfigured. A test asserts the
  tuple matches the directories present.
- **The cap filled primary-first**, so an operator archive larger than the cap
  starved the download root and re-created BL-11 silently. It is per root now.
- **"Narrow with `directory=`" was circular for the case the cap exists for**:
  an explicit directory is searched flat, and MAST nests. `search_mast`'s
  download warning now names the leaf directories products landed in, and the
  hints say to pass one of those.
- **`Path.resolve()` raises `RuntimeError`, not `OSError`, on a symlink loop
  under Python 3.12 — the version CI ran at the time (bumped to 3.14 since;
  3.12 remains the `pyproject.toml` floor).** Every `except OSError` around a
  resolve was wrong there and dead on 3.13+. Lifted into
  `tools.config.within`/`safe_resolve`, catching both, used by both modules.
- **`list_photometry_targets` was silently capped** — it went through the
  header lister for what is an index of filenames. It reads no headers now and
  is never capped.
- **Under truncation an ambiguous name came back as a unique match.** The frame
  now carries `resolved_from_truncated_listing`; the containment warning no
  longer rides onto bundled-frame resolves, where it described the operator's
  configuration rather than the match.
- **The default download root moved** from `<cwd>/fits_downloads` with no
  notice. A non-empty directory at the old repository-root location now
  produces a `legacy_download_root_present` warning.
- `KEPLER_MAX_FRAMES=0` returned empty listings and a negative value sliced
  from the wrong end; rejected below 1 at load. Per-file `resolve()` for
  dedup replaced by `(st_dev, st_ino)` from the one `stat` already needed.
  The system prompt's "listed on the next call" gained the cap caveat.

Not acted on: the observation that this PR bundles a fixture rename, two
behaviour changes and a documentation correction, against `CLAUDE.md`'s
"keep PRs narrow". The bundling was the maintainer's direction; the point is
recorded here for the maintainer to weigh.

**Verified:** default no-network suite **1694 passed, 41 skipped**;
`compileall` over `tools algorithms tests`; `git diff --check`; four LLM schema
goldens regenerated (description strings only); `git check-ignore` confirming
a download product under `data/fits_downloads/` is ignored while
`data/optical/*.fits` and `data/README.md` are not.

### Phase P4 — Exact-parity Python variable-star runtime (BL-10)

**Status:** Complete — merged to `dev` as PR #60.

**Intent:** expose the existing variable-star light-curve, fold, and
error-weighted periodogram algorithms through Python tools without changing the
TypeScript mathematical behavior.

**Architecture:** add `algorithms/variable_star/` as a deliberate Python port
of `algorithms/lightcurve/variable/` and `algorithms/periodogram/variable/`.
Its modules cover the source-pair merge, data/error models, differential
photometry, period folding, the periodogram driver, and the error-weighted
Lomb–Scargle helper. Keep the TypeScript extraction as provenance and mark each
Python source with `# PORTED:` references to its TypeScript symbols. Do not
replace formulas, defaults, row ordering, or documented quirks.

**Tool surface:** add `tools/variable_star.py` and typed models in
`tools/models.py`. Stage 0 lists and resolves the compact bundled paired-source
CSV fixture; later tools load the CSV, create the differential light curve,
compute the periodogram, and fold at an explicit period. Results follow the
pulsar pattern: bounded previews inline, complete tables as artifacts, and
typed warnings/errors at the tool boundary.

- [x] Add a compact, two-source variable-light-curve CSV fixture under
      `data/variable_star/`, using the extracted parser input columns
      `id`, `mjd`, `mag`, and `mag_error`, plus a README naming it a parity
      fixture rather than a catalog download.
- [x] Port every computational variable TypeScript symbol needed by the runtime:
      `mergeSourcesByMjd`, `errorMSE`, `VariableData`, variable-source choice,
      differential values and error bars, JD range, period folding,
      `getPeriodStep`, `getChartPeriodogramDataArray`, and
      `lombScargleWithError` with its supporting vector operations.
- [x] Preserve the original source semantics, including the documented
      error-weighting normalization, `errorMSE` calculation, empty-input and
      fold-edge behavior. The public tool may reject malformed file paths and
      invalid schema values, but must not change valid-input algorithm results.
- [x] Add the Stage 0 list/resolve functions, load/periodogram/fold tools,
      registry entries, and artifact writing. Do not add browser playback,
      Highcharts rendering, Angular/RxJS state, forms, or persistence APIs.
- [x] Add parity tests with complete expected rows at each stage, including
      merge ordering, uncertainty values, differential magnitudes, period-fold
      ordering, and the weighted periodogram samples. Pin documented quirks as
      parity behavior rather than silently correcting them.

**Validation:** focused variable-star tests; `npm run typecheck` over the
TypeScript provenance; `uv run --python 3.14 pytest -q`; Python compilation;
and `git diff --check`.

**Exit:** complete — a caller can discover the bundled fixture, run the entire variable
pipeline offline, and obtain Python results with documented TypeScript parity.

### Phase P5 — Complete Python HR-diagram port and local-grid operation (BL-9)

**Intent:** complete the Python port of all computational HR-diagram TypeScript
algorithms and run the existing HR tools from the local Girardi isochrone model
used by Astromancer's former `GET /cluster/isochrone` backend, with no
isochrone network dependency.

**Port boundary:** extend `algorithms/hrdiagram_py/` with ports of the remaining
computational TypeScript surface: CMD/FSR histogram helpers, source
serialization and field-star-result assembly, star counts, cluster summary and
derived quantities, Galactic projections, MWSC distributions, and the
non-browser isochrone-state calculations. Preserve TypeScript numerical
behavior and known quirks exactly; correctness remediation remains a separate
effort. Exclude Angular, Highcharts, form state, browser storage, and rendering.

**Local-grid contract:** `KEPLER_ISOCHRONE_DIR`, defined in `tools.config`, is
the operator-level path to an unpacked legacy Girardi grid. It has no bundled
or hard-coded default: Kepler neither ships nor downloads model files. The
directory contains exactly named NumPy tracks,
`Girardi_<log_age>_<metallicity>.npy`; the supplied asset has every 0.05 grid
point from log-age 6.60--10.20 and metallicity -2.20--+0.70. A missing setting,
directory, track, or invalid `(n, 23)` numeric array is an ordinary actionable
tool error. It never falls back to a PARSEC download or any other HTTP request.

The established 23-column Astromancer model layout is: log-age and metallicity;
U/B/V/R/I; uprime/gprime/rprime/iprime/zprime; J/H/K; W1/W2/W3/W4; G/BP/RP;
and a trailing metallicity repeat. The loader selects exact tracks only -- no
nearest-grid substitution or interpolation -- then returns the former backend's
`{data: [[blue - red, lum], ...], iSkip}` shape for the requested filters.
The browser request's inputs (`age`, `metallicity`, `blue_filter`,
`red_filter`, `lum_filter`) and its plot-break behavior are the compatibility
contract. There is no cluster registry, fixture resolver, public grid-path
argument, bundled cluster catalog, or public model-download API in this phase.

**Operator asset gate:** the full model remains outside this repository. The
reference operator archive at `/srv/agents/isochrones/isochrone.zip` contains
4,307 tracks and has SHA-256
`83b3cfb7fed46cc766a56f7f34aaa2a0edb50b847ac75548553c4e60936d9f8b`.
Operators obtain and manage it under the model's applicable terms; Kepler only
reads the configured unpacked directory.

**P5 inventory:** the pure TypeScript calculations now live in
`algorithms/hrdiagram_py/legacy.py`: CMD/FSR helpers; source serialization,
numeric FSR merge, partitioning and per-catalog tallies; filter normalization,
sorted astrometric/FSR projections and PM chart points; isochrone plot
transforms/ranges and distance reset; angle conversion, haversine, Galactic
coordinates, cluster-summary derivation, MWSC distributions and galaxy
projection. `hrfit.py` remains the Python home of the shared extinction
calculation. `local_grid.py` supplies the former endpoint response shape and
sets `iSkip` to zero: it is preserved for compatibility but has no local-grid
break metadata. The remaining TypeScript exports are interfaces/enums/constants
with no runtime calculation, Angular/RxJS/localStorage state, network job
orchestration, Highcharts/Canvas rendering, or DOM export; they are excluded
from the Python runtime. Matplotlib is the artifact renderer.

- [x] Inventory every exported computational TypeScript HR symbol and map it to
      a Python destination or an explicit browser/storage exclusion.
- [x] Port the unmapped computational functions into focused
      `algorithms/hrdiagram_py/` modules, preserving formulas and input/output
      shape; add `# PORTED:` provenance markers.
- [x] Add `KEPLER_ISOCHRONE_DIR` configuration and a focused Girardi-grid loader
      that selects exact legacy tracks and filter triples. Replace the live
      PARSEC fetch route; do not add a fallback download or a per-call
      `grid_path` parameter.
- [x] Add deterministic tests that construct minimal temporary
      `Girardi_*.npy` inputs from literal values. The default suite must not
      depend on the operator asset, a cluster fixture, or a live service.
- [x] Add port-parity and offline tests for every newly ported computation and
      a test that configured local-grid execution makes zero HTTP requests.

**Validation:** focused HR tests, `npm run typecheck`, the default Python suite,
and a configured-local-grid fit test. Any live Gaia/literature test stays
network-marked; the isochrone path itself has no live mode.

**Exit:** every non-browser HR computational algorithm has a documented Python
home, and a configured operator grid enables deterministic local isochrone
execution.

### Phase P6 — Explicit WCS search controls (BL-7) — Complete

**Intent:** make the wired plate solver usable when an observer deliberately
knows a bounded search region, without changing the parity default.

- [x] Extend the public `solve_astrometry` request and the internal settings
      seam with optional search radius and minimum/maximum pixel-scale bounds.
- [x] Preserve the current all-sky radius and 0.1–60 arcsec/px window whenever
      the caller supplies no overrides.
- [x] Validate all three explicit bounds at the tool boundary, report the
      effective search settings in the result diagnostics, and retain timeout,
      backend-attempt, fixture-protection, and atomic-write behavior.
- [x] Add deterministic settings-forwarding tests and a solver-data-gated test
      using an explicit scale window. Do not require solver indexes for the
      default suite.

**Validation:** focused WCS tests, `ANET_INDEX_PATH=... uv run pytest -m solver`
when the operator has indexes, the default Python suite, and `git diff --check`.

**Exit:** default calls retain extracted behavior; callers can explicitly request
a constrained, observable solve instead of waiting for an all-sky miss.

**P6 record (2026-09-12).** The seam is one frozen value object,
`algorithms.wcs.config.WcsSearchBounds(radius_deg, min_scale_arcsec,
max_scale_arcsec)`, passed as `solve_wcs(..., search_bounds=)`. Each field
left `None` keeps the value of the freshly built `WcsCalibrationSettings()`,
and the overrides are written to that object at the same point
`solve_settings` already writes `sip_order`/`crpix_center` — *before*
upstream's own `radius > 0` / `min_scale < max_scale` checks, so those cover
the overrides with no new validation in the algorithm. `WcsSearchBounds()` is
therefore the same call as passing nothing, and the default remains the
extracted all-sky 0.1–60 arcsec/px search; the algorithm tests pin both that
and the ATLAS branch's header-hint narrowing.

`tools.wcs.solve_astrometry` gained `search_radius_deg`, `min_scale_arcsec`
and `max_scale_arcsec`, validated at the boundary (`invalid_search_bounds`:
finite, positive, radius ≤ 180, and a single scale bound checked against the
other side's default so `min_scale_arcsec=70` alone is rejected) before the
FITS file is read or backend configuration is looked at. The result carries
`search` — radius, `all_sky`, scale window, the pointing centre the radius was
anchored on, `explicit` naming which bounds the caller set (by their tool
parameter names), and, when the ATLAS backend was attempted, `atlas_min` /
`atlas_max_scale_arcsec` — on every path that reached the backends, from
`WcsSolveMetadata.search_*`. The ATLAS pair exists because that backend's
blind path takes no radius at all and, absent explicit bounds, searches a
window narrowed around the header's pixel-scale estimate; reporting only the
requested window would describe an ATLAS-only miss as an already wide-open
search. Timeout,
attempted-backend reporting, the fixture guard and the atomic header write are
untouched; the existing tests for them still pass with the extra keyword.

Two decisions the checkboxes did not spell out:

1. **A bounded radius needs a pointing hint, and a frame without one is an
   error, not an all-sky search.** astrometry.net passes `--ra/--dec/--radius`
   only when the radius is below 180 and then reads the hint unconditionally,
   so a radius on a hint-less frame would have surfaced as a backend
   `TypeError` labelled `solver_failed`. `solve_wcs` now raises
   `SearchRadiusWithoutHint` before any backend runs and the tool reports it as
   `search_radius_without_hint` with `attempted_backends == []`. Widening
   silently was rejected because it re-creates exactly the wait P6 exists to
   avoid, behind a caller who asked for the opposite. The radius is anchored
   on the frame's own hint only — there is no explicit RA/Dec parameter; a
   frame that records no pointing cannot take a radius, and adding a centre
   parameter would be a separate decision.
2. **An explicit scale window bypasses the ATLAS branch's header-hint
   narrowing.** That branch halves/doubles the header's pixel-scale estimate;
   intersecting an explicit window with it hands ATLAS an inverted range
   precisely when the header scale is what the caller is overriding. Explicit
   bounds are used verbatim by both backends; the default narrowing is pinned
   by a test.

**Evidence.** On the development host, with `ANET_INDEX_PATH` naming the three
leaf directories under `/srv/agents/catalogs/astrometry` (`2MASS_ANET/4200`,
`TYCHO2/indices`, `UCAC5`, `os.pathsep`-joined — the root alone holds no index
files and `validate_index_dirs` rejects it), the new solver-data test solved
`m15_globular_open_000.fits` in **14 s** at `search_radius_deg=1,
min_scale_arcsec=0.4, max_scale_arcsec=0.8`: CRVAL (322.481, 12.195), 0.594
arcsec/px against the header's 0.586, parity accepted, `search` reporting the
bounded window. The parity default was then run against the same indexes for
comparison (`test_the_solver_runs_and_reports_its_outcome_either_way`): the
all-sky 0.1–60 arcsec/px search reached the **identical** solution in
**285 s** — so the 670 s miss in the BL-7 finding was the 4107–4119 set not
covering the field scale, and the bounds' contribution on a covered field is
a ~20× shorter run to the same answer, not a solve where there was none. One
nuance worth knowing when reading either log: `solve_field_glob` solves once
with the caller's bounds, then — M15 being a globular cluster in the field —
re-solves with the cluster core masked at its own field-sized radius (~0.08°)
around the first solution's CRVAL; the reported `search` is the primary
search, and the refinement passes ride on it.

**Review (2026-09-13).** A self-audit plus the code-review and security-review
passes over the branch produced four changes and one rejected suggestion.
(1) The boundary validator accepted a numeric string such as `"2"` (via
`float()`, as `timeout_s` does) but forwarded the *raw* object, so
`solve_wcs` would have crashed on `"2" < 180` and reported a bogus
`solver_failed`; `_validate_search_bounds` now returns the bounds as the
floats they were validated as. (2) `float(10**400)` raises `OverflowError`,
which neither `_finite_positive` nor the pre-existing `_timeout_error`
caught, and the agent engine has no guard around dispatch — both now catch
it. (3) The ATLAS window is reported separately, as above. (4) `explicit`
names the tool parameters (`search_radius_deg`), not the seam's field
(`radius_deg`). Rejected: intersecting an unspecified scale side with the
header-derived bound when the caller sets only one. It re-admits the header
the caller is contradicting — header 0.25″/px, truth 0.586, `min=0.4` gives
0.4–0.5 and misses where verbatim 0.4–60 finds it — so explicit bounds stay
verbatim and the schema text tells callers to pass both. The security review
found no HIGH or MEDIUM issue: the bounds reach `solve-field` only as
`str(float(...))` in a list argv, no path or file is derived from them, and
the fixture guard and atomic header write are untouched.

Default suite: 1779 passed, 42 skipped (was 1739 / 41; the new skip is the
solver-data test). The four LLM schema goldens were regenerated. The
`WcsSummary` docstring's reference to the deleted `algorithms.wcs.state` was
corrected in passing, since the model gained a field. P9 has since added the
ATLAS operator-data route. Not in scope and still open:
`tests/test_wcs_solution.py::test_blind_solve_recovers_the_known_plate_solution`
passes no `solver_settings`, so it can never reach a backend and always
self-skips — a pre-existing gap, left for a separate change.

### Phase P7 — Complete offline APASS replay (BL-4) — Complete

**Intent:** promote field-calibration replay from a selected-row comparison to a
complete offline catalog-selection replay.

**Why this phase is necessary:** the current `fit_data.csv` holds only the 35
catalog rows that already matched a detection. It cannot exercise candidate
normalization and matching over the full cone response or reproduce the
recorded `num_not_selected_by_field_cal: 263`. A full APASS response is the
missing input between catalog query and the existing zero-point calculation.

- [x] Record the APASS cone-search response for the NGC 5128 fixture once,
      store it as a compact versioned JSON or CSV fixture, and document query
      coordinates, radius, catalog release, retrieval date, columns, and source
      licence/provenance.
- [x] Extend `replay_catalog_sources` and the reference-comparison tool to use
      either the selected-row fixture or the full-response fixture explicitly;
      neither replay path may open a socket.
- [x] Assert catalog candidate count, selected/rejected counts, matched source
      identity/order, reference magnitudes, and the existing recorded solution.
- [x] Keep the existing selected-row replay as its smaller bit-exact regression
      case; label the full-response path as the end-to-end selection replay.

**Validation:** focused `fieldcal_reference` tests with network calls forbidden,
the default suite, and `git diff --check`.

**Exit:** Kepler reproduces the complete recorded local field-calibration path,
including catalog selection, without live VizieR access.

**P7 record (2026-09-13).** The fixture is two files next to the recorded
solve, `data/fieldcal/zp_solutions/ngc5128_b_002/apass_response.json` (132
rows, 30 KB) and `vsx_response.json` (12 rows, 6 KB): one JSON object each —
a provenance block (release, server, retrieval time, the exact column
request, row limit, licence and acknowledgement text), the `query`, the
columns with the dtypes and units VizieR returned, then one response row per
line. Both were retrieved once, on 2026-09-13, with the column request
`VizierCatalog._vizier()` builds — i.e. what the live tool path sends — as a
**10-arcmin cone** on the frame's WCS-footprint centre (RA 13.42413 h, Dec
−43.01841°), no cache rounding and no row cap. A cone rather than the box
the live path issues because the cone contains the 11.2′ × 10.9′ footprint
box with margin, so one recording serves whichever WCS defines the footprint
(the frame's header, or the TAN fit upstream's diagnostic built from the
CSV; both were run and select identically — pixel scales 0.6114660 and
0.6114665 arcsec). Float32 magnitude columns are stored as the exact float64
of each float32 and reloaded as float32, which is what keeps the replayed
reference magnitudes bit-exact against `fit_data.csv`'s `local_ref_mag`.
`recno` was requested but not returned — as live — so the candidates carry
no catalog id and are identified by position.

`tools.fieldcal_reference` gained `CATALOG_FIXTURES = ("selected_rows",
"full_response")`, a `fixture=` keyword on `replay_catalog_sources`
(default `selected_rows`, the existing bit-exact regression input; the
full response is rebuilt as an astropy table and mapped through the APASS
plugin's own `table_to_sources`, so candidate normalisation is the live
code, not a re-implementation), `replay_variable_sources` (the VSX rows),
`load_catalog_response` (the provenance, without the rows), and
**`replay_field_calibration(field)`** — the end-to-end selection replay: the
recorded Afterglow detections from `fit_data.csv` (298 with a finite,
non-zero `mag` and `flux`, upstream's own rule), the full APASS response and
the VSX rows through `perform_field_calibration(use_provided_photometry=True)`
with the bundled frame's header supplying WCS, epoch and filter and the
recorded run's own `strict_filter_parity`. Its `FieldCalReplay` reports
candidate / variable / detection counts, the matched and not-selected counts
on both sides, every match (detected id, candidate index, separation,
instrumental and reference magnitudes), the solve, the comparison, and
`selection_matches_recorded`. `tools.photometry.calibrate_zeropoint` gained
`catalog_fixture=` (requires `compare_to`; mutually exclusive with
`catalog_sources`; `conflicting_catalog_inputs`, `unknown_catalog_fixture`,
`catalog_fixture_requires_compare_to` and `catalog_fixture_missing` are
returned, never raised), which is how a model reaches an offline solve at
all — the registry schema never exposed `catalog_sources`, so the registered
tool always went to the network. Both are in the registry; the four LLM
schema goldens were regenerated.

**The one finding the plan did not anticipate: the recorded selection is
not reproducible from the APASS response alone.** With APASS only, the
replay matched **36** sources, not 35, and the zero point moved by 1.3e-10
(the extra star is Chauvenet-rejected — both solves keep 26 — and the
residual is `calc_solution`'s `sigma2` convergence carrying over from the
extra rejection round; a tolerance check would never have caught it, which
is why the counts are asserted). The 36th is detection SRC467 — a star Afterglow
detected twice, SRC335 being the same star 0.05″ away — against an APASS row
0.83″ from it. Upstream ran with the default `variable_check_tol = 5″`, and
VSX lists `Gaia DR3 6088704247666049024` (a YSO) 0.91″ from that APASS row,
so `_filter_variable_stars` removed it before matching and neither
detection could match. That is a real part of "the complete recorded local
field-calibration path", so the VSX response was recorded alongside the
APASS one and is applied on the `full_response` path; with it the replay
selects exactly the recorded 35, in the recorded order, with bit-exact
reference magnitudes and errors, and `calc_solution` returns
`21.147659857998637`, `rej_percent 25.714…`, matching
`production_calc_solution` to the bit. Both numbers are pinned:
`test_the_selection_replay_reproduces_the_recorded_run` and
`test_the_selection_replay_needs_the_recorded_vsx_rows` (36 without VSX,
with a `variable_sources_not_recorded` warning). On the selected-row path the
VSX check stays off, as before — every one of those rows is known to match.

Two smaller things worth knowing. (1) The extracted VizieR mapping stores
each band's uncertainty as the `np.float32` astroquery handed it and pydantic
warns on every `model_dump` of such a source (≈130 lines per replay); the
live path does the same, the resolved `ref_mag_error` is a Python float and
bit-exact, and the replay tests filter that one warning rather than alter
the algorithm. (2) The ECSV intermediate used while recording turned the
live table's *empty-string* cells (`n_max`, `f_min`) into masked ones, and
the VSX plugin hashes `row['n_max']`, which raises on a masked cell; the
fixture stores those as `""`, as VizieR returned them, and its provenance
says so.

**Audit (2026-09-13), before the PR.** The `/code-review high` run over
the branch died on a session rate limit before producing a finding, so the
review below is the author's own pass, checkbox by checkbox and against the
global constraints — worth re-running the independent review on the PR.
`algorithms/` has no diff; the kernels are untouched; every replay path runs
under a `socket.connect` guard; the fixture is the phase's own requested
artifact, not a generated one. Three things the audit changed. (1) A
hand-made `*_response.json` under `KEPLER_FIELDCAL_DATA_DIR` that did not
parse raised `TypeError` out of `np.dtype` inside a registered tool — the
P6 lesson again — so `_read_response` now validates the shape and rebuilds
the table itself (cheap), both the provenance loader and the source
builders report the same `fixture_missing` ("not present … or not
readable") for it, and a malformed provenance block (a non-dict `query`, a
numeric `vizier_table`) degrades to empty/stringified rather than raising
out of `dict()` or pydantic; pinned. (2) The from-pixels `full_response` path was asserted to reach the answer
but not to *apply* the VSX filter; a spy on `perform_field_calibration` now
pins `(variable_sources, variable_check_tol, candidates)` as `(12 rows, 5,
132)` for `full_response` and `(None, 0, 35)` for `selected_rows` — the
former since revised to `(5, 5, 45)` by the review below. (3) The
fixtures carry `format_version: 1`, and `tests/README.md` no longer claims
the VSX/APASS row mappers are never executed against real provider rows —
they now are; Landolt and USNO's still are not.

**Evidence.** From pixels, `calibrate_zeropoint(frame, catalog_fixture=...)`
lands on the identical zero point for both fixtures, 21.142973 (−4.7 mmag
from the recorded solve — re-measured photometry, inside the existing 0.1
bound), so the SEP extraction + selection over the on-frame candidates
chooses the same calibration set as the 35 known-good rows. `data/README.md` documents
the two files; `README.md`, `docs/tool-architecture.md` and `CLAUDE.md` name
the new switches. Default suite: 1801 passed, 42 skipped, 139 warnings (was 1779 / 42 / 139);
the new tests run under a `socket.connect` guard. Not in scope and still
open: the three NGC 5286 B solves have neither a frame nor a recorded
response, so `replay_field_calibration` returns `fixture_missing` +
`frame_not_bundled` for them (P8 territory); and `test_query_live.py`
remains the only exercise of the *live* selection path.

**Review (2026-09-13, after the rate-limit reset).** `/code-review high`
over PR #64 produced twelve findings; eleven were acted on and one declined.
The substantive one: the replay handed `perform_field_calibration` the
*whole* 10′ cone, while the live path (`algorithms.query.runner`, WCS mode)
clips a response to the detector first — so the fixture's own "reproduces
the box, the clipping and the matching" claim was not honoured, and the
reported counts were cone counts (132 candidates, 97 not selected) rather
than what a live solve sees. Verified before changing anything: clipping
keeps 45 of the 132 APASS rows and 5 of the 12 VSX rows, and the selection
and solution are **identical** either way. Both replays now run
`clip_sources_to_wcs` before the solve, and `FieldCalReplay` reports the
cone (`num_catalog_rows`, `num_variable_rows`) beside the candidates the
solve was handed (`num_catalog_candidates` 45, `num_variable_sources` 5,
`num_catalog_not_selected` 10). The rest, in order of weight: the reader's
gate caught only `TypeError`/`ValueError`, while numpy raises
`OverflowError` for an out-of-range integer cell — so the hardening the
audit claimed was incomplete; the gate now catches whatever the rebuild
rejects, non-scalar cells included, and the table is built once and handed
on rather than rebuilt per caller. `replay_field_calibration` took the
catalog name from `fit_summary.json` for the settings but the response
loader hard-coded APASS; one name now drives the file, the plugin mapping
and the settings (`replay_catalog_sources(..., catalog=)`), and a
present-but-unusable response is `fixture_empty`, not "not present".
Matched detections were recovered by a position dict that collapsed exact
duplicates onto the last row — `fit_data.csv` has one such pair
(SRC317/SRC319) — and the candidate by parsing `fieldcal_source_N`; matches
come in detection order and a kd-tree query on identical points returns the
lowest index, so attribution is now an ordered walk (`_detection_indices`,
unit-pinned) and the candidate is looked up by the id it was handed in
with. `calibrate_zeropoint` dropped its collected warnings on every error
return; they ride on all of them now. The two from-pixels tests gained the
`slow` marker the suite defines for them (and the pre-existing sibling that
lacked it). The comparison is built from the already-loaded reference rather
than re-parsing `fit_data.csv`. **Declined:** splitting the documentation
hunks into a separate PR under "keep PRs narrow" — every doc line here
describes the behaviour this PR adds, so landing them apart would leave
`dev` describing a switch that does not exist (or not describing one that
does); the rule is for unrelated documentation riding along, and #59/#63
landed the same way. Default suite after the review: 1806 passed, 42 skipped, 139 warnings.

### Phase P8 — Restore NGC 5286 B-frame end-to-end evidence — Complete

**Intent:** make all four recorded zero-point cases executable from pixels,
rather than validating three NGC 5286 B cases only at the solution level.

**Maintainer asset gate:** recover `ngc5286_b_000.fits`, `_001.fits`, and
`_002.fits`, verify their provenance against the recorded field-calibration
references, and add them through Git LFS. Do not expand broader FITS coverage
in this phase.

- [x] Add Git LFS tracking for only the three recovered B frames and document
      the expected LFS checkout requirement.
- [x] Extend frame provenance and optical discovery tests to identify them.
- [x] Run the existing real-pixel calibration path against each B frame and
      compare to the recorded reference at the established tolerance.

**Validation:** LFS checkout test, focused field-calibration tests, default
suite, and a documented LFS-free skip for contributors without the assets.

**Exit:** all four recorded zero-point references have an end-to-end local
pixel path.

**P8 record (2026-09-16).** The frames were recovered from
`skynet-data/pipeline_data/test_subjects/optical/globulars/` as
`ngc5286_globular_b_{000,001,002}.fits`, which is the name
`tools/fieldcal_reference.py` had already reserved for them, and the mapping to
the recorded solves is **index-for-index** — unlike the NGC 5128 pair, where
`ngc5128_b_002` is `ngc5128_galaxy_b_001.fits`.

*The pairing was established, not assumed*, and two independent routes agree.
Header identity is not enough: `_000` and `_002` are the same object, band,
geometry, telescope, exposure and OBSID, differing only in `DATE-OBS`.
Re-extracting sources and matching them against each solve's recorded `x`,`y`
separates them cleanly — the right frame reproduces its own recorded detections
at a **median nearest-neighbour separation of 0.000 px** (1225/945/1317 of the
recorded rows inside 0.5 px, against measured counts of 1231/947/1318 versus
recorded 1228/949/1319), while every cross-pairing lands at 24–37%. Separately,
`data/frame_provenance.json` — built from upstream's own `reorganize.py`, and
predating this phase — maps the three stems to exactly the `input_fits_name`
each `fit_summary.json` reports, browser deduplication suffixes (`-2 (1)`,
`(2) (1)`) included. Its recorded `_collisions` entry is also resolved: the
bundled `_000` is OBSID 12158933, the solved exposure, not the unrelated
12158952 one.

*One apparent mismatch is not one.* Two of the three report `SECPIX = 0.595`
where all three references record `pixel_scale_arcsec = 0.398353`. Afterglow
aligned every exposure onto one Prompt6 grid, so the **WCS** scale is 0.3984″/px
throughout while `SECPIX` still names the instrument that took the frame. The
WCS-derived scale matches the recorded value to eight digits on all three.

**Two things the plan did not anticipate, both load-bearing.**

*The recorded runs do not share an instrumental-magnitude scale.* Both families
record `mag = -2.5 log10(flux / exposure) + zero`, but the older NGC 5286
recorder put `zero` at **exactly 20.0** where `ngc5128_b_002` puts it at 0.0 —
which is also what `algorithms.fieldcal` measures on today. Nothing in
`fit_summary.json` names the constant, so an unconverted comparison misses by a
clean 20 magnitudes: the same size and shape as the Afterglow base-20 trap
`_compare_to_reference` already guards. It is now declared per field in
`_INSTRUMENTAL_ZERO_BY_FIELD`, exposed as
`ZeropointReference.instrumental_zero_mag`, applied by `calibrate_zeropoint`
before comparing (the returned `zero_point` stays as measured), and
**recomputed** from the recorded rows and each frame's `EXPTIME` by
`test_recorded_instrumental_zero_is_the_declared_one`, so a fixture re-recorded
on a third scale fails rather than shifting a comparison quietly.

*The third checkbox needed code, not just assets.* `replay_catalog_sources`
returned `[]` for all three fields and `calibrate_zeropoint` failed with
`field_calibration_failed: Missing catalog sources`, because
`_selected_row_sources` reads the newer `local_catalog_*` columns. The NGC 5286
`fit_data.csv` is the older schema: `ra`/`dec`/`ref_mag`/`catalog_name`, with
coordinates in **degrees** where the newer format is already in hours. Those
`ra`/`dec` are also the *detection's* position — verified, they round-trip from
`x`,`y` through the frame's WCS at 0.0000″ — not the catalog row's, which the
older recorder never wrote down; it kept only `match_distance_arcsec` (median
0.89″, max 2.04″) and wrote one identifier into both `source_id` and
`catalog_id`. `_legacy_selected_row` handles that format and documents why the
approximation is confined to what `"selected_rows"` already declares out of
scope: every row it yields is one the recorded run matched, so re-matching
cannot choose a different partner.

**Results.** All three now run extract → measure → match → resolve → solve from
pixels and land inside the 0.1-magnitude bound the NGC 5128 end-to-end cases
already use:

| Field | Measured (Kepler scale) | Recorded + 20.0 | Δ |
| --- | --- | --- | --- |
| `ngc5286_b_000` | 21.771578 | 21.821497 | −0.049919 |
| `ngc5286_b_001` | 22.569106 | 22.602478 | −0.033372 |
| `ngc5286_b_002` | 20.772267 | 20.830857 | −0.058590 |

Loose, deliberately, and for the same reason as NGC 5128: the photometry is
re-measured from pixels rather than replayed, so these are real solves, not
bit-exact ones. `solve_zeropoint_from_reference` remains the bit-exact check and
is untouched — `compare_zeropoint_to_reference`'s contract did not change, so
its input is still on the recorded scale.

**LFS scope and the no-LFS path.** `.gitattributes` names the three frames **by
path**, never `data/optical/*.fits`: a wildcard would convert the other 39
frames, whose content is already in history, buying nothing and breaking every
existing clone. `lfs: true` is set on the `python-tests` job only — the other
two read no pixels. Without the objects nothing breaks and nothing silently
passes: `tools.config.is_lfs_pointer` recognises a stub, `list_optical_frames`
drops it behind a `frames_not_checked_out` warning, `resolve_optical_frame` and
`_frame_path` return `frame_not_checked_out`, and `tests/conftest.py::_require`
plus the `lfs_frames` fixture skip the pixel and whole-tree tests with the
`git lfs pull` line.

*Why they are 31 MB each.* Each file carries **four** Afterglow-aligned
exposures, of which every Kepler code path reads the primary — they are the only
multi-HDU frames in `data/optical/`. Shipping the primary alone would have been
7.74 MB apiece, under the 9 MB plain-git cut-off and no LFS at all; the
maintainer chose to preserve all four exposures.

*Counts that moved:* 39 frames → 42, B 2 → 5, and the truncation-warning text.
`test_the_selection_replay_reports_a_field_it_cannot_run` now asserts
`frame_not_bundled` is **absent** — the selection replay still cannot run on
these three, but only for the remaining reason, the missing recorded cone
response (BL-4 / P7 recorded one for NGC 5128 only).

### Phase P9 — Validate the ATLAS WCS backend with operator data

**Intent:** cover the ATLAS branch without vendoring the UCAC4/UCAC5 catalogue.

**Operator asset gate:** provide a local UCAC4 or UCAC5 tree and set
`ATLAS_CATALOG_ROOT` and `ATLAS_CATALOG` according to the documented layout.

- [x] Document the supported catalogue layout, environment variables, expected
      disk cost, and a preflight command that confirms the backend can load it
      in `README.md`'s WCS configuration section. The supplied UCAC5 tree is
      an external 5.3 GB dependency at `/srv/agents/catalogs/ATLAS/UCAC5`.
- [x] Add the opt-in `solver_data`
      `test_atlas_looks_up_operator_catalog_with_an_explicit_scale_window`.
      It self-skips with setup instructions when `ATLAS_CATALOG_ROOT` or a
      supported `ATLAS_CATALOG` is absent, exercises the real UCAC lookup, and
      sends the explicit 0.58--0.59 arcsec/px window to ATLAS.
- [x] Assert ATLAS's recorded blind attempt, bounded scale window, source
      count, non-empty operator lookup, and normalized `no_sources` acceptance
      outcome. The test uses an intentionally blank image after the real
      catalog lookup, so it proves the backend dependency seam without making
      the bulk catalogue a default or CI dependency and without promising
      blind-solver convergence.

**Validation:** the operator-run `solver_data` test passes against the supplied
UCAC5 tree; the default suite keeps it self-skipped when UCAC data is absent.

**Exit:** both WCS backends have a documented, executable validation route.

## 6. Historical TypeScript runtime discussion (superseded)

The following research record explains the original gap. It is not an active
plan: P4 settles the variable-star Python port, and P5 settles the remaining HR
computational port and local-grid operation. In particular, the earlier
Node-subprocess alternative and the proposed cluster registry are rejected.

| | HR diagram | Variable star |
|---|---|---|
| Runtime | **now exists** on `dev` — `algorithms/hrdiagram_py/` plus seven registered tools | none — nothing executes the TypeScript |
| Input data | none in `data/` | none in `data/` |
| Catalog access | solvable — `algorithms/query` already queries VizieR for Gaia, 2MASS, APASS, WISE and MWSC | solvable — VizieR, ASAS-SN, ZTF |
| Model grids | operator-provided local Girardi grid; Kepler does not fetch or bundle it | not applicable |

**The runtime decision, now settled for BL-10.** `CLAUDE.md` is explicit that a
Python port is not a general licence: `algorithms/pulsar/` is the one instance,
and `docs/extraction.md` (Pulsar Sonification §5) records why it was allowed
there and why it is not general. That port was justified because the upstream
sonifier was welded to browser APIs and could not run headless. The variable-star
code is not — it is plain arithmetic on plain arrays — so the precedent does not
extend on its own. The choice between a Node subprocess seam (mirroring the
`solve-field` subprocess pattern `algorithms/wcs/` already uses, at the cost of
adding Node to the runtime dependency set when `package.json` has no build step),
a Python port marked `# PORTED:` with its divergences enumerated, and leaving it
as typechecked source was a real architectural decision. The maintainer has
chosen the Python port defined in P4. For the HR diagram, P5 extends the Python
port already present on `dev`.

---

## 7. Historical constraints and scope boundaries

Everything below surfaced during the investigation. P5–P9 now give the relevant
items a planned resolution with explicit asset gates. The broader FITS expansion
and independent algorithm-correctness remediation remain outside this rollout.
This historical analysis remains for provenance; it does not supersede the
approved phases above.

### 7.1 Resolved architectural choices

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
**Phase 4 therefore bounded the run with a timeout and narrowed nothing.** P6
settled the follow-up: callers may explicitly opt in to a search radius and
minimum/maximum pixel-scale bounds; omitted controls retain the all-sky defaults.

**The TypeScript runtime for the variable-star tools (BL-10).** P4 established a
Python-only, exact-parity port with artifact output and no browser/UI rendering.

**Whether Kepler carries, fetches, or requires an isochrone grid.** P5 requires a
maintainer-supplied local Girardi grid and replaces live fetching; it does not add
a public cluster registry. M67 remains test-only.

### 7.2 Asset-gated inputs

**Cluster photometry and variable-star light curves.** There is none in
`data/`. P5 is specifically gated on the maintainer supplying a local Girardi
grid, not on recording a cluster fixture or introducing a public lookup registry.

**UCAC4/UCAC5 catalog data.** This was absent when the investigation began, so
the ATLAS triangle solver was unreachable and no baseline test exercised its
pixel-scale narrowing. P9 now validates its operator-owned catalog reader,
bounded blind-attempt diagnostics, and source-lookup path against a supplied
local UCAC tree; full blind-triangle convergence remains intentionally outside
that bounded validation route.

**The B-band frames behind three of the four recorded zero-point solves.** Three
of them — `ngc5286_b_000`, `_001` and `_002` — describe NGC 5286 exposures in B;
the only NGC 5286 frame bundled is `ngc5286_globular_v_000.fits`, a V frame. So
all four solves are checked bit-exactly at the solution level, but **only NGC
5128 B can be driven end-to-end from pixels**. Three quarters of the recorded
ground truth is reachable as numbers and not as a pipeline. P8 recovers only
these three B frames through Git LFS.

### 7.3 Missing recorded artifacts

**The unmatched catalog rows (BL-4).** `fit_data.csv` recorded the 35 APASS rows
that *matched* a detection. The cone-search rows that did not match were never
written down, so the recorded count of sources not selected by field calibration
(`num_not_selected_by_field_cal: 263`) is unreproducible from the shipped
fixture, and the replay validates photometry → matching → reference magnitude →
solve but not catalog selection. Closing this needs a live VizieR cone search
re-recorded as a new fixture — a network operation producing a new artifact,
against two of this document's own constraints. P7 explicitly records the full
cone response so catalog selection, including the 263 unmatched rows, becomes
reproducible. **Done (P7 record below):** the cone was recorded once, and the
VSX rows with it, because the recorded selection turned out to depend on both.

**The 36 frames above the 9 MB cut-off.** The Afterglow web table covers 73
subjects (~1.5 GB); `data/optical/` carries the 37 under 9 MB plus the two
OCL frames. Widening coverage means adding large incompressible binaries to plain
git, permanently. This rollout does not widen that set: P8 uses Git LFS only for
the three NGC 5286 B frames above.

### 7.4 Real problems, different topic

Tracked elsewhere; this document must not quietly absorb them.

**`docs/analysis/pulsar-pipeline-review.md` — open pulsar tool bugs.** Enumerated
under P1 above, where the constraint bites. All are tool-correctness bugs,
not local-data links.

**`docs/analysis/algorithm-remediation-plan.md`'s 109 findings and 7 blockers.**
Algorithm correctness, untouched here by design. The extraction contract holds
throughout: no phase moves a numeric expression.

### 7.5 What "all phases complete" will not mean

**Not full Skynet parity.** This work validates the *tool seam* — that a tool can
find local data, run the real code path against it, and return a number
comparable to recorded ground truth. It does not validate that Kepler's whole
pipeline reproduces Skynet's.

**Not a guaranteed plate solve.** P6 made deliberate search narrowing available
without changing the default all-sky behavior. P9 validates ATLAS only when an
operator supplies UCAC data; neither promise guarantees convergence on every
frame.

---

## 8. References

* [`../tool-architecture.md`](../tool-architecture.md) — the master architecture
  this work sits under, and the document Phase S6 amends to define a tool call as
  the unit of execution.
* [`../extraction.md`](../extraction.md) — per-domain provenance; the WCS, HR
  Diagram, and Catalogs sections are the ones this work touches.
* [`../pulsar-tool-pipeline.md`](../pulsar-tool-pipeline.md) — the Stage 0
  pattern the curated-period registry generalizes, and the document P1 keeps in
  step.
* [`../analysis/pulsar-pipeline-review.md`](../analysis/pulsar-pipeline-review.md)
  — the open pulsar tool bugs P1 must leave alone.
* [`../analysis/algorithm-remediation-plan.md`](../analysis/algorithm-remediation-plan.md)
  — algorithm correctness, deliberately out of scope.
* `data/README.md` — the zero-point convention warning behind BL-5, and the
  Git LFS note behind section 7.3.
* The TUI track (`docs/tool-architecture.md` 10.2) — unblocked by the stateless rollout but
  separately scoped; it owns the photometry-pipeline rename that must operate on
  this document's result.
* [model-backends.md](model-backends.md) — owner of the system-prompt move that
  this document's P1 must account for.
