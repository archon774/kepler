# `test_data/` — real observational fixtures

Everything here is **real data copied verbatim** from the Skynet pipeline data
repository at `/home/claude/skynet-data/pipeline_data`. Nothing was synthesised,
resampled, trimmed, or re-headered. That is the point: Kepler's Python folders
are byte-preserving extractions from Skynet (see `CLAUDE.md`, "The extraction
contract"), so the tests that guard them have to run on the frames and the
recorded solver outputs the upstream pipeline actually produced.

**Total size: ~175 MB**, essentially all of it the 39 FITS frames. That is large
for a plain git repository; see "Repository size" at the bottom.

## Layout

```
test_data/
  optical/                     39 FITS frames (~169 MB)
  afterglow/                   Afterglow web service ground truth (160 KB)
    afterglow_web_values_*.csv   zero points for 73 subjects
    build_master_table.py        upstream merge script
    fieldcal/                    full API response for NGC 5128 B
    photometry/                  per-source photometry export for the same run
  fieldcal/
    zp_solutions/              4 recorded Skynet zero-point solves (in + out)
    ocl_filter_report.json     Open/Clear/Lum substitute-filter trials
  frame_provenance.json        bundled frame stem -> pre-rename upstream filename
  pulsar/                      5 Green Bank 20 m pulsar scans (5.7 MB)
    Curated pulsars.docx       the curation: periods + difficulty ratings
    curated_periods.json       that curation, machine-readable, for the tools
```

## `optical/` — 39 science frames

PROMPT / Skynet optical frames, `float32`, already bias/dark/flat corrected,
copied from `pipeline_data/test_subjects/optical/<category>/`.

The set is **every frame in the Afterglow web values table under 9 MB** (37 of
them), plus the two M15 unfiltered frames, which have no published zero point
precisely because unfiltered passes have no direct catalog band. So all but two
frames here carry independent ground truth in `afterglow/`.

Collectively they span the variation the algorithms branch on:

| Property | Coverage |
| --- | --- |
| Filters | V (25), R (7), B (2), Halpha (2), OIII (1), Lum (1), Open (1) |
| Telescopes | Prompt5 (23), Prompt2 (8), PROMPT-MO-1 (3), OAUJ-CDK500 (3), R-COP (2) |
| Geometry | 1056×1027 (34), 1024×1024 (3), 1600×1200 (2) |
| WCS representation | `CD` matrix (33), `PC` + `CDELT` (5), none at all (1) |
| Parity — sign of `det(CD)` | positive (35), negative (3), undefined (1) |
| Rotation | ~0°, ~±2°, ~±90°, ~±178° all present |
| `FOCALLEN` | 5 frames carry a real value (2011 mm, 4565 mm); the rest are 0 |

Several tests parametrize over the whole directory rather than a fixed list, so
adding a frame widens their coverage automatically. Frames the tests single out
by name have short aliases in `tests/conftest.py::FRAMES`:

| Alias | File | Why this one |
| --- | --- | --- |
| `nsv2849` | `nsv2849_star_v_000.fits` | WCS written as **`PC` + `CDELT`**, not `CD` — exercises `wcs.wcs._wcs_matrix`'s `has_cd()` fallback. Upstream's primary astrometry fixture (`skynet .../tests/runners/test_wcs.py`). |
| `ngc3628` | `ngc3628_galaxy_v_000.fits` | Photometry workhorse — upstream's pre-reduced photometry fixture object. |
| `m31` | `m31_galaxy_v_000.fits` | **Negative parity**, and RA/Dec strings with **comma decimal separators** (`'00:42:44,3'`). 1024², different telescope. |
| `carina` | `carina_nebula_v_000.fits` | ~**90° rotation** — `CD1_1` near zero, scale carried off-diagonal. Catches anything reading pixel scale off `CD1_1` alone. |
| `ngc5286` | `ngc5286_globular_v_000.fits` | Real **`FOCALLEN`** (4565 mm), the input to `wcs.header_utils._arcsec_from_optics`. |
| `m15_lum` | `m15_globular_lum_000.fits` | `FILTER = 'Lum'` — an OCL unfiltered pass routed through `_OCL_TO_V`. Has a WCS. |
| `m15_open` | `m15_globular_open_000.fits` | `FILTER = 'Open'`, and **no WCS keywords at all**. Same instrument and target as the Lum frame, isolating the missing-WCS path. |
| `ngc2070` | `ngc2070_nebula_v_000.fits` | Southern field at dec −69°, where `cos(dec)` in the footprint maths stops being negligible. Upstream's default in `zp_fit.py`. |
| `ngc5128_b` | `ngc5128_galaxy_b_001.fits` | **The frame behind the whole parity chain** — the recorded solve in `fieldcal/zp_solutions/ngc5128_b_002/`, the Afterglow API response, and the web table row all describe this exposure. |
| `ngc1982` | `ngc1982_nebula_r_000.fits` | 1600×1200 from a fifth instrument, with a `FOCALLEN` of 2011 mm. |

## `afterglow/` — independent ground truth

Results from the **hosted Afterglow photometry web service**, not from Skynet's
local pipeline. That independence is what makes them worth carrying: agreement
between Kepler and these numbers is a cross-implementation check, where
agreement with `fieldcal/zp_solutions/` is a check against the code Kepler was
extracted from.

- `afterglow_web_values_{bvr,narrowband,sdss}.csv` — per-category zero points
  and errors, keyed by the same renamed frame filenames used in `optical/`.
- `afterglow_web_values_master.csv` — the merged table, 73 subjects, built by
  `build_master_table.py` (copied verbatim; the tests re-derive the union to
  check the master is current).
- `fieldcal/ngc_5128_test_vals.json` — the complete field-calibration API
  response for NGC 5128 B: the settings Afterglow ran with, and its per-source
  photometry. This is where `apcorr_tol: 0` and `zero_point: 20` are recorded,
  which is the evidence behind the "LEGACY AFTERGLOW PARITY — DO NOT CLEAN UP"
  comment in `fieldcal/field_cal.py`.
- `photometry/afterglow_photometry_ngc5128_b.csv` — 303 sources from the same
  run, carrying `zero_point`, `zero_point_correction` and `calibrated_zero_point`
  per row.

**Afterglow's convention differs from Kepler's.** Afterglow fixes
`zero_point = 20` and reports a `zero_point_correction`; Kepler computes the
absolute zero point directly. Any comparison has to add the two, or it lands 20
magnitudes off in a way that looks entirely plausible.

## `fieldcal/zp_solutions/` — recorded Skynet solves

Four complete Skynet field calibrations, each a matched pair:

- `fit_data.csv` — every photometered source, with `used_for_calibration`
  marking the exact rows handed to `calc_solution`.
- `fit_summary.json` — run metadata and, under `production_calc_solution`, the
  five numbers `calc_solution` returned for those rows.

This pair is what makes `tests/test_fieldcal_solution.py` a genuine parity test
rather than a self-consistency check: inputs and expected outputs were both
recorded upstream, before the extraction. Kepler reproduces all four to the last
float bit — the only value with any drift is `limmag5`, which goes through
`np.polyfit`.

| Directory | Upstream source | Field |
| --- | --- | --- |
| `ngc5286_b_000` | `zp-fits/test_bad_vals/ngc_5286_12158933` | NGC 5286, B |
| `ngc5286_b_001` | `zp-fits/test_bad_vals/ngc_5286_12158933-2 (1)` | NGC 5286, B — same field, second frame |
| `ngc5286_b_002` | `zp-fits/test_bad_vals/ngc_5286_12158933 (2) (1)` | NGC 5286, B — same field, third frame |
| `ngc5128_b_002` | `zp-fits/afterglow_fits/ngc 5128_13909251_B_002` | NGC 5128, B — the Afterglow parity run |

The NGC 5286 trio are upstream's "bad values" fixtures: frames whose original
filenames contained spaces and parentheses, with pathological header values.
Their zero points differ by ~1.8 mag across three frames of one field, which is
what makes them a good regression target.

The NGC 5128 case is the interesting one — its summary carries both the local
result and Afterglow's, and declares them within a 5e-4 mag tolerance. The full
chain, all offline:

```
Kepler calc_solution        21.147659857998637   (bit-exact)
Skynet recorded local fit   21.147659857998637
Afterglow API              (21.14747923526837)   = 20.0 + 1.1474792352683736
Afterglow web table         21.147                (3 dp, recorded by hand)
```

The `_(1)`/`_(2)` upstream directory names were flattened to `_000`/`_001`/`_002`
so paths survive a checkout on any filesystem. File contents are untouched,
including the absolute `/Users/...` paths recorded inside the JSON — those are
provenance, and rewriting them would make the fixture no longer the artifact
Skynet emitted.

## `pulsar/` — Green Bank 20 m pulsar scans

Five Skynet radio continuum scans, `.A.cal.txt`, copied verbatim. Each is a
~60 s track of one pulsar at 1395 MHz, two linear polarizations sampled at
4.194 ms, with the instrument's full `#` metadata header intact.

These back `tests/test_pulsar_sonification.py` and are the input format
`tools.pulsar.sonify_pulsar` reads.

| File | Source | Curated `P0` (s) | Curated difficulty | `S1400` | `DM` | Fold at `P0` | Blind search |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Skynet_60898_psr_b0329_54_…` | B0329+54 | 0.7145197 | Easy | 203 mJy | 26.8 | **316σ** | **finds it** |
| `Skynet_60898_psr_b1133_16_…` | B1133+16 | 1.187913066 | Lightly Challenging | 20 mJy | 4.8 | 17.7σ | 60 Hz RFI |
| `Skynet_60900_psr_b1933_16_…` | B1933+16 | 0.358738411 | More Challenging | 58 mJy | 158.6 | 7.5σ | red noise |
| `Skynet_60901_3_Pulsar_Team_B2021+51_ERIRA_…` | B2021+51 | 0.529196918 | Lightly Challenging | 27 mJy | 22.5 | 4.9σ | red noise |
| `Skynet_60902_psr_b2045_16_…` | B2045−16 | 1.961572304 | Most Challenging | 22 mJy | 11.5 | 5.4σ | 60 Hz RFI |

Periods and difficulty come from `Curated pulsars.docx` (below); `S1400`/`DM`
from ATNF.

"Fold at `P0`" is the peak significance of a 100-bin fold at the catalogued
period after running-median subtraction (`back_scale=3`). "Blind search" is
what `compute_pulsar_periodogram` returns with default settings.

**Only B0329+54 survives a blind search**, and that is a property of the
sources, not a defect: at ~200 mJy it is an order of magnitude brighter than
the rest, and 60 seconds on a 20 m dish is not much integration. The four
failures are instructive and are pinned by
`tests/test_pulsar_sonification.py::test_blind_search_only_succeeds_on_the_bright_source`:

- **B1133+16 and B2045−16 both peak at 0.016665 s — 60.006 Hz, mains
  interference.** Not sky signal at all.
- **B1933+16 and B2021+51 peak near 2.1–2.2 s**, red noise left behind by the
  baseline subtraction. That peak moves when `back_scale` changes, which is how
  you tell it from a real periodicity.
- **All four still report "99.73% Confidence."** The false-alarm threshold
  assumes white noise; radio data is not white. `peak_fold_snr` is the field
  that separates them, and it does.

With a tuned `back_scale` and a search narrowed away from the artifacts, four
of the five land within 0.5% of the catalogued period. **B1933+16 does not**,
and the reason is physical: `DM = 158.6` smears its pulse by ~11% of its 359 ms
period across the 80 MHz effective band, and nothing in this pipeline
dedisperses. It is the brightest of the four faint scans and still the hardest.

The curated difficulty ratings are an **independent check on the pipeline** —
they were assigned before any of this code ran. Measured fold significance
tracks them: the one "Easy" source is the only one above 100σ, the "Most
Challenging" one folds near the floor, and the ordering matches for four of
five. B2021+51 is the exception, rated "Lightly Challenging" but folding
weakest; it is also the only scan from a different programme (`SRC_NAME` =
`3_Pulsar_Team_B2021+51_ERIRA`), so that looks like a property of the
observation rather than the source. Pinned by
`tests/…::test_measured_detectability_tracks_the_curated_difficulty`.

## `pulsar/Curated pulsars.docx` — the verification reference

The curation shipped with these scans. Two tables: 15 pulsars with archival
observation number, literature period and a difficulty rating, and a "Slow
Bright Pulsar Candidates to Observe" table with B1950 coordinates. Only the
five sources above have scans in this repository; the rest of the list is the
observing programme they were drawn from (including B1919+21, the first pulsar
discovered).

**This document, not ATNF, is the reference the tests compare against** —
`curated_periods.json` beside it carries the transcription, and
`tests/conftest.py::PULSAR_PERIODS_S` reads its `period_s` field, which is the
document's "Period(Literature)" column.

**The periods are not in the scan files.** They carry no `P_topo` header; that
field only appears on prefolded "standard" files, and none ship here. So the
period always comes from outside the data, which is what makes a successful
fold an independent check rather than a self-consistency one.

ATNF's live `P0` is carried alongside in each `curated_periods.json` entry's
`atnf` block, and reaches the suite as `PULSAR_ATNF`, as a cross-check. The
two agree to 4e-10 for B0329+54 and B2021+51 and differ by 4e-6 to 2e-5 for
the other three — different epochs or source references. **Neither is "more
correct" for this data**, and the choice cannot change a result here: across a
56 s scan the difference smears a fold by at most 3e-3 of a period, and it is
itself 10–25× smaller than the topocentric-vs-barycentric shift (v/c = 1e-4)
that neither value corrects for.

Each scan's own `RA(deg)`/`DEC(deg)` header agrees with the catalogue position
to within arcseconds — the check that confirms which pulsar each file actually
points at, since `SRC_NAME` renders both B1133**+**16 and B2045**−**16 as
`_16`.

### `pulsar/curated_periods.json` — the same numbers, reachable from a tool

A `.docx` is not readable by the pipeline, so the five curated rows are
transcribed into JSON beside it: `period_s`, `difficulty`/`difficulty_rank`,
the archival `observation` number, and the ATNF cross-check. Keys are
normalized designations (`b0329`), the form `tools.pulsar` matches a scan's
`SRC_NAME` against, so `list_pulsar_scans` and `resolve_pulsar_scan` report
`curated_period_s`, `curated_difficulty` and `period_source` on every bundled
scan.

The file sits in this directory rather than at a path the tool hardcodes,
because the curation belongs to the scans it describes: point
`KEPLER_PULSAR_DATA_DIR` at another archive and that archive's own
`curated_periods.json` is the one consulted.

That closes an offline gap rather than adding a convenience: a blind period
search succeeds on **one** of these five scans, so without a curated period the
only route to the other four is a network call to ATNF. The file is the one
copy of each number — `tests/conftest.py` reads it rather than restating it.

Two structural details the ingest depends on, both visible in any of the files:

- Every scan opens with a **noise-diode calibration block** — ~124 rows at
  0.1 s cadence before the 4.2 ms science data. It is dropped by the last
  column being zero, not by the `Cal` flag column.
- The column header line reads `... El(deg)  YY1  XX1  Cal  Sweeps` (9 names)
  while the rows carry **10** fields. Upstream reads the first 9 by position
  and ignores the last, which is the run flag the filter above keys on.

## `fieldcal/ocl_filter_report.json`

Skynet's OCL filter-substitution report: for ten Open/Clear/Lum frames it trials
`V`, `rprime` and `R` as substitute reference filters and records the resulting
slop, selecting the lowest. Copied from `zp-fits/ocl_fits/ocl_filter_report.json`.

Every row is keyed by `input_file` — the **pre-rename upstream filename** (e.g.
`messier 15_14111493_Lum_005.fits`). The report carries no `DATE-OBS`, exposure
time, or any other identifier, so once the frames were renamed to
`<object>_<category>_<filter>_<seq>.fits` the join was lost. `frame_provenance.json`
(below) is the only way back to it; `tools.fieldcal_reference.load_ocl_reference`
takes a bundled stem and returns the matching row.

Note the sweep only **read the header WCS** — it did not plate-solve. That is
why `m15_globular_open_000` fails every trial with `"no WCS solution found in
FITS header"` (it is the one bundled frame with no WCS keywords): a working
`solve_astrometry` could take that frame further than the recorded pipeline did.

## `frame_provenance.json`

`{ "frames": { "<bundled stem>": "<pre-rename upstream basename>" } }`, plus a
`_collisions` note for the one stem two upstream files mapped to. Transcribed
from `skynet-data/pipeline_data/reorganize.py`, the rename script, so the
mapping lives in this repository rather than only on the machine that ran it.

It exists because `ocl_filter_report.json` keys its rows by upstream filename
and nothing else does — the Afterglow CSVs were rewritten to the new names by
the same script, so they need no map. The full 90-entry table is kept (not just
the ten OCL frames) so the next fixture that needs a join already has it.

## Repository size

169 MB of FITS is a lot for plain git. Nothing here is generated, so it will not
grow on its own, but two things are worth knowing:

- Frames are binary and incompressible, so every re-copy of a frame adds its
  full size to history permanently. Replace a frame only when it must change.
- If clone times become a problem, these are natural Git LFS candidates —
  `test_data/optical/*.fits` is the whole of it, and the JSON/CSV ground truth
  (160 KB) should stay in regular git either way.

The frame cut-off is 9 MB. The Afterglow table covers 73 subjects totalling
~1.5 GB; the 36 frames above that cut-off were deliberately left out, and their
web values still ship, so any of them can be added later without touching the
ground-truth files.

## Refreshing

These are copies, not a submodule. To re-sync:

```bash
SRC=/home/claude/skynet-data/pipeline_data

# Ground truth (small, always safe to refresh)
cp "$SRC"/afterglow_results/afterglow_web_values_*.csv  test_data/afterglow/
cp "$SRC"/afterglow_results/build_master_table.py       test_data/afterglow/
cp "$SRC"/afterglow_results/fieldcal/*.json             test_data/afterglow/fieldcal/

# Frames: every web-table subject under 9 MB, plus the two OCL frames
python3 - <<'PY'
import csv, glob, os, shutil
master = {r["file"] for r in csv.DictReader(open("test_data/afterglow/afterglow_web_values_master.csv"))}
found = {os.path.basename(p): p for p in glob.glob(
    "/home/claude/skynet-data/pipeline_data/test_subjects/optical/*/*.fits")}
keep = (master & set(found)) | {"m15_globular_lum_000.fits", "m15_globular_open_000.fits"}
for name in sorted(keep):
    if os.path.getsize(found[name]) < 9_000_000:
        shutil.copy2(found[name], f"test_data/optical/{name}")
PY
```

If a frame is replaced, the pinned values in `tests/test_photometry_pipeline.py`
and `tests/test_wcs_headers.py` are expected to move with it — they are
recorded-behaviour baselines for *these* frames, and each failure message says so.
