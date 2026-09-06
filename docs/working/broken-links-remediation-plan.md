# Broken Links Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

Date: 2026-09-04
Status: proposed
Scope: the seam between the public `tools/` surface and the local data in
`test_data/` — not algorithm correctness (that is
[`algorithm-remediation-plan.md`](../analysis/algorithm-remediation-plan.md)) and not file
organization (that is [`tool-architecture.md`](../tool-architecture.md)).

**Goal:** Make every tool that *should* run against the data bundled in this
repository actually run against it, and make the recorded ground truth in
`test_data/afterglow/` and `test_data/fieldcal/` reachable as a tool result
rather than only as a pytest fixture.

**Architecture:** `tools/pulsar.py` already solves this problem correctly for
radio scans: a Stage 0 discovery pair (`list_pulsar_scans` /
`resolve_pulsar_scan`) backed by an env-overridable data directory, returning
typed models that carry `ToolError`s instead of raising. Every fix below
generalizes that pattern to the other data classes this repository ships —
optical frames, recorded zero-point solves, and the Afterglow cross-check —
and then registers the result so an agent loop can reach it.

**Tech Stack:** Python 3.12, Pydantic v2, astropy 8.0.1, numpy 2.4.6,
sep 1.4.1, numba 0.66.0, pytest. No new dependencies.

**Spec:** this document. §1 is the evidence, §2 onward is the plan; there is no
separate spec to read.

> **Branch basis — read §1.0 first.** The investigation was carried out against
> `main` (`c8f46a7`) plus `agent/model-backends`. `origin/dev` (`db2f7bd`) is
> 19 commits ahead and **already fixes three of the twelve findings** — it
> carries `algorithms/hrdiagram_py/`, `tools/hr_diagram.py`,
> `tools/photometry.py` and `tools/radio_sources.py`, none of which exist on
> `main`. Every finding below was re-verified against `dev` before this
> document was committed; §1.0 records the per-finding outcome, and the
> severity table carries the corrected status. **Tasks 1, 4 and 5 and the whole
> of §9 were written against `main` and are wrong or redundant in part.** They
> are kept rather than deleted because their tests and evidence remain useful,
> but §1.0 says exactly which parts to skip.

---

## Global Constraints

Copied from `CLAUDE.md` and `docs/tool-architecture.md`; every task below
inherits them.

- **The extraction contract holds.** `algorithms/` is byte-preserved from
  Skynet/Astromancer. No task in this plan edits algorithm numerics. Where a
  fix touches `algorithms/`, it adds a caller-facing seam, never a changed
  expression. Every newly severed dependency gets a `# EXTRACTED: was <symbol>`
  marker.
- **Known bugs stay pinned.** Documented parity quirks are deliberate. If a
  task's test reveals one, pin it in the test and say so in capitals.
- **Default checks stay offline and deterministic.** Nothing added here opens
  a socket unless marked `network`, which also requires `KEPLER_TEST_NETWORK=1`.
- **No generated files in the repo.** Artifacts go to `KEPLER_ARTIFACT_DIR`
  (default `artifacts/`, gitignored). Do not add FITS, plots, or caches to
  `test_data/`; the one new fixture this plan adds is a ~4 KB JSON map.
- **Dependencies are pinned with `==` in `pyproject.toml`.** Adding one means
  editing the pin and re-running `uv lock`. No task here needs one.
- **No linter or formatter is configured.** Match the surrounding file's style.
- **Target `dev`, not `main`.** Keep PRs narrow; separate documentation,
  workflow, dependency, and behavior changes.
- **Result contract:** public tools return typed models carrying
  `warnings: list[ToolWarning]` and `errors: list[ToolError]`. Failures are
  returned, not raised.

---

## 1. Findings

Twelve broken links. Each was verified against the working tree at `940efbf`
with the commands shown; none is inferred from documentation.

### Severity summary

Status is **as verified on `origin/dev` (`db2f7bd`)**, which is what the work
would actually land on. Findings marked *fixed on dev* were real on `main`; the
evidence is kept because it explains what the dev-side code is for.

| # | Broken link | Status on `dev` | Severity |
|---|---|---|---|
| BL-1 | `describe_image_wcs` raises `TypeError` on 38 of 39 bundled frames | **fixed on dev** — 39/39 pass | — |
| BL-2 | The agent registry omits the local no-network tools | **stands, narrowed** — 36 tools registered, but `astrometry`, `calibration`, `catalogs`, `workspace` still absent | **High** |
| BL-3 | No optical-frame lookup registry (the user's HR-diagram example) | **mostly fixed on dev** — `list_photometry_targets()` exists and is registered; no resolve-by-name, no header metadata | Medium |
| BL-4 | No tool reads `test_data/afterglow/` or `test_data/fieldcal/` | **stands** | **High** |
| BL-5 | `ZeropointSolution.zero_point_corr` holds an absolute zero point | **stands** | **High** |
| BL-6 | `ocl_filter_report.json` no longer joins to any bundled frame | **stands** — a pytest fixture reads it, still keyed by upstream filename | Medium |
| BL-7 | `solve_wcs` unreachable from tools; its index data present but unconfigured | **stands** | Medium |
| BL-8 | Curated pulsar periods unreachable from the tool layer | **stands** | Medium |
| BL-9 | HR diagram: no runtime, no data, one external dependency | **mostly fixed on dev** — see §1.0; the remaining gap is *offline* operation, not capability | Medium |
| BL-10 | Variable-star light curve / periodogram: TypeScript only, no data | **stands** | Medium (deferred) |
| BL-11 | Archive downloads dead-end — no tool consumes a downloaded FITS path | **stands** | Medium |
| BL-12 | `npm run typecheck` cannot run from a fresh checkout | **stands** — `node_modules/` absent | Low |

### 1.0 Status against `dev`, finding by finding

Re-verified in a `dev` checkout, not inferred from the commit log.

**BL-1 — fixed on dev, by the same edit this plan proposes.**
`tools/astrometry.py:100-103` now materializes the proxy before slicing, with a
comment naming the `StrListProxy` cause. A sweep over all 39 frames returns
`ok 39  fail 0`. **Skip Task 1's fix.** Its parametrized test file
(`tests/test_astrometry_tool.py`) is still worth adding — no test imports
`tools.astrometry` on `dev` either, which is how the bug reached `main` in the
first place.

**BL-3 — mostly fixed on dev.** `tools/photometry.py` provides
`list_photometry_targets()` and `run_photometry_on_target()`, both registered.
The listing returns a `PhotometryTargetLibrary` of category-grouped stems
(`{'nebula': ['carina_nebula_v_000', …], 'galaxy': […]}`). What Task 4 still
adds over it: resolution by object name with the pulsar chain's ambiguity
contract (there is no `resolve_photometry_target`), per-frame header metadata
(filter, telescope, WCS presence, field centre), filter narrowing, and a
`KEPLER_*_DATA_DIR` override. **Rescope Task 4** from "build the registry" to
"extend the existing one"; its model and tests carry over, its `_summary()`
header reader is the substance.

**BL-9 — mostly fixed on dev, and my §9 deferral is wrong.**
`algorithms/hrdiagram_py/` exists (`hrfit.py`, `isochrones.py`, `literature.py`,
`matching.py`, `membership.py`, `observations.py`) with seven registered tools
in `tools/hr_diagram.py`, including a full
`run_full_hr_pipeline_from_catalog(cluster_name)`. The isochrone dependency I
called "the one item wiring cannot fix" **was fixed**:
`algorithms/hrdiagram_py/isochrones.py::fetch_parsec_isochrone_grid` pulls
PARSEC grids from the CMD service at `stev.oapd.inaf.it` and caches them under
`isochrone_cache/`.

That resolves the capability question and leaves a narrower one that is
squarely this plan's topic: **the HR-diagram chain cannot run offline.** The
isochrone grid is a live HTTP fetch, Gaia photometry is a live VizieR query, and
there is no cluster fixture anywhere in `test_data/` — so nothing in the chain
has a bundled-data path, and the repository's "default checks stay deterministic
and bounded" constraint means none of it can be covered by the default suite.
The fix is a recorded fixture (one cluster's Gaia rows plus one PARSEC grid),
not a runtime or a data-licensing decision. **§9 should be read as superseded by
this paragraph;** its "recommended shape" list is still right about needing a
cluster fixture, and wrong about everything upstream of that being unbuilt.

**BL-2 — stands, narrowed.** `dev` registers 36 tools (up from 23), including
the new photometry, HR-diagram and radio surfaces. Still unregistered:
`tools.astrometry`, `tools.calibration`, `tools.catalogs`, `tools.workspace` —
so `describe_image_wcs` is *fixed but still unreachable from an agent loop*, and
the zero-point solver and catalog-band helpers remain library-only. Task 3
applies as written.

**BL-4, BL-5, BL-6, BL-7, BL-8, BL-10, BL-11, BL-12 — stand as written.**
Re-verified on `dev`: no `tools/` module reads `test_data/afterglow/` or
`test_data/fieldcal/`; `tools/models.py:151` still declares `zero_point_corr`;
`ocl_filter_report.json` is read only by `tests/conftest.py:332` and still keyed
by upstream filename; there is no `solve_astrometry`; `PulsarScan` carries no
curated period; `list_photometry_targets` searches `test_data/optical/` only, so
`FITS_DOWNLOAD_DIR` remains a dead end; `node_modules/` is absent.

One consequence worth stating plainly: **BL-4 is the largest surviving finding,
and it is the one the request that prompted this document named explicitly.**
`dev` added a photometry tool, an HR-diagram pipeline and a radio pipeline
without adding any path from a tool to the recorded ground truth those pipelines
could be checked against.

---

### BL-1 — `describe_image_wcs` raises on almost every bundled frame

`tools/astrometry.py:100` does:

```python
ctype = tuple(str(value) for value in wcs.wcs.ctype[:2])
```

`wcs.wcs.ctype` is an `astropy.wcs.StrListProxy`, which does not implement
slicing under astropy 8.0.1:

```
TypeError: sequence index must be integer, not 'slice'
```

Swept over the whole fixture directory:

```
ok 1   fail 38
TypeError: sequence index must be integer, not 'slice' -> 38 frames
astropy 8.0.1
```

The single "ok" is `m15_globular_open_000.fits`, which returns early at the
`no_celestial_wcs` branch because it carries no WCS keywords at all. **Every
frame that actually has a WCS raises.** This is the only local FITS tool in
`tools/`, so the local image surface is not merely thin — it is nonfunctional.

Nothing caught it because **no test imports `tools.astrometry`**. The tool-layer
importers under `tests/` are `test_pulsar_plots.py`, `conftest.py`,
`test_runner_session.py`, `test_photometry_tool_smoke.py` and
`test_pulsar_sonification.py`; `tools.astrometry`, `tools.calibration`,
`tools.catalogs` and `tools.workspace` appear in none of them.
`tests/test_wcs_headers.py` covers `algorithms.wcs`, not the wrapper.

### BL-2 — the agent registry exposes no local-data tool except pulsar

`tools/registry.py` maps 23 tools drawn from 10 modules:

```
modules with registered tools:
  tools.ads, tools.atnf, tools.casda, tools.mast, tools.mpc,
  tools.ned, tools.pulsar, tools.resolve, tools.simbad, tools.vizier
unregistered:
  tools.astrometry, tools.calibration, tools.catalogs, tools.workspace, …
```

Sixteen of the 23 are remote database queries; the remaining seven are the
pulsar chain. So an agent driven by `tools/runner.py` can query eight archives
and sonify a pulsar, but **cannot open, measure, calibrate, or even describe
any of the 39 FITS frames this repository ships**, and cannot list an artifact
it produced.

`docs/tool-architecture.md` §2 names `describe_image_wcs`,
`list_photometric_catalogs`, `resolve_reference_band`,
`solve_zeropoint_from_measurements`, `list_artifacts` and `describe_artifact`
as "the first local, no-network tools". None of them is registered.

### BL-3 — no optical-frame lookup registry

This is the user's HR-diagram example, generalized. The pulsar chain has a
Stage 0 (`tools/pulsar.py:992-1078`):

- `list_pulsar_scans(directory=None)` → `PulsarScanList`
- `resolve_pulsar_scan(name, directory=None)` → `PulsarScan | PulsarScanList`
- backed by `KEPLER_PULSAR_DATA_DIR`, defaulting to `test_data/pulsar/`
- name matching normalizes punctuation (`PSR B0329+54` ≡ `psr_b0329_54`)
- ambiguity and misses return `ToolError`s with the candidate list, never raise

The optical equivalent exists, but only inside a CLI script:
`tools/claude_photometry_haiku_tool.py:148` `resolve_fits_path()` and `:190`
`list_bundled_targets()`. It is not registered, not importable as a documented
tool, returns a bare `dict[str, list[str]]`, **raises `FileNotFoundError`
instead of returning a `ToolError`**, has no environment override, and reports
no header metadata — so a caller cannot ask "which frames are in B?" or "which
frames have a WCS?" without opening all 39 files.

`docs/pulsar-tool-pipeline.md:270` already names this precedent in the other
direction, citing the photometry script as the model the pulsar tools should
follow. Both halves should now converge on one pattern.

### BL-4 — no tool reads `test_data/afterglow/` or `test_data/fieldcal/`

Grepping `test_data` across `tools/` and `algorithms/` returns hits in exactly
two files: `tools/pulsar.py` (the scan directory) and
`tools/claude_photometry_haiku_tool.py` (the frame search roots). **Nothing in
the tool layer reads the recorded ground truth.**

What is sitting there unused:

| Fixture | Contents |
|---|---|
| `test_data/fieldcal/zp_solutions/<field>/fit_data.csv` | every photometered source, with `used_for_calibration` marking the exact rows handed to `calc_solution` |
| `…/fit_summary.json` | the five numbers `calc_solution` returned, plus Afterglow's own result and the declared tolerance |
| `test_data/afterglow/fieldcal/ngc_5128_test_vals.json` | the complete Afterglow field-calibration API response |
| `test_data/afterglow/photometry/afterglow_photometry_ngc5128_b.csv` | 303 sources with `zero_point`, `zero_point_correction`, `calibrated_zero_point` |
| `test_data/afterglow/afterglow_web_values_master.csv` | published zero points for 73 subjects |

The capability is there; only the tool in front of it is missing. Driving
`solve_zeropoint_from_measurements` by hand from the recorded rows reproduces
the recorded solve exactly:

```
zp: 21.147659857998637   n: 35   err: []
recorded (fit_summary.json, +20 base): 21.147659857998637
afterglow  (20.0 + 1.1474792352683736): 21.14747923526837
```

Two things stand between that and a tool call:

1. `solve_zeropoint_from_measurements(measurements, catalog_sources)` takes
   already-measured sources. Nothing produces them from a local frame.
2. The one path that does produce them —
   `claude_photometry_haiku_tool.compute_field_cal_zero_point` at
   `tools/claude_photometry_haiku_tool.py:69` — queries VizieR over the
   network, and **field calibration is on by default** (the flag is
   `--no-field-cal`). Offline, the default bundled-target run prints a warning
   to stderr and silently falls back to instrumental magnitudes — for
   `ngc5128_galaxy_b_001.fits`, whose true zero point is recorded three
   different ways in this repository.

An offline replay is feasible: `fit_data.csv` carries the matched catalog rows.

```
local_catalog_name    non-empty   35/304
local_catalog_ra      non-empty   35/304
local_catalog_dec     non-empty   35/304
local_ref_mag         non-empty   35/304
local_ref_mag_error   non-empty   32/304
sample: {'local_catalog_name': 'APASS',
         'local_catalog_ra': '13.422852431038365',
         'local_catalog_dec': '-42.944252137182126',
         'local_ref_mag': '16.590999603271484',
         'local_ref_mag_error': '0.16099999845027924'}
```

**Limitation to state up front:** only the 35 *matched* rows were recorded, not
the full cone-search response. A replay provider therefore validates
photometry → matching → ref-mag resolution → solve, but cannot reproduce the
`num_not_selected_by_field_cal: 263` statistic, because the catalog rows that
failed to match were never written down. Say so in the tool's docstring and in
the test; do not let a partial replay be mistaken for a full one.

Note also that `tests/test_fieldcal_pipeline.py:507`
(`test_perform_field_calibration_end_to_end_on_a_real_frame`) **synthesizes**
catalog sources at detected positions with a known offset. That is a good test
of the wiring, but it is a self-consistency check: it recovers a constant it
planted. The recorded APASS rows make a real cross-implementation check
possible and are not currently used for one.

### BL-5 — `zero_point_corr` holds an absolute zero point

`tools/models.py:137` names the field `zero_point_corr`. It is populated at
`tools/calibration.py:118` from `calc_solution`'s `m0`, which is the
**absolute** zero point:

```
tool ZeropointSolution.zero_point_corr : 21.147659857998637
fit_summary field_cal_zero_point_corr  :  1.1476598579986392
```

Afterglow fixes `zero_point = 20` and reports a correction; Kepler computes the
absolute value. `test_data/README.md` warns in bold that mixing the two
conventions "lands 20 magnitudes off in a way that looks entirely plausible" —
and the public model name is on the wrong side of exactly that trap.

### BL-6 — the OCL report no longer joins to any bundled frame

`test_data/fieldcal/ocl_filter_report.json` records a full
wcs → photometry → field_calibration sweep over ten Open/Clear/Lum frames,
keyed by upstream filename:

```
messier 15_14111493_Lum_005.fits  | Lum  | best V    | zp 20.141497332382436
messier 15_14111493_Open_000.fits | Open | best None | zp None
…
```

The bundled frames were renamed to `m15_globular_lum_000.fits` and
`m15_globular_open_000.fits`. The report carries no `DATE-OBS`, no exposure
time, and no other identifier — only `input_file` — so **the join key was lost
in the rename** and the ground truth is stranded.

The mapping is recoverable, but only from outside this repository, at
`/home/claude/skynet-data/pipeline_data/reorganize.py:72,79`:

```
ocl/messier 15_14111493_Lum_005.fits  -> …/m15_globular_lum_000.fits
ocl/messier 15_14111493_Open_000.fits -> …/m15_globular_open_000.fits
```

The `Open_000` row corroborates it independently: all three of its trial
filters failed with `"no WCS solution found in FITS header"`, and
`m15_globular_open_000.fits` is precisely the one bundled frame with no WCS
keywords. The mapping is certain; it just is not written down here.

Worth noting for BL-7: upstream's OCL sweep only *read* the header WCS — it did
not plate-solve. A working `solve_astrometry` tool would take that frame
further than the recorded pipeline did.

### BL-7 — `solve_wcs` is unreachable, and its data dependency is present but unconfigured

Three separate gaps stack here.

1. **No tool.** `docs/tool-architecture.md` §2 lists `solve_astrometry(path,
   settings=None)` under "next Python tools". It was never built.
   `algorithms.wcs.wcs.solve_wcs` is reachable only by importing the algorithm
   package directly.
2. **A state object with no factory.** `solve_wcs` calls
   `processing_run.ensure_wcs_solution()` (`algorithms/wcs/wcs.py:578`). A bare
   stand-in fails:
   ```
   AttributeError: 'Run' object has no attribute 'ensure_wcs_solution'
   ```
   `algorithms.wcs.state.ProcessingRun` is the intended duck-type and works, but
   nothing in `tools/` constructs it, and neither `README.md` nor
   `docs/tool-architecture.md` mentions that a caller must.
3. **The index data is on this machine and nothing points at it.**
   ```
   /usr/bin/solve-field
   /usr/share/astrometry/data/index-4107.fits … index-4119.fits   (13 files, ~350 MB)
   ANET_INDEX_PATH=   (unset)
   ATLAS_CATALOG_ROOT= (unset)
   ```
   `CLAUDE.md` explains that both WCS backends "degrade to *unavailable* rather
   than failing … This is why full parity has never been validated here." That
   reasoning is sound in general and **wrong on this host**: astrometry.net is
   installed, and the solver has simply never been pointed at it.

   With `ANET_INDEX_PATH=/usr/share/astrometry/data`, the solve reached the
   backend and ran for real:

   ```
   solve_wcs: sources=100 size=1056x1027 ra_hint=21.4995 dec_hint=12.1669
              max_sep_deg=1.00 radius=180.0 anet=True atlas=False
   anet: 1 index dir(s) accepted: /usr/share/astrometry/data [standard]
   … 670.30s …
   anet: solve-field produced no solve.wcs (no solution).
     command=… --scale-units arcsecperpix --scale-low 0.1 --scale-high 60.0 …
   solve_wcs: no accepted solution
   ```

   So the wiring works, the index files are accepted, and the RA/Dec hints are
   correctly derived from the frame's own header (M15 sits at 21.4995 h,
   +12.167°). What the log shows is why it still found nothing in 11 minutes:
   `radius=180.0` and `--scale-low 0.1 --scale-high 60.0` — an all-sky search
   across a 600× pixel-scale window, on a frame whose header states
   `SECPIX = 0.5864922312362758`.

   **That is deliberate upstream behaviour, not a bug**, and it constrains what
   a tool wrapper may do. `solve_wcs` constructs `WcsCalibrationSettings()`
   fresh (`algorithms/wcs/wcs.py:541`) and exposes only two of its fields
   through `PlateSolveSettings`:

   > Only the two knobs that shape the *written* WCS are exposed — SIP order and
   > where the reference pixel sits. Search radii, scale windows and source caps
   > stay internal: they are accuracy tuning, not a product choice, and an
   > observer narrowing the search would silently cause misses.
   > — `algorithms/wcs/wcs.py:543-547`

   And the `pixel_scale_hint_arcsec` parameter does **not** narrow the
   astrometry.net search. `anet_min_scale`/`anet_max_scale` are assigned
   straight from the settings defaults (`wcs.py:642-645`, under the comment
   "The `WcsCalibrationSettings` defaults (radius=180 → a true all-sky
   search)"). The hint feeds only the acceptance threshold `max_sep_deg`
   (`wcs.py:654-658`) and the *ATLAS* backend's scale narrowing
   (`wcs.py:786-792`) — and no UCAC4/UCAC5 data exists anywhere on this host,
   so ATLAS is unavailable and that narrowing never runs.

   **Consequence for Task 9:** a wrapper cannot make this solve fast through
   the public signature. It can only (a) bound it with a timeout and report
   non-convergence as a warning, or (b) reassign `WcsCalibrationSettings`
   defaults — which diverges from upstream and is a maintainer decision, not a
   tool-layer one. Task 9 takes route (a) and flags route (b) as an open
   question. The finding stands regardless: the tool is missing, and the index
   data was present and unconfigured the whole time.

### BL-8 — the curated pulsar periods are unreachable from the tool layer

`PulsarScan` carries `path`, `source_name`, `date_obs`, `receiver`,
`obs_freq_mhz`, `ra_deg`, `dec_deg`, `duration_s`, `size_bytes` — and no
period. The periods live in two places, neither of which is a tool:

- `test_data/pulsar/Curated pulsars.docx` — the reference
  `test_data/README.md` calls "the verification reference … **This document,
  not ATNF, is the reference the tests compare against**".
- `tests/conftest.py:54` `PULSAR_PERIODS_S` — its "Period(Literature)" column,
  transcribed. A pytest module; not importable as a tool.

Meanwhile `tools/runner.py:73` tells the agent:

> For a catalogued source, search_atnf gives a period more accurate than a
> short scan can measure — prefer it over step 2's result when the two
> disagree.

`search_atnf` is `psrqpy` over the network. Offline the agent must blind-search,
and `tests/test_pulsar_sonification.py::test_blind_search_only_succeeds_on_the_bright_source`
pins that this works for **one of the five** bundled scans; the other four peak
on 60 Hz mains interference or red noise while still reporting "99.73%
Confidence". So the documented recovery path is exactly the one that is
unreachable without a socket, and the local data that would fix it is sitting
in the same directory as the scans.

### BL-9 — HR diagram: no runtime, no data, one genuinely external dependency

`algorithms/hrdiagram/` is 14 TypeScript files. Per `CLAUDE.md`, the TypeScript
folders have "no build, bundle, or test step, and no runtime — nothing executes
the TypeScript." There is no Python port. So every HR-diagram "tool call" is
broken in the strongest sense: there is no tool.

`docs/extraction.md` §3 (HR Diagram) records four severed backend endpoints:

| Endpoint | Supplied | Can Kepler do this locally? |
|---|---|---|
| `POST/GET {apiUrl}/cluster/catalog` | cone search → `output_sources`, `input_sources`, `cluster`, `star_counts` | **Yes** — `algorithms/query` already queries VizieR; Gaia/2MASS/APASS/WISE are the same catalogs |
| `POST/GET {apiUrl}/cluster/fsr` | field-star-removal astrometry | **Yes** — `fsr/fsr.util.ts` + `cluster-data.service.util.ts` carry the cut itself; only the data delivery was severed |
| `GET {apiUrl}/cluster/allMWSC` | the Milky Way Star Cluster catalogue | **Yes** — MWSC is a VizieR catalog |
| `GET {apiUrl}/cluster/isochrone` | `{data: number[][], iSkip: number}` | **No** |

The isochrone endpoint is the real blocker, and `docs/extraction.md` is explicit
about why: the response arrives "**already in `[colour, absolute magnitude]`
pairs for the requested filter triple** — i.e. the server does the grid
interpolation and the synthetic photometry." Astromancer ships no isochrone data
(verified: `src/assets/` contains two font families and a `static/` folder, no
CSVs, no sample data of any kind). Kepler ships none either. This needs an
external model grid — PARSEC or MIST — plus the interpolation and
bolometric-correction step that lived in a backend that is not in this
repository.

There is also no cluster photometry in `test_data/`: the fixtures are optical
FITS frames, radio scans, and recorded zero-point solves. So a lookup registry
for HR-diagram inputs has nothing to look up yet.

**This is a separate subsystem and gets its own plan.** See §9.

### BL-10 — variable-star light curve and periodogram

`algorithms/lightcurve/variable/` and `algorithms/periodogram/variable/` are in
the same position: TypeScript with no runtime, and no fixture data anywhere in
`test_data/`. Astromancer ships no sample light curves. Unlike BL-9 there is no
external-data blocker — a variable-star light curve is an ordinary time series
and VizieR/ASAS-SN/ZTF can supply one — but it needs the same runtime decision.
Deferred with BL-9.

### BL-11 — archive downloads dead-end

`tools/mast.py:141` creates `FITS_DOWNLOAD_DIR` and downloads products into it
when `download=True`. Nothing can then be done with them: no registered tool
accepts a FITS path (BL-2), and the one unregistered tool that does raises on
any frame with a WCS (BL-1). The chain **find data → measure → calibrate →
compare** is severed at every joint.

### BL-12 — `npm run typecheck` cannot run from a fresh checkout

`CLAUDE.md` lists `npm run typecheck` in Commands. `node_modules/` is absent and
`tsc` is not on `PATH`; the command needs `npm install` first, which `CLAUDE.md`
does not mention, and it is not a CI job so nothing else runs it. One-line
documentation fix.

---

## 2. File Structure

New files:

| Path | Responsibility |
|---|---|
| `tools/optical.py` | Stage 0 for optical frames: `list_optical_frames`, `resolve_optical_frame`. Header summary only; no pixel reads. |
| `tools/fieldcal_reference.py` | Loaders for the recorded ground truth in `test_data/fieldcal/` and `test_data/afterglow/`, plus `compare_zeropoint_to_reference`. |
| `tools/photometry.py` | `measure_photometry(path, …)` — the missing FITS-path-in, table-artifact-out photometry tool. |
| `tools/wcs.py` | `solve_astrometry(path, …)` — constructs `ProcessingRun`, passes header hints, returns a `WcsSummary`. |
| `test_data/frame_provenance.json` | The upstream-filename ↔ bundled-filename map that BL-6 needs. ~4 KB. |
| `tests/test_optical_registry.py` | Covers `tools/optical.py`. |
| `tests/test_fieldcal_reference.py` | Covers `tools/fieldcal_reference.py` against the recorded solves. |
| `tests/test_tool_registry_coverage.py` | Pins BL-2: every public tool module is represented in the registry. |
| `tests/test_astrometry_tool.py` | Covers `tools/astrometry.py` across all 39 frames — the test whose absence hid BL-1. |

Modified:

| Path | Change |
|---|---|
| `tools/astrometry.py:100` | Fix the `StrListProxy` slice. |
| `tools/models.py` | Add `OpticalFrame`, `OpticalFrameList`, `ZeropointComparison`, `PhotometryMeasurement`; rename the `ZeropointSolution` zero-point field. |
| `tools/calibration.py` | Follow the model rename; add `solve_zeropoint_from_recorded_solve`. |
| `tools/registry.py` | Register the local tools. |
| `tools/runner.py` | Teach the system prompt that local frames and recorded ground truth exist. |
| `tools/pulsar.py` | Add the curated-period lookup to Stage 0. |
| `tools/claude_photometry_haiku_tool.py` | Delegate `resolve_fits_path`/`list_bundled_targets` to `tools/optical.py`. |
| `test_data/README.md`, `README.md`, `docs/tool-architecture.md`, `CLAUDE.md` | Document what changed. |

---

## 3. Phase 1 — Make the existing local tools work and reachable

Fixes BL-1, BL-2, BL-5. This phase is worth landing on its own: it turns four
already-written tools from unreachable-or-broken into working.

### Task 1: Fix the WCS summary crash and cover it across every frame

**Files:**
- Modify: `tools/astrometry.py:100`
- Test: `tests/test_astrometry_tool.py` (create)

**Interfaces:**
- Consumes: `tests/conftest.py::FRAMES` (frame aliases), the `test_data_dir` fixture.
- Produces: nothing new; `describe_image_wcs(path) -> WcsSummary` is unchanged
  in signature.

- [ ] **Step 1: Write the failing test**

Create `tests/test_astrometry_tool.py`:

```python
"""Tool-layer coverage for ``tools.astrometry``.

BL-1: this file exists because ``describe_image_wcs`` raised ``TypeError`` on
38 of the 39 bundled frames and no test imported the module. The parametrized
sweep is the point -- a fix that works on one frame and not the rest is not a
fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.astrometry import describe_image_wcs

FRAME_PATHS = sorted((Path(__file__).resolve().parents[1] / "test_data" / "optical").glob("*.fits"))


def test_the_fixture_directory_is_populated():
    assert len(FRAME_PATHS) == 39


@pytest.mark.parametrize("path", FRAME_PATHS, ids=lambda p: p.stem)
def test_describe_image_wcs_never_raises_on_a_bundled_frame(path):
    summary = describe_image_wcs(path)
    assert summary.file.exists is True


def test_frame_with_a_wcs_reports_ctype_and_a_centre():
    summary = describe_image_wcs(
        Path(__file__).resolve().parents[1] / "test_data" / "optical" / "ngc5128_galaxy_b_001.fits"
    )
    assert summary.has_wcs is True
    assert summary.ctype == ("RA---TAN", "DEC--TAN")
    assert summary.center_ra_deg == pytest.approx(201.36, abs=0.5)
    assert summary.center_dec_deg == pytest.approx(-43.02, abs=0.5)
    assert summary.pixel_scale_arcsec is not None


def test_frame_without_a_wcs_warns_instead_of_erroring():
    """m15_globular_open_000 carries no WCS keywords at all (test_data/README.md)."""
    summary = describe_image_wcs(
        Path(__file__).resolve().parents[1] / "test_data" / "optical" / "m15_globular_open_000.fits"
    )
    assert summary.has_wcs is False
    assert [w.code for w in summary.warnings] == ["no_celestial_wcs"]
    assert summary.errors == []


def test_missing_file_returns_an_error_not_an_exception():
    summary = describe_image_wcs("test_data/optical/does_not_exist.fits")
    assert summary.has_wcs is False
    assert [e.code for e in summary.errors] == ["file_not_found"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_astrometry_tool.py -q`
Expected: 38 parametrized failures plus `test_frame_with_a_wcs_reports_ctype_and_a_centre`,
all `TypeError: sequence index must be integer, not 'slice'`.

- [ ] **Step 3: Fix the slice**

In `tools/astrometry.py`, replace line 100:

```python
    ctype = tuple(str(value) for value in wcs.wcs.ctype[:2])
```

with:

```python
    # `wcs.wcs.ctype` is an astropy StrListProxy, which supports integer
    # indexing but not slicing (astropy 8.0.1). Materialize before slicing.
    ctype = tuple(str(value) for value in list(wcs.wcs.ctype)[:2])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_astrometry_tool.py -q`
Expected: PASS, 43 tests.

- [ ] **Step 5: Confirm nothing else regressed**

Run: `uv run pytest -q`
Expected: the suite passes as before, plus the new file.

- [ ] **Step 6: Commit**

```bash
git add tools/astrometry.py tests/test_astrometry_tool.py
git commit -m "fix(tools): describe_image_wcs raised TypeError on every frame with a WCS

wcs.wcs.ctype is an astropy StrListProxy; it indexes but does not slice.
38 of 39 bundled frames raised. Adds the parametrized tool-layer sweep whose
absence hid this."
```

### Task 2: Rename the zero-point field to say what it holds

**Files:**
- Modify: `tools/models.py:136-144`, `tools/calibration.py:110-125`
- Test: `tests/test_fieldcal_reference.py` (created in Task 6; add the assertion
  to `tests/test_calibration_tool.py` here)

**Interfaces:**
- Produces: `ZeropointSolution.zero_point` (absolute, magnitudes) replacing
  `ZeropointSolution.zero_point_corr`. Tasks 6 and 7 consume the new name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_calibration_tool.py`:

```python
"""Tool-layer coverage for ``tools.calibration``.

BL-5: the result field was named ``zero_point_corr`` while holding an
*absolute* zero point. Afterglow fixes zero_point = 20 and reports a
correction; Kepler computes the absolute value. test_data/README.md warns that
confusing the two "lands 20 magnitudes off in a way that looks entirely
plausible", so the public name has to be unambiguous.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.calibration import solve_zeropoint_from_measurements

ROOT = Path(__file__).resolve().parents[1]
SOLVE = ROOT / "test_data" / "fieldcal" / "zp_solutions" / "ngc5128_b_002"


def _float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calibration_rows() -> list[dict[str, float | None]]:
    with (SOLVE / "fit_data.csv").open() as handle:
        rows = [r for r in csv.DictReader(handle)
                if r["used_for_calibration"].strip().lower() in ("true", "1")]
    return [
        {
            "mag": _float(r["mag"]),
            "mag_error": _float(r["mag_error"]),
            "ref_mag": _float(r["ref_mag"]),
            "ref_mag_error": _float(r["ref_mag_error"]),
        }
        for r in rows
    ]


def test_result_reports_an_absolute_zero_point_under_an_unambiguous_name():
    solution = solve_zeropoint_from_measurements(_calibration_rows(), [])

    assert solution.source_count == 35
    assert solution.errors == []
    # The absolute zero point Skynet recorded, bit for bit.
    assert solution.zero_point == 21.147659857998637
    # The old name held this same absolute value and must not survive.
    assert not hasattr(solution, "zero_point_corr")


def test_the_absolute_zero_point_is_afterglows_base_plus_correction():
    """Afterglow reports 20.0 + correction; Kepler reports the sum directly."""
    summary = json.loads((SOLVE / "fit_summary.json").read_text())
    solution = solve_zeropoint_from_measurements(_calibration_rows(), [])

    assert summary["field_cal_zero_point_corr"] == pytest.approx(
        solution.zero_point - 20.0, abs=1e-12
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_calibration_tool.py -q`
Expected: FAIL — `AttributeError: 'ZeropointSolution' object has no attribute 'zero_point'`.

- [ ] **Step 3: Rename the field**

In `tools/models.py`, change `ZeropointSolution`:

```python
class ZeropointSolution(KeplerToolModel):
    #: The ABSOLUTE photometric zero point in magnitudes, as ``calc_solution``
    #: returns it. Afterglow's API instead fixes ``zero_point = 20`` and
    #: reports a ``zero_point_correction``; adding the two gives this number.
    #: Confusing the conventions is a clean, plausible 20-magnitude error --
    #: see test_data/README.md.
    zero_point: float | None = None
    zero_point_error_mag: float | None = None
    zero_point_slop: float | None = None
    limmag5: float | None = None
    rej_percent: float | None = None
    source_count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)
```

In `tools/calibration.py`, change the construction at the end of
`solve_zeropoint_from_measurements`:

```python
    return ZeropointSolution(
        zero_point=_finite(m0),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_calibration_tool.py -q`
Expected: PASS, 2 tests.

- [ ] **Step 5: Check for other readers of the old name**

Run: `grep -rn 'zero_point_corr' tools/ tests/ docs/ README.md`
Expected: hits only in `docs/` prose describing Afterglow's own
`field_cal_zero_point_corr` key (which is Afterglow's name for its correction
and must not be renamed) and in this plan. Update any `tools/` hit.

- [ ] **Step 6: Commit**

```bash
git add tools/models.py tools/calibration.py tests/test_calibration_tool.py
git commit -m "fix(tools): name the zero-point field for what it holds

ZeropointSolution.zero_point_corr carried an absolute zero point (21.15), not
Afterglow's correction (1.15). Renames to zero_point and pins both the
bit-exact recorded value and the base-20 relationship."
```

### Task 3: Register the local tools

**Files:**
- Modify: `tools/registry.py`
- Test: `tests/test_tool_registry_coverage.py` (create)

**Interfaces:**
- Consumes: `describe_image_wcs`, `list_photometric_catalogs`,
  `resolve_reference_band`, `solve_zeropoint_from_measurements`,
  `list_artifacts`, `describe_artifact`.
- Produces: six new `TOOL_SCHEMAS` entries and `TOOL_FUNCTIONS` keys of the
  same names. Later tasks add to the same two structures.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_registry_coverage.py`:

```python
"""The registry is the agent's whole world; anything absent does not exist.

BL-2: before this test, every module in tools/ that reads local data -- except
tools.pulsar -- was unregistered, so an agent loop could query eight remote
archives but could not open any of the 39 bundled FITS frames.
"""

from __future__ import annotations

from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

#: Modules that are infrastructure, not a public tool surface.
NOT_TOOL_MODULES = {
    "tools.artifacts",
    "tools.config",
    "tools.models",
    "tools.registry",
    "tools.runner",
    "tools.sessions",
    # A CLI entry point; its library halves are re-exported through
    # tools.optical and tools.photometry instead.
    "tools.claude_photometry_haiku_tool",
}


def _tool_modules() -> set[str]:
    import pkgutil

    import tools

    return {
        f"tools.{module.name}"
        for module in pkgutil.iter_modules(tools.__path__)
    } - NOT_TOOL_MODULES


def test_every_public_tool_module_is_represented_in_the_registry():
    registered = {fn.__module__ for fn in TOOL_FUNCTIONS.values()}
    assert _tool_modules() - registered == set()


def test_schemas_and_functions_agree():
    assert {s["name"] for s in TOOL_SCHEMAS} == set(TOOL_FUNCTIONS)


def test_the_local_no_network_tools_are_reachable():
    """docs/tool-architecture.md 2 calls these the first local tools."""
    for name in (
        "describe_image_wcs",
        "list_photometric_catalogs",
        "resolve_reference_band",
        "solve_zeropoint_from_measurements",
        "list_artifacts",
        "describe_artifact",
    ):
        assert name in TOOL_FUNCTIONS, name
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_tool_registry_coverage.py -q`
Expected: FAIL — the module-set difference is
`{'tools.astrometry', 'tools.calibration', 'tools.catalogs', 'tools.workspace'}`.

- [ ] **Step 3: Register the six tools**

In `tools/registry.py`, add to the imports:

```python
from tools.astrometry import describe_image_wcs
from tools.calibration import solve_zeropoint_from_measurements
from tools.catalogs import list_photometric_catalogs, resolve_reference_band
from tools.workspace import describe_artifact, list_artifacts
```

Append to `TOOL_SCHEMAS`:

```python
    {
        "name": "describe_image_wcs",
        "description": "Summarize the celestial WCS of a local FITS image: "
        "CTYPE, field centre in degrees and hours, pixel scale in arcseconds, "
        "and rotation. Reads the header only. A frame with no WCS returns "
        "has_wcs=false with a warning, not an error -- one bundled frame "
        "(m15_globular_open_000.fits) is deliberately in that state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to a local FITS file. Get one from "
                    "resolve_optical_frame rather than guessing.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_photometric_catalogs",
        "description": "List the photometric catalogs this repository can "
        "resolve a reference band from, with their bands. Declaration only -- "
        "no network call.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "resolve_reference_band",
        "description": "Given a catalog and an image FILTER, report which "
        "catalog band calibration would use and how it was reached (direct "
        "band, lookup, or colour transform). Unfiltered passes (Open/Clear/"
        "Lum) resolve through a substitute band, which is why an unfiltered "
        "frame has no published zero point of its own.",
        "input_schema": {
            "type": "object",
            "properties": {
                "catalog": {"type": "string", "description": "Catalog name, e.g. 'APASS'."},
                "image_filter": {
                    "type": "string",
                    "description": "The frame's FILTER keyword, e.g. 'B', 'Lum', 'Halpha'.",
                },
            },
            "required": ["catalog", "image_filter"],
        },
    },
    {
        "name": "solve_zeropoint_from_measurements",
        "description": "Solve a photometric zero point from instrumental "
        "magnitudes paired with catalog reference magnitudes. Returns the "
        "ABSOLUTE zero point in magnitudes -- Afterglow's API instead reports "
        "20.0 plus a correction, so never compare the two without adding "
        "Afterglow's base first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "measurements": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Per-source measurements with mag, mag_error, "
                    "and either ref_mag/ref_mag_error or an id matching a catalog source.",
                },
                "catalog_sources": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Catalog rows to resolve reference magnitudes from. "
                    "May be empty when the measurements already carry ref_mag.",
                },
            },
            "required": ["measurements", "catalog_sources"],
        },
    },
    {
        "name": "list_artifacts",
        "description": "List artifact files this tool set has written to the "
        "local artifact directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to list. Defaults to KEPLER_ARTIFACT_DIR.",
                }
            },
        },
    },
    {
        "name": "describe_artifact",
        "description": "Describe one local artifact file: type, size, and "
        "creation time.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Artifact path."}},
            "required": ["path"],
        },
    },
```

Append to `TOOL_FUNCTIONS`:

```python
    "describe_image_wcs": describe_image_wcs,
    "list_photometric_catalogs": list_photometric_catalogs,
    "resolve_reference_band": resolve_reference_band,
    "solve_zeropoint_from_measurements": solve_zeropoint_from_measurements,
    "list_artifacts": list_artifacts,
    "describe_artifact": describe_artifact,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tool_registry_coverage.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 5: Confirm the registry still imports without a network stack**

Run: `uv run python -c "from tools.registry import TOOL_FUNCTIONS; print(len(TOOL_FUNCTIONS))"`
Expected: `29`.

- [ ] **Step 6: Commit**

```bash
git add tools/registry.py tests/test_tool_registry_coverage.py
git commit -m "feat(registry): register the local no-network tools

An agent driven by tools.runner could query eight remote archives but could
not open any of the 39 bundled frames: astrometry, calibration, catalogs and
workspace were all unregistered. Adds a coverage test so a new tool module
cannot be added without a registry entry."
```

---

## 4. Phase 2 — The optical frame registry

Fixes BL-3. This is the user's HR-diagram example applied where the data
actually exists today.

### Task 4: `tools/optical.py` — Stage 0 for FITS frames

**Files:**
- Create: `tools/optical.py`
- Modify: `tools/models.py` (add `OpticalFrame`, `OpticalFrameList`)
- Test: `tests/test_optical_registry.py` (create)

**Interfaces:**
- Consumes: `tools.config.env_path`, `tools.models.{ToolError, ToolWarning}`.
- Produces:
  - `OPTICAL_DATA_DIR_ENV: str = "KEPLER_OPTICAL_DATA_DIR"`
  - `list_optical_frames(directory: str | Path | None = None, *, image_filter: str | None = None) -> OpticalFrameList`
  - `resolve_optical_frame(name: str, directory: str | Path | None = None) -> OpticalFrame | OpticalFrameList`
  - `OpticalFrame` fields: `path, object_name, category, image_filter, telescope,
    date_obs, exposure_s, width, height, has_wcs, center_ra_deg, center_dec_deg,
    pixel_scale_arcsec, size_bytes`
  - Tasks 7, 9 and 10 call `resolve_optical_frame`.

- [ ] **Step 1: Add the models**

In `tools/models.py`, add to `__all__` the names `"OpticalFrame"` and
`"OpticalFrameList"`, and add after `PulsarScanList`:

```python
class OpticalFrame(KeplerToolModel):
    """An optical FITS frame available on local disk.

    ``path`` is what every image tool takes. Everything else is read from the
    primary header, so listing 39 frames stays cheap -- no pixel data is read.
    """

    path: str
    object_name: str | None = None
    category: str | None = None
    image_filter: str | None = None
    telescope: str | None = None
    date_obs: str | None = None
    exposure_s: float | None = None
    width: int | None = None
    height: int | None = None
    has_wcs: bool = False
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    pixel_scale_arcsec: float | None = None
    size_bytes: int | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class OpticalFrameList(KeplerToolModel):
    """Frames found locally, plus where they were looked for."""

    frames: list[OpticalFrame] = Field(default_factory=list)
    search_root: str
    count: int = 0
    filters: list[str] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_optical_registry.py`:

```python
"""Stage 0 for optical frames, mirroring tools.pulsar's scan discovery.

BL-3: the only frame resolver lived inside a CLI script, raised
FileNotFoundError instead of returning a ToolError, and reported no header
metadata -- so a caller could not ask "which frames are in B?" without opening
all 39 files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.models import OpticalFrame, OpticalFrameList
from tools.optical import list_optical_frames, resolve_optical_frame

ROOT = Path(__file__).resolve().parents[1]
OPTICAL = ROOT / "test_data" / "optical"


def test_lists_every_bundled_frame():
    listing = list_optical_frames()
    assert listing.count == 39
    assert Path(listing.search_root) == OPTICAL
    assert listing.errors == []


def test_listing_reports_the_filter_spread_recorded_in_the_readme():
    """test_data/README.md: V (25), R (7), B (2), Halpha (2), OIII (1), Lum (1), Open (1)."""
    listing = list_optical_frames()
    counts: dict[str, int] = {}
    for frame in listing.frames:
        counts[frame.image_filter] = counts.get(frame.image_filter, 0) + 1
    assert counts == {
        "V": 25, "R": 7, "B": 2, "Halpha": 2, "OIII": 1, "Lum": 1, "Open": 1,
    }


def test_filter_narrowing():
    listing = list_optical_frames(image_filter="B")
    assert listing.count == 2
    assert {Path(f.path).stem for f in listing.frames} == {
        "ngc5128_galaxy_b_000", "ngc5128_galaxy_b_001",
    }


def test_category_comes_from_the_filename_convention():
    """Frames are named <object>_<category>_<filter>_<seq> (test_data/README.md)."""
    frame = resolve_optical_frame("ngc1846_cluster_r_000")
    assert isinstance(frame, OpticalFrame)
    assert frame.category == "cluster"
    assert frame.image_filter == "R"


def test_resolves_a_bare_stem_a_filename_and_a_full_path():
    for query in (
        "ngc5128_galaxy_b_001",
        "ngc5128_galaxy_b_001.fits",
        str(OPTICAL / "ngc5128_galaxy_b_001.fits"),
    ):
        frame = resolve_optical_frame(query)
        assert isinstance(frame, OpticalFrame), query
        assert Path(frame.path).stem == "ngc5128_galaxy_b_001"


def test_resolves_an_object_name_with_punctuation_variants():
    """'NGC 5128' and 'ngc5128' both name the same field; only B has two frames."""
    result = resolve_optical_frame("NGC 5128")
    assert isinstance(result, OpticalFrameList)
    assert [e.code for e in result.errors] == ["ambiguous"]
    assert result.count == 4  # two B frames, two V frames


def test_the_frame_with_no_wcs_is_reported_not_hidden():
    frame = resolve_optical_frame("m15_globular_open_000")
    assert isinstance(frame, OpticalFrame)
    assert frame.has_wcs is False
    assert frame.center_ra_deg is None
    assert [w.code for w in frame.warnings] == ["no_celestial_wcs"]


def test_a_frame_with_a_wcs_carries_a_centre_and_a_pixel_scale():
    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    assert frame.has_wcs is True
    assert frame.center_ra_deg == pytest.approx(201.36, abs=0.5)
    assert frame.center_dec_deg == pytest.approx(-43.02, abs=0.5)
    assert frame.pixel_scale_arcsec == pytest.approx(1.2, abs=1.0)


def test_an_unknown_name_returns_the_candidates_not_an_exception():
    result = resolve_optical_frame("messier 87")
    assert isinstance(result, OpticalFrameList)
    assert [e.code for e in result.errors] == ["not_found"]
    assert result.count == 39


def test_a_missing_directory_returns_an_error_naming_the_env_override():
    listing = list_optical_frames("/nonexistent/optical")
    assert listing.count == 0
    assert [e.code for e in listing.errors] == ["directory_not_found"]
    assert "KEPLER_OPTICAL_DATA_DIR" in listing.errors[0].message


def test_env_override_redirects_the_search_root(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPLER_OPTICAL_DATA_DIR", str(tmp_path))
    listing = list_optical_frames()
    assert Path(listing.search_root) == tmp_path
    assert listing.count == 0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_optical_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.optical'`.

- [ ] **Step 4: Implement `tools/optical.py`**

```python
"""Stage 0 for optical frames: find a FITS frame on local disk.

There is no archive query behind the image tools -- every stage takes a *file
path*, and a path only resolves if the frame is already here. This is the
discovery step, so a caller asked to work on a named object can find out what
is actually on hand instead of guessing a path or hitting a bare
FileNotFoundError.

Modelled directly on ``tools.pulsar``'s scan discovery: an env-overridable
data directory, punctuation-insensitive name matching, and ambiguity returned
as a candidate list with a ``ToolError`` rather than raised.

Reads only each file's primary header, so listing all 39 bundled frames does
not touch pixel data.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs.utils import proj_plane_pixel_scales

from algorithms.wcs.source_extraction import build_wcs_from_header
from tools.models import OpticalFrame, OpticalFrameList, ToolError, ToolWarning

__all__ = [
    "OPTICAL_DATA_DIR_ENV",
    "list_optical_frames",
    "resolve_optical_frame",
]

#: Where frames are looked for. Overridable so a caller with their own archive
#: does not have to move files into the repo.
OPTICAL_DATA_DIR_ENV = "KEPLER_OPTICAL_DATA_DIR"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _optical_data_dir() -> Path:
    from tools.config import env_path

    default = _REPO_ROOT / "test_data" / "optical"
    return env_path(OPTICAL_DATA_DIR_ENV, default) or default


def _normalize(name: str) -> str:
    """Reduce an object designation to comparable characters.

    ``NGC 5128``, ``ngc5128`` and ``NGC-5128`` all reduce to ``ngc5128``. The
    same reduction is applied to filename stems, so ``ngc5128_galaxy_b_001``
    contains ``ngc5128`` as a substring match.
    """
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


def _float(header, *keys: str) -> float | None:
    for key in keys:
        value = header.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _int(header, key: str) -> int | None:
    try:
        return int(header[key])
    except (KeyError, TypeError, ValueError):
        return None


def _summary(path: Path) -> OpticalFrame:
    """Read one frame's primary header without touching pixel data."""

    warnings: list[ToolWarning] = []
    errors: list[ToolError] = []
    try:
        header = fits.getheader(path)
    except Exception as exc:
        return OpticalFrame(
            path=str(path),
            errors=[ToolError(code="fits_header_error", message=str(exc))],
        )

    # test_data/optical is flat; the category is the second token of the stem,
    # per the <object>_<category>_<filter>_<seq> convention documented in
    # test_data/README.md.
    parts = Path(path).stem.split("_")
    category = parts[1] if len(parts) > 1 else None

    center_ra = center_dec = None
    scale = None
    wcs = build_wcs_from_header(header)
    if wcs is None:
        warnings.append(
            ToolWarning(
                code="no_celestial_wcs",
                message="FITS header does not contain a celestial WCS.",
            )
        )
    else:
        width = _int(header, "NAXIS1")
        height = _int(header, "NAXIS2")
        if width and height:
            try:
                ra_deg, dec_deg = wcs.all_pix2world(
                    (width + 1.0) / 2.0, (height + 1.0) / 2.0, 1
                )
                center_ra = float(ra_deg) % 360.0
                center_dec = float(dec_deg)
            except Exception:
                warnings.append(
                    ToolWarning(
                        code="wcs_projection_failed",
                        message="WCS present but the field centre could not be projected.",
                    )
                )
        try:
            scales = np.asarray(
                proj_plane_pixel_scales(wcs.celestial), dtype=float
            ) * 3600.0
            if len(scales) >= 2 and np.all(np.isfinite(scales[:2])):
                scale = abs(float(scales[0]))
        except Exception:
            pass

    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        size_bytes = None
        warnings.append(ToolWarning(code="stat_failed", message=str(exc)))

    return OpticalFrame(
        path=str(path),
        object_name=(str(header["OBJECT"]).strip() if "OBJECT" in header else None),
        category=category,
        image_filter=(str(header["FILTER"]).strip() if "FILTER" in header else None),
        telescope=(str(header["TELESCOP"]).strip() if "TELESCOP" in header else None),
        date_obs=(str(header["DATE-OBS"]).strip() if "DATE-OBS" in header else None),
        exposure_s=_float(header, "EXPTIME", "EXPOSURE"),
        width=_int(header, "NAXIS1"),
        height=_int(header, "NAXIS2"),
        has_wcs=wcs is not None,
        center_ra_deg=center_ra,
        center_dec_deg=center_dec,
        pixel_scale_arcsec=scale,
        size_bytes=size_bytes,
        warnings=warnings,
        errors=errors,
    )


def list_optical_frames(
    directory: str | Path | None = None, *, image_filter: str | None = None
) -> OpticalFrameList:
    """Stage 0. List the optical frames available on local disk.

    Pass ``image_filter`` to narrow to one FILTER value (case-insensitive).
    Reads headers only, so this stays cheap over the whole fixture set.
    """
    root = Path(directory).expanduser() if directory else _optical_data_dir()

    if not root.is_dir():
        return OpticalFrameList(
            frames=[],
            search_root=str(root),
            count=0,
            errors=[
                ToolError(
                    code="directory_not_found",
                    message=f"No optical data directory at {root}. Set "
                    f"{OPTICAL_DATA_DIR_ENV} to point at one.",
                )
            ],
        )

    frames = [_summary(p) for p in sorted(root.glob("*.fits")) if p.is_file()]
    if image_filter is not None:
        wanted = image_filter.strip().lower()
        frames = [f for f in frames if (f.image_filter or "").lower() == wanted]

    filters = sorted({f.image_filter for f in frames if f.image_filter})
    return OpticalFrameList(
        frames=frames, search_root=str(root), count=len(frames), filters=filters
    )


def resolve_optical_frame(
    name: str, directory: str | Path | None = None
) -> OpticalFrame | OpticalFrameList:
    """Stage 0. Find the frame for a name, stem, filename, or explicit path.

    Matching is on alphanumerics only, so ``NGC 5128``, ``ngc5128`` and
    ``NGC-5128`` are equivalent. A name that matches several frames -- which
    it will whenever a field was observed in more than one band -- returns an
    :class:`~tools.models.OpticalFrameList` of the candidates with an
    ``ambiguous`` error, so the caller chooses rather than the tool guessing.
    """
    root = Path(directory).expanduser() if directory else _optical_data_dir()

    direct = Path(name).expanduser()
    if direct.is_file():
        return _summary(direct)
    for candidate in (root / name, root / f"{name}.fits"):
        if candidate.is_file():
            return _summary(candidate)

    listing = list_optical_frames(root)
    if listing.errors:
        return listing

    wanted = _normalize(name)
    if not wanted:
        listing.errors.append(
            ToolError(code="invalid_input", message="name must not be blank")
        )
        return listing

    matches = [
        frame
        for frame in listing.frames
        if wanted in _normalize(Path(frame.path).stem)
        or wanted in _normalize(frame.object_name or "")
    ]

    if len(matches) == 1:
        return matches[0]

    if not matches:
        listing.errors.append(
            ToolError(
                code="not_found",
                message=f"No local frame matches {name!r}. "
                f"{listing.count} frames are available; call list_optical_frames "
                f"to see them.",
            )
        )
        return listing

    listing.frames = matches
    listing.count = len(matches)
    listing.filters = sorted({f.image_filter for f in matches if f.image_filter})
    listing.errors.append(
        ToolError(
            code="ambiguous",
            message=f"{name!r} matches {len(matches)} frames "
            f"({', '.join(sorted(set(f.image_filter or '?' for f in matches)))}); "
            f"pass a filename or narrow with image_filter.",
        )
    )
    return listing
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_optical_registry.py -q`
Expected: PASS, 11 tests.

If `test_listing_reports_the_filter_spread_recorded_in_the_readme` fails,
compare the observed counts against `test_data/README.md`'s table before
changing the test — a mismatch means a frame was added or replaced, and the
README is the record of what should be there.

- [ ] **Step 6: Commit**

```bash
git add tools/optical.py tools/models.py tests/test_optical_registry.py
git commit -m "feat(tools): add optical frame discovery, mirroring the pulsar Stage 0

list_optical_frames/resolve_optical_frame give the image tools the same
name-to-path step the pulsar chain has had, backed by KEPLER_OPTICAL_DATA_DIR
and returning ToolErrors for misses and ambiguity instead of raising."
```

### Task 5: Register the frame registry and point the CLI at it

**Files:**
- Modify: `tools/registry.py`, `tools/claude_photometry_haiku_tool.py:148-215`,
  `tools/runner.py` (system prompt)
- Test: `tests/test_optical_registry.py` (extend), `tests/test_photometry_tool_smoke.py`

**Interfaces:**
- Consumes: `list_optical_frames`, `resolve_optical_frame` from Task 4.
- Produces: `TOOL_FUNCTIONS["list_optical_frames"]`,
  `TOOL_FUNCTIONS["resolve_optical_frame"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_optical_registry.py`:

```python
def test_the_frame_registry_is_reachable_from_an_agent_loop():
    from tools.registry import TOOL_FUNCTIONS

    assert TOOL_FUNCTIONS["list_optical_frames"] is list_optical_frames
    assert TOOL_FUNCTIONS["resolve_optical_frame"] is resolve_optical_frame


def test_the_cli_resolver_delegates_to_the_registry():
    """One resolution rule, not two. BL-3."""
    from tools.claude_photometry_haiku_tool import resolve_fits_path

    resolved = resolve_fits_path("ngc5128_galaxy_b_001")
    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    assert Path(resolved) == Path(frame.path)


def test_the_cli_resolver_still_raises_for_its_own_callers():
    """The CLI contract is an exception; the tool contract is a ToolError."""
    from tools.claude_photometry_haiku_tool import resolve_fits_path

    with pytest.raises(FileNotFoundError):
        resolve_fits_path("messier 87")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_optical_registry.py -q -k "registry or cli"`
Expected: FAIL — `KeyError: 'list_optical_frames'`.

- [ ] **Step 3: Register both tools**

In `tools/registry.py` add the import and the two schemas:

```python
from tools.optical import list_optical_frames, resolve_optical_frame
```

```python
    {
        "name": "list_optical_frames",
        "description": "Stage 0 for image work: list the optical FITS frames "
        "available on local disk, with object, filter, telescope, geometry and "
        "whether each carries a WCS. There is no archive behind the image "
        "tools -- a path only resolves if the frame is already on this "
        "machine, so call this before assuming a frame exists. Reads headers "
        "only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to search. Defaults to "
                    "KEPLER_OPTICAL_DATA_DIR, then the bundled test_data/optical.",
                },
                "image_filter": {
                    "type": "string",
                    "description": "Narrow to one FILTER value, e.g. 'B', 'V', 'Halpha'.",
                },
            },
        },
    },
    {
        "name": "resolve_optical_frame",
        "description": "Stage 0. Find the local FITS frame for an object name, "
        "a filename stem, or an explicit path. Matching ignores punctuation, "
        "so 'NGC 5128' and 'ngc5128' are equivalent. A name matching several "
        "frames -- which happens whenever a field was observed in more than "
        "one band -- returns the candidates with an 'ambiguous' error so you "
        "can choose. Never invent a path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Object name, filename stem, filename, or full path.",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search. Defaults as for list_optical_frames.",
                },
            },
            "required": ["name"],
        },
    },
```

```python
    "list_optical_frames": list_optical_frames,
    "resolve_optical_frame": resolve_optical_frame,
```

- [ ] **Step 4: Delegate the CLI resolver**

Replace the bodies of `resolve_fits_path` and `list_bundled_targets` in
`tools/claude_photometry_haiku_tool.py` so one rule governs both surfaces:

```python
def resolve_fits_path(query: str | Path) -> Path:
    """Resolve a FITS path from an explicit path, a relative path, or a bundled target name.

    Delegates to ``tools.optical.resolve_optical_frame`` so the CLI and the
    registered tool cannot drift apart. The CLI contract is an exception on
    failure; the tool contract is a ToolError, so this translates.
    """
    from tools.optical import resolve_optical_frame

    query_path = Path(str(query))
    if query_path.is_absolute():
        if query_path.exists():
            return query_path.resolve()
        raise FileNotFoundError(f"FITS file '{query_path}' was not found locally.")

    for candidate in (query_path, ROOT / query_path):
        if candidate.exists():
            return candidate.resolve()

    result = resolve_optical_frame(str(query))
    if hasattr(result, "path"):
        return Path(result.path).resolve()
    raise FileNotFoundError(
        "; ".join(error.message for error in result.errors)
        or f"FITS file '{query}' was not found locally."
    )


def list_bundled_targets() -> dict[str, list[str]]:
    """Return the FITS target stems bundled locally, by category.

    Delegates to ``tools.optical.list_optical_frames``; the category is the
    second token of each stem, per the <object>_<category>_<filter>_<seq>
    convention documented in test_data/README.md.
    """
    from tools.optical import list_optical_frames

    targets: dict[str, list[str]] = {}
    for frame in list_optical_frames().frames:
        targets.setdefault(frame.category or "uncategorized", []).append(
            Path(frame.path).stem
        )
    return {category: sorted(stems) for category, stems in sorted(targets.items())}
```

- [ ] **Step 5: Teach the runner's system prompt that frames exist**

In `tools/runner.py`, insert after the `PULSAR PIPELINE` block:

```
LOCAL OPTICAL FRAMES. Image work has the same Stage 0 as the pulsar chain: \
list_optical_frames / resolve_optical_frame find a FITS frame on this machine. \
There is no archive behind them -- a path only resolves if the frame is \
already here, so never invent one. resolve_optical_frame returns candidates \
with an "ambiguous" error whenever a field was observed in more than one band; \
pick a band rather than guessing. Once you have a path, describe_image_wcs \
summarizes its pointing and pixel scale.
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_optical_registry.py tests/test_photometry_tool_smoke.py tests/test_tool_registry_coverage.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/registry.py tools/claude_photometry_haiku_tool.py tools/runner.py tests/test_optical_registry.py
git commit -m "feat(registry): register optical frame discovery and unify the CLI resolver

The CLI script and the tool layer now share one resolution rule. The runner
system prompt gains the local-frame Stage 0 so an agent stops inventing paths."
```

---

## 5. Phase 3 — The field-calibration reference comparison

Fixes BL-4 and BL-6. This is the second half of the user's request: the field
calibration tool should compare directly against `test_data/afterglow/`.

### Task 6: `tools/fieldcal_reference.py` — load and compare the recorded solves

**Files:**
- Create: `tools/fieldcal_reference.py`
- Modify: `tools/models.py` (add `ZeropointReference`, `ZeropointComparison`)
- Test: `tests/test_fieldcal_reference.py` (create)

**Interfaces:**
- Produces:
  - `FIELDCAL_DATA_DIR_ENV = "KEPLER_FIELDCAL_DATA_DIR"`
  - `list_zeropoint_references(directory=None) -> list[ZeropointReference]`
  - `load_zeropoint_reference(field: str, directory=None) -> ZeropointReference`
  - `solve_zeropoint_from_reference(field: str, directory=None) -> ZeropointSolution`
  - `compare_zeropoint_to_reference(zero_point: float, field: str, directory=None) -> ZeropointComparison`
  - `ZeropointReference` fields: `field, frame_path, catalog, num_calibration_sources,
    skynet_zero_point, afterglow_zero_point, afterglow_base, afterglow_correction,
    web_table_zero_point, parity_tolerance_mag, measurements`
  - `ZeropointComparison` fields: `zero_point, reference, delta_vs_skynet,
    delta_vs_afterglow, within_tolerance, tolerance_mag, warnings, errors`
- Consumed by Task 7.

- [ ] **Step 1: Add the models**

In `tools/models.py`, add `"ZeropointReference"` and `"ZeropointComparison"` to
`__all__`, and after `ZeropointSolution`:

```python
class ZeropointReference(KeplerToolModel):
    """A recorded zero-point solve shipped as ground truth.

    Three independent numbers describe the same exposure and they do not use
    the same convention: ``skynet_zero_point`` and ``web_table_zero_point`` are
    absolute magnitudes, while Afterglow's API fixes a base of 20.0 and reports
    a correction. ``afterglow_zero_point`` is the sum, already computed, so a
    caller never has to remember which side the 20 goes on -- getting that
    wrong is a clean, plausible 20-magnitude error (test_data/README.md).
    """

    field: str
    frame_path: str | None = None
    catalog: str | None = None
    num_calibration_sources: int = 0
    skynet_zero_point: float | None = None
    afterglow_zero_point: float | None = None
    afterglow_base: float | None = None
    afterglow_correction: float | None = None
    web_table_zero_point: float | None = None
    parity_tolerance_mag: float | None = None
    measurements: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class ZeropointComparison(KeplerToolModel):
    """A computed zero point placed against the recorded ground truth."""

    zero_point: float | None = None
    reference: ZeropointReference | None = None
    delta_vs_skynet: float | None = None
    delta_vs_afterglow: float | None = None
    within_tolerance: bool | None = None
    tolerance_mag: float | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_fieldcal_reference.py`:

```python
"""The recorded ground truth, reachable as a tool result.

BL-4: test_data/fieldcal/ and test_data/afterglow/ carry a complete
cross-implementation parity chain for NGC 5128 B, and before this module
nothing outside tests/ could read any of it.

The chain, all offline (test_data/README.md):

    Kepler calc_solution        21.147659857998637   (bit-exact)
    Skynet recorded local fit   21.147659857998637
    Afterglow API              (21.14747923526837)   = 20.0 + 1.1474792352683736
    Afterglow web table         21.147                (3 dp, recorded by hand)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fieldcal_reference import (
    compare_zeropoint_to_reference,
    list_zeropoint_references,
    load_zeropoint_reference,
    solve_zeropoint_from_reference,
)

#: The upstream diagnostic's own declared agreement threshold, in magnitudes.
PARITY_ZP_TOLERANCE = 0.0005

#: The number every step of the chain has to reproduce.
SKYNET_ZERO_POINT = 21.147659857998637
AFTERGLOW_ZERO_POINT = 21.14747923526837


def test_lists_the_four_recorded_solves():
    fields = {ref.field for ref in list_zeropoint_references()}
    assert fields == {"ngc5128_b_002", "ngc5286_b_000", "ngc5286_b_001", "ngc5286_b_002"}


def test_the_ngc5128_reference_carries_all_three_recorded_numbers():
    ref = load_zeropoint_reference("ngc5128_b_002")
    assert ref.catalog == "APASS"
    assert ref.num_calibration_sources == 35
    assert ref.skynet_zero_point == SKYNET_ZERO_POINT
    assert ref.afterglow_zero_point == pytest.approx(AFTERGLOW_ZERO_POINT, abs=1e-12)
    assert ref.afterglow_base == 20.0
    assert ref.web_table_zero_point == pytest.approx(21.147, abs=5e-4)
    assert ref.parity_tolerance_mag == PARITY_ZP_TOLERANCE


def test_the_afterglow_zero_point_is_base_plus_correction():
    """Kepler computes the absolute value; Afterglow reports 20.0 + a correction."""
    ref = load_zeropoint_reference("ngc5128_b_002")
    assert ref.afterglow_zero_point == pytest.approx(
        ref.afterglow_base + ref.afterglow_correction, abs=1e-12
    )


def test_the_reference_names_the_bundled_frame_it_describes():
    ref = load_zeropoint_reference("ngc5128_b_002")
    assert Path(ref.frame_path).name == "ngc5128_galaxy_b_001.fits"
    assert Path(ref.frame_path).is_file()


@pytest.mark.parametrize(
    "field",
    ["ngc5128_b_002", "ngc5286_b_000", "ngc5286_b_001", "ngc5286_b_002"],
)
def test_solving_from_the_recorded_rows_reproduces_the_recorded_solve(field):
    """PARITY: bit-exact against what Skynet returned for these exact rows."""
    reference = load_zeropoint_reference(field)
    solution = solve_zeropoint_from_reference(field)
    assert solution.errors == []
    assert solution.zero_point == reference.skynet_zero_point


def test_comparison_places_a_zero_point_against_both_implementations():
    comparison = compare_zeropoint_to_reference(SKYNET_ZERO_POINT, "ngc5128_b_002")
    assert comparison.delta_vs_skynet == 0.0
    assert abs(comparison.delta_vs_afterglow) == pytest.approx(1.806e-4, abs=1e-6)
    assert comparison.within_tolerance is True
    assert comparison.tolerance_mag == PARITY_ZP_TOLERANCE


def test_comparison_flags_a_zero_point_outside_the_recorded_tolerance():
    comparison = compare_zeropoint_to_reference(21.2, "ngc5128_b_002")
    assert comparison.within_tolerance is False
    assert comparison.delta_vs_skynet == pytest.approx(0.0523401, abs=1e-6)


def test_the_twenty_magnitude_trap_is_called_out_not_silently_compared():
    """Handing in Afterglow's bare correction must warn, not report a 20 mag error."""
    comparison = compare_zeropoint_to_reference(1.1474792352683736, "ngc5128_b_002")
    assert comparison.within_tolerance is False
    assert "afterglow_base_convention" in [w.code for w in comparison.warnings]


def test_an_unknown_field_returns_the_candidates_not_an_exception():
    reference = load_zeropoint_reference("ngc9999_z_000")
    assert [e.code for e in reference.errors] == ["not_found"]
    assert "ngc5128_b_002" in reference.errors[0].message


def test_a_missing_directory_returns_an_error_naming_the_env_override():
    reference = load_zeropoint_reference("ngc5128_b_002", "/nonexistent/fieldcal")
    assert [e.code for e in reference.errors] == ["directory_not_found"]
    assert "KEPLER_FIELDCAL_DATA_DIR" in reference.errors[0].message
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_fieldcal_reference.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.fieldcal_reference'`.

- [ ] **Step 4: Implement `tools/fieldcal_reference.py`**

Key implementation notes, so the engineer does not have to reverse-engineer the
fixtures:

- `fit_data.csv` columns used: `mag`, `mag_error`, `ref_mag`, `ref_mag_error`,
  `used_for_calibration`, `local_catalog_name`, `local_catalog_ra`,
  `local_catalog_dec`, `local_ref_mag`, `local_ref_mag_error`. **Many cells are
  empty strings**, so every numeric read goes through a `float`-or-`None`
  helper — a bare `float(...)` raises `ValueError: could not convert string to
  float: ''`.
- `used_for_calibration` is the string `"True"`/`"False"`; compare
  case-insensitively against `("true", "1")`.
- `fit_summary.json` keys used: `field_cal_zero_point_corr` (Afterglow-relative,
  add 20.0 for the absolute value), `afterglow_calibrated_zero_point`,
  `parity_zp_tolerance`, `zero_point_within_tolerance`, `catalog_queried`,
  `num_calibration_candidates`.
- The web-table value comes from
  `test_data/afterglow/afterglow_web_values_master.csv`, keyed by the `file`
  column against the frame filename.
- `frame_path` comes from a static map in this module, since the solve
  directory name (`ngc5128_b_002`) and the frame filename
  (`ngc5128_galaxy_b_001.fits`) do not match — the `_(1)`/`_(2)` upstream
  directory names were flattened separately from the frame rename.
  Only `ngc5128_b_002` has a bundled frame; the three NGC 5286 B solves
  describe frames that are not in `test_data/optical/` (only
  `ngc5286_globular_v_000.fits`, a V frame, ships). Set `frame_path=None` for
  those and attach a `frame_not_bundled` warning.
- `compare_zeropoint_to_reference` emits an `afterglow_base_convention`
  `ToolWarning` when `abs(zero_point - (reference.afterglow_zero_point - 20.0))`
  is under the tolerance — i.e. when the caller has plainly handed in a
  correction rather than an absolute zero point.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_fieldcal_reference.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 6: Commit**

```bash
git add tools/fieldcal_reference.py tools/models.py tests/test_fieldcal_reference.py
git commit -m "feat(tools): make the recorded zero-point ground truth a tool result

test_data/fieldcal/ and test_data/afterglow/ carry a complete offline parity
chain for NGC 5128 B that only pytest could read. Adds loaders, a solve from
the recorded rows (bit-exact on all four fields), and a comparison that warns
when a caller hands in Afterglow's base-20 correction instead of an absolute
zero point."
```

### Task 7: Offline field calibration end to end, compared to Afterglow

**Files:**
- Create: `tools/photometry.py`
- Modify: `tools/fieldcal_reference.py` (add `replay_catalog_sources`),
  `tools/registry.py`
- Test: `tests/test_fieldcal_reference.py` (extend)

**Interfaces:**
- Consumes: `resolve_optical_frame` (Task 4), `load_zeropoint_reference` (Task 6).
- Produces:
  - `tools.fieldcal_reference.replay_catalog_sources(field, directory=None) -> list[CatalogSource]`
  - `tools.photometry.calibrate_zeropoint(path, *, catalog_sources=None, catalogs=None, compare_to=None) -> ZeropointComparison`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fieldcal_reference.py`:

```python
def test_replay_returns_the_recorded_catalog_rows():
    sources = replay_catalog_sources("ngc5128_b_002")
    assert len(sources) == 35
    assert {s.catalog_name for s in sources} == {"APASS"}
    assert all(s.ra_hours is not None and s.dec_degs is not None for s in sources)


@pytest.mark.slow
def test_offline_field_calibration_lands_inside_the_afterglow_tolerance():
    """The full chain on a real frame with no network: extract, measure, match,
    resolve reference magnitudes, solve, compare.

    LIMITATION -- only the 35 *matched* APASS rows were recorded upstream, not
    the full cone-search response. This exercises photometry -> matching ->
    ref-mag resolution -> solve against real catalog values, but it cannot
    reproduce fit_summary.json's num_not_selected_by_field_cal (263): the rows
    that failed to match were never written down.
    """
    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    comparison = calibrate_zeropoint(
        frame.path,
        catalog_sources=replay_catalog_sources("ngc5128_b_002"),
        compare_to="ngc5128_b_002",
    )

    assert comparison.errors == []
    # A loose bound, deliberately: this re-measures photometry from pixels
    # rather than replaying the recorded instrumental magnitudes, so it will
    # not be bit-exact. test_solving_from_the_recorded_rows_reproduces_the_
    # recorded_solve is the bit-exact check.
    assert abs(comparison.delta_vs_afterglow) < 0.1


def test_calibrate_zeropoint_does_not_reach_the_network_when_rows_are_supplied(monkeypatch):
    """A supplied catalog must short-circuit query_catalogs entirely."""
    import algorithms.fieldcal.deps as deps

    def explode(*args, **kwargs):
        raise AssertionError("calibrate_zeropoint queried the network")

    monkeypatch.setattr(deps, "query_catalogs", explode)

    from tools.optical import resolve_optical_frame
    from tools.photometry import calibrate_zeropoint

    frame = resolve_optical_frame("ngc5128_galaxy_b_001")
    comparison = calibrate_zeropoint(
        frame.path,
        catalog_sources=replay_catalog_sources("ngc5128_b_002"),
        compare_to="ngc5128_b_002",
    )
    assert comparison.zero_point is not None
```

Add the import at the top of the file:

```python
from tools.fieldcal_reference import replay_catalog_sources
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_fieldcal_reference.py -q -k replay`
Expected: FAIL — `ImportError: cannot import name 'replay_catalog_sources'`.

- [ ] **Step 3: Implement `replay_catalog_sources`**

In `tools/fieldcal_reference.py`, build `CatalogSource` rows from the recorded
matched columns:

```python
def replay_catalog_sources(field: str, directory=None) -> list["CatalogSource"]:
    """Rebuild the catalog rows Skynet actually matched, for an offline solve.

    LIMITATION: ``fit_data.csv`` recorded only the rows that *matched* a
    detection, not the full cone-search response. Injecting these reproduces
    the photometry -> matching -> ref-mag -> solve path against real APASS
    values, but not the selection statistics: the catalog rows that failed to
    match were never written down, so ``num_not_selected_by_field_cal`` cannot
    be recovered from this fixture.
    """
    from algorithms.fieldcal.schemas import CatalogSource, Mag
    ...
```

Populate `id`, `catalog_name` from `local_catalog_name`, `ra_hours` from
`local_catalog_ra`, `dec_degs` from `local_catalog_dec`, and
`mags={<band>: Mag(value=local_ref_mag, error=local_ref_mag_error)}` where
`<band>` is the frame's `filter` column value.

- [ ] **Step 4: Implement `tools/photometry.py`**

`calibrate_zeropoint(path, …)`:

1. `describe_file(path)`; return errors for missing/not-a-file.
2. Open the frame; copy the header (the solve writes `PHOT_M0`/`PHOT_CAL` back
   into whatever header it is handed, and a tool must not mutate a caller's).
3. Wire the `algorithms.fieldcal.deps` seam exactly as
   `claude_photometry_haiku_tool.compute_field_cal_zero_point` does — the four
   assignments plus the `build_wcs_for_processing_run` lambda. Do not duplicate
   that block: move it into a shared `tools/photometry.py::wire_fieldcal_deps()`
   and have the CLI call it, so there is one wiring site.
4. If `catalog_sources` is supplied, pass it straight to
   `perform_field_calibration(..., catalog_sources=...)` — that parameter
   bypasses `deps.query_catalogs` entirely, which is what makes the offline
   path offline.
5. If `compare_to` is given, hand the resulting zero point to
   `compare_zeropoint_to_reference` and return that; otherwise return a
   `ZeropointComparison` with `reference=None`.

- [ ] **Step 5: Register `calibrate_zeropoint` and the reference tools**

Add to `tools/registry.py`: `list_zeropoint_references`,
`load_zeropoint_reference`, `compare_zeropoint_to_reference`,
`calibrate_zeropoint`. Write each schema description to say plainly that the
zero point is absolute and that Afterglow's is base-20-plus-correction.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_fieldcal_reference.py tests/test_tool_registry_coverage.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/photometry.py tools/fieldcal_reference.py tools/registry.py tests/test_fieldcal_reference.py
git commit -m "feat(tools): offline field calibration compared against Afterglow

calibrate_zeropoint runs the real extract -> measure -> match -> solve chain on
a bundled frame using the recorded APASS rows, then places the result against
both Skynet's and Afterglow's recorded numbers. No network."
```

### Task 8: Restore the OCL report's join key

**Files:**
- Create: `test_data/frame_provenance.json`
- Modify: `tools/fieldcal_reference.py`, `test_data/README.md`
- Test: `tests/test_fieldcal_reference.py` (extend)

**Interfaces:**
- Produces: `tools.fieldcal_reference.load_ocl_reference(frame_stem) -> dict`

- [ ] **Step 1: Write the failing test**

```python
def test_the_bundled_ocl_frames_join_back_to_the_recorded_sweep():
    """BL-6: the rename lost the join key; frame_provenance.json restores it."""
    from tools.fieldcal_reference import load_ocl_reference

    lum = load_ocl_reference("m15_globular_lum_000")
    assert lum["input_file"] == "messier 15_14111493_Lum_005.fits"
    assert lum["best_filter"] == "V"
    assert lum["winning_trial"]["metrics"]["zero_point"] == pytest.approx(
        20.141497332382436, abs=1e-12
    )

    openf = load_ocl_reference("m15_globular_open_000")
    assert openf["input_file"] == "messier 15_14111493_Open_000.fits"
    assert openf["best_filter"] is None
    # Corroborates the mapping independently: this is the one bundled frame
    # with no WCS keywords, and every trial failed for exactly that reason.
    assert all(
        t["pipeline"]["wcs"]["failure_reason"] == "no WCS solution found in FITS header"
        for t in openf["trials"]
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_fieldcal_reference.py -q -k ocl`
Expected: FAIL — `ImportError: cannot import name 'load_ocl_reference'`.

- [ ] **Step 3: Write the provenance map**

Create `test_data/frame_provenance.json`. Source of truth is
`/home/claude/skynet-data/pipeline_data/reorganize.py`, the upstream rename
script; copy every mapping whose destination is a bundled frame:

```json
{
  "_comment": "Upstream filename for each bundled frame. The recorded ground truth in fieldcal/ocl_filter_report.json keys its rows by the upstream name, and the rename to <object>_<category>_<filter>_<seq> lost that join. Source: /home/claude/skynet-data/pipeline_data/reorganize.py.",
  "_source": "skynet-data/pipeline_data/reorganize.py",
  "frames": {
    "m15_globular_lum_000": "messier 15_14111493_Lum_005.fits",
    "m15_globular_open_000": "messier 15_14111493_Open_000.fits"
  }
}
```

Include every other frame whose upstream name `reorganize.py` records, not just
the two OCL ones — the map costs a few kilobytes and the next fixture that
needs a join will already have it.

- [ ] **Step 4: Implement `load_ocl_reference`**

Read `test_data/frame_provenance.json`, map the stem to the upstream filename,
and return the matching entry from
`test_data/fieldcal/ocl_filter_report.json`'s `results` list. Return a dict with
a `not_found` error rather than raising when a stem has no recorded row.

- [ ] **Step 5: Document it**

Add a `frame_provenance.json` subsection to `test_data/README.md` under Layout,
stating what the map is for and that `ocl_filter_report.json` is otherwise
unjoinable. Note that upstream's OCL sweep only read the header WCS — it did
not plate-solve — which is why the Open frame failed there and why a working
`solve_astrometry` (Task 9) can take it further than the recorded pipeline did.

- [ ] **Step 6: Run the tests and commit**

```bash
uv run pytest tests/test_fieldcal_reference.py -q
git add test_data/frame_provenance.json test_data/README.md tools/fieldcal_reference.py tests/test_fieldcal_reference.py
git commit -m "fix(test_data): restore the join between bundled frames and the OCL sweep

ocl_filter_report.json keys its rows by upstream filename; the rename to
m15_globular_lum_000.fits stranded the ground truth. Records the mapping from
skynet-data's reorganize.py so it lives in this repository."
```

---

## 6. Phase 4 — Plate solving as a tool

Fixes BL-7.

### Task 9: `tools/wcs.py` — `solve_astrometry`

**Files:**
- Create: `tools/wcs.py`
- Modify: `tools/registry.py`, `algorithms/wcs/config.py` (documentation only),
  `CLAUDE.md`
- Test: `tests/test_wcs_solve_tool.py` (create)

**Interfaces:**
- Consumes: `algorithms.wcs.wcs.solve_wcs`, `algorithms.wcs.state.ProcessingRun`,
  `algorithms.wcs.header_utils.{estimate_pixel_scale_arcsec_per_pix, guess_icrs_radec_from_header}`,
  `tools.optical.resolve_optical_frame`.
- Produces: `solve_astrometry(path, *, index_path=None, write_header=False, timeout_s=None) -> WcsSummary`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wcs_solve_tool.py`. Two classes of test:

```python
"""Tool-layer coverage for plate solving.

BL-7: solve_wcs was reachable only by importing the algorithm package, needed a
processing-run object exposing ensure_wcs_solution() that nothing constructed,
and its astrometry.net index directory was never configured. The solve itself
is marked `network`-adjacent via a `solver` marker: it needs index files and a
solve-field binary that are not in this repository, so it must not run in the
default suite.
"""

import os
import shutil
from pathlib import Path

import pytest

from tools.wcs import solve_astrometry

ROOT = Path(__file__).resolve().parents[1]

solver_available = pytest.mark.skipif(
    shutil.which("solve-field") is None or not os.environ.get("ANET_INDEX_PATH"),
    reason="needs solve-field on PATH and ANET_INDEX_PATH set",
)


def test_a_missing_file_returns_an_error_not_an_exception():
    summary = solve_astrometry("test_data/optical/does_not_exist.fits")
    assert [e.code for e in summary.errors] == ["file_not_found"]


def test_an_unconfigured_solver_degrades_with_a_named_warning(monkeypatch):
    """CLAUDE.md: both backends degrade to 'unavailable' rather than failing."""
    monkeypatch.delenv("ANET_INDEX_PATH", raising=False)
    monkeypatch.delenv("ATLAS_CATALOG_ROOT", raising=False)
    summary = solve_astrometry(ROOT / "test_data" / "optical" / "m15_globular_open_000.fits")
    assert summary.has_wcs is False
    assert "solver_unavailable" in [w.code for w in summary.warnings]
    assert "ANET_INDEX_PATH" in " ".join(w.message for w in summary.warnings)


def test_a_frame_that_already_has_a_wcs_is_not_resolved_by_default():
    summary = solve_astrometry(ROOT / "test_data" / "optical" / "ngc5128_galaxy_b_001.fits")
    assert summary.has_wcs is True
    assert "wcs_from_header" in [w.code for w in summary.warnings]


@pytest.mark.solver
@solver_available
def test_the_solver_runs_and_reports_its_outcome_either_way():
    """RECORDED BEHAVIOUR, NOT AN ASPIRATION.

    A real run of this frame with ANET_INDEX_PATH=/usr/share/astrometry/data
    accepted the index directory, derived correct RA/Dec hints from the header
    (21.4995 h, +12.167 deg), searched for 670 s and returned NO SOLUTION --
    because solve_wcs hands astrometry.net radius=180 and a 0.1-60 arcsec/px
    scale window by design (algorithms/wcs/wcs.py:642-645, and the comment at
    :543-547 explaining why a caller may not narrow them).

    So this test asserts the *contract*, not a successful solve: the tool must
    return, must not raise, and must say which backend it reached. If it does
    converge, tighten this test to the centre below. Do not loosen an assertion
    to make a non-convergence pass silently -- a documented non-convergence is
    a finding.
    """
    summary = solve_astrometry(
        ROOT / "test_data" / "optical" / "m15_globular_open_000.fits", timeout_s=900
    )
    assert summary.errors == []
    codes = [w.code for w in summary.warnings]
    assert "solver_unavailable" not in codes
    if summary.has_wcs:
        # M15: RA 21:29:58.3, Dec +12:10:01 from the frame's own header.
        assert summary.center_ra_deg == pytest.approx(322.49, abs=0.2)
        assert summary.center_dec_deg == pytest.approx(12.167, abs=0.2)
    else:
        assert "no_solution" in codes
```

Register the marker in `pyproject.toml` alongside `slow` and `network`:

```toml
markers = [
    "slow: runs source extraction or photometry over a real frame",
    "network: opens a socket; also needs KEPLER_TEST_NETWORK=1",
    "solver: needs astrometry.net index files and a solve-field binary",
]
```

and deselect it by default the same way `network` is.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_wcs_solve_tool.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.wcs'`.

- [ ] **Step 3: Implement `tools/wcs.py`**

The four things this wrapper exists to supply, all of which a caller currently
has to know:

1. **Construct the state object.** `solve_wcs` calls
   `processing_run.ensure_wcs_solution()`; use
   `algorithms.wcs.state.ProcessingRun`, not an ad-hoc class. A bare object
   raises `AttributeError` (verified).
2. **Distinguish "no index files" from "no solution".** When `ANET_INDEX_PATH`
   is unset and no ATLAS catalog root is configured, warn
   `solver_unavailable` and name the variable, rather than returning a bare
   no-solution. That is the difference between "this field is hard" and "you
   never told me where the index files are" — and it is the single most useful
   thing this wrapper does, because the index files have been present and
   unconfigured on this host all along.
3. **Bound the run.** The astrometry.net search is all-sky across a 0.1–60
   arcsec/px window by design and took 670 s to fail on the one frame that
   needs it. Take a `timeout_s`, pass it to the backend, and return
   `no_solution` (a warning, not an error) when it expires. Do **not** pass
   `pixel_scale_hint_arcsec` expecting it to help: it feeds only the acceptance
   threshold and the ATLAS scale narrowing, and ATLAS is unavailable here
   (see BL-7). Passing it is harmless and slightly tightens acceptance, so
   derive it from `header_utils.estimate_pixel_scale_arcsec_per_pix(header)`
   anyway — just do not describe it as a speedup.
4. **Short-circuit a frame that already has a WCS.** 38 of the 39 bundled
   frames do. Return the header WCS with a `wcs_from_header` warning unless the
   caller passes `force=True`; otherwise the obvious first call an agent makes
   costs 11 minutes and returns nothing new.

**Open question for the maintainer, not for the implementer:** whether Kepler
should expose the search radius and scale window that upstream deliberately
keeps internal. Narrowing them to the header's `SECPIX` would very likely make
this solve tractable, and would equally likely be the "silently cause misses"
outcome `wcs.py:543-547` warns about. Raise it; do not decide it inside this
task.

Copy the header before handing it to `solve_wcs`; the solve writes its result
back into whatever header it is given. Only write to the file when
`write_header=True`, and never for a frame under `test_data/` — guard on the
resolved path and return a `ToolError(code="refusing_to_modify_fixture")`
otherwise. The fixtures are byte-preserved copies and a rewritten header would
silently invalidate `tests/test_wcs_headers.py`.

- [ ] **Step 4: Run the default tests**

Run: `uv run pytest tests/test_wcs_solve_tool.py -q`
Expected: PASS, 3 tests, 1 deselected (`solver`).

- [ ] **Step 5: Run the solver test explicitly**

Run:
```bash
ANET_INDEX_PATH=/usr/share/astrometry/data uv run pytest tests/test_wcs_solve_tool.py -q -m solver
```
Expected: PASS in roughly 11 minutes, most likely on the `no_solution` branch —
that is what a real run of this frame did. If it converges instead, tighten the
test to the field centre. Never loosen an assertion to make a non-convergence
pass silently.

- [ ] **Step 6: Correct the CLAUDE.md claim**

`CLAUDE.md` currently says end-to-end runs need "astrometry.net index files plus
a `solve-field` binary on `PATH`" and concludes "This is why full parity has
never been validated here." Amend to state what is actually true after this
task:

- `solve-field` is at `/usr/bin/solve-field` and index files 4107–4119 are at
  `/usr/share/astrometry/data` on the development host; `ANET_INDEX_PATH` must
  be set to reach them, and nothing in the repo sets it.
- No UCAC4/UCAC5 data exists on this host, so the ATLAS backend stays
  unavailable and its pixel-scale narrowing never runs.
- The astrometry.net path searches all-sky across 0.1–60 arcsec/px by design;
  a run on `m15_globular_open_000.fits` took 670 s and returned no solution.
  Reaching the backend is now demonstrated; **a successful solve is not**, and
  the honest claim is "the solver is wired and exercised", not "parity is
  validated".
- The `solver`-marked tests are the gate.

- [ ] **Step 7: Register and commit**

```bash
git add tools/wcs.py tools/registry.py tests/test_wcs_solve_tool.py pyproject.toml CLAUDE.md
git commit -m "feat(tools): add solve_astrometry

Wraps algorithms.wcs.solve_wcs with the two things every caller had to supply
by hand: a ProcessingRun exposing ensure_wcs_solution(), and a pixel-scale hint
from the frame's own header. Reports an unconfigured index path as a named
warning instead of a silent no-solution."
```

---

## 7. Phase 5 — The curated pulsar periods

Fixes BL-8.

### Task 10: Put the curated period on `PulsarScan`

**Files:**
- Create: `test_data/pulsar/curated_periods.json`
- Modify: `tools/pulsar.py`, `tools/models.py`, `tools/runner.py`,
  `tests/conftest.py`
- Test: `tests/test_pulsar_sonification.py` (extend)

**Interfaces:**
- Produces: `PulsarScan.curated_period_s: float | None`,
  `PulsarScan.curated_difficulty: str | None`,
  `PulsarScan.period_source: str | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pulsar_sonification.py`:

```python
def test_stage_zero_reports_the_curated_period():
    """BL-8: the reference the tests fold at was unreachable from the tools.

    test_data/README.md: "This document, not ATNF, is the reference the tests
    compare against." An agent with no network had no way to reach it, and a
    blind search finds only one of these five sources.
    """
    from tools.pulsar import resolve_pulsar_scan

    scan = resolve_pulsar_scan("B0329+54")
    assert scan.curated_period_s == 0.7145197
    assert scan.curated_difficulty == "Easy"
    assert scan.period_source == "Curated pulsars.docx"


def test_every_bundled_scan_carries_its_curated_period():
    from tools.pulsar import list_pulsar_scans

    listing = list_pulsar_scans()
    assert listing.count == 5
    assert all(s.curated_period_s is not None for s in listing.scans)


def test_the_curated_periods_fixture_matches_the_conftest_table():
    """One source of truth. If these diverge, the docx is the arbiter."""
    import json
    from pathlib import Path

    from tests.conftest import PULSAR_PERIODS_S

    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "test_data" / "pulsar" / "curated_periods.json").read_text()
    )
    assert {k: v["period_s"] for k, v in fixture["pulsars"].items()} == PULSAR_PERIODS_S
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_pulsar_sonification.py -q -k curated`
Expected: FAIL — `AttributeError: 'PulsarScan' object has no attribute 'curated_period_s'`.

- [ ] **Step 3: Write the fixture**

Create `test_data/pulsar/curated_periods.json`, transcribed from
`tests/conftest.py::PULSAR_PERIODS_S`, `PULSAR_ATNF` and `PULSAR_DIFFICULTY`,
which are themselves the docx's "Period(Literature)" column:

```json
{
  "_comment": "Literature periods and difficulty ratings from 'Curated pulsars.docx', which ships beside the scans. That document, not ATNF, is the reference the tests compare against (test_data/README.md). The scan files carry no P_topo header, so the period always comes from outside the data.",
  "_source": "test_data/pulsar/Curated pulsars.docx",
  "pulsars": {
    "b0329": {"period_s": 0.7145197,   "difficulty": "Easy",                 "atnf_p0_s": 0.714519699725801},
    "b1133": {"period_s": 1.187913066, "difficulty": "Lightly Challenging",  "atnf_p0_s": 1.1879172746306204},
    "b1933": {"period_s": 0.358738411, "difficulty": "More Challenging",     "atnf_p0_s": 0.3587451401989297},
    "b2021": {"period_s": 0.529196918, "difficulty": "Lightly Challenging",  "atnf_p0_s": 0.5291969178083342},
    "b2045": {"period_s": 1.961572304, "difficulty": "Most Challenging",     "atnf_p0_s": 1.9615846233291023}
  }
}
```

- [ ] **Step 4: Read it in `_scan_summary`**

Add the three fields to `PulsarScan` in `tools/models.py`, then in
`tools/pulsar.py` load `curated_periods.json` once (module-level, guarded so a
missing file is a warning, not an import error) and match a scan to a key with
the existing `_normalize_pulsar_name` — the keys are already in its normalized
form (`b0329`), so `"b0329" in _normalize_pulsar_name(scan.source_name)` is the
lookup.

- [ ] **Step 5: Repoint `tests/conftest.py` at the fixture**

Replace the literal `PULSAR_PERIODS_S` dict with a read of
`curated_periods.json` so the number lives in one place. Keep the surrounding
comment block — it explains why the docx and not ATNF is the arbiter, and that
reasoning is not in the JSON.

- [ ] **Step 6: Update the runner system prompt**

In `tools/runner.py`, amend the ATNF sentence so the offline path is stated
first:

```
resolve_pulsar_scan reports a curated literature period for every bundled \
scan; prefer it over step 2's blind search, which succeeds on only the \
brightest of the five. search_atnf gives a catalogued period for sources \
without a bundled scan, but it needs the network.
```

- [ ] **Step 7: Run the tests and commit**

```bash
uv run pytest tests/test_pulsar_sonification.py -q
git add test_data/pulsar/curated_periods.json tools/pulsar.py tools/models.py tools/runner.py tests/conftest.py tests/test_pulsar_sonification.py
git commit -m "feat(pulsar): surface the curated literature period on PulsarScan

The reference the tests fold at lived in a .docx and a pytest module. An agent
with no network had to blind-search, which works on one of the five bundled
scans. Moves the table to a fixture both the tools and conftest read."
```

---

## 8. Phase 6 — Close the archive-to-analysis loop and the documentation

Fixes BL-11 and BL-12.

### Task 11: Make a downloaded frame usable, and correct the docs

**Files:**
- Modify: `tools/mast.py`, `tools/optical.py`, `README.md`,
  `docs/tool-architecture.md`, `CLAUDE.md`
- Test: `tests/test_optical_registry.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
def test_the_download_directory_is_searched_too(tmp_path, monkeypatch):
    """BL-11: search_mast(download=True) wrote FITS that no tool could open."""
    import shutil

    monkeypatch.setenv("KEPLER_FITS_DOWNLOAD_DIR", str(tmp_path))
    shutil.copy2(OPTICAL / "ngc5128_galaxy_b_001.fits", tmp_path / "downloaded.fits")

    listing = list_optical_frames()
    stems = {Path(f.path).stem for f in listing.frames}
    assert "downloaded" in stems

    frame = resolve_optical_frame("downloaded")
    assert isinstance(frame, OpticalFrame)
    assert frame.has_wcs is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_optical_registry.py -q -k download`
Expected: FAIL — `"downloaded" not in stems`.

- [ ] **Step 3: Search the download directory as a second root**

In `tools/optical.py`, make `_optical_data_dir` return a *list* of roots —
`KEPLER_OPTICAL_DATA_DIR` (or `test_data/optical`) plus
`tools.config.FITS_DOWNLOAD_DIR` when it exists — and have
`list_optical_frames`/`resolve_optical_frame` walk all of them. Keep
`search_root` reporting the primary root and add a `search_roots: list[str]`
field to `OpticalFrameList` so the caller can see both. An explicit `directory`
argument still means exactly that one directory.

- [ ] **Step 4: Cross-reference from the archive tools**

In `tools/mast.py`, extend the existing download warning so it names the next
step:

```python
warnings.append(
    f"downloaded {len(local_paths)} file(s) to {FITS_DOWNLOAD_DIR}; "
    f"list_optical_frames now sees them, and describe_image_wcs / "
    f"calibrate_zeropoint take their paths"
)
```

- [ ] **Step 5: Correct the documentation**

- `README.md`: the photometry-tool section says `--list-targets` lists targets
  "it can run against with no live archive query". True of *resolution*, but
  field calibration is on by default and queries VizieR. State that the zero
  point needs either `--no-field-cal`, a `--zero-point` override, or the new
  offline `compare_to` path.
- `README.md` and `docs/tool-architecture.md` §2: add the new tools to the
  local-tool lists and strike `solve_astrometry` from "next tools" now that it
  exists.
- `CLAUDE.md` Commands: note that `npm run typecheck` needs `npm install`
  first — `node_modules/` is not present in a fresh checkout and the typecheck
  is not a CI job (BL-12).

- [ ] **Step 6: Run everything and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add -A
git commit -m "feat(tools): close the archive-to-analysis loop, and correct the docs

Downloaded FITS under KEPLER_FITS_DOWNLOAD_DIR are now visible to the frame
registry, so search_mast(download=True) leads somewhere. Documents that field
calibration is on by default in the photometry CLI, and that npm run typecheck
needs npm install first."
```

---

## 9. Deferred: the TypeScript-backed tools (BL-9, BL-10)

> **Partly superseded — see §1.0.** This section was written against `main`,
> where neither tool had a Python runtime. On `dev` the HR diagram has one
> (`algorithms/hrdiagram_py/` plus seven registered tools), and the isochrone
> dependency this section calls unfixable is fetched from the PARSEC CMD
> service. What still holds: the variable-star half (BL-10) is untouched, and
> neither tool has any offline fixture. Read the runtime-decision discussion
> below as history that explains the shape of the dev-side code, not as an open
> question — except for BL-10, where it remains open.

**These are a separate subsystem and need their own plan.** They are deferred
here deliberately, not overlooked: the HR diagram and the variable-star tools
share a runtime decision this plan cannot make for them, and one of them has a
genuine external-data dependency that no amount of wiring resolves.

### What is actually blocked

| | HR diagram | Variable star |
|---|---|---|
| Runtime | none — nothing executes the TypeScript | none |
| Input data | none in `test_data/` | none in `test_data/` |
| Catalog access | **solvable** — `algorithms/query` already queries VizieR for Gaia/2MASS/APASS/WISE and MWSC | **solvable** — VizieR/ASAS-SN/ZTF |
| Model grids | **blocked** — needs PARSEC or MIST plus interpolation and bolometric corrections | n/a |

Three of the HR diagram's four severed endpoints (`/cluster/catalog`,
`/cluster/fsr`, `/cluster/allMWSC`) are catalog work this repository can already
do. The fourth is not: `GET /cluster/isochrone` returned
`{data: [[colour, absolute_mag], …], iSkip}` — *already interpolated for the
requested filter triple*. Astromancer ships no grid (verified: `src/assets/`
holds two font families and a `static/` folder), and neither does Kepler.

### The decision that has to be made first

`CLAUDE.md` is explicit that a Python port is not a general licence: "A tool
that needs TypeScript behaviour at runtime today has to go through a Python
port; `algorithms/pulsar/` is the one instance, and `docs/extraction.md`
(Pulsar Sonification §5) records why that was allowed there and why it is not a
general licence." The pulsar port was justified because the upstream sonifier
was welded to browser APIs and could not run headless. **The HR-diagram code is
not** — `computePlotDelta`, the FSR cut and the result derivations are plain
arithmetic on plain arrays. So the pulsar precedent does not automatically
extend, and the choice between a Node runtime, a Python port, and leaving it as
a typechecked source module is a real architectural decision.

### Recommended shape for that plan

1. **Decide the runtime.** Options, in the order I would evaluate them: (a) a
   Node subprocess seam mirroring the `solve-field` subprocess pattern
   `algorithms/wcs/` already uses — no port, no divergence risk, but adds Node
   to the runtime dependency set and `package.json` currently has no build step;
   (b) a Python port under `algorithms/hrdiagram_py/` marked `# PORTED:` like
   `algorithms/pulsar/`, with the divergences enumerated in
   `docs/extraction.md`; (c) leave it as source and build nothing. Requires
   brainstorming with the maintainer — do not pick one from a plan document.
2. **Source the isochrone grid.** PARSEC (CMD web interface) and MIST both
   publish downloadable grids. This is a licensing and repository-size question
   as much as a technical one: the grids are large, `.gitignore` already
   excludes `data/`, and `test_data/` is at 175 MB before adding any. Decide
   whether Kepler carries a grid, fetches one, or requires the operator to
   supply one via an env var like the `ANET_INDEX_PATH` precedent.
3. **Build the cluster ingest on `algorithms/query`.** A cone search returning
   Gaia astrometry plus multi-band photometry is exactly what
   `query_catalogs(wcs=…)` already does; the HR-diagram `Source` shape is a
   normalization of it.
4. **Record a cluster fixture in `test_data/`.** One well-studied open cluster
   (M67 is the conventional choice — old enough for a clean turnoff, well
   covered by Gaia and 2MASS) as a recorded VizieR response, so the FSR cut and
   `computePlotDelta` get an offline test the way `calc_solution` has one.
5. **Then, and only then, a lookup registry** — `list_clusters` /
   `resolve_cluster` over that fixture, mirroring Tasks 4 and 5.

Step 4 is the one that makes the user's original request literally true for the
HR diagram, and it is fifth in the list because the four steps above it are its
prerequisites.

---

## 10. What this plan cannot fix

Everything below surfaced during the investigation and **no task above closes
it**. Each is here because it needs something this plan does not have: a
maintainer's decision, data that is not in this repository, a fixture nobody
recorded, or a different topic entirely. None is an oversight; grouping them by
*why* they are stuck is the point, because that is what tells you who unblocks
each one.

### 10.1 Needs a maintainer decision, deliberately not made here

**The astrometry.net search window (BL-7).** This is the one that stops plate
solving from being useful on the only frame that needs it. `solve_wcs`
constructs `WcsCalibrationSettings()` internally and exposes just two of its
fields, under an explicit rationale:

> Search radii, scale windows and source caps stay internal: they are accuracy
> tuning, not a product choice, and an observer narrowing the search would
> silently cause misses.
> — `algorithms/wcs/wcs.py:543-547`

So astrometry.net always gets `radius=180` and a 0.1–60 arcsec/px window. On
`m15_globular_open_000.fits` that ran 670 s and returned nothing, on a frame
whose own header says `SECPIX = 0.5864922312362758`. Narrowing the window to
the header value would very probably make the solve tractable — and would be
precisely the failure mode that comment warns about. **Task 9 therefore bounds
the run with a timeout and does not narrow anything.** Until this is decided,
`solve_astrometry` is a tool that reaches the backend correctly and reports an
honest non-result. Deciding it is a change to extracted behaviour and belongs
in its own PR under the extraction contract.

**The TypeScript runtime (BL-9, BL-10).** Node subprocess, Python port, or
leave it as typechecked source. `CLAUDE.md` is explicit that `algorithms/pulsar/`
is not a general licence — that port was justified by browser-welded audio APIs,
and the HR-diagram code is plain arithmetic on plain arrays, so the precedent
does not extend on its own. See §9.

**Whether Kepler carries, fetches, or requires an isochrone grid.** As much a
licensing and repository-size question as a technical one: `test_data/` is
already 175 MB and `.gitignore` excludes `data/`. The `ANET_INDEX_PATH`
precedent — operator supplies the bulk data, repo carries only the pointer — is
the obvious model, but that is a call for the maintainer.

### 10.2 Needs data that is not in this repository

**~~Isochrone model grids.~~ Superseded — see §1.0.** This was written against
`main`, where the HR diagram had no isochrone source at all. `dev` solves it:
`algorithms/hrdiagram_py/isochrones.py::fetch_parsec_isochrone_grid` fetches
PARSEC grids from the CMD service and caches them in `isochrone_cache/`. What
survives is narrower and belongs in §10.3 rather than here: the fetch is a live
network call with no recorded fixture behind it.

**Cluster photometry and variable-star light curves.** There is none in
`test_data/`. On `dev` this now bites harder than it did on `main`, because the
HR-diagram chain exists and still cannot be exercised offline: Gaia crossmatch
is a live VizieR query and the isochrone grid is a live HTTP fetch, so no part
of `tools/hr_diagram.py` can be covered by the default deterministic suite. A
lookup registry for HR-diagram or variable-star inputs likewise has nothing to
look up until a fixture is recorded.

**UCAC4/UCAC5 catalog data.** Absent from this host entirely. The ATLAS
triangle solver is therefore unreachable, and **no test this plan adds
exercises that backend at all** — including its pixel-scale narrowing, which is
the one place `pixel_scale_hint_arcsec` actually does something
(`algorithms/wcs/wcs.py:786-792`). Half of `algorithms/wcs/`'s solver surface
stays unvalidated after Phase 4, and the plan cannot change that.

**The B-band frames behind three of the four recorded zero-point solves.**
`ngc5286_b_000`, `_001` and `_002` describe NGC 5286 exposures in B; the only
NGC 5286 frame bundled is `ngc5286_globular_v_000.fits`, a V frame. So Task 6
checks all four solves bit-exactly at the `calc_solution` level, but **only
NGC 5128 B can be driven end-to-end from pixels** (Task 7). Three quarters of
the recorded ground truth is reachable as numbers and not as a pipeline.

### 10.3 Needs a fixture nobody recorded upstream

**The unmatched catalog rows (BL-4).** `fit_data.csv` recorded the 35 APASS rows
that *matched* a detection. The cone-search rows that did not match were never
written down, so `fit_summary.json`'s `num_not_selected_by_field_cal: 263` is
unreproducible from the shipped fixture, and Task 7's replay validates
photometry → matching → ref-mag → solve but not catalog selection. Closing this
needs a live VizieR cone search re-recorded as a new fixture — a network
operation producing a new artifact, against two of this plan's own constraints.
Task 7's docstring and test say so explicitly rather than letting a partial
replay pass for a full one.

**The 36 frames above the 9 MB cut-off.** The Afterglow web table covers 73
subjects (~1.5 GB); `test_data/optical/` carries the 37 under 9 MB plus the two
OCL frames. Widening coverage means adding large incompressible binaries to
plain git, permanently. `test_data/README.md` already names Git LFS as the
answer; that is an infrastructure change, not a broken link.

### 10.4 Real problems, different topic

These are tracked elsewhere and this plan must not quietly absorb them.

**`docs/analysis/pulsar-pipeline-review.md` — open pulsar tool bugs.** The
periodogram chart hard-codes "Polarization XX" while the default channel is
`sum`; frequency-mode periodograms inherit period-mode axis semantics; a constant
light curve raises `ZeroDivisionError` out of `lomb_scargle()`; `top_peaks` is
ambiguous between seconds and Hz; `fold_lightcurve()` has no guard against a tiny
period; Stage 0 can still raise `OSError` on an unreadable file. Every one is a
tool-correctness bug rather than a local-data link. **Task 10 edits
`tools/pulsar.py` and must leave all of them alone** — fixing one in passing
would put a behaviour change in a documentation-and-plumbing PR.

**`docs/pulsar-tool-pipeline.md` §7 (name-to-scan resolution) was stale and has
been fixed** in the docs reorganization — it described `list_pulsar_scans` /
`resolve_pulsar_scan` as missing after they had landed. Task 10 adds a curated
period to that Stage 0; keep the doc in step.

**`docs/analysis/algorithm-remediation-plan.md`'s 109 findings and 7 blockers.**
Algorithm correctness, untouched here by design. The extraction contract holds
throughout this plan: no task moves a numeric expression.

### 10.5 What "all tasks complete" will not mean

**Not full Skynet parity.** This plan validates the *tool seam* — that a tool
can find local data, run the real code path against it, and return a number
comparable to recorded ground truth. It does not validate that Kepler's whole
pipeline reproduces Skynet's. The single end-to-end number it pins (Task 7)
re-measures photometry from pixels and is asserted to 0.1 mag; the bit-exact
claim lives in Task 6, which replays recorded inputs. Those are different
claims and the tests say which is which.

**Not a working plate solve.** Task 9 demonstrates that the solver is wired,
configured and exercised. Whether it *converges* on the one frame that needs it
is unresolved and, per §10.1, may stay unresolved until the search-window
question is answered.

---

## 11. Verification

After each phase:

```bash
uv run pytest                            # default no-network suite
python3 -m compileall tools algorithms   # syntax smoke
git diff --check                         # whitespace
```

After Phase 4, additionally:

```bash
ANET_INDEX_PATH=/usr/share/astrometry/data uv run pytest -m solver
```

Full-suite expectations at the end of the plan:

- `tests/test_astrometry_tool.py` — 43 passing (39 parametrized + 4).
- `tests/test_optical_registry.py` — 14 passing.
- `tests/test_fieldcal_reference.py` — 17 passing, 1 `slow`.
- `tests/test_calibration_tool.py` — 2 passing.
- `tests/test_tool_registry_coverage.py` — 3 passing.
- `tests/test_wcs_solve_tool.py` — 3 passing, 1 `solver`-deselected.
- `TOOL_FUNCTIONS` grows from 23 to 36: +6 in Task 3, +2 in Task 5, +4 in
  Task 7, +1 in Task 9.
- Every existing test still passes unchanged; no algorithm numerics moved.

---

## 12. Self-review notes

- **BL-12** is the only finding not given its own task; it is folded into
  Task 11 Step 5 as a one-line `CLAUDE.md` correction, which is proportionate.
- **BL-9 and BL-10** are deliberately not given tasks. §9 states why, what is
  blocked, and what the follow-on plan needs to decide. Writing TDD steps for
  a runtime that has not been chosen would be a placeholder in disguise.
- **§10 is the scope boundary and should be read before the tasks are
  scheduled.** Four items there need a maintainer's answer or data that is not
  in this repository, and two of them bound what "done" means: the ATLAS solver
  backend is untestable on any host without UCAC data, and three of the four
  recorded zero-point solves have no bundled frame, so only NGC 5128 B can be
  driven end-to-end from pixels. Neither is discoverable from the task list
  alone.
- **Task 7 Steps 3–4** describe implementations in prose rather than complete
  code, because both are assemblies of functions specified exactly elsewhere in
  this plan (`replay_catalog_sources` from the columns listed in Task 6 Step 4;
  `calibrate_zeropoint` from the deps-wiring block already in
  `tools/claude_photometry_haiku_tool.py:95-105`). The tests are complete and
  are the contract.
- **Naming consistency check:** `ZeropointSolution.zero_point` (Task 2) is the
  name used by Tasks 6 and 7. `resolve_optical_frame` (Task 4) is the name used
  by Tasks 5, 7, 9 and 11. `load_zeropoint_reference` /
  `compare_zeropoint_to_reference` (Task 6) are the names used by Task 7.
- **BL-7 was corrected mid-investigation.** A first draft of Task 9 told the
  implementer to pass `pixel_scale_hint_arcsec` to speed the solve up. Reading
  `algorithms/wcs/wcs.py:642-645` after the real run showed the hint never
  reaches the astrometry.net scale window — it feeds the acceptance threshold
  and the ATLAS backend, and ATLAS has no catalog data on this host. The task
  now bounds the run with a timeout instead and raises the search-window
  question to the maintainer rather than answering it.
- **The whole investigation was run against the wrong branch and then
  corrected.** `main` was the checkout; `origin/dev` is 19 commits ahead and had
  already fixed BL-1 outright and built most of BL-3 and BL-9. Every finding was
  re-verified in a `dev` checkout before this document was committed, and §1.0
  records the outcome per finding rather than silently editing the evidence.
  Tasks 1, 4, 5 and §9 are left in place with pointers to §1.0 instead of being
  deleted: their tests and header-reading code still apply, and the `main`-side
  evidence explains what the dev-side code is for. **A reader who skips §1.0
  will implement work that already exists.**
- **The `slow` and `solver` markers** keep the two expensive additions
  (pixel-level field calibration; a real plate solve) out of the default run,
  per the repository's "default checks stay deterministic and bounded"
  constraint.
