# Kepler Algorithm Remediation Plan

Date: 2026-08-10
Status: proposed
Scope: correctness of the algorithms in `algorithms/wcs/`, `algorithms/photometry/`,
`algorithms/fieldcal/`, `algorithms/catalogs/`, `algorithms/query/`,
`algorithms/lightcurve/`, `algorithms/periodogram/`, `algorithms/hrdiagram/`.

This document is the output of a four-part algorithm review and the plan for
rolling out fixes. It is deliberately **separate from**
[`tool-architecture.md`](../tool-architecture.md), which owns file organization and
tool wiring and asserts nothing about correctness.

---

## 1. What was reviewed, and how

Four reviewers worked in parallel over 34 TypeScript files and the five Python
domain packages — about 22,400 lines.

| Reviewer | Scope | Upstream available for diffing |
|---|---|---|
| WCS | `algorithms/wcs/` incl. the extracted astrometry stack | `/home/claude/skynet` |
| Photometry / field cal | `algorithms/photometry/`, `algorithms/fieldcal/`, and the extracted `skylib` subset | `/home/claude/skynet` |
| Catalogs / query | `algorithms/catalogs/`, `algorithms/query/` | `/home/claude/skynet`, `/home/claude/afterglow-core` |
| TypeScript | `algorithms/periodogram/`, `algorithms/lightcurve/`, `algorithms/hrdiagram/` | `/home/claude/astromancer` @ `657b709` |

Every reviewer diffed against upstream rather than reasoning about provenance,
and verified numeric claims with throwaway scripts against the real stack
(numpy 2.4.6, scipy 1.18.0, astropy 8.0.1, numba 0.66.0, sep 1.4.1). No
repository file was modified and no live provider call was made.

**109 actionable findings. 7 blockers.**

### The headline: the extraction is faithful

`algorithms/wcs/`, `algorithms/photometry/` and `algorithms/fieldcal/` have **zero** extraction-introduced
defects. Every difference from upstream is confined to import lines and
`# EXTRACTED:` provenance comments; `header_utils.py` is byte-identical to
`runners/utils.py:159-441`. The TypeScript is likewise byte-identical to
Astromancer, including `algorithms/periodogram/core/lomb-scargle.ts` against
`astromancer/src/app/tools/shared/data/utils.ts`.

**So what follows is not a report on a botched extraction. It is a report on what
Skynet and Astromancer have been shipping to production.** That reframing matters
for prioritization: these defects have been live, and the fields they touch have
been calibrated with them.

The five genuine extraction artifacts are all in `algorithms/catalogs/`/`algorithms/query/` or are
documentation claims rather than code — see §4, class C.

---

## 2. The prerequisite: every fix needs a targeted test

This repository still has very little automated coverage. The architecture
migration makes the Python algorithms importable under `algorithms/`, but it
does not prove that a numeric edit is correct.

You cannot safely fix a weighted zero-point solver, a triangle matcher, or a
Lomb-Scargle normalization without a check tied to the behavior being changed.
Several findings below are *pairs of errors that currently cancel* —
`getMass`/`getPhysicalRadius` (TS-21) has two 1000× unit errors that cancel
exactly, and "fixing" either one alone introduces a 10⁶× error. Without a
targeted test, that is a live hazard.

### Test rule for every remediation PR

Each bug-fix PR must include the smallest test that would have failed before the
fix and passes after it. Prefer tiny deterministic inputs over broad
characterization suites.

Good first tests are pure-function checks that need no remote services or large
data:

- catalog band/filter resolution;
- `calc_solution` zero-point behavior;
- Lomb-Scargle helpers;
- CCM extinction helpers;
- `equatorial2Galactic`;
- `floatMod`;
- `getPeriodStep`;
- sexagesimal parsing and formatting.

For image, catalog-query, and field-calibration bugs, keep tests as small as the
bug allows:

- use synthetic FITS headers before real FITS products;
- use synthetic source/catalog rows before downloaded catalogs;
- use mocks or tiny in-memory tables before live providers;
- use one focused fixture per changed behavior.

When a full runtime dependency is unavoidable, mark that test separately and keep
the default test suite deterministic. The fix PR should still include a local
unit-level test for the decision logic whenever possible.

---

## 3. What makes a finding urgent for Kepler specifically

Severity alone is the wrong sort key for a tool package. Kepler's callers are
LLMs, and an LLM cannot tell a plausible wrong number from a right one. So every
finding carries a second attribute:

- **Silent** — returns a plausible, finite, wrong answer with no error and no
  warning. The agent will believe it and reason onward from it.
- **Loud** — raises, hangs, returns empty, or produces an obvious `NaN`. The
  agent can tell something went wrong and can report it.

A silent 1.4-magnitude zero-point error is worse for this package than a crash,
even though a crash looks more dramatic. **Of the 7 blockers, 3 are silent.**
Those three are the top of the queue.

---

## 4. Finding classes (provenance, not permission)

Under the current scope every class gets fixed. Class is recorded so each fix PR
can say whether it is restoring extraction intent, diverging from upstream, or
addressing an operational hazard.

| Class | Meaning | Count |
|---|---|---:|
| **A** | Upstream defect already documented in `docs/extraction.md` | 14 |
| **B** | Upstream defect documented nowhere — the review's main yield | ~90 |
| **C** | Introduced by the extraction | 5 |
| **D** | Operational hazard rather than a numeric error | ~15 |

The five class-C findings, in full, since they are the only things the extraction
itself broke:

| ID | What |
|---|---|
| CAT-08 | `docs/extraction.md`, Query §5.7 claims the runner passes a fresh `constraints` dict per catalog. It does not — SkyMapper's `flags=0` leaks into every subsequent catalog **and** into the caller's dict |
| CAT-17 | `_round_for_cache`'s docstring claims the region "is never shrunk". The centre snap moves by up to ±5″ with no compensating growth |
| CAT-22 | Kepler moved SIMBAD's probe from import-time to lazy+cached, introducing a latch: one transient failure disables resolution for the process lifetime |
| CAT-29 | `query_catalogs_for_image` re-pointed from `CATALOG_OPTIONS` to `CATALOGS`, unlisted in the extraction record |
| TS-03 | The extraction replaced `this.service.setData(result)` with "return to caller", removing the invariant that populated `errorMSE` — the variable periodogram now returns an all-`NaN` spectrum, silently |

---

## 5. The blockers

Seven findings that make a tool unsafe to expose at all.

### Silent — wrong science, no signal

**TS-01 — `equatorial2Galactic` is 180° wrong over half the sky.**
`algorithms/hrdiagram/result/result.utils.ts:63-68` uses `Math.atan(N/D)` where the
two-argument form is required, then patches the sign with a conditional that only
recovers the `D < 0` branch. Verified against `astropy`: M67 → *l* = 35.697°
against a true 215.696°. A random-sky sample is **49.9% wrong by exactly 180°**.
Propagates into `ClusterSummary`, `computeGalacticCoordinates`, and both Galaxy
projections — M67 gets drawn inside the bulge instead of the outer disc.
*Fix: `Math.atan2(N, D)`.*

**CAT-01 — SkyMapper's violet band is used as Johnson V.**
SkyMapper split the SDSS-u region into `u` (ultraviolet) and `v` (violet, ~384 nm,
the metallicity-sensitive band). Case-folding in `_filter_token_candidates` makes
`V` match `v`. `selection.py:73-74`'s own docstring states the intent — "some
catalogs distinguish `v` (a SkyMapper band) from `V` (Johnson V)" — and the code
defeats it. ≈1.4 mag zero-point error with 0.5–1.5 mag of colour-dependent
scatter, so the sigma-clip either rejects nearly everything or converges on a
badly biased subset. The same mechanism makes `U` resolve to `u` on SDSS and
SkyMapper, shadowing the correct Jester transform declared two lines away.
*Fix: drop case-folding from the direct-band step; keep it for `filter_lookup`.*

**TS-03 — the variable periodogram returns a spectrum of pure `NaN`.**
`lombScargleWithError` guards `ts` against `ys` but never against `error`. A short
or zero-containing error array makes the weighted mean `NaN`, which propagates to
every grid point. `mergeSourcesByMjd` returns every row with `errorMSE: null`, so
a caller feeding merge output straight to the periodogram gets 2000 `NaN`s — no
alert, no exception, no empty array.
*Fix: add `error.length` and `error[i] > 0` to the guard.*

### Loud — but catastrophic

**WCS-01 — a missing `PIXSCALE` keyword turns the catalog query into a near-all-sky load.**
`estimate_pixel_scale_arcsec_per_pix` has two of its three sources commented out
upstream, leaving only `PIXSCALE`/`SECPIX`. A frame with a perfect CD matrix but
no `PIXSCALE` returns `None`, so ATLAS gets `min_scale=0.1, max_scale=60`, and the
catalog box is sized off `max_scale` then doubled. Measured for 4096²: 193°×193°
at dec 0, **965°×193° at dec +85** — the RA span exceeds 360°, so UCAC5's wrap
branch returns the entire ~107 M-row catalog and projects it before `max_catalog_stars`
is applied. OOM, not a slow solve.
*Fix: set `catalog_max_radius_deg` (already plumbed, currently `None`) — a cap
that does not diverge from Skynet. Re-enabling `_arcsec_from_wcs` fixes the root
cause but does diverge.*

**WCS-02 — `solve-field` is launched with no timeout of any kind.**
`build_anet_config` never sets `timeout_s`, and `SolverSettings` exposes no anet
timeout key. So `--cpulimit` is absent *and* `communicate(timeout=None)` blocks
forever. Every piece of the kill path — `_kill_process_group`, `SolveFieldTimeout`,
the grace constant, the handler at `wcs.py:733` — is unreachable. The module's own
comment names the failure it was built to prevent: "the 12–16 min runaways the
timeout exists to prevent". Compounded by WCS-04 (the pointing hint is never
passed, so every solve is blind).
*Fix: add `ANET_TIMEOUT_S` to `SolverSettings`. Restores already-written code.*

**TS-02 — `floatMod` is a linear-search modulo that never terminates for `b ≤ 0`.**
`while (a > b) a -= b;` — cost is `O(a/b)`, and for `b ≤ 0` the subtraction
*increases* `a`. Called per-sample inside both period-folding paths. Measured for
a 125 k-sample Green Bank file: 1.9×10⁸ iterations at the default period,
**9.4×10⁹** at the Nyquist-seeded floor, which is one slider drag away. The
correct idiom `((a % b) + b) % b` already exists in `foldAndBin` in the same repo.
*Fix: use it, with a `b > 0` guard.*

**CAT-02 — SDSS queries are unbounded.**
Alone among the eleven catalogs, SDSS emits no `TOP` clause; `row_limit` and the
`limit` argument are both silently ignored. A 1° field at moderate galactic
latitude is of order 10⁵ clean stars, returned over a synchronous CSV connection
and then run through an O(N·M) clipping scan. Load-dependent, so small-field
testing will never show it.
*Fix: `SELECT DISTINCT TOP {limit or row_limit}` and thread `limit` through.*

---

## 6. Rollout waves

Ordered by silent wrong science first, then severity, then dependency. A wave is
not a release train or a framework phase; it is a priority queue for small
bug-fix PRs. Every PR should name the finding IDs it closes and include the
smallest targeted test for those IDs.

| Wave | Contents | Gate |
|---|---|---|
| **W1** | The 7 blockers (§5), silent three first | targeted test per finding |
| **W2** | **Silent wrong-number defects, all severities.** The ones that hand an agent a plausible lie: reference-magnitude mis-declarations (CAT-03, CAT-04, CAT-05, CAT-06, CAT-13, CAT-14), photometry bias (PHOT-01, PHOT-02, PHOT-03, PHOT-06, PHOT-10), astrometry acceptance (WCS-03, WCS-06), geometry (CAT-09, CAT-10, CAT-11), cluster/timeseries numerics (TS-05, TS-14, TS-09) | targeted test per finding |
| **W3** | **Loud failures — crashes, hangs, aborts.** WCS-05, WCS-21, WCS-22, PHOT-04, PHOT-05, PHOT-11, CAT-07, CAT-18, TS-04, TS-12, TS-16, TS-18 | targeted test per finding |
| **W4** | **Bounded and latent defects.** WCS-08..WCS-20, PHOT-07..PHOT-09, PHOT-12..PHOT-14, CAT-12, CAT-15, CAT-16, CAT-19, TS-06..TS-08, TS-10, TS-11, TS-13, TS-15 | targeted test per finding |
| **W5** | **Hygiene and documentation.** Remaining low-severity findings, the class-C documentation corrections (CAT-08 §5.7, CAT-17 docstring, CAT-29 §3), and recording every class-B finding in `docs/extraction.md` | docs or targeted test, as appropriate |

### Immediate action plan after architecture migration

Start with Python findings that affect the first likely tools and can be tested
without live services or large datasets:

| PR | Findings | Test shape |
|---|---|---|
| 1 | CAT-01 | Pure unit test for direct-band filter resolution: Johnson `V` must not resolve to SkyMapper `v`; `U` must not shadow the declared transform path. |
| 2 | CAT-02 | Unit test the SDSS SQL/query builder so a limit becomes `TOP <n>` and the public `limit` argument is honored without making a live SkyServer call. |
| 3 | WCS-02 | Unit test `SolverSettings` and astrometry.net config construction so `ANET_TIMEOUT_S` produces a finite `timeout_s` and reaches the already-written timeout path. |
| 4 | WCS-01 / WCS-25 | Synthetic-header/settings test proving the ATLAS catalog search radius is capped and the cap is constructible through settings. |
| 5 | PHOT-03 | Tiny `calc_solution` or rejection-kernel test showing <=10 calibration stars with an outlier get the intended rejection behavior. |

TypeScript blockers stay out of the first Python-tool remediation path unless a
minimal TypeScript test runner is added in the same PR. Before exposing any
TypeScript-backed tool, close TS-01, TS-02 and TS-03 with targeted tests against
the relevant exported functions.

### Three sequencing rules that are not negotiable

1. **Duplicated files are 2–3 fixes, not one.** A fix landing in one copy and not
   the others is a *new* defect, and the reviews found several such defects
   already:

   | Defect | File | Copies |
   |---|---|---:|
   | Saturation counts lost when `downsample > 1` (PHOT-06) | `algorithms/skylib_lite/extraction/main.py` | 2 |
   | `a >= b` swap and θ normalization are no-ops (WCS-16 / PHOT A-3) | `algorithms/skylib_lite/extraction/main.py` | 2 |
   | `get_fits_fov` returns dec 0 for southern targets (WCS-27) | `algorithms/skylib_lite/util/fits.py` | 3 |
   | `errorMSE` halves every error bar (TS-14) | three TS modules | 3 |
   | `getPeriodStep` returns a step of 0 (TS-12) | three TS modules | 3 |
   | `floatMod` non-terminating (TS-02) | two TS modules | 2 |

   The simplified architecture does not consolidate helper trees as part of the
   tool migration. Until that changes intentionally, each remediation PR must
   patch every duplicate copy it affects and test the public behavior reached
   through each domain.

2. **Do not fix TS-21.** `getMass`/`getPhysicalRadius` carry two 1000× unit errors
   that cancel exactly: `rad(vd)/3600` treats mas/yr as arcsec/yr while
   `3.086e13 km/pc` expects pc where kpc is passed. The assembled result is the
   correct `σ = 4.74·μ·d` identity. Correcting either factor in isolation
   introduces a 10⁶× error. This is recorded as a finding **so that nobody fixes
   it**. Any change here replaces the whole routine at once, with a fixture.

3. **TS-20 cannot be fixed by its own description.** The velocity-dispersion
   percentile band is asymmetric (15.85–65.85 rather than 15.85–84.15), but
   because the statistic is a mean of a Rayleigh magnitude rather than an rms, the
   two errors partly cancel and the coded value lands within +2.6% of the true 1-D
   σ. Fixing only the slice bounds makes the mass **27% worse**. Replace the
   statistic or leave it.

---

## 7. Where this track touches the architecture

The simplified architecture migration should land first: create root-level
`tools/` and `algorithms/` packages and add the first simple local tools. That
gives remediation stable import paths and avoids mixing file moves with behavior
changes.

After that, algorithm fixes start as focused PRs with targeted tests. A tool can
still guard its own inputs and keep outputs bounded, but the following findings
remain remediation work when they affect algorithm behavior:

- timeout and runaway behavior, such as WCS-02 and WCS-21;
- mutation of caller-owned objects, such as WCS-28 and PHOT-17;
- unbounded query behavior, such as CAT-02;
- swallowed mapping or provider errors, such as CAT-20 and WCS-23;
- browser-only TypeScript behavior, such as TS-17, when those algorithms are
  exposed.

Do not rely on the tool wrapper to hide a known algorithm bug. If a bug can
produce wrong science or unsafe runtime behavior, either fix it with a targeted
test before exposing the tool, or keep that tool out of the first public surface.

---

## 8. Fix notes

Each remediation PR should include a concise fix note in its PR body or in
`docs/extraction.md` when the divergence is important for future readers:

```
Finding:      <IDs closed>
Before:       <what Skynet/Astromancer/current Kepler did>
After:        <what Kepler now does>
Test:         <targeted test added>
Notes:        <numeric delta or compatibility concern, if relevant>
```

Do not create a separate tracking document until the project has a concrete need
for one.

---

## 9. Full finding register

Severity as assigned by the reviewers. **S** = silent (returns a plausible wrong
answer with no signal). Locations are given in the source reports.

### `wcs/` — 28 findings

| ID | Sev | S | Summary |
|---|---|:-:|---|
| WCS-01 | blocker | | No pixel-scale hint → catalog box up to 965°×193° → whole-catalog load, OOM |
| WCS-02 | blocker | | `solve-field` launched with no timeout; entire kill path unreachable |
| WCS-03 | high | ● | Pointing-acceptance gate inert without a scale prior; a 40°-wrong solution is accepted and written to the header |
| WCS-04 | high | | RA/Dec hint never reaches `solve-field` — `radius` is always exactly 180, so `180 < 180` discards it. Every solve is blind |
| WCS-05 | high | | ATLAS raises `TypeError` on `float(None)` when no pointing hint exists |
| WCS-06 | high | ● | A string RA in decimal degrees is parsed as hours — 15× error, `'185.6'` → 2784° → wraps to 264° |
| WCS-07 | high | | Triangle collinearity cut is an absolute area threshold applied to both pixels and radians; discards ~96% of catalog triangles for a 5′ field |
| WCS-08 | medium | ● | `CDELT1A`/`CDELT2A` are degrees but read as arcsec — 3600× under-estimate, makes `min_scale > max_scale` |
| WCS-09 | medium | ● | `_gnomonic_projection` divides by `cos c` unguarded; antipodal stars fold onto the near side and sort *first* by distance |
| WCS-10 | medium | | `cos δ` RA widening clamped at 0.2 (correct only to \|dec\|≈78.5°); no pole-crossing handling |
| WCS-11 | medium | | `Ucac4Index.query_box` modulo-collapses any RA span >360° to a 40° wedge |
| WCS-12 | medium | ● | `PC @ diag(CDELT)` instead of `diag(CDELT) @ PC` — off-diagonals mis-scaled. Latent: both shipped backends emit CD |
| WCS-13 | medium | ● | `delta_ra_deg`/`delta_dec_deg` store **arcseconds**, and `delta_ra` is additionally cos-δ scaled |
| WCS-14 | medium | ● | After an accepted solve, catalog sources are re-queried around the *hint* using `max_scale`, discarding the solved centre and scale |
| WCS-15 | medium | ● | **(A)** `_clear_wcs_solution_fields` leaves `ra_deg`, `dec_deg`, `pixel_scale_arcsec_per_px`, `rotation_deg` stale after a failed solve |
| WCS-16 | medium | ● | `a >= b` swap and θ normalization write to a masked *copy* — silent no-ops. θ ends in [0,π) not (−π/2,π/2] |
| WCS-17 | medium | ● | Catalog trimmed by angular distance, not brightness (depth mismatch vs the image); UCAC5 Gaia-2015.0 positions get no proper-motion correction — 1.1″ for a 100 mas/yr star in 2026 |
| WCS-18 | medium | | Header write-back leaves stale `RADECSYS`, `EQUINOX`, `EPOCH`, `A_DMAX`/`B_DMAX`; the two SIP regexes in the package disagree |
| WCS-19 | medium | | UCAC4 reader's zone geometry, filenames and 80-byte record layout disagree with the published 900-zone/78-byte distribution — *possible*, needs one real zone file |
| WCS-20 | medium | | Explicit `parity` fed to both backends without the documented inversion; ATLAS's blind path ignores parity entirely |
| WCS-21 | medium | | Blind matcher's time budget unbounded by default, checked in the wrong loop, doubled by the retry; `sample_triangles` (15–17 s) sits outside it entirely |
| WCS-22 | medium | | `_frame_from_header` crashes on a string `EQUINOX='J2000'`, silently discarding the pointing hint three layers up |
| WCS-23 | medium | | Blanket `except Exception` reports missing binaries, bad catalog roots and full disks as "no solution" |
| WCS-24 | low | | `_estimate_fov` returns 4096° for the WCS-stripped temp FITS; `missing_fov` guard can never fire |
| WCS-25 | low | | `catalog_pad_frac`/`catalog_max_radius_deg` lack annotations, so they are not dataclass fields — the documented lever for WCS-01 is unreachable via the constructor |
| WCS-26 | low | | `_write_xylist` ignores `max_sources` when no flux array is supplied; one bad source disables the cap for the frame |
| WCS-27 | low | ● | `get_fits_fov` returns dec **0** for every southern target (`1 - True == 0`) |
| WCS-28 | low | | Mutates the caller's `SourceExtractionSettings`; prints to stdout per frame |

### `photometry/` + `fieldcal/` — 19 findings

| ID | Sev | S | Summary |
|---|---|:-:|---|
| PHOT-01 | high | ● | Non-positive aperture flux leaves `mag = 0.0, mag_err = 0.0` — a finite, very bright magnitude. Survives the flag mask (the two flags that would catch it are never set by the numba port) and the SNR gate (`not 0.0` is truthy) |
| PHOT-02 | high | ● | An empty background annulus silently skips sky subtraction and discards the annulus's flags. Measured +41% flux = **0.37 mag too bright, `flag=0`** |
| PHOT-03 | high | ● | `chauvenet`'s `min_vals=10` default is checked *before* the rejection pass, so outlier rejection is entirely disabled for fields with ≤10 calibration stars — and reports `rej_percent = 0` |
| PHOT-04 | high | | `_match_detected_sources` raises `TypeError` for any catalog source carrying a proper-motion epoch — `np.transpose` on a ragged list yields an object array |
| PHOT-05 | high | | One catalog source without a position aborts the whole calibration inside `cKDTree`; if *none* has RA/Dec, `NameError: cx` |
| PHOT-06 | high | ● | Saturation counting silently lost whenever `downsample > 1` — coordinates are downsampled, then divided again. `discard_saturated` becomes a no-op |
| PHOT-07 | medium | ● | `isophotal_analysis` called with 1-based coordinates but computes on a 0-based grid. A round star measures a/b = 1.017 with θ pinned to −45°, and 2.8% less flux |
| PHOT-08 | medium | | A degenerate (NaN) solve writes no header keywords, logs a warning, and is reported as success — `PHOT_M0` is unguarded where `PHOT_M0E` is guarded, so astropy rejects it first |
| PHOT-09 | medium | ● | The intrinsic-scatter root find cannot bracket when scatter is fully explained by errors; the bare `except` leaves `sigma2` as the *total* scatter, ~3.5× overstating `zero_point_slop` and flattening the fit weights |
| PHOT-10 | medium | ● | `max_stars` trims by catalog brightness — preferentially retaining saturated stars, which have excellent formal SNR. `ref_mag == 0.0` also sorts as faintest |
| PHOT-11 | medium | | `mode="auto"` is unusable from field calibration: the matcher strips the FWHM columns the adaptive path needs, and `centroid_radius` is 0 by design |
| PHOT-12 | medium | ● | Growth-curve aperture correction: the "nearby source" guard is dead code (`df_prev` assigned, never read), so a neighbour's flux walks into `f_tot` and shifts *every* source's magnitude |
| PHOT-13 | medium | | Two different SNR definitions inside `fieldcal`; `min_snr=10` actually cuts at true SNR ≈ 10.36, and fit weights are 5–14% small at the faint end |
| PHOT-14 | medium | ● | `settings.gain == 1` — the documented way to say "already in electrons" — is silently overridden by the FITS header |
| PHOT-15 | medium | | `_safe_eval_expr` is a sandboxed `eval`: permits `.` and `()`, `9**9**9` hangs the process, and band names are interpolated into a regex unescaped |
| PHOT-16 | medium | | Reference batch driver swallows every exception into a blank CSV cell; its `centroid_radius=5` contradicts the documented parity setting |
| PHOT-17 | medium | | `fieldcal.deps` process globals; `perform_field_calibration` mutates the caller's `CatalogSource` objects and `Header` |
| PHOT-18 | low | | Angular source matching fails across RA = 0 (plain arithmetic mean of RA); `variable_check_tol` is arcsec while `source_match_tol` is pixels, both defaulting to 5 |
| PHOT-19 | low | | `triangle_unitcircle_overlap` reuses a stale `pt2` in the third-edge branch — *possible*, needs a diff against `sep`'s `overlap.c` |

### `catalogs/` + `query/` — 32 findings

| ID | Sev | S | Summary |
|---|---|:-:|---|
| CAT-01 | blocker | ● | SkyMapper's `v` (violet, 384 nm) used as Johnson V; `U` likewise resolves to `u` |
| CAT-02 | blocker | | SDSS queries unbounded — no `TOP`, `row_limit` and `limit` both ignored |
| CAT-03 | high | ● | 2MASS `Bmag`/`Rmag` and UCAC5 `Rmag` are *photographic plate* magnitudes declared under standard band names, with no error column. Direct-band matching prefers them over the correct declared transforms |
| CAT-04 | high | ● | Tycho-2 `BT`/`VT` declared as Johnson `B`/`V` — a 0.32 mag colour-dependent spread the ZP fit cannot absorb |
| CAT-05 | high | ● | UCAC5's `{'*': 'Open'}` wildcard makes every filter resolve to the 579–642 nm bandpass; with `stop_on_success` it short-circuits the whole chain. ~1.7 mag of colour-dependent scatter |
| CAT-06 | high | | APASS's `U` transform references `uprime`, a band APASS does not carry — so U-band calibration against the default catalog always fails, with a message naming neither filter nor catalog |
| CAT-07 | high | | `boxes_from_wcs` raises `ValueError` whenever CRPIX is at or outside the array edge; the docstring blames a cause that is not the trigger |
| CAT-08 | high | | **(C)** SkyMapper's `flags=0` leaks into every subsequent catalog *and* the caller's dict — `docs/extraction.md`, Query §5.7 claims otherwise |
| CAT-09 | high | ● | `image_boxes_from_wcs` swaps the x and y pixel scales. A 2×1-binned frame gets a box 4× too wide and 4× too short — the field is silently under-covered |
| CAT-10 | high | ● | 2MASS `JHK→BVRI` cubics applied with no colour-range guard; the published relation is valid only for −0.1 < J−K < 1.0. At J−K = 2.0 the result is nonsense |
| CAT-11 | high | | Wide, short fields near a pole: `arcsin` of >1 yields NaN. VizieR path silently drops every source; SDSS path emits `nan` into the SQL |
| CAT-12 | medium | ● | APASS's `I` transform is attributed to Lupton 2005 but is Lupton's `i−z` form with a stellar-locus substitution — undocumented, one-signed, ~0.11 mag at r−i = 1.2 |
| CAT-13 | medium | ● | The two registries disagree on `Halpha`'s **value**, not just the `H_alpha` spelling — 0.176 mag. Selection reads one, resolution the other. Undocumented |
| CAT-14 | medium | | Four registry keys don't match their plugin `.name` (`Stetson`→`StetsonGlobs`, `Tycho`→`Tycho2`, `UCAC`→`UCAC5`, `USNO`→`USNOB1`), so their `filter_lookup` is unreachable at resolution time |
| CAT-15 | medium | ● | SkyMapper→SDSS′ transform is a single constant per band from one spectral type (F5V); the real offset spans ~0.2 mag in g′ and ~0.4 mag in r′ across A0V–K0V |
| CAT-16 | medium | ● | Narrowband→broadband reference mapping is defensible for a *relative* ZP but not an absolute one, with no flag distinguishing the two downstream |
| CAT-17 | medium | | **(C)** `_round_for_cache` moves the centre by up to ±5″ with no compensating growth, contradicting its own docstring |
| CAT-18 | medium | | `SDSSQueryBackend.query_objects` calls `sdss.query_object`, which astroquery does not have. No `try` covers it |
| CAT-19 | medium | ● | A truncated VizieR result is indistinguishable from a complete one — and every catalog sorts ascending by magnitude, so truncation yields the *brightest* N, biased toward saturation |
| CAT-20 | medium | | `table_to_sources` swallows every mapping exception per row, so a column-rename makes a populated field look empty |
| CAT-21 | medium | | The SIMBAD otype table has no entry for `*` or `G` — the two commonest codes — and the fallback returns `""` where the docstring promises the raw code |
| CAT-22 | medium | | **(C)** One transient SIMBAD failure latches resolution off for the process lifetime |
| CAT-23 | low | ● | Magnitude and error values of exactly `0.0` are treated as "not measured" |
| CAT-24 | low | | **(A)** `_derive_columns` requests columns literally named `int` and `float` — twice each, for Landolt and Stetson |
| CAT-25 | low | | The NaN→`None` serializer erases "was NaN" vs "absent"; a band can return a real error with a `None` value |
| CAT-26 | low | | `prune_vizier_cache` runs a full-directory scan before *every* cache write, and only prunes the Vizier subdirectory |
| CAT-27 | low | | SDSS SQL built by string interpolation; safe for the eleven shipped catalogs, but `build_custom_vizier_catalog` reaches it unvalidated |
| CAT-28 | low | | `_filter_token_candidates` never combines whitespace stripping with typographic-quote normalization |
| CAT-29 | low | | **(C)** `query_catalogs_for_image` re-pointed from `CATALOG_OPTIONS` to `CATALOGS`, unrecorded |
| CAT-30 | low | ● | `stop_on_success` short-circuits on the first catalog returning even *one* source — a 3-star ZP with a meaningless uncertainty |
| CAT-31 | low | | **(A)** `_MutatingCatalog` mutates the class dict; contained today because both classes are module-private |
| CAT-32 | low | | APASS dedup keys on VizieR's `recno`, which CDS documents as unstable across re-ingests |

### `algorithms/lightcurve/` + `algorithms/periodogram/` + `algorithms/hrdiagram/` — 31 findings

| ID | Sev | S | Summary |
|---|---|:-:|---|
| TS-01 | blocker | ● | `equatorial2Galactic` 180° wrong for 49.9% of the sky |
| TS-02 | blocker | | `floatMod` linear-search modulo: unbounded work, infinite loop for `b ≤ 0` |
| TS-03 | blocker | ● | **(C)** Variable periodogram returns 2000 `NaN`s silently when any `errorMSE` is null or zero |
| TS-04 | high | | **(A)** Variable fold two-pass misalignment — confirmed, and it *always* throws rather than returning wrong values (better than documented) |
| TS-05 | high | ● | MWSC age histogram converts log₁₀(yr) to **Myr** then applies a **13.8 Gyr** cut — discards everything older than 13.8 Myr, i.e. most of the catalog |
| TS-06 | high | ● | `appendFSRResults` sorts numerically and merges lexicographically; the two-pointer join silently skips matches, and unmatched sources are then dropped |
| TS-07 | high | ● | FSR membership test uses `&&`-truthiness, so a star with `pm_ra` exactly `0` — the most cluster-like astrometry possible — is classified as a field star |
| TS-08 | high | ● | `foldSingleSourceByIndex` divides a *time* by the *sample count*; the doc comment describes an index fold the code does not perform |
| TS-09 | medium | ● | `lombScargleWithError` mixes a weighted numerator with unweighted denominators — power comes out scaled by 1/N². The weighting is real and beneficial; the normalization is not |
| TS-10 | medium | ● | `getExtinction` returns **0** for all four WISE filters (all outside CCM's 0.3–3.3 μm⁻¹ range) and for any unrecognized filter |
| TS-11 | medium | ● | Confidence thresholds use the *plot resolution* as the independent-frequency count; a peak "3σ" at 100 points is below 1σ at 20000. Label says 67.3% for 68.3% |
| TS-12 | medium | | `getPeriodStep` returns exactly `0` for ordinary parameters — the guard threshold is 1e-5 but `toFixed(4)` quantizes to 1e-4 |
| TS-13 | medium | ● | The "Nyquist" derivation telescopes to `2·baseline/(N−1)` — it never inspects the actual sampling. One gap hides a genuine fast pulsar; sub-5 µs sampling rounds to 0 |
| TS-14 | medium | ● | `errorMSE` divides by 2 — every differential-photometry error bar is half its correct size |
| TS-15 | medium | ● | **(A)** `d2DMS` computes a sign and discards it — a cluster at Dec −30.5° reports as +30.5° |
| TS-16 | medium | | `findLocalMax` is poisoned by a `NaN` at index 0 and returns `[undefined]` on empty input |
| TS-17 | medium | | Lomb–Scargle yields silent `NaN` for degenerate inputs; the only guard calls the DOM `alert()` |
| TS-18 | medium | | `getDefaultBin` returns `Infinity` on a tied quartile range and `NaN` for a single point |
| TS-19 | low | ● | **(A)** `getExtinction` ignores its own `rv` — 38% low at Rv=5. Latent: no caller passes `rv` |
| TS-20 | low | ● | **(A)** Asymmetric percentile band — but see §6 rule 3; fixing the bounds alone makes the mass 27% worse |
| TS-21 | — | | **No defect. Do not fix.** Two 1000× unit errors cancel exactly |
| TS-22 | low | | **(A)** `getStandardViewRange` mixes `red` into a `lum`-only expression — ~0.2 mag of axis padding |
| TS-23 | low | | **(A)** Isochrone break splice drops one model point |
| TS-24 | low | | `binData` always discards the maximum-x sample |
| TS-25 | low | | Pulsar fold maps phase 0 to phase 1 — the earliest sample plots at the far right |
| TS-26 | low | | `differenceAndSum` pairs two independently binned arrays by index |
| TS-27 | low | | `ArrMath.sub`/`div` compute the reverse operation in their scalar-first branches — dead today, a trap for anyone extending the module |
| TS-28 | low | | `getHistogramExtremes` returns `undefined` as the minimum for a one-element array |
| TS-29 | low | ● | `λ_V = 0.540 μm` breaks the CCM normalization — the "E(B−V)" slider produces a colour excess 8% smaller than nominal |
| TS-30 | low | | Edge-on Galaxy projection uses 32 px/kpc horizontally and 16 px/kpc vertically |
| TS-31 | low | | **(A)** `getJdRange` returns `−Infinity` on an all-null table; the pulsar sibling's guard was never mirrored |

---

## 10. What the reviews could not establish

Carried forward as open work, not as findings:

1. **No end-to-end run of anything.** No `solve-field`, no index files, no UCAC
   catalog, no `node`/`tsc`, no reference FITS. Every runtime claim is isolated
   execution of an extracted function against the real numeric stack, or
   arithmetic on the code. Targeted remediation tests should close these gaps
   only when a fix needs that runtime path.
2. **No live provider response.** VizieR/SkyServer/SIMBAD were deliberately not
   called, so astroquery's column-renaming behavior (CAT-20), SkyServer's
   response to a `nan` in a WHERE clause (CAT-11), and which otype vocabulary
   astroquery 0.4.11 emits (CAT-21) all remain untested. This is the gap
   `docs/extraction.md`, Query §7 already declares.
3. **UCAC4/UCAC5 on-disk formats (WCS-19).** Decisive test needs one real zone
   file: check `size % 78` vs `% 80`, the filename convention, and the sign of the
   I*4 at offset 4 for a southern zone.
4. **VizieR column provenance (CAT-03).** CDS returned access-denied pages for
   every ReadMe fetch. The claim that 2MASS `Bmag`/`Rmag` are USNO-A2.0 plate
   magnitudes rests on secondary sources — though the *code-path* half of the
   finding is verified and holds regardless.
5. **SkyMapper transform constants (CAT-15).** The ANU page returned two different
   column layouts on two fetches. The absence of a colour term is certain; the
   specific claim that `uprime: u - 0.069` is wrong is not.
6. **`sep`'s `overlap.c` (PHOT-19).** Only the compiled wheel is present, so
   whether the stale `pt2` is a port bug or faithful could not be settled.
7. **The standard/prefolded pulsar file format (TS-08).** Severity depends on
   whether column 0 is a time or a sample index. Astromancer ships no sample data
   and no format documentation; both readings are flagged.
