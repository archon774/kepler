<!-- Rendered from tools/skill/source/references/hr.md by `python -m tools.skill`. Edit the source, not this file. -->

# HR diagrams

Two entry points, chosen by **what the user has**, not by what sounds more
thorough.

| The user | Use | Needs |
| --- | --- | --- |
| names a cluster and wants its HR diagram | `run_full_hr_pipeline_from_catalog` | nothing but the name |
| has supplied their own plate-solved FITS frame and wants that frame's photometry used | `run_full_hr_pipeline` | the frame |

"Give me information about NGC 6124 and produce an HR diagram" names no frame:
it is the catalog path. Do not ask for a FITS file the user never implied they
have.

> Authority: `tools/agent/prompt.py`, "Other guidance from observed failure
> modes" (the HR-diagram items).

## The stages, when the one-call tools need tuning

Catalog path: `get_literature_cluster_params` → `crossmatch_gaia_by_position`
→ `select_cluster_members` → `fit_and_compare_hr_diagram`.

Frame path: `extract_photometry_from_fits` → `crossmatch_gaia` →
`select_cluster_members` → `fit_and_compare_hr_diagram`.

Each passes a CSV artifact path to the next. Reach for the stages only to tune
or diagnose — for instance, widening `plx_sigma`, `pm_sigma` or
`pm_dispersion_km_s` in `select_cluster_members` when too few (or too many)
members survive. A nearby cluster needs a larger `pm_dispersion_km_s` floor
than a distant one for the same physical dispersion.

## What the results are, and are not

- **Open clusters only.** The literature source is Cantat-Gaudin & Anders
  (2020). A globular cluster ("M13", "47 Tuc") comes back `not_found`; say so
  rather than retrying other spellings.
- The literature parameters are **one catalog's numbers**, not a literature
  review. If the user wants citations or context, pair the pipeline with
  `build_literature_review`.
- The isochrone fit needs the Girardi grid: `KEPLER_ISOCHRONE_DIR`, or the
  optional bundle `kepler-mcp fetch-data isochrones` installs. Without it the
  fit stage cannot run; say that rather than reporting a partial run as a fit.
- A fit's `parameter_uncertainty` is always null: the Nelder-Mead optimizer has
  no covariance. Report "no uncertainty reported", and do not infer a
  precision from `reduced_cost`.
- `run_photometry_on_target` is not a substitute for this pipeline (it has no
  colour), and `extract_photometry_from_fits` is not a calibrated single-frame
  photometry report. Pick by what was asked for.

> Authority: `tools/agent/prompt.py`, "Other guidance from observed failure
> modes", "UNCERTAINTY AND NOT KNOWING"; `tools/registry.py`, the
> `fit_and_compare_hr_diagram` description.
