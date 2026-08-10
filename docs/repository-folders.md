# Repository Folder Guide

This guide explains the current top-level folders in Kepler. It documents the
repository as it exists now: extracted algorithm modules, a prototype database
tool, and planning material for a future package.

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

## `docs/`

Project documentation and planning material.

- `architecture-brainstorm.md` describes the intended future package direction:
  public astronomy tool contracts, application services, Pydantic models,
  provenance, artifacts, bounded remote calls, and dependency policy.
- `repository-folders.md` is this current-state folder guide.

Docs in this folder should distinguish clearly between the repository's current
extracted-code state and the planned package architecture.

## `fieldcal/`

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
- `catalog_query.py`: catalog-selection/query orchestration.
- `deps.py`: seam for cross-domain dependencies owned by `wcs/` and
  `photometry/`.
- `catalogs/`: metadata-only catalog classes and preserved magnitude/filter
  transforms.
- `skylib/`: vendored utility subset used by calibration.
- `EXTRACTION.md`: provenance, severed Skynet dependencies, known parity
  behavior, dependency notes, and verification.

Current caveats:

- Catalog network backends are intentionally inert until Kepler supplies real
  backends.
- `fieldcal.deps` must be wired before `perform_field_calibration` can call WCS,
  source extraction, or photometry.
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

## `photometry/`

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

## `wcs/`

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
