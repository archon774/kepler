# Kepler Tool Architecture

Date: 2026-08-10
Status: proposed, simplified

Kepler should expose a small set of basic Python tools around the detailed
astronomy algorithms already extracted in this repository. The tools are for
scripts, notebooks, agents, and command-line use. They should be ordinary Python
functions with clear inputs and clear outputs, not a framework.

This document covers only the tool package shape and the wiring between tools
and algorithms. Algorithm correctness, numerical fixes, large datasets, and
service deployment are outside this architecture.

---

## 1. Design Goal

The current algorithm folders contain useful astronomy logic, but many entry
points still look like pipeline or UI code. A tool package should make those
algorithms easy to call:

- pass normal Python values, file paths, or small Pydantic models;
- return normal Python dictionaries, small Pydantic models, or file paths;
- keep large arrays and tables out of inline results;
- avoid global setup wherever practical;
- keep tool modules thin enough to read in one pass.

The public tool layer should not reimplement astronomy math. It should prepare
inputs, call the extracted algorithm, and shape the result.

---

## 2. Target Layout

```text
kepler/
  __init__.py
  tools/
    __init__.py
    astrometry.py       # solve/read WCS
    photometry.py       # extract sources, measure photometry
    calibration.py      # zero-point calibration
    catalogs.py         # catalog declarations and band helpers
    query.py            # remote catalog queries
    workspace.py        # simple file/artifact helpers
  models.py             # small shared input/output/result models
  config.py             # environment and runtime settings
  artifacts.py          # simple local artifact path handling

  wcs/                  # existing Python algorithms, moved under kepler
  photometry/
  fieldcal/
  catalogs/
  query/

lightcurve/             # keep TypeScript extracts in place until needed
periodogram/
hrdiagram/
```

The Python tools are the public surface. The algorithm packages remain the source
of truth for scientific behavior.

Do not create extra architectural layers until a real tool needs them. If a tool
can call an algorithm directly with a small amount of input/output shaping, do
that. Add a private helper function inside the tool module before adding another
package.

---

## 3. Tool Rules

**Tools are thin.** A tool validates input, opens files if needed, calls one
algorithm workflow, and returns a compact result. If a helper starts doing
astronomy math, move that logic into the relevant algorithm package instead.

**Use simple shared models.** Put common result wrappers, image references,
table summaries, WCS summaries, and error shapes in `kepler/models.py`. Avoid a
large model tree until the package needs it.

**Prefer explicit dependencies.** Where old code expects global wiring, pass the
needed callables or settings through a small object. Compatibility globals can
remain temporarily, but new tools should not mutate process state.

**Keep outputs bounded.** Inline results should be summaries. Full source lists,
tables, generated FITS files, and plots should be written to disk and returned as
paths with basic metadata.

**Keep errors boring.** Use a small set of broad error codes only where a caller
needs to react differently: `invalid_input`, `not_found`, `no_solution`,
`dependency_missing`, `provider_unavailable`, `timeout`, and `internal_error`.
Do not build a large taxonomy before tools need it.

**Do not reorganize extracted helper trees as part of tool work.** The current
algorithm folders can keep their internal helper directories. Tool work should
focus on making useful callable entry points, not reshaping every implementation
detail.

---

## 4. Initial Tools

Start with the tools that are useful and easy to test locally:

- `describe_image_wcs(path)` — read WCS/header information from a FITS file.
- `list_photometric_catalogs()` — return available catalog declarations.
- `resolve_reference_band(catalog, image_filter)` — explain usable reference
  bands.
- `solve_zeropoint_from_measurements(measurements, catalog_sources)` — run the
  zero-point solve on caller-provided data.
- `list_artifacts()` / `describe_artifact(path)` — inspect local outputs.

Then add the heavier tools:

- `solve_astrometry(path, settings=None)`
- `extract_sources(path, settings=None)`
- `measure_photometry(path, sources, settings=None)`
- `calibrate_zeropoint(path, settings=None)`
- `resolve_target(name)`
- `search_catalog(catalog, region, limit=50)`
- `search_catalogs_for_image(path, limit=50)`

TypeScript-backed light-curve and HR-diagram tools can come later. Keep their
first Python wrapper simple: write/read JSON, run the existing implementation,
return a compact result.

---

## 5. Serving

Serving should be optional. A Python user should be able to import and call every
tool without running a server.

If Kepler later exposes a serving surface, generate it from the same Python
functions and models. Do not let serving requirements dictate the internal
package design.

---

## 6. Non-Goals

- No orchestration framework.
- No serving framework design.
- No migration audit machinery.
- No broad internal consolidation project as part of the tool architecture.
- No large error taxonomy before real tool behavior requires it.
- No TypeScript runtime redesign until those tools are actively implemented.
