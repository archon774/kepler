# Photometry extraction record

Source: `/home/claude/skynet` (read-only). Destination: `/home/claude/Kepler/photometry/`.

This is a **verbatim extraction**, not a port. Every algorithm, constant, comment,
and numeric quirk is preserved exactly as it was in Skynet. The only edits are
import rewiring and the removal of hard dependencies on Skynet's ORM and
plate-solving stage, each marked in-place with an `# EXTRACTED:` comment.

Current package note: the copied Skylib files described below now live under
`kepler/skylib_lite/`; historical paths in this record describe the original
extraction layout.

---

## 1. Layout

```
photometry/
├── EXTRACTION.md          this file
├── __init__.py            new
├── pipeline/              the observation-asset processing stage (orchestration)
│   ├── __init__.py        new
│   ├── photometry.py      edited: 3 seams
│   ├── source_extraction.py  edited: 2 seams
│   └── schemas.py         subset + base-model shim
└── skylib/                vendored algorithmic core (all files byte-identical)
    ├── __init__.py        new
    ├── photometry/{__init__,aperture,aperture_numba,exposure}.py
    ├── extraction/{__init__,main,centroiding}.py
    ├── calibration/{__init__,background}.py
    └── util/{__init__,overlap,stats,angle,fits}.py
```

`pipeline/` orchestrates; `skylib/` does the math. The split mirrors the original
package boundary (`skynet-db` runner vs. the `skylib` library).

---

## 2. What was copied

### 2.1 Vendored skylib — byte-identical, zero edits

Verified with `diff -q` against the source after copying. All paths below are
relative to `/home/claude/skynet/packages/py/skylib/skylib/`.

| Source | Lines | Destination |
|---|---:|---|
| `photometry/aperture.py` | 570 | `skylib/photometry/aperture.py` |
| `photometry/aperture_numba.py` | 873 | `skylib/photometry/aperture_numba.py` |
| `photometry/exposure.py` | 647 | `skylib/photometry/exposure.py` |
| `photometry/__init__.py` | 5 | `skylib/photometry/__init__.py` |
| `extraction/main.py` | 381 | `skylib/extraction/main.py` |
| `extraction/centroiding.py` | 315 | `skylib/extraction/centroiding.py` |
| `extraction/__init__.py` | 8 | `skylib/extraction/__init__.py` |
| `calibration/background.py` | 76 | `skylib/calibration/background.py` |
| `util/overlap.py` | 385 | `skylib/util/overlap.py` |
| `util/stats.py` | 772 | `skylib/util/stats.py` |
| `util/angle.py` | 60 | `skylib/util/angle.py` |
| `util/fits.py` | 211 | `skylib/util/fits.py` |
| `util/__init__.py` | 8 | `skylib/util/__init__.py` |

**3,311 lines, unmodified.** Their intra-package relative imports
(`from ..calibration.background import ...`, `from ..util.stats import ...`,
`from .aperture_numba import ...`) resolve unchanged inside the vendored tree —
that is why the skylib directory layout was preserved rather than flattened.

`skylib/__init__.py` and `skylib/calibration/__init__.py` are the only two new
files in that tree; the originals pulled in `_version.py` and the bias/dark/flat
calibration modules respectively, neither of which came along.

Modules that came along but are **not on the photometry call path**:

- `photometry/exposure.py` — exposure-time calculator, sky-brightness model
  (Henyey–Greenstein scattering), Planck's law, CCM dust extinction. In the
  `skylib.photometry` package and squarely algorithmic, so it was pulled in as
  instructed, but nothing in `pipeline/` calls it. Its only internal dependency
  is `util/angle.airmass_for_el`.
- `util/angle.py` `angdist` / `average_radec`, `util/fits.py` `get_fits_fov`,
  `util/stats.py` `chauvenet2*` / `chauvenet3*` / `chauvenet` / `stddev2` /
  `stddev3`. These files were taken whole rather than sliced: they are
  self-contained (numpy + numba + astropy only) and cutting them apart would
  have risked silently changing behavior for no benefit.

### 2.2 Pipeline stage

| Source (under `skynet/packages/py/skynet-db/skynet_db/`) | Lines | Destination | Lines |
|---|---:|---|---:|
| `runners/observation_asset_processing/optical_data_processing/photometry.py` | 264 | `pipeline/photometry.py` | 289 |
| `runners/observation_asset_processing/optical_data_processing/source_extraction.py` | 310 | `pipeline/source_extraction.py` | 319 |
| `runners/common/schemas.py` (subset) | 331 total | `pipeline/schemas.py` | 311 |

The growth in the first two files is entirely `# EXTRACTED:` comment blocks. No
executable line was altered other than the import statements and the two
parameter annotations listed in §3.

`pipeline/schemas.py` takes these classes verbatim from `runners/common/schemas.py`:
`IPhotometry` (19–28), `IAperture` (31–40), `PhotometrySettings` (43–60),
`ISourceMeta` (63–68), `IAstrometry` (71–86), `IFwhm` (89–92), `ISourceId` (95–96),
`SourceExtractionSettings` (98–126), `SourceExtractionData` (129–157),
`Photometry` (176–192), `PhotometryData` (195–240). `Photometry` is not called by
the extracted code; it is kept because it documents the unit-suffixed output
names (`flux_err_counts`, `magnitude_err_mag`) that `run_photometry` translates
the skylib columns into.

---

## 3. Infrastructure seams cut

Every seam is marked in the source with `# EXTRACTED: was <original symbol>`.

| # | File | Cut | Consequence |
|---|---|---|---|
| 1 | `pipeline/photometry.py`, `pipeline/source_extraction.py` | `from skylib...` (installed package) → `from ..skylib...` (vendored) | None. Same code. |
| 2 | `pipeline/source_extraction.py` | `from skynet_db.models import ObservationAssetProcessingRun`; the `processing_run:` annotation on `perform_source_extraction` | None. The body already read the run duck-typed (`getattr(processing_run, "observation_asset_id", None)`); only the SQLAlchemy type annotation was dropped. |
| 3 | `pipeline/photometry.py` | Same ORM import + annotation on `perform_photometry` | None on the returned values. |
| 4 | `pipeline/photometry.py` | `from .wcs import build_wcs_from_header` → `from .source_extraction import build_wcs_from_header` | None. Not a reimplementation: `wcs.py` itself does `from .source_extraction import build_wcs_from_header`, so this is the identical function imported from its point of definition. Avoids dragging in the astrometry.net/ATLAS plate-solving stage (which belongs to Kepler `wcs/`). |
| 5 | `pipeline/photometry.py` | `build_wcs_for_processing_run(processing_run, header)` → `build_wcs_from_header(header)` | **Behavioral.** The original (`optical_data_processing/wcs.py:151`) is `build_wcs_from_header(header) or build_wcs_from_processing_run_solution(processing_run)`. The first term is kept; the second reconstructs a WCS from the plate solution persisted on the ORM row. If the FITS header carries no celestial WCS, `wcs` is now `None` where Skynet could still have recovered one from the database. Affects `perform_photometry()` only — `run_photometry()`, the numeric entry point, is untouched. |
| 6 | `pipeline/photometry.py` | `processing_run.ensure_photometry()` / `photometry_state.zero_point_mag = ...` | None on the returned values. Pure ORM job-state persistence; `settings.zero_point_mag` is already folded into each magnitude by `PhotometryData.from_source_and_row()`. |
| 7 | `pipeline/schemas.py` | `from skynet_sdk.schemas import SkynetBaseModel` → local base class | See below. |

### Seam 7 in detail

`SkynetBaseModel` (`skynet-sdk/skynet_sdk/schemas/base.py:139`) carries FastAPI /
OpenAPI / SQLAlchemy plumbing — the module imports `sqlalchemy`,
`sqlalchemy_utils`, and `annotated_types` at load time, so it cannot even be
imported without a database stack installed. Two of its behaviors are load-bearing
for photometry and were reproduced verbatim:

- **`model_config`** — `alias_generator=to_camel` (base.py:85–103), plus
  `populate_by_name`, `from_attributes`, `use_enum_values`. Required because the
  pipeline constructs and round-trips these models by snake_case field name while
  `IPhotometry.flux_error` / `mag_error` rely on their *explicit* aliases
  (`flux_err_counts` / `magnitude_err_mag`) matching the columns
  `run_photometry()` renames the skylib output to.
- **`_clean_nans` wrap serializer** (base.py:122–130, 176–178) — converts NaN/Inf
  floats to `None` on every `model_dump()`. This is numeric behavior, not JSON
  cosmetics: `PhotometryData.from_source_and_row()` calls
  `source.model_dump(exclude_unset=True)`.

Dropped as pure infrastructure: `model_registry` / `union_registry` /
`rebuilt_models` class registries and `rebuild_all_models()` /
`register_union()` / `get_registered_models()` / `clear_registry()`; the
`_strip_schema_titles` `json_schema_extra` hook; and the
`protected_namespaces=("protect_me_", "also_protect_")` config entry. All exist
to serve Skynet's generated API schema.

Verified after extraction: settings construction and `model_copy(update=...)`,
`from_source_and_row` (including `zero_point_mag` folding and the annulus
derivation `annulus_b_in = aper_a_in * aper_b_out / aper_a_out`), NaN→None on
dump, and camelCase alias generation with the two explicit aliases surviving.

### What was *not* cut

`logging` was left exactly as-is in `pipeline/photometry.py` (module logger, six
`logger.info` calls) and the `print(f"[source_extraction] ...")` diagnostic in
`run_source_extraction` was left in place. These are stdlib, carry no Skynet
dependency, and removing them would have been a rewrite.

---

## 4. What was left behind, and why

| Left in Skynet | Reason |
|---|---|
| `optical_data_processing/wcs.py` (932 lines) | Astrometric plate solving (astrometry.net + ATLAS backends). Belongs to Kepler `wcs/`. Only `build_wcs_from_header` was needed, and it is defined in `source_extraction.py`, which did come along. |
| `optical_data_processing/field_cal.py` (701 lines) | Photometric zero-point / field calibration. Belongs to Kepler `fieldcal/`. **See §6 — it holds one of the legacy-parity behaviors.** |
| `optical_data_processing/catalog_query.py`, `catalogs/` | Catalog access. Belongs to Kepler `catalogs/`. |
| `optical_data_processing/reduce.py`, `validate.py`, `batch_wcs_photometry_zeropoint_export.py` | Image reduction, validation harness, batch export driver. Not photometric math. |
| `optical_data_processing/test-photometry.py` (110 lines) | See §5. |
| `skylib/calibration/{bias,dark,flat,cosmic,cosmetic}.py` | Pre-photometry image calibration; not reachable from the photometry path. |
| `skylib/{astrometry,catalogs,combine,color,enhancement,ephem,io,quality,sonification}/` | Unrelated to photometry. |
| `runners/common/schemas.py`: `Mag`, `WcsCalibrationSettings`, `ICatalogSource`, `CatalogSource`, `Catalog`, `PhotometricCalibrationSettings`, `FieldCalResult`, `ImageProperties` | Other pipeline stages / other Kepler modules. |
| `skynet_db.models`, `skynet_db.config`, `runners/utils.py`, `runners/common` job machinery | ORM, S3, job-state. The seams above. |

---

## 5. `test-photometry.py` — not brought along

**Judgment: not a useful reference test; do not port it.** It is a scratch driver,
not a test:

- No assertions and no expected values. `main()` falls off the end returning
  `None`, so `sys.exit(main())` always exits 0 — it cannot fail.
- It does not exercise photometry directly. It calls `solve_wcs()` then
  `perform_field_calibration()`, i.e. it is a *field-calibration* driver that
  reaches photometry only transitively.
- It depends on the ORM (`ObservationAssetProcessingRun`) and on the astrometry
  and fieldcal stages — all three of which are outside this extraction.
- Its fixture path is stale. It looks for
  `../skynet-data/pipeline_data/test_subjects/bvr/ngc_3628_hamburer_test_12499172_V_0003_reduced.fits`;
  that tree has since been reorganized to `test_subjects/optical/<category>/` and
  neither the `bvr/` directory nor that FITS file exists any more.

The one thing worth keeping from it is the known-good aperture configuration it
encodes, recorded here so it is not lost:

```python
PhotometrySettings(a=5, b=5, theta=0,
                   a_in_px=10, a_out_px=15, b_out_px=15,
                   theta_out_deg=0, centroid_radius=5)
```

For actual parity testing, the useful material is elsewhere and is **not** part of
this repo: `/home/claude/skynet-data/pipeline_data/afterglow_results/` holds
legacy Afterglow reference outputs (`photometry/afterglow_photometry (4).csv`,
`afterglow_web_values_*.csv`) alongside FITS subjects in
`test_subjects/optical/`. That is the ground truth the "legacy parity" comments
below are defending.

---

## 6. Legacy Afterglow parity behaviors

These exist to reproduce a previous system's numeric output. All comments are
preserved verbatim. **Do not "clean these up".**

Preserved here:

| Location | Behavior |
|---|---|
| `pipeline/photometry.py:55` | `# Always recompute RA/Dec from current x/y — legacy parity (legacy always overwrote via wcs arg)` |
| `pipeline/photometry.py:237–238` | Build `PhotometryData` first, *then* apply WCS, so RA/Dec reflects the row's centroided pixel position — legacy parity. |
| `pipeline/schemas.py:279` | `# x/y from the row (post-centroid positions) override source positions — legacy parity` |
| `skylib/photometry/aperture.py:218` | `k = 0  # temporary fix for k = 0 not being allowed in AgA` — "AgA" is Afterglow Access. Clamps any automatic aperture factor ≤ 0.1 to 0, which then triggers the SNR-optimal aperture search. |

**No centroiding during field-calibration photometry** — this is realized by two
pieces that are both preserved: `PhotometrySettings.centroid_radius` defaults to
`0.0` (`pipeline/schemas.py`), and `run_photometry()` centroids only under
`if r_cent > 0:` (`pipeline/photometry.py:207`). `field_cal.py` does not override
`centroid_radius`, so calibration photometry runs uncentroided by default.

**`apcorr_tol=0` during calibration** — ⚠️ this one is **outside this extraction**.
It lives at `field_cal.py:612`:

```python
cal_phot_settings = phot_settings.model_copy(update={"apcorr_tol": 0.0})
```

Whoever extracts Kepler `fieldcal/` must carry that line across. Its effect is
here, in `skylib/photometry/aperture.py`: `apcorr_tol > 0` gates both the
growth-curve aperture-correction block (line 426) and the annulus-parameter setup
(lines 276, 374), so `0` disables aperture correction entirely.

---

## 7. The numba / plain relationship

**Correction to the briefing:** `aperture_numba.py` is *not* an accelerated
alternative to `aperture.py`. They are two layers of one implementation, and
`aperture.py` imports from `aperture_numba.py` unconditionally:

```python
from .aperture_numba import sum_circle, sum_ellipse, sum_circann, sum_ellipann, _sum_circle, _sum_ellipse
```

- **`aperture.py`** is the driver: aperture/annulus geometry, isophotal analysis,
  the SNR-optimal aperture search (`scipy.optimize.minimize` over
  `calc_flux_err`), flux-weighted medians for fixed aperture/ellipticity/rotation,
  background handling, ADU→electron conversion, magnitudes, and the growth-curve
  aperture correction. It calls the kernels below to sum pixels.
- **`aperture_numba.py`** is the pixel-summation kernel layer — a Numba port of
  SEP's `sum_circle` / `sum_circann` / `sum_ellipse` / `sum_ellipann`.

So the "plain implementation" that the numba module parallels is the **`sep` C
library**, not another file in this tree. Per its own module docstring, the port
differs from `sep` in three ways:

1. It always uses exact sub-pixel math (`subpix = 0`).
2. `sum_*()` returns `(flux, fluxerr, area, flags)` — SEP returns
   `(flux, fluxerr, flags)`. The extra `area` is what lets `aperture.py` compute
   aperture and annulus areas that correctly account for masked pixels and image
   edges, instead of using analytic ellipse areas.
3. It adds optional background outlier rejection (`reject_outliers=True`), which
   SEP has no equivalent for: it least-squares fits a plane to the annulus pixels
   and iteratively drops Chauvenet outliers from the residuals
   (`util/stats.chauvenet1`).

There is **no non-numba fallback path**. `numba` is a hard runtime requirement for
aperture photometry, not an optional accelerator.

Internal structure worth knowing before touching the file: `sum_aper_factory()`
generates a *pair* of jitted kernels per aperture shape — `_sum_aper` and
`_sum_aper_reject` — from six small `@njitc(inline='always')` shape callbacks
(`_aper_init_*`, `_aper_boxextent_*`, `_aper_rpix2_*`, `_aper_compare1_*`,
`_aper_compare2_*`, `_aper_exact_*`). Exact pixel/aperture overlap comes from
`util/overlap.py` (`circoverlap`, `ellipoverlap`), a Numba port of the
Robitaille/Barbary exact-overlap code. The factory-produced kernels are compiled
`cache=False` (closures are not cacheable); everything else uses the `njitc`
default of `cache=True`.

`sep` is still required — for `sep.Background` (`calibration/background.py`),
`sep.extract` (`extraction/main.py`), `sep.winpos` (`centroiding.py`), and the
`sep.APER_*` / `sep.OBJ_*` flag constants.

---

## 8. Preserved oddities

Verbatim extraction means these came across unchanged. Several look like bugs.
They are recorded, **not fixed** — any of them may be load-bearing for numeric
parity with legacy output.

1. `skylib/photometry/aperture_numba.py:537` — `_aper_init_ellipann` validates
   `if aper[3] > aper[3]:`, comparing a value to itself. Presumably meant
   `aper[3] > aper[4]` (inner > outer radius). The check is dead.
2. `skylib/photometry/aperture_numba.py:307` — `_sum_aper_reject` indexes the mask
   box-relative (`mask[iy - ymin, ix - xmin]`) while `_sum_aper` at line 212
   indexes it absolutely (`mask[iy, ix]`). Reached only with
   `reject_outliers=True` and a non-`None` mask.
3. `skylib/extraction/centroiding.py:305` — in the `method='win'` all-good branch,
   `y[:] = y + 1` uses the input `y` rather than the windowed result `y1`.
   Unreached on this pipeline path: `run_photometry` calls `centroid_sources`
   with the default `method='iraf'`.
4. `skylib/extraction/main.py:257–261` — the "Make sure that a >= b" block assigns
   through `sources[s][...]` where `s` is a boolean mask. Boolean indexing returns
   a copy, so those three statements are no-ops. The adjacent
   `sources['theta'] %= np.pi` (line 260) is a field view and does take effect.
5. `skylib/extraction/main.py:105–106, 280–286` — the `centroid` parameter is
   documented as using "the windowed algorithm (SExtractor's XWIN_IMAGE,
   YWIN_IMAGE)" but the code calls `centroid_iraf` / `centroid_iraf_masked`. The
   comment at line 281 (`# Centroid sources using IRAF-like method`) matches the
   code; the docstring does not.
6. `skylib/photometry/aperture.py:542–545` — a `background_rms` column is appended
   to the output record array but never assigned, so it stays 0. (The docstring
   lists it as an output field.)
7. `skylib/util/stats.py:292` — a second `from numba import njit` mid-module,
   immediately before `chauvenet1 = njit(...)(chauvenet1py)`, with the comment
   "Compile WITHOUT parallel=True to avoid parfors entirely". Redundant but
   harmless; the comment records a real constraint.

---

## 9. External dependencies

Required by the extracted code:

| Package | Used for |
|---|---|
| `numpy` | Everywhere. Record arrays (`numpy.lib.recfunctions.append_fields`), masked arrays. |
| `scipy` | `optimize.minimize` (optimal aperture), `optimize.leastsq` (PSF centroiding), `ndimage.gaussian_filter` (downsample prefilter); `optimize.fsolve` / `least_squares` and `special.erf` in `exposure.py`. |
| `numba` | **Hard requirement.** All aperture summation kernels, exact overlap, centroiding, Chauvenet rejection, isophotal analysis. No pure-Python fallback exists. |
| `astropy` | `wcs.WCS`, `io.fits.Header`, `stats.gaussian_fwhm_to_sigma` / `gaussian_sigma_to_fwhm`, `convolution.Gaussian2DKernel` / `Kernel2D`, `modeling.models.Gaussian2D`; `time.Time` and `coordinates.*` in `exposure.py`. |
| `sep` | `Background`, `extract`, `winpos`, and the `APER_*` / `OBJ_*` flag constants. |
| `pydantic` (v2) | `pipeline/schemas.py` settings and data objects; `pydantic.alias_generators.to_pascal` backs the local `to_camel`. |

**Optional / lazy:**

| Package | Used for |
|---|---|
| `photutils` | Imported *inside* `skylib/extraction/main.py: histogram()` and only when called with `bins='background'` (`Background2D`, `ModeEstimatorBackground`, `MADStdBackgroundRMS`). The photometry path never passes that argument — `auto_sat_level()` calls `histogram(data, bins=16)` — so `photutils` is not needed unless that branch is used. |

**Not required** (severed): `sqlalchemy`, `sqlalchemy_utils`, `skynet_db`,
`skynet_sdk`, `annotated_types`, and anything S3 or job-runner related.

`astropy.coordinates.NonRotationTransformationWarning` (imported by
`exposure.py`) requires a reasonably recent astropy; note that `exposure.py` is
not on the photometry call path if that import proves inconvenient.

---

## 10. Verification performed

- `diff -q` against source for all 13 vendored skylib files — byte-identical.
- `python3 -m compileall` over the whole tree — clean.
- Import-graph audit: no `skynet_db`, `skynet_sdk`, or absolute `skylib` imports
  remain outside `# EXTRACTED:` comments.
- `pipeline/schemas.py` executed and exercised (settings construction,
  `model_copy(update={"apcorr_tol": 0.0})`, `from_source_and_row` with
  `zero_point_mag`, annulus derivation, NaN→None dump, alias generation).

**Not** verified: no end-to-end numeric run was possible in this environment —
`scipy`, `numba`, `sep`, and `photutils` are not installed here. The vendored
skylib files are byte-identical to their source, so no numeric drift can have
been introduced there; the untested surface is limited to the import rewiring in
`pipeline/`.
