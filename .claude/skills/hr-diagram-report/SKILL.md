---
name: HR Diagram Report Standard
description: Use whenever building, fitting, or reporting an HR/colour-magnitude diagram for a star cluster (via tools.hr_diagram, hr_agent.py, or by calling algorithms.hrdiagram directly) — before presenting results, cite every catalogue/source used and flag anything uncertain rather than stating fitted numbers as settled fact. Triggers on "HR diagram", "colour-magnitude diagram", "CMD", "isochrone fit", "cluster distance/age/reddening/E(B-V)/metallicity", "field star removal", "cluster members".
---

# HR diagram reporting standard

This pipeline (`tools.hr_diagram`, the thin tool layer; `hr_agent.py`,
the conversational front end; `algorithms.hrdiagram`, the algorithm package
underneath both) pulls numbers from several external catalogues and fits them
with an optimizer that has known, demonstrated failure modes (see
`kepler/hrdiagram/isochrones.py`'s MIST_FILTER_MAP comment and the
`age_is_literature_default` handling — both exist because a real fit went
wrong in ways that looked plausible until checked). Every report built from
this pipeline's output must therefore do two things, every time, not just
when something looks obviously wrong:

1. **State which catalogue(s) supplied every literature number.**
2. **Flag uncertainty explicitly, and phrase unresolved numbers as a
   hypothesis, not a fact.**

Both are cheap to do because the pipeline's own output already carries the
information needed — this is about not dropping it when summarizing for a
human, not about doing extra analysis.

## 1. Always cite sources

Pull straight from the tool output, don't paraphrase from memory:

- **Open cluster params** (distance, age, E(B-V), parallax, PM): `literature["source"]`
  → Cantat-Gaudin & Anders 2020, A&A 640, A1 (VizieR `J/A+A/640/A1`), Gaia-DR2-based.
- **Globular cluster params**: `literature["source"]` → Harris 1996 (2010 ed.,
  VizieR `VII/202`) for distance/E(B-V)/[Fe/H]; Vasiliev & Baumgardt 2021,
  MNRAS 505, 5978 (VizieR `J/MNRAS/505/5978`) for parallax/proper motion — these
  are *two different catalogues*, name both, don't collapse to "Harris".
- **Isochrone grid**: `isochrone_path` (and `isochrone_source`) tells you which —
  MIST v1.2 (Choi et al. 2016; Dotter 2016, mist.science) is the default, PARSEC
  (Bressan et al. 2012, stev.oapd.inaf.it/cmd) is a fallback/cross-check, and
  SPOTS (Somers, Pinsonneault & Cao 2019, Zenodo, doi:10.5281/zenodo.3593339) is
  a starspot-inflated pre-main-sequence grid for young clusters. Say which one
  produced the plot.
- **Multi-band photometry** (when the diagram used `crossmatch_gaia`): Gaia DR3
  (`gaiadr3.gaia_source`), not the frame's own instrumental magnitude.
- **Name resolution**: if `resolve_cluster_name`/`resolve_globular_cluster_name`
  had to fall back to a SIMBAD alias (e.g. "M35" → NGC 2168, "47 Tuc" → NGC 104),
  say so — don't present the resolved name as if the user typed it.

A one-line "Sources: Cantat-Gaudin & Anders (2020); MIST v1.2" (or the
globular-cluster equivalent, or "...; SPOTS (Somers, Pinsonneault & Cao 2019)"
when that grid was used) at the end of a report costs nothing and is required,
not optional.

## 2. Flag uncertainty — check every one of these before reporting a number as solid

- **`literature.get("age_is_literature_default")` is True**: the "literature"
  age for this globular cluster is a fabricated ~12.6 Gyr placeholder (Harris
  doesn't publish per-cluster ages), *not a measurement*. Never present a fit's
  age-agreement/disagreement with it as validation or contradiction of
  anything. Say plainly that no real literature age exists for comparison.
- **Small `fitted["n_stars_fitted"]`** (rule of thumb: under ~50-100 for a
  cluster fit): say the sample is small and the fit correspondingly noisy.
- **Giant-branch-only photometry (no main-sequence turnoff reached)**: age is
  essentially unconstrained by the data no matter what number comes out of the
  optimizer — this was empirically confirmed on NGC 1851 (nearly flat cost
  surface across the whole age grid, and independently, human-fit results
  across a class group had a standard deviation of ~0.7 dex in log(age), a
  factor of ~5 in linear age). Don't report a fitted age from RGB-only data
  without this caveat.
- **`fitted["pre_dereddened_ebv"]` unset (0.0) but you don't actually know
  whether the input photometry was pre-corrected for reddening**: ask, don't
  assume. Getting this wrong makes E(B-V) look artificially small next to
  literature. If it *is* set, report both `ebv_residual` and the total `ebv`,
  and make clear the total is residual + pre-applied, not an independent
  measurement.
- **Crowded-field / low Gaia match rate** (`n_gaia_matched` much smaller than
  `n_detected`, or membership cuts loose): field-star contamination is a real,
  demonstrated driver of fit instability here — note that repeated runs on the
  same data can land on visibly different (distance, E(B-V)) pairs (observed
  directly: three runs on the same NGC 1851 file gave E(B-V) totals of 0.15,
  0.11, and 0.15 with distance 11.6-14.2 kpc). A single run's numbers are a
  point estimate, not a precise result — say so, and prefer reporting a range
  or re-running when precision matters.
- **`select_cluster_members` is a simplified circular PM cut + parallax
  window**, not Astromancer's fitted elliptical field-star-removal region
  (see its docstring in `kepler/hrdiagram/membership.py`). If field
  contamination looks likely given the diagram, name this as a methodological
  simplification, not treat the membership list as ground truth.
- **`isochrone_source == "spots"`**: `fitted["fspot"]` is a *fit result*, not a
  literature-known cluster property — it's whichever of the grid's 6 discrete
  starspot covering fractions (0/17/34/51/68/85%) gave the lowest cost when
  scanned alongside age, the same way distance/E(B-V)/age are fit, not an
  independently measured quantity. Report it as "the fit preferred a covering
  fraction of ~X%", not as a known property of the cluster. The SPOTS grid is
  also single (solar) metallicity only — for a cluster with a literature [Fe/H]
  far from solar, say that the metallicity match is approximate.
- **Large `comparison["distance_pct_diff"]` / `ebv_diff` / `age_pct_diff`**:
  don't silently report a big literature discrepancy as if the fit is simply
  wrong. Check whether it's consistent with an independent estimate (another
  fit run, a different isochrone_source, a group's own by-eye result) before
  concluding the catalogue value or the fit is the problem — sometimes, as
  with NGC 1851's E(B-V), the fit and an independent human estimate agree with
  each other and disagree with the catalogue, which is itself worth reporting
  plainly rather than picking a side.

## 3. Language

Prefer: "the fit suggests...", "consistent with...", "not well constrained by
this data", "should be treated as a working estimate, not a confirmed value".

Avoid stating a fitted distance/age/E(B-V) as a bare fact ("NGC 1851 is at
11.6 kpc") when any of the flags above apply — attach the caveat in the same
sentence or the next one, not buried in a footnote.
