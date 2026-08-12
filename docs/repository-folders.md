# Repository Folder Guide

This guide explains the current source folders in Kepler. It documents the
repository as it exists now: root-level tool modules, distinguished extracted
algorithm modules, and planning material for future tool work.

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

## `tools/`

Important files and subfolders:

- `models.py`: small shared result, warning/error, WCS, catalog, zero-point,
  remote query, and artifact summary models.
- `config.py`: small environment-backed settings helpers for the tool layer.
- `artifacts.py`: local artifact description and listing helpers.
- `astrometry.py`, `calibration.py`, `catalogs.py`, `pulsar.py`,
  `photometry.py`, `workspace.py`: local plain Python user-facing tool
  wrappers.
- `simbad.py`, `ned.py`, `vizier.py`, `atnf.py`, `ads.py`, `mast.py`,
  `mpc.py`, `casda.py`, `resolve.py`: split remote database/archive tools.
- `hr_diagram.py`: FITS-to-HR-diagram pipeline orchestration, backed by
  `algorithms.hrdiagram_py` plus `tools.vizier.search_vizier` for the Gaia
  DR3 and cluster-literature catalog lookups.
- `radio_sources.py`: radio FITS -> catalog-identified sources -> labeled SED
  plot, backed by `algorithms.radio` plus `tools.vizier.search_vizier` and
  `tools.ned.search_ned`.
- `registry.py`, `runner.py`: optional agent schema registry and Anthropic
  runner over the same ordinary Python tool functions.
- `sessions.py`: `AgentSession` and `make_cache_key` -- per-run manifest
  recording (tool calls, cache hits, artifacts, turns) plus the shared cache
  key used both by `runner.py`'s in-memory repeat-call cache and by the
  manifest's own cache-hit bookkeeping. Manifests are written under
  `artifacts/sessions/<session_id>/session_manifest.json`; `list_session_manifests`
  and `read_session_manifest` read them back.

Current tools:

- `astrometry.describe_image_wcs(path)`: describe celestial WCS metadata in a
  FITS header.
- `catalogs.list_photometric_catalogs()`: list local catalog declarations
  without querying remote services.
- `catalogs.resolve_reference_band(catalog, image_filter)`: summarize the local
  filter-to-reference-band mapping Kepler would use.
- `calibration.solve_zeropoint_from_measurements(measurements, catalog_sources)`:
  solve a zero point from local measurement and catalog-source records.
- `pulsar.resolve_pulsar_scan(...)` / `pulsar.list_pulsar_scans(...)`,
  `pulsar.load_pulsar_lightcurve(path)`, `pulsar.compute_pulsar_periodogram(path)`,
  `pulsar.fold_pulsar_lightcurve(path, period_s)` and
  `pulsar.sonify_pulsar(path, period_s=None)`: the pulsar pipeline, local
  only, each stage's artifact feeding the next. `pulsar.plot_pulsar(...)`
  renders any stage's artifact as a PNG. See
  [pulsar-tool-pipeline.md](pulsar-tool-pipeline.md).
- `photometry.list_photometry_targets()` and
  `photometry.run_photometry_on_target(target, ...)`: local aperture
  photometry (source extraction, optional live zero-point verification) over
  a fixed bundled FITS library -- a thin wrapper reusing
  `tools.claude_photometry_haiku_tool`'s pipeline, not a reimplementation.
  Not a substitute for the HR-diagram pipeline below (no Gaia crossmatch, no
  isochrone fit); `run_photometry_on_target(..., write_source_table=True)`
  writes a CSV that bridges into it (see `hr_diagram.crossmatch_gaia` below).
- `workspace.list_artifacts(directory=None)` and
  `workspace.describe_artifact(path)`: inspect local artifact files.
- `resolve.resolve_target(name)`: resolve a target through SIMBAD.
- `simbad.*`, `ned.search_ned`, `vizier.*`, `atnf.search_atnf`,
  `ads.*`, `mast.search_mast`, `mpc.search_mpc`, and `casda.search_casda`:
  query remote astronomy databases and archives, returning bounded previews
  plus local artifact paths for complete tables or reviews.
- `hr_diagram.extract_photometry_from_fits`, `crossmatch_gaia`,
  `get_literature_cluster_params`, `select_cluster_members`,
  `fit_and_compare_hr_diagram`, `run_full_hr_pipeline`: FITS frame -> HR
  diagram -> literature comparison, chained through
  `algorithms.hrdiagram_py` and `tools.vizier.search_vizier`. Deliberately
  cheaper, uncalibrated source extraction than `photometry.py` above -- the
  frame's own magnitude is discarded once Gaia's is fetched.
- `hr_diagram.crossmatch_gaia_by_position`, `run_full_hr_pipeline_from_catalog`:
  the same HR-diagram pipeline with no FITS frame required -- Gaia DR3 is
  fetched directly around the cluster's own resolved position instead of
  matched against a frame's detected sources. Prefer this path whenever the
  user has not supplied a FITS file.
- `radio_sources.plot_field_sed(fits_path, ...)`: the main radio entry point --
  identifies sources in a radio FITS frame against VizieR's radio catalogs
  (`identify_radio_sources`), then plots every identified source's spectral
  energy distribution from NED on one labeled plot, each with its own fitted
  spectral index (`analyze_source_spectrum`, callable standalone for one
  already-named source). Replaces the non-functional `Spectral_Plot.py` /
  `Best_Fit_Analysis.py` scratch scripts.

## `algorithms/`

Extracted algorithm packages and shared algorithm support code.

Important files and subfolders:

- `algorithms/wcs/`, `algorithms/photometry/`, `algorithms/fieldcal/`,
  `algorithms/catalogs/`, `algorithms/query/`: extracted Python algorithm
  packages.
- `algorithms/skylib_lite/`: consolidated local subset of Skynet's `skylib` used
  by the extracted Python algorithms.
- `algorithms/lightcurve/`, `algorithms/periodogram/`, `algorithms/hrdiagram/`:
  extracted TypeScript algorithm packages.

## `algorithms/catalogs/`

Extracted Python catalog declarations from Skynet and Afterglow.

What Kepler knows about catalogs and provider vocabularies, and nothing about
reaching them: no module here imports `astroquery`, `psrqpy`, or opens a
socket. Photometric catalog declarations cover eleven catalogs — APASS,
Landolt, PanSTARRS, SDSS, SkyMapper, Stetson, 2MASS, Tycho-2, UCAC5, USNO-B1,
VSX.

Each plugin declares its band table (`mags`), its filter/colour transforms
(`filter_lookup`), its column mapping, and its VizieR table ID. Three plugins
also carry photometric conversions applied to their rows.

Important files:

- `catalog.py`: the plugin base class — the declaration contract.
- `<name>_catalog.py`: one module per catalog.
- `catalog_options.py`: the second, smaller registry (`CATALOG_OPTIONS`) that
  reference-magnitude resolution reads. It is *not* redundant with `CATALOGS`;
  see [extraction.md](extraction.md), Catalogs §4.
- `schemas.py`: `CatalogSource` and friends — the data contract between
  `algorithms.catalogs` and `algorithms.query`.
- `simbad.py`: the 206-entry SIMBAD object-type vocabulary.
- `ads.py`: ADS field lists and citation formatting helpers for `tools.ads`.
- `atnf.py`: ATNF pulsar-parameter vocabulary for `tools.atnf`.
- `ned.py`: NED table-name and photometry-format vocabulary for `tools.ned`.
- [extraction.md](extraction.md), Catalogs: provenance, renames, preserved
  behaviours, verification.

Current caveats:

- Two registries exist and disagree deliberately. Merging them changes which
  reference band a narrowband or unfiltered image calibrates against.

## `docs/`

Project documentation and planning material.

- `tool-architecture.md` is the master package architecture document: public
  tools, algorithm ownership, future services, runtime policy, and
  `skylib_lite` consolidation.
- `extraction.md` is the master extraction record for every algorithm package
  under `algorithms/`.
- `repository-folders.md` is this current-state folder guide.

Docs in this folder should distinguish clearly between the repository's current
extracted-code state and the planned package architecture.

## `algorithms/fieldcal/`

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
- `deps.py`: seam for cross-domain dependencies owned by `algorithms.wcs`,
  `algorithms.photometry`, and `algorithms.query`.
- `algorithms.skylib_lite`: shared vendored utility subset used by calibration.
- [extraction.md](extraction.md), Field Calibration: provenance, severed Skynet
  dependencies, known parity behavior, dependency notes, and verification.

Current caveats:

- Field calibration does not own catalogs. Band tables and colour transforms
  live in `algorithms.catalogs`; catalog selection and querying live in
  `algorithms.query`.
- `algorithms.fieldcal.deps` must be wired before `perform_field_calibration` can
  call WCS, source extraction, or photometry. `deps.query_catalogs` is the
  exception: it defaults to `algorithms.query` and needs no wiring.
- `numba` and `scipy` are required for real numeric execution.

## `algorithms/hrdiagram/`

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
- [extraction.md](extraction.md), HR Diagram / Isochrone Matching: extraction
  boundaries, framework seams, and dropped UI code.

Current caveats:

- There is no TypeScript package manifest or build config in this repository.
- Angular, RxJS, HTTP job polling, Highcharts, canvas rendering, and browser
  export handlers were removed.

## `algorithms/hrdiagram_py/`

A Python parity **port** of the CM/HR transform above, plus a real optimizer
Astromancer never had -- not a byte-preserving extraction, and deliberately
named with the `_py` suffix so it doesn't collide with `algorithms/hrdiagram/`
(TypeScript) under this repo's Python/TypeScript domain-boundary rules. See
[extraction.md](extraction.md), "HR Diagram (Python)".

Important files:

- `hrfit.py`: the CM<->HR transform (`computePlotDelta`/`getExtinction`
  ported from `isochrone-matching/isochrone-plot.util.ts` /
  `cluster.util.ts`), CCM extinction, isochrone loading, and the
  distance/E(B-V)/age optimizer (`fit_distance_reddening`, `fit_cluster`) --
  a new capability, Astromancer's own tool is manual/by-eye only.
  `isochrone_cmd` drops PARSEC/COLIBRI thermally-pulsing-AGB rows (`label`
  column > 7) by default -- a raw PARSEC download's dust/mass-loss modelling
  breaks down there, and left in, it both scribbles the plotted track and
  biases the optimizer's nearest-point cost.
- `observations.py`: FITS frame -> detected sources, via `algorithms.photometry`.
  Cheap "auto" Kron-like apertures, no zero-point solve -- the frame's own
  magnitude is discarded once Gaia's is fetched.
- `matching.py`: detected sources <-> a fetched comparison-catalog table, by
  sky position (mutual nearest-neighbour).
- `literature.py`: a fetched cluster-catalog row (Cantat-Gaudin & Anders 2020)
  -> age/distance/E(B-V). Open clusters only.
- `membership.py`: field-star removal -- a per-source error-scaled parallax
  window, and Astromancer's own elliptical proper-motion acceptance region
  (ported from `algorithms/hrdiagram/photometry/cluster-data.service.util.ts::updateClusterFieldSources`,
  with each source's own ellipse semi-axes sized from its proper-motion error
  and a distance-aware velocity-dispersion floor -- the ellipse's *shape*
  alone doesn't help without that, since a circle and a fixed-radius ellipse
  reject the same points).
- `isochrones.py`: the one module here with its own network call -- fetches
  PARSEC isochrones from stev.oapd.inaf.it directly, since no existing tool
  wraps that service.

`algorithms/hrdiagram_py/` never imports `tools.*`; all network I/O besides
the PARSEC fetch above (Gaia DR3, cluster-literature lookups) lives one layer
up in `tools/hr_diagram.py`, via `tools.vizier.search_vizier`.

## `algorithms/radio/`

New first-party capability -- no upstream Skynet/Astromancer equivalent, so
there is no parity to preserve here.

Important files:

- `spectral_fitting.py`: pure-numpy flux-vs-frequency model fitting --
  `fit_power_law` (log-log OLS, the standard `S_nu ~ nu**spectral_index`
  radio spectral index), `fit_log_parabola` (quadratic in log-log space, for
  spectral curvature/turnover), and `analyze_spectrum`, which fits both and
  reports whichever the data actually supports. Every candidate model is fit
  against the same target (`log10(flux)`), so their R^2 values are directly
  comparable -- unlike an earlier draft of this fit, which compared R^2
  across models fit to different targets and was fixed here, not preserved.
- `matching.py`: `guess_radec_columns` (tries common VizieR RA/Dec
  column-name conventions, since a `category="radio"` catalog search returns
  one differently-shaped table per matched survey) and
  `match_sources_to_catalog` (flat-sky KD-tree nearest-neighbour, not
  mutual -- catalog density varies too much between radio surveys for a
  mutual-nearest-neighbour requirement to be appropriate the way it is for
  `algorithms/hrdiagram_py/matching.py`'s Gaia-specific version).

`algorithms/radio/` never imports `tools.*`; VizieR/NED network I/O lives one
layer up in `tools/radio_sources.py`.

## `algorithms/lightcurve/`

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

- `pulsar/`: pulsar data types, ingest logic, light-curve algorithms,
  period-folding functions, and sonification.
- `variable/`: variable-star data types, ingest logic, light-curve algorithms,
  and period-folding functions.
- `shared/`: small shared helpers such as `floatMod` and the common data
  interface.
- [extraction.md](extraction.md), Light Curve: source provenance and
  Angular/RxJS/Highcharts seams.

Current caveats:

- Typechecked by the root `tsconfig.json` (`npm run typecheck`), but there is
  no build, bundle, or runtime — nothing executes this TypeScript.
- Browser/UI concerns were removed except where browser APIs carried the
  original ingest algorithm.
- Periodogram logic lives separately in `algorithms/periodogram/`.
- The runnable sonification is the Python port in `algorithms/pulsar/`; the
  TypeScript here is the provenance record it was ported from.

## `algorithms/pulsar/`

Python pulsar time-series ingest and sonification. **The one folder under
`algorithms/` that is a port rather than an extraction** — it carries the
Astromancer TypeScript sonifier into Python because that code is welded to
`Blob`, `document` and `AudioContext` and cannot run headless. Seams are marked
`# PORTED:`, not `# EXTRACTED:`.

One module per pipeline stage, in the order they must run.

Primary responsibilities:

- Parse Green Bank / Skynet pulsar files, both flavours (two-polarization
  `.cal.txt` continuum scans and prefolded single-column "standard" files),
  drop the leading noise-diode calibration block, rebase the time axis, and
  subtract a running-median background.
- Compute the Lomb-Scargle periodogram, locate its peak, and give the peak a
  false-alarm confidence level.
- Fold the light curve at a period and bin it into a pulse profile.
- Render either the profile or the raw scan as amplitude-modulated noise, and
  encode 16-bit PCM WAV.

Important files and subfolders:

- `ingest.py`: file parsing, header extraction, `median` /
  `background_subtraction`.
- `periodogram.py`: `lomb_scargle`, `find_global_max`, `confidence_threshold`,
  `nyquist_periodogram_range`, `compute_periodogram`.
- `folding.py`: `float_mod`, `fold_to_phase`, `bin_data`, `fold_and_bin`,
  `duplicate_if_needed`, `difference_and_sum`, `fold_lightcurve`.
- `sonification.py`: `interpolate_linear`, `window_sonification_input`,
  `folded_sonification_input`, `sonify`, `write_wav`.
- [pulsar-tool-pipeline.md](pulsar-tool-pipeline.md): the stage-by-stage
  architecture and the extracted Astromancer code behind each stage.
- [extraction.md](extraction.md), Pulsar Sonification: provenance, the seams
  cut, the port's deliberate divergences, and the preserved upstream quirks.

Current caveats:

- **Stage order is a dependency, not a convention.** Only the periodogram
  produces a period, and folding at a wrong period returns a flat profile
  rather than an error — which is why each stage reports a quality number.
- The rendered audio is not real-time: the synthesis ignores sample timestamps,
  so a period measured off it is wrong by a few tenths of a percent (folded) to
  a few percent (unfolded). `tools/pulsar.py` reports it as `playback_stretch`.
  Catalogued periods come from `tools.atnf.search_atnf`.
- The noise carrier is seeded for determinism; upstream's `Math.random()` is
  not reproducible, so no byte-for-byte reference render exists to diff against.
- `sonificationBrowser` is not ported — it exists to drive an `AudioContext`.
- No dedispersion, no barycentric correction, no period uncertainty. Upstream
  has none of these either.

## `algorithms/periodogram/`

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
- [extraction.md](extraction.md), Periodogram: source provenance, algorithm
  notes, and recent bug-fix context.

Current caveats:

- Typechecked by the root `tsconfig.json` (`npm run typecheck`), but there is
  no build, bundle, or runtime — nothing executes this TypeScript.
- Highcharts rendering fixes and UI storage paths are documented but not
  extracted.
- Period folding itself is owned by `algorithms/lightcurve/`.

## `algorithms/skylib_lite/`

Consolidated local subset of Skynet's `skylib` used by the extracted Python
algorithm packages.

Important files and subfolders:

- `astrometry/`: astrometry.net subprocess backend, ATLAS triangle solver,
  solver data, and related types used by `algorithms.wcs`.
- `calibration/`: background estimation and SEP compatibility helpers.
- `extraction/`: SEP-based source extraction and centroiding.
- `io/`: FITS compression/HDU selection helper used by the WCS solver stack.
- `photometry/`: aperture photometry, exact aperture sums, and exposure helpers.
- `util/`: angle, FITS, overlap, and statistics helpers shared across WCS,
  photometry, and field calibration.

Current caveats:

- This is vendored legacy science code. Architecture work should move imports
  and package boundaries only; numerical fixes belong in targeted remediation
  PRs with tests.

## `algorithms/photometry/`

Extracted Python source-extraction and aperture-photometry code from Skynet.

Primary responsibilities:

- Extract image sources with the vendored SEP-based detector.
- Build WCS objects from FITS headers for source coordinate conversion.
- Run aperture or automatic photometry on detected/provided sources.
- Preserve legacy Afterglow numeric behavior around WCS application, centroided
  positions, and aperture-correction settings.

Important files:

- `source_extraction.py`: FITS-header WCS construction and source
  extraction entry points.
- `photometry.py`: `run_photometry` and `perform_photometry`.
- `schemas.py`: Pydantic settings and data models.
- `algorithms.skylib_lite`: vendored algorithmic core for aperture photometry,
  exact aperture overlap, centroiding, background estimation, and statistics.
- [extraction.md](extraction.md), Photometry: source provenance, dependency
  requirements, parity behaviors, and verification.

Current caveats:

- `numba` and `sep` are hard runtime requirements.
- Full parity checks need real FITS fixtures and native science dependencies.
- This folder intentionally owns photometry, not WCS plate solving or field
  calibration.

## `algorithms/query/`

Extracted Python remote catalog access from Skynet and Afterglow.

Every network call in the catalog path. Sits above `algorithms.catalogs` and imports
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
- [extraction.md](extraction.md), Query: provenance, seams cut, preserved
  behaviours, verification.

Current caveats:

- Verified offline only. No live VizieR, SkyServer, or SIMBAD response has been
  exercised, so provider response-shape assumptions remain untested.
- Live remote calls must stay out of default checks; see the repository
  conventions.

## `algorithms/wcs/`

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
- `algorithms.skylib_lite`: vendored astrometry stack, including astrometry.net and
  ATLAS backends.
- [extraction.md](extraction.md), WCS: full provenance, backend requirements,
  and validation notes.

Current caveats:

- End-to-end solving requires a configured backend: astrometry.net indexes plus
  `solve-field`, or a local UCAC4/UCAC5 catalog for ATLAS.
- Without solver data, imports still work and solves degrade to no solution.
- `numba`, `sep`, `scipy`, `astropy`, and Pydantic v2 are required for the real
  runtime path.
