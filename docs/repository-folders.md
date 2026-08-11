# Repository Folder Guide

This guide explains the current source folders in Kepler. It documents the
repository as it exists now: a Python package shell around extracted algorithm
modules, a prototype database tool, TypeScript extraction folders, and planning
material for future tool work.

Generated folders such as `__pycache__/`, Git internals such as `.git/`, and
workspace support folders are not part of the source layout.

## `.github/`

Repository automation and ownership policy.

- `CODEOWNERS` assigns maintainer ownership for the repository.
- `pull_request_template.md` defines the review checklist shape.
- `workflows/ci.yml` runs the current lightweight Python/repository-shape checks.
- `workflows/secret-scan.yml` runs gitleaks against the tree and history.
- `workflows/workflow-safety.yml` runs actionlint and zizmor against workflows.

Keep workflow changes narrow and security-conscious. The current checks are
deliberately small because the extracted science code still needs native
dependencies, external catalog data, and reference FITS fixtures for full
end-to-end validation.

## `kepler/`

The installable Python package root.

Important files and subfolders:

- `tools/`: the first plain Python user-facing tool wrappers.
- `models.py`: small shared result, warning/error, WCS, catalog, zero-point,
  and artifact summary models.
- `config.py`: small environment-backed settings helpers for the tool layer.
- `artifacts.py`: local artifact description and listing helpers.
- `kepler/wcs/`, `kepler/photometry/`, `kepler/fieldcal/`,
  `kepler/catalogs/`, `kepler/query/`: extracted Python algorithm packages.

## `kepler/tools/`

Plain Python tool wrappers around the first local Kepler surfaces.

Current tools:

- `astrometry.describe_image_wcs(path)`: describe celestial WCS metadata in a
  FITS header.
- `catalogs.list_photometric_catalogs()`: list local catalog declarations
  without querying remote services.
- `catalogs.resolve_reference_band(catalog, image_filter)`: summarize the local
  filter-to-reference-band mapping Kepler would use.
- `calibration.solve_zeropoint_from_measurements(measurements, catalog_sources)`:
  solve a zero point from local measurement and catalog-source records.
- `workspace.list_artifacts(directory=None)` and
  `workspace.describe_artifact(path)`: inspect local artifact files.

## `kepler/catalogs/`

Extracted Python catalog declarations from Skynet and Afterglow.

What Kepler knows about each photometric catalog, and nothing about reaching
them: no module here imports `astroquery` or opens a socket. Eleven catalogs —
APASS, Landolt, PanSTARRS, SDSS, SkyMapper, Stetson, 2MASS, Tycho-2, UCAC5,
USNO-B1, VSX.

Each plugin declares its band table (`mags`), its filter/colour transforms
(`filter_lookup`), its column mapping, and its VizieR table ID. Three plugins
also carry photometric conversions applied to their rows.

Important files:

- `catalog.py`: the plugin base class — the declaration contract.
- `<name>_catalog.py`: one module per catalog.
- `catalog_options.py`: the second, smaller registry (`CATALOG_OPTIONS`) that
  reference-magnitude resolution reads. It is *not* redundant with `CATALOGS`;
  see `EXTRACTION.md` §4.
- `schemas.py`: `CatalogSource` and friends — the data contract between
  `kepler.catalogs` and `kepler.query`.
- `simbad.py`: the 206-entry SIMBAD object-type vocabulary.
- `EXTRACTION.md`: provenance, renames, preserved behaviours, verification.
- `ned.py`, `atnf.py`, `ads.py`: newer, non-extracted lookup tables for
  `kepler.tools.ned`, `kepler.tools.atnf`, and `kepler.tools.ads` — NED's
  `table=` vocabulary, the ATNF/psrqpy parameter list (copied as static data
  rather than importing `psrqpy` here), and ADS's field-search syntax plus a
  citation formatter, all declaration/formatting only, keeping this package's
  zero-query-library-import contract.

Current caveats:

- Two registries exist and disagree deliberately. Merging them changes which
  reference band a narrowband or unfiltered image calibrates against.

## `docs/`

Project documentation and planning material.

- `architecture-brainstorm.md` describes the intended future package direction:
  public astronomy tool contracts, application services, Pydantic models,
  provenance, artifacts, bounded remote calls, and dependency policy.
- `repository-folders.md` is this current-state folder guide.

Docs in this folder should distinguish clearly between the repository's current
extracted-code state and the planned package architecture.

## `kepler/fieldcal/`

Extracted Python photometric field-calibration code from Skynet.

Primary responsibilities:

- Match catalog sources to detected image sources.
- Reject known variable stars through the VSX path when wired.
- Resolve reference magnitudes for the image filter.
- Run aperture photometry on matched sources through injected dependencies.
- Solve the photometric zero point with Chauvenet rejection.
- Write `PHOT_M0`, `PHOT_M0E`, and `PHOT_CAL` into the FITS header when possible.

Important files and subfolders:

- `field_cal.py`: main calibration workflow, exposed as
  `perform_field_calibration`.
- `solution.py`: zero-point solver, exposed as `calc_solution`.
- `ref_mag.py`: reference-magnitude/filter-resolution logic.
- `deps.py`: seam for cross-domain dependencies owned by `kepler.wcs`,
  `kepler.photometry`, and `kepler.query`.
- `skylib/`: vendored utility subset used by calibration.
- `EXTRACTION.md`: provenance, severed Skynet dependencies, known parity
  behavior, dependency notes, and verification.

Current caveats:

- Field calibration does not own catalogs. Band tables and colour transforms
  live in `kepler.catalogs`; catalog selection and querying live in
  `kepler.query`.
- `kepler.fieldcal.deps` must be wired before `perform_field_calibration` can
  call WCS, source extraction, or photometry. `deps.query_catalogs` is the
  exception: it defaults to `kepler.query` and needs no wiring.
- `numba` and `scipy` are required for real numeric execution.

## `hrdiagram/`

Extracted TypeScript algorithms from Astromancer's cluster/HR-diagram tool.

Primary responsibilities:

- Represent cluster sources, photometry, filters, and isochrone parameters.
- Split cluster members from field stars with field-star-removal parameters.
- Generate color-magnitude and HR-diagram data.
- Apply extinction and distance offsets to observed stars or model isochrones.
- Compute cluster result summaries such as half-light radius, physical radius,
  galactic coordinates, velocity dispersion, and virial mass.

Important files and subfolders:

- `cluster.util.ts`: shared cluster domain types, filter tables, and extinction
  logic.
- `fsr/`: field-star-removal utilities and histogram/CMD helpers.
- `photometry/`: in-memory cluster source handling and source partitioning.
- `isochrone-matching/`: fitted-parameter state and plot transforms.
- `result/`: cluster-summary and projection calculations.
- `shared/`: angle conversion helpers.
- `storage/`: storage-shape interfaces retained from Astromancer.
- `EXTRACTION.md`: extraction boundaries, framework seams, and dropped UI code.

Current caveats:

- There is no TypeScript package manifest or build config in this repository.
- Angular, RxJS, HTTP job polling, Highcharts, canvas rendering, and browser
  export handlers were removed.

## `kepler/`

Per-database astronomy tools, following `docs/tool-architecture.md`. Not part
of the Skynet/Astromancer extraction — this is new code, built on top of the
existing `catalogs/`/`query/` packages (which it imports but does not modify)
and directly on `astroquery`/`psrqpy` for databases those packages don't
cover.

- `tools/simbad.py`, `ned.py`, `vizier.py`, `atnf.py`, `mast.py`, `mpc.py`,
  `casda.py`, `ads.py`: one thin tool module per database. `vizier.py` reaches
  any of VizieR's ~20,000 catalogs (any spectrum, via `category=`), bypassing
  the photometric `catalogs`/`query` mapping entirely to avoid a
  magnitude-vs-flux bug in `query/vizier.py` that would otherwise drop radio
  measurements. `ads.py` builds NASA/SAO ADS's fielded query syntax
  (`author:"..."`, `title:"..."`, `year:2015-2020`) from structured
  parameters rather than passing free text through, and can write a Markdown
  literature review with full citations to `artifacts/ads/`
  (`build_literature_review`). Needs `ADS_DEV_KEY`.
- `tools/resolve.py`: shared SIMBAD name resolution.
- `tools/registry.py`: every tool's schema, for wiring into an agent loop.
- `models.py`, `artifacts.py`, `config.py`: the shared result shape, local
  output handling (including `write_text` for non-tabular artifacts like
  literature reviews), and environment-backed settings every tool uses.
- `runner.py`: an optional agentic loop over the tool schemas (needs
  `ANTHROPIC_API_KEY`); every tool works from ordinary Python without it.

Current caveats:

- `kepler/tools/ads.py` has not been run against the real ADS API — no
  `ADS_DEV_KEY` was available in the environment this was built in. Its
  query-building is grounded in ADS's own documentation and
  `astroquery.nasa_ads`'s source, not live confirmation.
- `wcs/`, `photometry/`, `fieldcal/`, `catalogs/`, and `query/` have not moved
  under `kepler/` — only the per-database tool slice has, per an explicit,
  narrower request than `docs/tool-architecture-migration.md`'s full plan.

## `lightcurve/`

Extracted TypeScript algorithms from Astromancer's pulsar and variable-star
light-curve tools.

Primary responsibilities:

- Parse and transform pulsar light-curve data.
- Merge variable-star source rows by MJD.
- Maintain pulsar and variable light-curve data models.
- Perform pulsar background subtraction, binning, calibration transforms, and
  folding-related computations.
- Perform variable-star differential photometry and period-folding transforms.

Important files and subfolders:

- `pulsar/`: pulsar data types, ingest logic, light-curve algorithms, and
  period-folding functions.
- `variable/`: variable-star data types, ingest logic, light-curve algorithms,
  and period-folding functions.
- `shared/`: small shared helpers such as `floatMod` and the common data
  interface.
- `EXTRACTION.md`: source provenance and Angular/RxJS/Highcharts seams.

Current caveats:

- There is no TypeScript package manifest or build config in this repository.
- Browser/UI concerns were removed except where browser APIs carried the
  original ingest algorithm.
- Periodogram logic lives separately in `periodogram/`.

## `periodogram/`

Extracted TypeScript periodogram algorithms from Astromancer.

Primary responsibilities:

- Compute Lomb-Scargle periodograms.
- Preserve the pulsar and variable-star periodogram differences.
- Detect local maxima and compute confidence thresholds for pulsar periodograms.
- Derive pulsar Nyquist-based search ranges and folding-range links.

Important files and subfolders:

- `core/lomb-scargle.ts`: shared Lomb-Scargle implementation and numeric
  helpers.
- `core/peak-detection.ts`: local maxima and confidence-threshold helpers.
- `pulsar/`: pulsar periodogram models, compute wrapper, range defaults, and
  folding link.
- `variable/`: variable-star periodogram model and compute wrapper.
- `EXTRACTION.md`: source provenance, algorithm notes, and recent bug-fix
  context.

Current caveats:

- There is no TypeScript package manifest or build config in this repository.
- Highcharts rendering fixes and UI storage paths are documented but not
  extracted.
- Period folding itself is owned by `lightcurve/`.

## `kepler/photometry/`

Extracted Python source-extraction and aperture-photometry code from Skynet.

Primary responsibilities:

- Extract image sources with the vendored SEP-based detector.
- Build WCS objects from FITS headers for source coordinate conversion.
- Run aperture or automatic photometry on detected/provided sources.
- Preserve legacy Afterglow numeric behavior around WCS application, centroided
  positions, and aperture-correction settings.

Important files and subfolders:

- `pipeline/source_extraction.py`: FITS-header WCS construction and source
  extraction entry points.
- `pipeline/photometry.py`: `run_photometry` and `perform_photometry`.
- `pipeline/schemas.py`: Pydantic settings and data models.
- `skylib/`: vendored algorithmic core for aperture photometry, exact aperture
  overlap, centroiding, background estimation, and statistics.
- `EXTRACTION.md`: source provenance, dependency requirements, parity behaviors,
  and verification.

Current caveats:

- `numba` and `sep` are hard runtime requirements.
- Full parity checks need real FITS fixtures and native science dependencies.
- This folder intentionally owns photometry, not WCS plate solving or field
  calibration.

## `kepler/query/`

Extracted Python remote catalog access from Skynet and Afterglow.

Every network call in the catalog path. Sits above `kepler.catalogs` and imports
it; never the reverse.

Primary responsibilities:

- Query VizieR-hosted catalogs: derive the column list, issue box/circle/object
  queries, map rows onto `CatalogSource`.
- Query SDSS through SkyServer SQL, which VizieR does not serve.
- Narrow a catalog list to those that can resolve an image's filter.
- Build query regions from solved WCS, clip results to the detector, deduplicate
  across overlapping fields.
- Resolve free-text identifiers against SIMBAD.
- Keep the astroquery response cache pruned, and keep cache failures from
  failing queries.

Important files:

- `registry.py`: the live, queryable catalog registry — the usual entry point.
- `runner.py`: orchestration; `query_catalogs` and `query_catalogs_for_image`.
- `vizier.py`: the VizieR engine.
- `sdss.py`, `skymapper.py`: the two catalogs needing their own backend.
- `binding.py`: joins declarations to backends through the MRO.
- `selection.py`: filter-aware catalog selection.
- `geometry.py`: sky and image geometry — pure, no network.
- `cache.py`, `config.py`: astroquery cache policy and settings seam.
- `simbad.py`: identifier resolution.
- `EXTRACTION.md`: provenance, seams cut, preserved behaviours, verification.

Current caveats:

- Verified offline only. No live VizieR, SkyServer, or SIMBAD response has been
  exercised, so provider response-shape assumptions remain untested.
- Live remote calls must stay out of default checks; see the repository
  conventions.

## `kepler/wcs/`

Extracted Python astrometric WCS-calibration code from Skynet.

Primary responsibilities:

- Extract bright sources for plate solving.
- Derive coordinate, scale, and parity hints from settings and FITS headers.
- Try astrometry.net through the system `solve-field` binary.
- Fall back to the in-process ATLAS triangle solver against local UCAC data.
- Validate candidate solutions and write accepted WCS metadata to FITS headers.

Important files and subfolders:

- `wcs.py`: main plate-solving pipeline, exposed as `solve_wcs`.
- `source_extraction.py`: source list and FITS-header WCS helpers.
- `header_utils.py`: pixel-scale and RA/Dec guessing from FITS headers.
- `schemas.py`: WCS settings and data models.
- `config.py`: environment-backed solver configuration seam.
- `state.py`: dataclass stand-ins for the Skynet ORM rows touched by WCS.
- `skylib/`: vendored astrometry stack, including astrometry.net and ATLAS
  backends.
- `EXTRACTION.md`: full provenance, backend requirements, and validation notes.

Current caveats:

- End-to-end solving requires a configured backend: astrometry.net indexes plus
  `solve-field`, or a local UCAC4/UCAC5 catalog for ATLAS.
- Without solver data, imports still work and solves degrade to no solution.
- `numba`, `sep`, `scipy`, `astropy`, and Pydantic v2 are required for the real
  runtime path.
