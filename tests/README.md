# `tests/` — algorithm and tool smoke suite

```bash
uv sync
uv run pytest                 # default no-network suite
uv run pytest -m "not slow"   # skip the pixel-level work on real frames
```

## What this suite is for

Kepler's Python folders are **byte-preserving extractions** from Skynet (see
`CLAUDE.md`, "The extraction contract"). So these are not tests of whether the
algorithms are *right* — that question was settled upstream. They test whether
the algorithms still do **exactly what they did before the extraction**,
including the parts that are wrong.

Most files are algorithm-preservation tests. Tool smoke tests live here too
when they cover the public `tools/` surface without network calls or generated
artifacts, so the default `pytest` run collects them with the rest of the suite.

Three consequences shape everything here:

1. **Real data, not synthetic.** Fixtures are 39 real PROMPT/Skynet frames and
   four complete recorded Skynet zero-point solves. See `test_data/README.md`.
2. **Recorded output, not recomputed expectations.** The centrepiece,
   `test_fieldcal_solution.py`, feeds `calc_solution` the exact rows Skynet fed
   it and compares against the exact numbers Skynet returned — bit-for-bit on
   four fields.
3. **Known bugs are pinned, not fixed.** Where a test documents a defect it says
   so in capitals, gives the upstream file it was verified against, and states
   what to do if someone decides to diverge. Deleting such a test is part of
   fixing the bug; changing the algorithm without touching the test is not.

## Layout

| File | Covers |
| --- | --- |
| `conftest.py` | Fixtures, frame aliases, skip guards, the `network` opt-in |
| `test_fieldcal_solution.py` | **`calc_solution` bit-exact parity** against four recorded Skynet fits |
| `test_fieldcal_afterglow_parity.py` | Cross-implementation parity vs the Afterglow web service |
| `test_fieldcal_ref_mag.py` | Reference-magnitude resolution order, colour transforms, the `eval` guardrail |
| `test_fieldcal_pipeline.py` | The `deps` seam, source matching, end-to-end calibration on a real frame |
| `test_catalogs_registries.py` | Declarations, the two-registry divergence, no-network guarantee |
| `test_query_selection.py` | Filter-aware catalog selection and its agreement with ref-mag resolution |
| `test_query_geometry.py` | WCS footprints, sky-box clipping, deduplication |
| `test_query_binding_runner.py` | The `(Declaration, Backend)` MRO contract, region validation, config |
| `test_photometry_extraction.py` | SEP extraction on real frames, crop regions, WCS construction |
| `test_photometry_pipeline.py` | Aperture photometry, magnitude arithmetic, aperture correction |
| `test_photometry_tool_smoke.py` | Cheap no-network smoke coverage for the Claude photometry tool and bundled target resolution |
| `test_wcs_headers.py` | Pixel scale and pointing across all 39 real headers |
| `test_wcs_solution.py` | CD/PC matrices, parity, acceptance, header write-back |
| `test_skylib_stats.py` | `chauvenet` and the statistics under the zero-point solve |
| `test_skylib_geometry.py` | Pixel/aperture overlap, spherical angles, orientation decomposition |
| `test_skylib_fits.py` | Gain, exposure, observation time, field of view |
| `test_skylib_exposure.py` | Exposure-time calculators |

## Markers

- `slow` — runs source extraction or photometry over a real frame. Included by
  default; `-m "not slow"` skips them.
- `network` — reaches a live catalog service. **Never runs by default.** Needs
  both `-m network` and `KEPLER_TEST_NETWORK=1`, per CLAUDE.md's rule that
  default checks stay deterministic and bounded.
- `solver_data` — needs astrometry.net index files covering a ~10 arcmin field,
  or a local UCAC4/UCAC5 tree. Skips itself when the data is absent, which it
  normally is: the commonly packaged 4107-4119 index set starts at 22 arcmin
  and cannot solve these frames.

## CI

`.github/workflows/ci.yml` runs `uv run --locked pytest` as a required job.
The default suite remains deterministic: network-marked tests are skipped unless
`KEPLER_TEST_NETWORK=1` is set explicitly.

## Defects recorded here

Everything below was verified against the upstream Skynet source **before**
being written down; each one reproduces there too, so these are preserved by the
extraction contract rather than introduced by it. Nothing here has been fixed.

They are collected in one place because they are the single most likely thing to
be mistaken for a broken test. If one of these assertions fails, the algorithm
changed — which may be the intent, but is never an accident.

### Wrong output or a crash

| Where | What | Test |
| --- | --- | --- |
| `skylib_lite/util/overlap.py` | `ellipoverlap` **segfaults** — does not raise — when a rectangle is centred on the ellipse and large relative to it. The shared diagonal passes through the circle centre and the recursive clipping in `triangle_unitcircle_overlap` never terminates. Reachable from `aperture_numba.py:579` whenever a source sits on a pixel centre with an effective semi-axis below ~0.36 px; `run_photometry` validates only `a > 0`. Measured boundary: 0.40 fine, 0.35 fatal. Pinned in a subprocess so pytest survives. | `test_skylib_geometry.py` |
| `skylib_lite/util/fits.py` | `get_fits_fov`'s no-WCS fallback collapses **southern declinations to 0.0**. The sign factor is `(1 - startswith('-'))`, i.e. `1 - True = 0`; the correct form — used by `catalogs/landolt_catalog.py` for the same job — is `(1 - 2*…)`. Only reachable for an *unsolved* southern frame, and every southern fixture frame is solved. | `test_skylib_fits.py` |
| `photometry/source_extraction.py` | Any crop that narrows the **columns** raises `ValueError: array is not C-contiguous` inside `sep`. `_crop_data` returns a numpy view; row-only slices stay contiguous, column slices do not. `_ensure_native_contiguous` exists in the sibling `photometry.py` and was never applied here. | `test_photometry_extraction.py` |
| `query/geometry.py` | `clip_sources_to_box` **silently returns zero sources** near a pole. Once `sin(w/2)/cos(dec) > 1` the `arcsin` yields NaN, every subsequent comparison against NaN is `False` — including the pole and RA-wrap guards — and execution falls through to a filter that rejects everything. At dec 89.5 a 60-arcmin box is already enough. The failure surfaces as "no catalog sources", not as an error. | `test_query_geometry.py` |
| `wcs/header_utils.py` | `_parse_ra_dec_values` **raises** on the comma decimal separators three fixture frames use (`'00:42:44,3'`), and `guess_icrs_radec_from_header` does not catch it. Latent only because those frames are solved, so `CRVAL` answers at step 1. An unsolved frame from the same telescope — exactly the case a solver hint exists for — would raise. | `test_wcs_headers.py` |
| `wcs/wcs.py` | `_clear_wcs_solution_fields` clears `ra`/`dec`/`pixel_scale`/`rotation` while the solve writes `ra_deg`/`dec_deg`/`pixel_scale_arcsec_per_px`/`rotation_deg`. The four clears are no-ops and stale astrometry survives a failed solve. Documented in `wcs/EXTRACTION.md` §5.2; `WcsSolution` is deliberately **not** a `slots` dataclass so this stays a silent no-op rather than an `AttributeError`. | `test_wcs_solution.py` |
| `wcs/wcs.py` | A header rewrite clears `RADESYS` but **not** `EQUINOX` or `RADECSYS`, so a stale frame declaration can outlive the solution it described — a ~0.6° error if a B1950 `EQUINOX` survives onto an ICRS solve. Latent: no fixture frame carries either keyword. | `test_wcs_solution.py` |
| `fieldcal/solution.py` | `calc_solution` raises `ValueError: math domain error` on perfectly zero-scatter input, via float cancellation in the weighted-error term at `solution.py:141`. Unreachable with real photometry; very reachable from a tidy synthetic fixture. Pinned against a real frame because the cancellation depends on the exact magnitudes. | `test_fieldcal_solution.py` |

### Divergences and dead code

| Where | What | Test |
| --- | --- | --- |
| `catalogs/` + `fieldcal/ref_mag.py` | OCL (Open/Clear/Lum) filters resolve for catalog **selection** but not for **strict** reference-magnitude resolution — the two read different registries, and only `CATALOGS` carries `_OCL_TO_V`. Unfiltered frames still calibrate against V, but by the non-legacy preferred-band fallback rather than the declared mapping. `strict_filter_parity=True` calibrates nothing for them. The recorded OCL policy (`ocl_filter_report.json`) is a three-way V/r'/R trial the fixed fallback cannot express. | `test_query_selection.py` |
| `wcs/header_utils.py` | `estimate_pixel_scale_arcsec_per_pix` documents a three-step preference order but has steps 1 (WCS) and 3 (optics) **commented out** upstream. Only direct keywords are consulted, so a header with a good CD matrix and no `SECPIX` returns `None`. | `test_wcs_headers.py` |
| `query/geometry.py` | The `ra_max >= ra_min + 24` "whole sky" branch is **unreachable**: `arcsin` caps at 90°, so the RA half-width never exceeds 6 h and the span never reaches 24. Beyond that point the NaN path above takes over. | `test_query_geometry.py` |
| `query/geometry.py` | `combined_bounding_box` is a working function that upstream guarded off with `if False:`; nothing in Kepler calls it. Kept as code because the reason it was disabled was never recorded. | `test_query_geometry.py` |
| `query/geometry.py` | Two footprint implementations disagree by design: `boxes_from_wcs` projects corners and tracks rotation; `image_boxes_from_wcs` multiplies pixel scale by axis length and is **blind to rotation**. 2.6% apart on a 1.6° frame, and growing with angle. | `test_query_geometry.py` |
| `catalogs/vsx_catalog.py` | VSX declares all 35 of its bands as the empty **string** `''`, where every other catalog uses a list of column names. Both are falsy so readers keying on `set(catalog.mags)` are unaffected — but anything indexing the value breaks, and `_filter_variable_stars` swallows exceptions, so it would silently disable variable-star rejection. | `test_catalogs_registries.py` |
| `catalogs/catalog_options.py` | `_MutatingCatalog` merges `filter_lookup` into the **class** dict, where `catalogs.catalog.Catalog` rebinds an instance copy. Preserved as an upstream difference; safe only because both classes are private and instantiated once. | `test_catalogs_registries.py` |
| `catalogs/apass_catalog.py` | APASS declares a `U` transform referencing `uprime`, which APASS does not carry. The entry is unsatisfiable, and reference-magnitude resolution deliberately returns `(None, None)` rather than falling back — substituting V for a U frame is ~1.5 mag. Tracked in `UNSATISFIABLE_LOOKUPS` so a *new* unresolvable entry fails the test. | `test_catalogs_registries.py` |
| `catalogs/__init__.py` | Four registry keys differ from the plugin's own `name`: `Stetson`→`StetsonGlobs`, `Tycho`→`Tycho2`, `UCAC`→`UCAC5`, `USNO`→`USNOB1`. `CatalogSource.catalog_name` is populated from `name`, so a source from Stetson reports a catalog string matching no registry key. | `test_catalogs_registries.py` |
| `fieldcal/ref_mag.py` | `_ALLOWED_TOKENS` rejects the raw expression **before** the apostrophe sanitiser runs, so a band spelled `g'` can never appear inside a transform — the sanitiser is unreachable for exactly the names it looks written for. Every shipped transform uses `gprime`/`rprime`/`iprime` for this reason; a `g'`-spelled one would fail silently as `None`. | `test_fieldcal_ref_mag.py` |
| `query/selection.py` | `_filter_token_candidates(" v ")` returns `[" v ", "v", " V "]` — never a bare `"V"`, because `.upper()` runs on the unstripped string. Safe only because `select_catalogs_for_filter` normalises first; calling `catalog_supports_filter` directly with a padded name can miss. | `test_query_selection.py` |
| `photometry/photometry.py` | With aperture correction on (the default `apcorr_tol=1e-4`), `mag` and `flux` **disagree**: the correction adjusts the magnitude but `flux` keeps the raw aperture sum, so recomputing `-2.5*log10(flux/texp)` is ~0.11 mag off on the fixture frame. One more reason field calibration forces `apcorr_tol = 0`. | `test_photometry_pipeline.py` |
| `photometry/photometry.py` | A supplied `gain` of exactly `1` is treated as **unset** and replaced from the header, so a caller genuinely wanting unit gain cannot ask for it. Changes every reported flux uncertainty. | `test_photometry_pipeline.py` |
| `wcs/wcs.py` | Header write-back is **not bit-exact**: `to_header(relax=True)` refactors `CD` into `PC` × `CDELT` and the recovered matrix differs in the 5th significant figure (~5e-5 relative). A few hundredths of an arcsec across a frame — harmless, but not zero. | `test_wcs_solution.py` |
| `skylib_lite/util/stats.py` | `quantile` is the Maples et al. (2018) estimator with a sample-size correction factor, **not** `np.quantile`; its own docstring warns it "does not work for q near 0 and 1", and at q=1 it returns a value above the sample maximum. | `test_skylib_stats.py` |
| `skylib_lite/util/stats.py` | `chauvenet` on a small sample rejects **nothing**: sigma is estimated from the same data, so two ±50 outliers in six points produce sigma≈32 and nothing exceeds the criterion. This is why `calc_solution` supplies its own `sigma_override`. | `test_skylib_stats.py` |
| `skylib_lite/photometry/exposure.py` | `mag_for_exptime_and_snr` and `flux15_for_exptime_mag_and_snr` are **approximate** inverses — 0.07 mag and ~10% respectively — where the exptime/SNR pair round-trips to 1e-6. Fine for planning, not for a calibration round trip. | `test_skylib_exposure.py` |
| `skylib_lite/photometry/exposure.py` | Neighbouring helpers disagree on units: `planck_law` takes **metres**, `dust_extinction` takes **nanometres**. Passing metres to the latter silently returns 0.0 extinction. | `test_skylib_exposure.py` |
| `wcs/header_utils.py` | `_parse_ra_dec_values` reads any numeric RA ≤ 24 as **hours**, so a header meaning 10 degrees yields 150. Undecidable from the number alone; real headers use sexagesimal strings, and every fixture frame does. | `test_wcs_headers.py` |

## Not covered

Gaps are listed so they are visible rather than assumed.

| Area | Why not, and what it would take |
| --- | --- |
| **TypeScript** — `algorithms/lightcurve/`, `periodogram/`, `hrdiagram/` | `package.json` provides `tsc --noEmit` typechecking only; there is **no test runner**. Covering the Lomb-Scargle core, period folding, field-star removal and `computePlotDelta` needs a runner (vitest or jest) added as a devDependency — a tooling decision left to a maintainer. The FITS fixtures here do not apply to light curves; those algorithms would need their own recorded Astromancer inputs and outputs. |
| **`solve_wcs` end to end** | Marked `solver_data` and skips. `solve-field` is on PATH but the packaged 4107-4119 index set starts at 22 arcmin, and these frames are ~10 arcmin — so the blind solve returns no solution rather than failing. Needs the 4200-series indexes, or a local UCAC4/UCAC5 tree with `ATLAS_CATALOG_ROOT` set. The test asserts the recovered centre and parity against the frame's own solution once data is available. |
| **The ATLAS triangle solver** | `skylib_lite/astrometry/atlas/` — `sample_triangles`, `triangle_invariant_and_order`, `build_kdtree`, `solve_oriented`, `solver.py`. Only the orientation round-trip (`decompose_linear` ↔ `_known_cd_rad_per_pix`) is covered; matching itself needs a local UCAC catalog. |
| **Live catalog queries** | `query/runner.py`'s network path, the VizieR/SDSS/SkyMapper backends, and `query/cache.py`. One `network`-marked smoke test exists for APASS. The row mappers (`table_to_sources` on Landolt, USNO, VSX) are covered structurally via the MRO contract but not executed against real provider rows — that needs recorded VizieR responses, which this repository does not carry. |
| **`fieldcal/batch_wcs_photometry_zeropoint_export.py`** | A batch driver over the whole pipeline; every stage it calls is covered individually, but the driver itself needs the solver data above to run. |
| **Broader `tools/` coverage** | The Claude photometry tool has no-network smoke coverage here. The rest of `tools/` still warrants focused tests over the public tool schemas and runner behavior. |

## Adding tests

- Say **why** a value is what it is. A bare `assert x == 0.61153` is a
  tripwire; the same assertion with "SECPIX, as the camera reported it" is
  documentation.
- Label recorded baselines as recorded, in the failure message, so the next
  person knows whether to re-record or investigate.
- Anything that could open a socket gets `@pytest.mark.network`.
- Prefer a real frame over a synthetic array. If a synthetic one is genuinely
  clearer, give it realistic noise — several algorithms here misbehave on
  perfectly clean input, and that is the trap, not the point.
