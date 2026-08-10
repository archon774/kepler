# Kepler Architecture Brainstorm

Date checked: 2026-08-10

Kepler should become an astronomy tooling package that agents can call safely and repeatedly. The current `database_tools.py` file is a useful prototype: it proves that an agent can query SIMBAD, NED, VizieR, ATNF, and ADS. The next architecture should separate agent-facing tool contracts from astronomy backends, preserve scientific metadata internally, and return compact, provenance-rich JSON at the boundary.

## Product Direction

Kepler should expose a model-agnostic astronomy tool layer for AI agents:

- Resolve target names, coordinates, aliases, and object classifications.
- Query catalogs, archives, literature, ephemerides, and observation services.
- Inspect local astronomy data products such as FITS images, tables, spectra, and light curves.
- Run bounded analysis workflows such as observability checks, aperture photometry, source detection, light-curve period search, and spectral line measurement.
- Return data with units, coordinate frames, uncertainties, provenance, warnings, and reproducible query parameters.

The primary design rule is:

> Astropy-native inside, JSON-native outside.

Internally, Kepler should use `astropy.units.Quantity`, `astropy.coordinates.SkyCoord`, `astropy.time.Time`, `astropy.table.Table` or `QTable`, FITS/WCS objects, and package-native science containers. Tool responses should serialize these into strict Pydantic models that are easy for agents to inspect.

## Architecture Sketch

```text
Agent clients
  - MCP tools
  - OpenAI tool schemas
  - Anthropic tool schemas
  - Python API / CLI

Tool gateway
  - schema registry
  - validation
  - authentication lookup
  - timeout and rate-limit policy
  - result shaping and redaction

Application services
  - target resolution
  - catalog search
  - data discovery and fetch
  - FITS/image analysis
  - observation planning
  - literature search
  - spectra and light-curve workflows

Backend adapters
  - astropy
  - astroquery
  - pyvo
  - psrqpy
  - ads or astroquery.nasa_ads
  - optional science extras

Remote archives and local files
  - SIMBAD, NED, VizieR, MAST, JPL Horizons, NASA Exoplanet Archive, ADS, ATNF
  - VO TAP/SIA/SSA/SCS services
  - FITS, VOTable, ECSV, Parquet, CSV, local cache
```

The gateway should know nothing about SIMBAD, FITS headers, or spectra. It should only validate inputs, route tool calls, apply policies, and serialize results. Backend-specific behavior belongs in adapters.

## Proposed Package Layout

```text
kepler/
  __init__.py
  tools/
    registry.py           # Tool definitions and dispatch
    schemas.py            # JSON schemas generated from Pydantic models
    errors.py             # Agent-visible error contracts
  models/
    target.py             # TargetIdentity, SkyPosition, SearchRegion
    catalog.py            # CatalogRow, CatalogQuery, CrossmatchResult
    data_product.py       # ArchiveProduct, LocalProduct, ProductSummary
    provenance.py         # Source, Citation, QueryTrace
    result.py             # ToolResult, warnings, artifacts, pagination
  services/
    resolver.py           # Multi-provider object resolution
    catalogs.py           # SIMBAD/NED/VizieR/VO catalog workflows
    discovery.py          # Archive and VO discovery
    literature.py         # ADS search and citation lookup
    observability.py      # Astroplan-backed visibility checks
    ephemeris.py          # Solar system object positions
    image.py              # FITS/WCS, photometry, source detection
    timeseries.py         # Kepler/TESS and generic light curves
    spectrum.py           # Spectrum loading and line measurements
  backends/
    astropy_core.py
    simbad.py
    ned.py
    vizier.py
    mast.py
    pyvo_services.py
    ads_client.py
    atnf.py
    horizons.py
    exoplanet_archive.py
    photutils_backend.py
    astroplan_backend.py
    lightkurve_backend.py
    specutils_backend.py
    sunpy_backend.py
  io/
    fits_summary.py
    serialization.py
    cache.py
    artifacts.py
  runtime/
    config.py
    auth.py
    limits.py
    logging.py
    execution.py          # Sync/async wrappers and thread pool handling
  server/
    mcp.py
    openai_tools.py
    anthropic_tools.py
    cli.py
tests/
  unit/
  integration/
  fixtures/
```

`database_tools.py` can remain temporarily as a compatibility wrapper, but its logic should move into `services/` and `backends/` modules.

## Backend Package Map

| Area | Package | Role in Kepler |
| --- | --- | --- |
| Core astronomy types | `astropy` | Coordinates, units, times, tables, FITS, WCS, cosmology, statistics, visualization helpers. |
| Archive-specific queries | `astroquery` | SIMBAD, NED, VizieR, MAST, JPL Horizons, NASA Exoplanet Archive, and other named-service adapters. |
| Virtual Observatory | `pyvo` | TAP, SIA, SSA, SCS, registry search, and standards-based archive discovery. |
| Pulsars | `psrqpy` | ATNF Pulsar Catalogue queries with table output. |
| Literature | `ads` or `astroquery.nasa_ads` | SAO/NASA ADS search, bibcodes, citations, abstracts, and library-aware research workflows. |
| Imaging and photometry | `photutils` | Aperture photometry, background estimation, source detection, segmentation, PSF photometry. |
| CCD reduction | `ccdproc` | Bias/dark/flat correction, image combination, uncertainty propagation, bad-pixel tracking. |
| WCS reprojection | `reproject` | Resample astronomical images across WCS frames and align image products. |
| Regions | `regions` | DS9/CRTF/FITS region parsing, masks, aperture definitions, and spatial selections. |
| Observation planning | `astroplan` | Observer/site models, rise/set/transit, airmass, moon separation, observability constraints. |
| Light curves | `lightkurve` | Kepler, K2, TESS search/download/read flows, light-curve cleaning, periodograms. |
| Spectra | `specutils` | Spectrum containers, spectral regions, line flux, centroid, width, fitting, resampling. |
| Spectral reduction | `specreduce` | Optional optical/IR spectral reduction workflows when raw spectra are in scope. |
| Solar physics | `sunpy` | Solar coordinates, maps, time series, and Fido-based solar data search/download. |
| Numeric base | `numpy`, `scipy`, `pandas` | Arrays, optimization, statistics, tabular transformations, and bridge formats. |
| Validation | `pydantic` | Tool input/output models and generated JSON schemas. |

Suggested dependency policy:

- Keep `astropy`, `astroquery`, `pyvo`, `pydantic`, `numpy`, `scipy`, `pandas`, `requests/httpx`, `psrqpy`, and ADS support in the core install because the current repository already points there.
- Add optional extras for heavier workflows: `kepler[image]`, `kepler[planning]`, `kepler[timeseries]`, `kepler[spectra]`, `kepler[solar]`, and `kepler[all]`.
- Review the ADS client choice before locking the public API. The existing repository pins `ads==0.12.7`, while newer ADS client documentation describes a v1 data-model API. Kepler should hide that choice behind `backends/ads_client.py`.

## Tool Families

### 1. Target Context

`resolve_target`

- Inputs: name or coordinate string, preferred resolvers, optional epoch/frame.
- Backends: Astropy coordinates, SIMBAD, NED, MAST resolver.
- Output: canonical coordinates, frame, aliases, object types, redshift/radial velocity when available, source provenance, ambiguity warnings.

`target_context_pack`

- Inputs: target, radius, desired catalog families.
- Backends: SIMBAD, NED, VizieR, PyVO registry/TAP, ADS.
- Output: compact research context for an agent: identity, nearby catalog entries, selected measurements, representative literature, and follow-up suggestions.

### 2. Catalog And Archive Search

`catalog_cone_search`

- Inputs: center, radius, provider, catalog ID, selected columns, row limit.
- Backends: SIMBAD, NED, VizieR, PyVO SCS/TAP.
- Output: catalog rows with units, UCDs when available, sky positions, query trace, and pagination token if supported.

`archive_discovery`

- Inputs: target or region, product type, wavelength band, time range, mission/provider filters.
- Backends: PyVO registry/discovery, Astroquery MAST, archive-specific adapters.
- Output: data products with provider, access URL, calibration level, footprint, time/wavelength coverage, size estimate.

`fetch_data_product`

- Inputs: product identifier or URL, cache policy, max bytes.
- Backends: Astroquery, PyVO, `astropy.utils.data`, provider downloads.
- Output: local cache path, checksum when available, product summary, license/citation notes.

### 3. Local Data Inspection

`summarize_fits`

- Inputs: local path, HDU selector, summary depth.
- Backends: `astropy.io.fits`, `astropy.wcs`, `astropy.table`.
- Output: HDU inventory, dimensions, units, WCS footprint, time metadata, basic statistics, warnings about missing or invalid headers.

`extract_wcs_footprint`

- Inputs: FITS path or header, coordinate frame preference.
- Backends: Astropy WCS.
- Output: sky polygon, center, pixel scale, orientation, projection metadata.

### 4. Image Analysis

`detect_sources`

- Inputs: FITS image, threshold model, background model, mask/region.
- Backends: Photutils, Astropy stats.
- Output: source table with centroids, fluxes, morphology, segmentation artifact path.

`aperture_photometry`

- Inputs: image, target positions, aperture shape/radius, background annulus, zeropoint.
- Backends: Photutils, Regions, Astropy WCS.
- Output: fluxes, magnitudes when calibrated, uncertainties, aperture masks, provenance.

`ccd_reduce_basic`

- Inputs: science frames, bias/dark/flat frames, combination policy.
- Backends: Ccdproc, Astropy CCDData.
- Output: reduced image products, processing log, uncertainty and mask summary.

`reproject_image`

- Inputs: source image, target WCS/header or reference image, algorithm.
- Backends: Reproject.
- Output: reprojected FITS artifact and footprint/coverage summary.

### 5. Observation Planning

`observability_window`

- Inputs: target list, observer site or geodetic location, time range, constraints.
- Backends: Astroplan, Astropy coordinates/time.
- Output: rise/set/transit, airmass windows, moon separation/illumination, boolean observability matrix.

`night_plan`

- Inputs: target list, priorities, exposure estimates, site, date.
- Backends: Astroplan plus local scheduling heuristics.
- Output: ranked target windows and a schedule proposal. This should be explicitly labeled as advisory.

### 6. Solar System And Ephemerides

`solar_system_ephemeris`

- Inputs: object name/designation, observer center/site, time range, step size, quantities.
- Backends: Astroquery JPL Horizons or direct JPL Horizons API adapter.
- Output: RA/Dec, alt/az when observer is topocentric, rates, phase, distance, light time, query trace.

`small_body_context`

- Inputs: designation, time range, observer.
- Backends: JPL Horizons, SBDB via Astroquery when useful.
- Output: orbit summary, observability, uncertainty notes, close-approach metadata when available.

### 7. Time Series

`search_light_curves`

- Inputs: target, mission, cadence, sector/quarter, time range.
- Backends: Lightkurve and/or Astroquery MAST.
- Output: available products, sectors/quarters, cadence, quality flags, download handles.

`analyze_light_curve`

- Inputs: light-curve file or downloaded product, cleaning options, period search settings.
- Backends: Lightkurve, Astropy timeseries, SciPy.
- Output: normalized curve summary, periodogram peaks, quality warnings, plot artifacts.

### 8. Spectra

`summarize_spectrum`

- Inputs: spectrum file or archive product, format hint, redshift/rest frame option.
- Backends: Specutils, Astropy IO.
- Output: spectral axis range, flux unit, resolution metadata if available, SNR estimate, masks.

`measure_spectral_lines`

- Inputs: spectrum, line list or regions, continuum model, redshift.
- Backends: Specutils.
- Output: line flux, equivalent width, centroid, width, fit status, uncertainty.

### 9. Literature

`literature_search`

- Inputs: query string or structured fields, result limit, sort, field list.
- Backends: ADS client or `astroquery.nasa_ads`.
- Output: title, authors, bibcode, year, citations, DOI, abstract snippet, ADS URL.

`citation_context`

- Inputs: bibcodes or DOI list.
- Backends: ADS.
- Output: normalized citation metadata, references/citations if requested, BibTeX artifact.

## Data Contracts

All public tools should return a `ToolResult` envelope:

```python
class ToolResult(BaseModel):
    status: Literal["ok", "partial", "not_found", "error"]
    data: list[dict] | dict | None
    provenance: list[Source]
    warnings: list[str] = []
    errors: list[ToolError] = []
    artifacts: list[Artifact] = []
    pagination: Pagination | None = None
    query: QueryTrace
```

Important modeling choices:

- Coordinates should serialize as decimal degrees plus frame, not only sexagesimal strings.
- Quantities should serialize as `{ "value": 1.23, "unit": "arcsec" }`.
- Times should serialize as ISO strings plus scale where known, and optionally MJD/JD for precision-sensitive workflows.
- Tables should include column metadata: name, unit, description, UCD/Utype when available.
- Every remote result should include the provider, endpoint or service name, query parameters, retrieval timestamp, package adapter version, and citation hints.
- Large arrays should not be embedded in agent responses. Store them as artifacts and return paths plus summaries.

## Agent Safety And Ergonomics

Agents need strong guardrails because astronomy tools can be slow, remote, ambiguous, and data-heavy.

- Require explicit `limit` parameters for table-returning tools, with conservative defaults.
- Add `max_radius` and `max_rows` caps to prevent accidental all-sky or huge archive queries.
- Report ambiguous name resolutions instead of silently picking the first match.
- Keep remote SQL/TAP querying behind templates or a reviewed allowlist by default. Arbitrary ADQL can be offered under an advanced tool.
- Provide partial results if one backend fails in a multi-provider workflow.
- Use stable error codes: `invalid_coordinates`, `ambiguous_target`, `not_found`, `auth_required`, `rate_limited`, `timeout`, `backend_unavailable`, `too_many_results`, `unsupported_format`.
- Redact API tokens and credentials from logs and tool outputs.
- Treat local file reads as explicit user/agent choices. Avoid recursively scanning arbitrary directories.

## Runtime Design

### Configuration

Use a single config object loaded from environment variables, optional config files, and direct constructor arguments:

- `ADS_DEV_KEY`
- `NASA_API_KEY`
- provider-specific timeout and row-limit defaults
- cache directory and cache TTL
- allowed local data roots
- user agent string for archive providers

### Caching

Use a cache layer for remote queries and downloaded products:

- Query cache key: backend name, normalized parameters, package version, service endpoint, and schema version.
- Product cache key: provider ID, URL, checksum/ETag when available.
- TTLs should vary by source. Literature and catalog metadata can often be cached longer than observability or ephemeris products.
- Store raw responses only when licensing and provider policy allow it.

### Execution

Most Astroquery clients are synchronous. The service layer can still support concurrent agent workflows by running blocking calls in a bounded worker pool:

- hard timeout per backend call
- retry only idempotent remote requests
- fanout limits for multi-catalog searches
- cancellation support when exposed through MCP or HTTP
- structured logging around query traces, not raw giant payloads

### Artifacts

Analysis workflows should create durable artifacts:

- FITS outputs
- CSV/ECSV/Parquet tables
- PNG/SVG plots
- JSON provenance manifests
- segmentation masks
- reduced spectra or light curves

Artifact responses should include path, MIME type, size, created time, and generating tool.

## MVP Roadmap

### Phase 1: Package Core

- Convert the repository into an installable package with `pyproject.toml`.
- Move prototype logic from `database_tools.py` into backend adapters.
- Add Pydantic input/output models.
- Implement tool registry that can emit Anthropic, OpenAI, MCP, and Python callable views.
- Keep the first tools narrow: `resolve_target`, `catalog_cone_search`, `literature_search`, `atnf_query`, and `target_context_pack`.
- Add unit tests with mocked Astropy tables and recorded minimal fixtures. Live network tests should be opt-in.

### Phase 2: Data Discovery

- Add PyVO registry/TAP/SIA/SSA workflows.
- Add MAST discovery and download wrappers.
- Add cache, result pagination, and artifact manifests.
- Add FITS summary tooling for local and downloaded products.

### Phase 3: Analysis Extras

- Add optional `image` extra: Photutils, Ccdproc, Reproject, Regions.
- Add optional `planning` extra: Astroplan.
- Add optional `timeseries` extra: Lightkurve.
- Add optional `spectra` extra: Specutils and optionally Specreduce.
- Build one end-to-end workflow per extra, with deterministic fixture tests.

### Phase 4: Domain Expansion

- Add solar physics tools through SunPy.
- Add direct JPL Horizons/SBDB ephemeris tools if Astroquery coverage is insufficient.
- Add NASA Exoplanet Archive workflows.
- Add richer citation, bibliography, and research-context tools.

## Testing Strategy

- Unit tests should not require network access.
- Use tiny in-repo fixtures for FITS headers, tables, and response payloads.
- Add adapter contract tests that validate returned `ToolResult` envelopes and provenance.
- Gate live provider tests behind environment variables such as `KEPLER_LIVE_TESTS=1`.
- Include tests for coordinate parsing, unit conversion, row limits, timeout behavior, ambiguous targets, empty results, and serialization of masked tables.
- Snapshot JSON schemas so agent-facing contracts do not drift silently.

## Open Questions

- Should Kepler be primarily a Python library with optional servers, or an MCP-first tool server?
- Should remote network access be enabled by default, or should tools require explicit provider enablement?
- Which ADS client should be the long-term API: current pinned `ads` 0.12.x, newer `ads` v1, or `astroquery.nasa_ads`?
- How much raw data should Kepler download automatically versus returning product handles for a human or downstream tool?
- What citation format should be included in every result: BibTeX, provider text, DOI, or a compact source record?
- Should workflows optimize for professional astronomy users, education/outreach, or general agent research assistance first?

## Reference Notes

These docs were checked while drafting this brainstorm:

- [Astropy user guide](https://docs.astropy.org/en/stable/index_user_docs.html): core units, coordinates, time, tables, FITS, WCS, IO, cosmology, and stats.
- [Astroquery docs](https://astroquery.readthedocs.io/en/stable/): archive and catalog clients including SIMBAD, VizieR, NED, MAST, JPL Horizons, and NASA Exoplanet Archive.
- [PyVO docs](https://pyvo.readthedocs.io/en/stable/): Virtual Observatory TAP, SIA, SSA, SCS, SLAP, registry, and discovery support.
- [Photutils API](https://photutils.readthedocs.io/en/stable/reference/index.html): aperture photometry, backgrounds, source detection, segmentation, and PSF tools.
- [Ccdproc docs](https://ccdproc.readthedocs.io/en/stable/): CCD reduction with uncertainty propagation and bad-pixel tracking.
- [Reproject docs](https://reproject.readthedocs.io/en/stable/): astronomical image reprojection and WCS-based resampling.
- [Astroplan docs](https://astroplan.readthedocs.io/en/stable/): observation planning, target observability, and site/time constraints.
- [Lightkurve docs](https://lightkurve.github.io/lightkurve/): Kepler, K2, and TESS light-curve access and analysis.
- [Specutils docs](https://specutils.readthedocs.io/en/stable/index.html): spectrum containers, spectral regions, analysis, fitting, and manipulation.
- [SunPy docs](https://docs.sunpy.org/en/stable/): solar coordinates, maps, time series, and data search/download.
- [JPL Horizons API docs](https://ssd-api.jpl.nasa.gov/doc/horizons.html): programmatic solar-system ephemeris access.
- [ADS Python client docs](https://ads.readthedocs.io/en/v1/): SAO/NASA ADS data models, search, libraries, and client API.
