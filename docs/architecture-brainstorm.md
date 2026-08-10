# Kepler Architecture Brainstorm

Date checked: 2026-08-10

Kepler should become an astronomy tool package that any general agent, script, notebook, or application can call. It is not a multi-agent framework, a multi-model framework, or an orchestration layer. The architecture should focus on a small set of useful astronomy tools backed by reusable application services.

The current `database_tools.py` file is a useful prototype: it proves that an agent can query SIMBAD, NED, VizieR, ATNF, and ADS. The next step is to turn that prototype into a package with clear tool contracts, shared science models, reliable service code, and provenance-rich outputs.

## Product Direction

Kepler should expose practical astronomy tools in four initial areas:

- Data retrieval: resolve targets, search catalogs, discover archive products, fetch data, and inspect local files.
- Analysis and plotting: summarize FITS files, analyze images/tables/light curves/spectra, and generate plot artifacts.
- Data integration: normalize tables, crossmatch sources, merge measurements, and build compact target context packs.
- Literature lookup: search ADS, retrieve citation metadata, and connect papers to targets, catalogs, and data products.

The primary design rule is:

> Astropy-native inside, JSON-and-artifact-native outside.

Internally, Kepler should use `astropy.units.Quantity`, `astropy.coordinates.SkyCoord`, `astropy.time.Time`, `astropy.table.Table` or `QTable`, FITS/WCS objects, and package-native science containers. Public tool responses should serialize those objects into strict Pydantic models with units, coordinate frames, uncertainties, provenance, warnings, and reproducible query parameters.

## Non-Goals For This Planning Pass

This document should not design:

- Agent coordination or task planning.
- Model-specific tool schemas.
- Chat, assistant, or workflow runtimes.
- Provider-specific wrapper layers as an architecture concern.
- Long-term server deployment details.

Packages such as `astropy`, `astroquery`, `pyvo`, `photutils`, `lightkurve`, `specutils`, and `ads` are implementation dependencies used by tools and services. They do not need to appear as a separate architectural layer yet.

## Conceptual Architecture

```text
General caller
  - agent
  - Python script
  - notebook
  - CLI or application code

Public tool package
  - data retrieval tools
  - analysis and plotting tools
  - data integration tools
  - literature lookup tools

Application services
  - target resolution
  - catalog and archive discovery
  - product fetch and cache
  - local data inspection
  - analysis workflows
  - plot/artifact creation
  - table normalization and crossmatch
  - literature search and citation lookup
  - provenance and query tracing

Shared core
  - Pydantic models
  - units, coordinates, and time helpers
  - error contracts
  - configuration
  - cache policy
  - artifact manifests

External packages and data sources
  - astronomy/data Python packages
  - remote catalogs and archives
  - local FITS, VOTable, ECSV, Parquet, CSV, and plot files
```

The public tools should stay small and predictable. Application services can hold the reusable logic that multiple tools need, such as target parsing, query tracing, table cleanup, unit conversion, cache lookup, and artifact writing.

## Proposed Package Layout

```text
kepler/
  __init__.py
  tools/
    __init__.py
    retrieval.py          # resolve/search/discover/fetch tools
    analysis.py           # FITS, image, table, light-curve, spectrum tools
    plotting.py           # plot-producing tools and plot summaries
    integration.py        # normalization, crossmatch, context-pack tools
    literature.py         # ADS and citation tools
    registry.py           # optional in-package registry of available tools
  models/
    __init__.py
    target.py             # TargetInput, TargetIdentity, SkyPosition, SearchRegion
    catalog.py            # CatalogQuery, CatalogRow, CrossmatchResult
    data_product.py       # ArchiveProduct, LocalProduct, ProductSummary
    analysis.py           # Measurement, StatisticSummary, AnalysisResult
    literature.py         # PaperSummary, Citation, BibliographyArtifact
    provenance.py         # Source, QueryTrace, PackageUsage
    result.py             # ToolResult, ToolError, Artifact, Pagination
  services/
    __init__.py
    target_resolution.py  # name/coordinate parsing and identity resolution
    catalog_search.py     # catalog queries and row normalization
    archive_discovery.py  # data-product discovery
    product_fetch.py      # downloads, cache lookup, checksum handling
    local_data.py         # FITS/table/product inspection
    analysis.py           # reusable analysis workflows
    plotting.py           # plot creation and artifact metadata
    integration.py        # table normalization, joins, crossmatch
    literature.py         # paper search and citation metadata
    provenance.py         # query traces, citations, package/version capture
  io/
    __init__.py
    fits.py               # FITS summaries and WCS helpers
    tables.py             # table serialization and column metadata
    serialization.py      # JSON-safe conversion for science objects
    artifacts.py          # artifact paths, manifests, MIME types
    cache.py              # query and product cache helpers
  runtime/
    __init__.py
    config.py             # environment/config-file/direct configuration
    limits.py             # max rows, radius, bytes, timeout defaults
    logging.py            # structured logs without credentials or huge payloads
    execution.py          # bounded sync helpers for slow remote calls
tests/
  unit/
  integration/
  fixtures/
```

`database_tools.py` can remain temporarily as a compatibility wrapper, but its logic should move into `tools/` and `services/` modules. The end state should make individual tools easy to import, test, document, and call directly.

## Tool Design Principles

- Each tool should do one useful astronomy operation with explicit inputs and bounded outputs.
- Tools should return compact structured summaries, not giant raw arrays or full remote payloads.
- Large generated or downloaded files should be returned as artifacts with paths, MIME types, sizes, and provenance.
- Every remote query should preserve provider, endpoint or service name, normalized query parameters, retrieval timestamp, package versions, and citation hints.
- Tools should expose conservative defaults and explicit limits for rows, radius, bytes, time ranges, and timeouts.
- Ambiguous target names should produce ambiguity warnings or partial results instead of silently selecting the first match.
- Tool names should be stable, verb-first, and direct enough for a general agent to choose without understanding internal package choices.

## Initial Tool Families

### 1. Data Retrieval

`resolve_target`

- Inputs: target name or coordinate string, optional frame, epoch, preferred resolver list, and ambiguity policy.
- Uses: `astropy.coordinates`, SIMBAD/NED/MAST-style resolvers where available.
- Output: canonical coordinates, coordinate frame, aliases, object classifications, redshift or radial velocity when available, provenance, ambiguity warnings.

`catalog_search`

- Inputs: center target or coordinates, radius, catalog/provider, selected columns, row limit.
- Uses: SIMBAD, NED, VizieR, ATNF, Virtual Observatory services, and package-supported catalog access.
- Output: normalized catalog rows with units, column metadata, sky positions, query trace, provider metadata, pagination when available.

`archive_discovery`

- Inputs: target or region, wavelength band, product type, mission/provider filters, time range, row limit.
- Uses: MAST, VO discovery services, archive package access, and provider metadata endpoints.
- Output: data products with provider, product ID, access URL or handle, calibration level, footprint, time/wavelength coverage, size estimate, citation notes.

`fetch_data_product`

- Inputs: product identifier or URL, cache policy, max bytes, expected format.
- Uses: provider download helpers, `astropy.utils.data`, HTTP libraries, and local cache services.
- Output: local path, checksum when available, product summary, cache metadata, license/citation notes.

`summarize_local_product`

- Inputs: local path, format hint, optional HDU/table selector, summary depth.
- Uses: Astropy FITS/table readers and local IO helpers.
- Output: file inventory, dimensions, units, WCS footprint when present, time metadata, table columns, basic statistics, warnings.

`ephemeris_lookup`

- Inputs: object name/designation, observer center/site, time range, step size, quantities.
- Uses: JPL Horizons or package-supported ephemeris access.
- Output: RA/Dec, alt/az when topocentric, rates, phase, distance, light time, query trace.

### 2. Analysis And Plotting

`summarize_fits`

- Inputs: FITS path, HDU selector, summary depth.
- Uses: `astropy.io.fits`, `astropy.wcs`, `astropy.table`.
- Output: HDU inventory, dimensions, units, WCS footprint, time metadata, basic image/table statistics, header warnings.

`detect_sources`

- Inputs: FITS image or image artifact, threshold model, background model, mask/region, output artifact options.
- Uses: Photutils, Astropy statistics, Regions when available.
- Output: source table with centroids, fluxes, morphology, segmentation artifact path, provenance.

`aperture_photometry`

- Inputs: image, target positions, aperture shape/radius, background annulus, zeropoint/calibration metadata.
- Uses: Photutils, Regions, Astropy WCS and units.
- Output: fluxes, magnitudes when calibrated, uncertainties, aperture masks or plots, provenance.

`analyze_light_curve`

- Inputs: light-curve file or fetched product, cleaning options, period-search settings, plot options.
- Uses: Lightkurve, Astropy timeseries, NumPy/SciPy.
- Output: normalized curve summary, periodogram peaks, quality warnings, plot artifacts.

`summarize_spectrum`

- Inputs: spectrum file or archive product, format hint, redshift/rest-frame option.
- Uses: Specutils and Astropy IO.
- Output: spectral axis range, flux unit, resolution metadata if available, SNR estimate, masks, quick-look plot artifact.

`measure_spectral_lines`

- Inputs: spectrum, line list or spectral regions, continuum model, redshift.
- Uses: Specutils and SciPy fitting where needed.
- Output: line flux, equivalent width, centroid, width, fit status, uncertainty, diagnostic plot artifacts.

`plot_data_product`

- Inputs: artifact or local path, plot type, selected columns/HDU, stretch/binning options, overlay options.
- Uses: Matplotlib, Astropy visualization helpers, WCSAxes, Pandas plotting where useful.
- Output: PNG/SVG artifact, plot metadata, warnings about clipping, missing WCS, masked values, or unsupported units.

### 3. Data Integration

`normalize_table`

- Inputs: table artifact/path or inline small table, column mapping, unit mapping, coordinate columns, time columns.
- Uses: Astropy Table/QTable, Pandas, unit and time helpers.
- Output: normalized table artifact, column metadata, conversion warnings, rejected rows summary.

`crossmatch_sources`

- Inputs: two or more source tables, coordinate columns, match radius, join strategy, output columns.
- Uses: Astropy coordinates and table joins.
- Output: crossmatch table, unmatched summaries, separation statistics, artifact path, provenance.

`merge_catalog_measurements`

- Inputs: catalog result sets, target identity, preferred measurement rules, conflict policy.
- Uses: table normalization, units, source ranking, provenance service.
- Output: merged measurement record, competing values, selected-value rationale, citation/provider trace.

`target_context_pack`

- Inputs: target, search radius, desired catalog families, literature limit, product filters.
- Uses: target resolution, catalog search, archive discovery, literature lookup, integration services.
- Output: compact research context with identity, nearby entries, selected measurements, relevant products, representative papers, warnings, and next-query suggestions.

`build_dataset`

- Inputs: retrieval results, local products, normalization rules, output format.
- Uses: integration service, artifact writer, provenance service.
- Output: reproducible dataset artifact plus manifest describing sources, filters, transformations, and citations.

### 4. Literature Lookup

`literature_search`

- Inputs: query string or structured fields, result limit, sort, field list.
- Uses: ADS package access or other package-supported ADS access.
- Output: title, authors, bibcode, year, citations, DOI, abstract snippet, ADS URL, query trace.

`papers_for_target`

- Inputs: target identity, aliases, optional topic filters, year range, result limit.
- Uses: target resolution and ADS search.
- Output: ranked paper summaries, matched aliases/terms, citation counts, ADS links, warnings about ambiguous names.

`citation_context`

- Inputs: bibcodes, DOI list, or ADS URLs, optional references/citations flag.
- Uses: ADS metadata lookup.
- Output: normalized citation metadata, references/citations when requested, BibTeX or CSL artifact.

`literature_to_dataset_links`

- Inputs: paper list and data-product/catalog identifiers.
- Uses: ADS metadata, DOI links, provider metadata, citation/provenance service.
- Output: candidate links between papers, catalogs, missions, and products with confidence notes.

## Application Services

Services should be internal building blocks rather than public API commitments. They allow multiple tools to share careful astronomy logic without turning each package dependency into an architecture layer.

| Service | Supports | Responsibilities |
| --- | --- | --- |
| Target resolution | retrieval, integration, literature | Parse names/coordinates, resolve identities, normalize frames, preserve aliases and ambiguity. |
| Catalog search | retrieval, integration | Run bounded catalog queries, normalize rows, attach units/metadata, handle partial provider failures. |
| Archive discovery | retrieval, integration | Find product handles, normalize product metadata, preserve footprints and coverage. |
| Product fetch | retrieval, analysis | Download or locate data products, enforce byte limits, populate cache and checksums. |
| Local data inspection | retrieval, analysis | Summarize FITS/tables/products without loading huge arrays into responses. |
| Analysis workflows | analysis, integration | Execute source detection, photometry, time-series, and spectral measurements with reusable validation. |
| Plot artifacts | analysis, integration | Create quick-look and diagnostic plots with stable filenames and metadata manifests. |
| Data integration | integration | Normalize schemas, join tables, crossmatch sources, resolve conflicts, build dataset manifests. |
| Literature | literature, integration | Search papers, normalize citation metadata, connect bibcodes/DOIs to targets and datasets. |
| Provenance | all tools | Record provider, package versions, query parameters, timestamps, citations, warnings, and transformations. |
| Cache and limits | all tools | Enforce TTLs, row/radius/byte caps, timeouts, retry policy, and artifact lifecycle. |

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
- Measurements should preserve uncertainty, method, calibration assumptions, and source.
- Large arrays should not be embedded in tool responses. Store them as artifacts and return paths plus summaries.
- Plot-producing tools should return both the plot artifact and enough metadata to understand how it was generated.

Core model concepts:

- `TargetInput`: name, coordinates, alias, or structured target reference.
- `SearchRegion`: center, radius, frame, optional shape.
- `QuantityValue`: JSON-safe quantity with value, unit, uncertainty, and optional description.
- `TimeRange`: start, end, scale, format, and optional cadence.
- `CatalogRow`: source identity, sky position, measurements, provider row metadata.
- `DataProduct`: provider, product ID, product type, access handle, footprint, coverage, size.
- `Artifact`: local path, MIME type, size, created time, producing tool, manifest path.
- `Source`: provider/package/source record with citation hints.
- `QueryTrace`: normalized input parameters, service/package names, execution timestamp, warnings.

## Dependency Policy

Dependencies should be selected by tool capability, not by architectural layering.

Likely core dependencies:

- `astropy`: coordinates, units, time, tables, FITS, WCS, cosmology, statistics, and visualization helpers.
- `astroquery`: SIMBAD, NED, VizieR, MAST, JPL Horizons, NASA Exoplanet Archive, and other named-service access.
- `pyvo`: TAP, SIA, SSA, SCS, registry search, and standards-based archive discovery.
- `psrqpy`: ATNF Pulsar Catalogue queries.
- `ads` or `astroquery.nasa_ads`: ADS search, bibcodes, citations, abstracts, and metadata.
- `pydantic`: tool input/output models and JSON-safe contracts.
- `numpy`, `scipy`, `pandas`: arrays, statistics, optimization, table transforms, and bridge formats.
- `requests` or `httpx`: direct HTTP access where existing packages are insufficient.

Optional extras can keep heavier workflows out of the base install:

- `kepler[image]`: `photutils`, `ccdproc`, `reproject`, `regions`.
- `kepler[plot]`: `matplotlib`, WCS plotting helpers, optional interactive plotting support.
- `kepler[planning]`: `astroplan`.
- `kepler[timeseries]`: `lightkurve`.
- `kepler[spectra]`: `specutils`, optionally `specreduce`.
- `kepler[solar]`: `sunpy`.
- `kepler[all]`: all optional science extras.

The ADS package choice should remain hidden behind the literature service until the public API is stable. The existing repository pins `ads==0.12.7`, while newer ADS documentation describes a v1 data-model API.

## Safety And Ergonomics

Astronomy tools can be slow, remote, ambiguous, and data-heavy. Tool behavior should be intentionally bounded.

- Require explicit `limit` parameters for table-returning tools, with conservative defaults.
- Add `max_radius`, `max_rows`, `max_bytes`, and `max_runtime` caps.
- Report ambiguous name resolutions instead of silently picking the first match.
- Provide partial results if one provider or package call fails in a multi-source tool.
- Keep arbitrary TAP/ADQL querying out of the initial public tool set. Start with reviewed query templates.
- Use stable error codes: `invalid_coordinates`, `ambiguous_target`, `not_found`, `auth_required`, `rate_limited`, `timeout`, `provider_unavailable`, `too_many_results`, `unsupported_format`, `artifact_too_large`.
- Redact API tokens and credentials from logs and tool outputs.
- Treat local file reads as explicit caller choices. Avoid recursive directory scans by default.
- Prefer artifact paths and summaries over embedding large payloads.

## Runtime Design

### Configuration

Use a single config object loaded from environment variables, optional config files, and direct constructor arguments:

- `ADS_DEV_KEY`
- `NASA_API_KEY`
- provider-specific timeout and row-limit defaults
- cache directory and cache TTL
- artifact output directory
- allowed local data roots
- user agent string for archive providers

### Caching

Use a cache layer for remote queries and downloaded products:

- Query cache key: service/tool name, normalized parameters, package versions, provider endpoint, and schema version.
- Product cache key: provider ID, URL, checksum/ETag when available.
- TTLs should vary by source. Literature and catalog metadata can often be cached longer than observability or ephemeris products.
- Store raw responses only when licensing and provider policy allow it.
- Always preserve enough metadata to reproduce the original query.

### Execution

Most astronomy package calls are synchronous and may involve remote services. Service code should provide bounded execution:

- hard timeout per remote call
- retry only idempotent remote requests
- fanout limits for multi-catalog searches
- cancellation support where the caller environment provides it
- structured logging around query traces, not raw giant payloads

### Artifacts

Analysis and plotting tools should create durable artifacts:

- FITS outputs
- CSV/ECSV/Parquet tables
- PNG/SVG plots
- JSON provenance manifests
- segmentation masks
- reduced spectra or light curves

Artifact responses should include path, MIME type, size, created time, and generating tool.

## MVP Roadmap

### Phase 1: Tool Package Core

- Convert the repository into an installable package with `pyproject.toml`.
- Define `ToolResult`, shared error models, artifact models, provenance models, and common input models.
- Move prototype query logic from `database_tools.py` into `tools/retrieval.py`, `tools/literature.py`, and supporting services.
- Implement the first narrow tools: `resolve_target`, `catalog_search`, `literature_search`, `citation_context`, and `target_context_pack`.
- Add unit tests with mocked Astropy tables and recorded minimal fixtures. Live network tests should be opt-in.

### Phase 2: Data Retrieval And Local Inspection

- Add archive discovery and product fetching tools.
- Add cache, result pagination, and artifact manifests.
- Add local FITS/table summary tooling for downloaded and user-provided products.
- Add ephemeris lookup if the initial data-retrieval use cases need solar-system support.

### Phase 3: Data Integration

- Add table normalization and column metadata handling.
- Add source crossmatch and merged-measurement tools.
- Add dataset-building artifacts with reproducible manifests.
- Expand `target_context_pack` to combine resolved identity, catalog measurements, archive products, and representative papers.

### Phase 4: Analysis And Plotting

- Add plotting artifact infrastructure.
- Add image analysis tools: FITS summary, source detection, aperture photometry, image plots.
- Add time-series and spectrum summary tools if those data products are common in early workflows.
- Build one deterministic fixture test per analysis workflow.

### Phase 5: Domain Expansion

- Add observation-planning tools if scheduling or visibility workflows become important.
- Add solar physics tools through SunPy if solar data is in scope.
- Add NASA Exoplanet Archive workflows.
- Add richer bibliography and research-context tools.

## Testing Strategy

- Unit tests should not require network access.
- Use tiny in-repo fixtures for FITS headers, tables, plot outputs, and response payloads.
- Add service-level tests for target parsing, coordinate conversion, unit conversion, row limits, timeout behavior, ambiguous targets, empty results, and masked tables.
- Add tool contract tests that validate returned `ToolResult` envelopes, artifacts, warnings, and provenance.
- Gate live provider tests behind environment variables such as `KEPLER_LIVE_TESTS=1`.
- Snapshot public JSON schemas so tool-facing contracts do not drift silently.
- Test artifact creation with temporary directories and verify paths, MIME types, sizes, and manifests.

## Open Questions

- Which five tools should define the first usable package milestone?
- Should Python callers receive Astropy objects directly anywhere, or should all public tools return JSON-safe models plus artifacts?
- Which data source should be treated as the default for target resolution when SIMBAD, NED, and MAST disagree?
- How much raw data should Kepler download automatically versus returning product handles?
- What citation format should be included in every result: BibTeX, provider text, DOI, or a compact source record?
- What plotting formats should be standard: PNG only, SVG only, or both?
- Should early workflows optimize for professional astronomy users, education/outreach, or general research assistance?

## Reference Notes

These docs were checked while drafting this brainstorm:

- [Astropy user guide](https://docs.astropy.org/en/stable/index_user_docs.html): core units, coordinates, time, tables, FITS, WCS, IO, cosmology, and stats.
- [Astroquery docs](https://astroquery.readthedocs.io/en/stable/): archive and catalog access including SIMBAD, VizieR, NED, MAST, JPL Horizons, and NASA Exoplanet Archive.
- [PyVO docs](https://pyvo.readthedocs.io/en/stable/): Virtual Observatory TAP, SIA, SSA, SCS, SLAP, registry, and discovery support.
- [Photutils API](https://photutils.readthedocs.io/en/stable/reference/index.html): aperture photometry, backgrounds, source detection, segmentation, and PSF tools.
- [Ccdproc docs](https://ccdproc.readthedocs.io/en/stable/): CCD reduction with uncertainty propagation and bad-pixel tracking.
- [Reproject docs](https://reproject.readthedocs.io/en/stable/): astronomical image reprojection and WCS-based resampling.
- [Astroplan docs](https://astroplan.readthedocs.io/en/stable/): observation planning, target observability, and site/time constraints.
- [Lightkurve docs](https://lightkurve.github.io/lightkurve/): Kepler, K2, and TESS light-curve access and analysis.
- [Specutils docs](https://specutils.readthedocs.io/en/stable/index.html): spectrum containers, spectral regions, analysis, fitting, and manipulation.
- [SunPy docs](https://docs.sunpy.org/en/stable/): solar coordinates, maps, time series, and data search/download.
- [JPL Horizons API docs](https://ssd-api.jpl.nasa.gov/doc/horizons.html): programmatic solar-system ephemeris access.
- [ADS Python docs](https://ads.readthedocs.io/en/v1/): SAO/NASA ADS data models, search, libraries, and package API.
