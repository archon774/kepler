# `test_data/` — real observational fixtures

Everything here is **real data copied verbatim** from the Skynet pipeline data
repository at `/home/claude/skynet-data/pipeline_data`. Nothing was synthesised,
resampled, trimmed, or re-headered. That is the point: Kepler's Python folders
are byte-preserving extractions from Skynet (see `CLAUDE.md`, "The extraction
contract"), so the tests that guard them have to run on the frames and the
recorded solver outputs the upstream pipeline actually produced.

**Total size: ~169 MB**, essentially all of it the 39 FITS frames. That is large
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

## `fieldcal/ocl_filter_report.json`

Skynet's OCL filter-substitution report: for ten Open/Clear/Lum frames it trials
`V`, `rprime` and `R` as substitute reference filters and records the resulting
slop, selecting the lowest. Copied from `zp-fits/ocl_fits/ocl_filter_report.json`.

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
