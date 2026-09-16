# Kepler

[![CI](https://github.com/archon774/kepler/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/archon774/kepler/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

An agentic, tool-enabled system for automated astronomy — an LLM agent,
named Kepler, that plans and executes astronomy tasks by calling a registry
of purpose-built tools backed by algorithms extracted from two production
systems.

## Contents

- [Overview](#overview)
- [The Agent](#the-agent)
- [Highlights](#highlights)
- [Current Contents](#current-contents)
- [Repository Shape](#repository-shape)
- [Getting Started](#getting-started)
- [Testing & Validation](#testing--validation)
- [Configuration](#configuration)
- [TypeScript Extracts](#typescript-extracts)
- [Architecture & Further Reading](#architecture--further-reading)
- [Development Notes](#development-notes)
- [Contributing](#contributing)

## Overview

Kepler is an agentic, tool-enabled system for automated astronomy: an LLM
agent that plans and executes astronomy research and data-reduction tasks —
literature and catalog search, target resolution, and, as the underlying
algorithms come online, WCS plate solving, photometry, and photometric
calibration — by calling a registry of purpose-built tools. See
[The Agent](#the-agent) for the agent and its reusable local pipeline.

This repository is where the agent's tools, and the algorithms they call, are
built and staged. Its current state is a small installable Python tool
collection, extracted astronomy algorithms, a split database-query tool
surface, and an architecture document for turning those pieces into a
coherent tool surface.

The algorithms come out of two production systems built around the
[Skynet Robotic Telescope Network](https://skynet.unc.edu/), operated by the
University of North Carolina at Chapel Hill: Skynet itself, and
[Astromancer](https://astromancer.skynet.unc.edu/home), its companion web
application for light-curve, periodogram, and star-cluster (HR-diagram)
analysis. The Python folders here were extracted from Skynet; the TypeScript
folders from Astromancer.

These were **extractions, not rewrites**: algorithms, constants, comments, and
known bugs are byte-preserved from their source systems rather than
reimplemented. See [Highlights](#highlights) below and
`docs/extraction.md` for what that means in practice.

## The Agent

Kepler has an agent entry point and a reusable local pipeline, both built on
the plain Python functions in `tools/`:

- **`tools.runner` — the astronomy research agent** (entry point:
  `kepler-astro-query`). A bounded tool-use loop (`max_turns=20`, default model
  `claude-sonnet-5`) over `tools.registry.TOOL_SCHEMAS`: one
  schema per remote database — SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA,
  and ADS — plus SIMBAD-backed target resolution, local aperture photometry
  on a bundled FITS library (`tools.photometry`), a local pulsar pipeline
  (`tools.pulsar`: ingest a scan, compute its periodogram, fold it into a
  pulse profile, sonify it, and plot any stage), and an HR-diagram pipeline
  (`tools.hr_diagram`) with two entry points: a catalog-only one that needs
  nothing but a cluster name (fetches Gaia DR3 directly around the cluster's
  own resolved position) and a FITS-frame one for a user who has their own
  plate-solved frame and wants that frame's own photometry driving the fit —
  both end at the same literature comparison, isochrone fit, and plot — and a
  radio-source pipeline (`tools.radio_sources.plot_field_sed`): identify
  sources in a processed radio FITS frame against VizieR's radio catalogs,
  then plot every identified source's spectral energy distribution from NED
  together on one labeled plot, each with its own fitted spectral index. Its
  system prompt encodes per-database quirks confirmed by direct testing
  (NED's resolver fails on colloquial names where SIMBAD's succeeds; MPC and
  ATNF do zero name resolution and require formal designations; ADS needs
  fielded queries, not natural language), sourcing discipline (quote a
  paper's abstract before attributing a number to it), and repeat-call
  caching, so an identical tool call costs no extra network round trip. Every
  run also writes a session manifest (`tools.sessions.AgentSession`) recording
  each turn and tool call — including cache hits — under
  `artifacts/sessions/<session_id>/session_manifest.json`, so a session's
  tool-call history can be inspected or replayed after the fact
  (`tools.sessions.list_session_manifests` / `read_session_manifest`). The loop
  itself lives in `tools/agent/` and drives a provider-neutral model port
  (`tools/llm/`); `tools/runner.py` is the console shim over it. Run it with:

  ```bash
  ANTHROPIC_API_KEY=... uv run kepler-astro-query "all historical radio data on Cassiopeia A"

  # or another provider, via a provider/model spec:
  KEPLER_MODEL_BACKEND=ollama/qwen3:8b uv run kepler-astro-query "resolve NGC 6334"
  ```

- **`tools/photometry_pipeline.py` — reusable automated photometry.** It
  loads a FITS image, runs source extraction and aperture photometry, resolves
  an optional verified zero point through a live field-calibration catalog
  solve, and saves plots. `tools.photometry`
  (`list_photometry_targets`, `run_photometry_on_target`) is the public wrapper
  over this same pipeline. The retired standalone CLI and direct Claude summary
  are not part of this module. **Listing and resolving a target are offline;
  running field calibration is not.** `run_photometry_on_target` defaults to
  `use_field_cal=True`, which queries VizieR for reference magnitudes. Pass
  `use_field_cal=False` for instrumental magnitudes, or provide
  `zero_point_mag` when a trusted value is already available. The recorded-solve
  replay — `tools.photometry.calibrate_zeropoint(path,
  catalog_fixture="selected_rows", compare_to="ngc5128_b_002")` injects the
  APASS rows Skynet actually matched, so extraction → photometry → matching →
  reference magnitude → solve all run for real with no socket opened, and
  `catalog_fixture="full_response"` does the same from the recorded APASS
  response for the whole field (with the recorded VSX variables filtered
  out), so the matches are *chosen* rather than given. Either way
  `compare_to` checks the answer against the recorded Skynet solve.
  `tools.fieldcal_reference.replay_field_calibration("ngc5128_b_002")` is the
  bit-exact form of the second path: the recorded detections through the
  whole selection — 132 rows in the cone, 45 on the frame after the live
  path's clipping, the recorded 35 chosen — and `21.147659857998637`
  exactly. Only `ngc5128_galaxy_b_001.fits` can be
  driven that way end to end; the three NGC 5286 solves have no bundled
  frame and no recorded response. Neither this nor `tools.photometry`
  calibrates
  against Gaia or fits an isochrone — for that, see `tools.hr_diagram` above;
  `run_photometry_on_target(..., write_source_table=True)` writes a CSV in the
  column shape `tools.hr_diagram.crossmatch_gaia` expects, as a bridge between
  the two when a bundled photometry target turns out to be a cluster.

Both components call directly into the same plain Python functions and
extracted algorithm packages described below — an agent's tool call is the
identical function any other caller would import and run.

## Highlights

- **Provider-neutral agent surface.** `tools.runner`
  (`kepler-astro-query`) runs a bounded, provider-neutral tool-use loop over
  eight remote astronomy databases — Anthropic by default, or an
  OpenAI-compatible, Ollama, or Gemini backend via `KEPLER_MODEL_BACKEND`.
  The registered `tools.photometry` wrapper runs the local FITS photometry
  pipeline without a separate model client. See [The Agent](#the-agent).
- **Byte-preserved extraction contract.** Every severed upstream dependency is
  marked inline with `# EXTRACTED: was <symbol>` (Python) or
  `// EXTRACTED: was …` (TypeScript) — an index of exactly what was cut and
  why. Documented parity quirks and known upstream bugs are deliberately kept
  rather than "fixed" in transit.
- **Bit-exact parity test suite.** `tests/` backs the Python algorithms with
  39 real PROMPT/Skynet FITS frames and four complete recorded Skynet
  zero-point solves, checked bit-for-bit against production output. These
  aren't tests of whether the algorithms are *right* — that was settled
  upstream — they're tests of whether the extraction still does exactly what
  Skynet did, wrong parts included. See `tests/README.md` and
  [Testing & Validation](#testing--validation).
- **Strict domain ownership.** `algorithms/wcs/`, `algorithms/photometry/`,
  and `algorithms/fieldcal/` deliberately do not import each other; the same
  discipline holds between `algorithms/catalogs/` (declarations, no network)
  and `algorithms/query/` (the only layer that opens a socket). Cross-domain
  values are passed in explicitly by the caller rather than injected through a
  seam, and one public tool call is the whole execution boundary — no run,
  stage, or session state survives it.

## Current Contents

| Path | Status | What it contains |
| --- | --- | --- |
| `tools/` | Python tools | Plain Python wrappers for local frame discovery (`tools/optical.py`), WCS description and plate solving (`tools/astrometry.py`, `tools/wcs.py`), catalog metadata, reference-band resolution, zero-point solving and the recorded-solve references (`tools/fieldcal_reference.py`), local artifact inspection, remote database/archive queries, local aperture photometry (`tools/photometry.py`), the pulsar pipeline (`tools/pulsar.py`), and FITS-to-HR-diagram pipeline orchestration (`tools/hr_diagram.py`). |
| `tools/runner.py`, `tools/agent/`, `tools/llm/`, `tools/registry.py`, `tools/sessions.py` | Python agent | The `kepler-astro-query` tool-use loop: a console shim (`runner.py`) over the headless engine (`tools/agent/`), the provider-neutral model port (`tools/llm/`: Anthropic, OpenAI-compatible, Ollama, Gemini), the tool-schema registry, and the per-run session manifest recorder. See [The Agent](#the-agent). |
| `tools/photometry_pipeline.py` | Python pipeline | Reusable FITS photometry, zero-point resolution, and plotting implementation used by `tools.photometry`; it has no CLI or model-provider client. |
| `algorithms/wcs/` | Extracted Python algorithm | Skynet WCS calibration: source extraction, FITS-header hinting, astrometry.net `solve-field`, ATLAS triangle solving, solution validation, and FITS-header write-back. |
| `algorithms/photometry/` | Extracted Python algorithm | Skynet source extraction and aperture photometry using the shared `algorithms/skylib_lite/` Skylib subset. |
| `algorithms/fieldcal/` | Extracted Python algorithm | Skynet photometric zero-point calibration: catalog-source matching, variable-star filtering, reference-magnitude resolution, and weighted zero-point solving. |
| `algorithms/skylib_lite/` | Shared Python support | Consolidated local Skylib subset used by WCS, photometry, and field calibration: astrometry, SEP extraction, background estimation, aperture photometry, FITS helpers, angle math, and statistics. |
| `algorithms/catalogs/` | Extracted Python algorithm | Skynet and Afterglow photometric catalog declarations, SIMBAD object-type vocabulary, and provider lookup tables used by ADS/NED/ATNF tools. Declaration only — no network code. |
| `algorithms/query/` | Extracted Python algorithm | Skynet and Afterglow remote catalog access: the VizieR engine, SDSS SkyServer SQL, SIMBAD identifier resolution, astroquery cache handling, filter-aware catalog selection, and WCS-footprint query orchestration. |
| `algorithms/hrdiagram_py/` | Python parity port + new capability | Star-cluster CMD/HR-diagram fitting: CM↔HR transform, extinction, isochrone loading, a distance/E(B-V)/age optimizer Astromancer's own tool never had, field-star removal, and geometric catalog matching. Not a byte-preserving extraction — see `docs/extraction.md`, "HR Diagram (Python)". |
| `algorithms/radio/` | New Python capability | Radio spectral-index/log-parabola flux-vs-frequency fitting and generic RA/Dec-column-guessing catalog cross-matching. No upstream Skynet/Astromancer equivalent. |
| `algorithms/pulsar/` | Ported Python algorithm | The four-stage pulsar chain: file ingest and background subtraction, Lomb-Scargle periodogram, phase folding and binning, and light-curve sonification. A **port** of the Astromancer TypeScript, not an extraction — see `docs/pulsar-tool-pipeline.md`. |
| `algorithms/lightcurve/` | Extracted TypeScript algorithm | Astromancer pulsar and variable-star light-curve ingestion, transformation, period-folding, and sonification logic with Angular/RxJS/Highcharts removed. |
| `algorithms/periodogram/` | Extracted TypeScript algorithm | Astromancer Lomb-Scargle periodogram logic, peak/confidence helpers, pulsar range defaults, and periodogram-to-folding coupling. |
| `algorithms/hrdiagram/` | Extracted TypeScript algorithm | Astromancer cluster/HR-diagram logic: field-star removal, isochrone matching, extinction offsets, cluster summaries, and result projections. |
| `package.json` / `tsconfig.json` | TypeScript tooling | Private npm metadata and compiler configuration for the extracted TypeScript algorithm modules. |
| `tests/` | Python test suite | Algorithm-preservation and tool-smoke tests: bit-exact parity against recorded Skynet output, real FITS fixtures, and no-network coverage of the public `tools/` surface. See `tests/README.md`. |
| `docs/` | Documentation | `docs/README.md` is the map: reference docs at the top level, `docs/analysis/` for review output, `docs/working/` for in-progress plans. |
| `docs/tool-architecture.md` | Architecture | Master package architecture: public tools, algorithm ownership, future services, runtime policy, and `skylib_lite` consolidation. |
| `docs/extraction.md` | Provenance | Consolidated extraction records for every algorithm package under `algorithms/`. |
| `docs/pulsar-tool-pipeline.md` | Architecture | The pulsar tool chain — light curve, periodogram, fold, sonify — and the extracted Astromancer code behind each stage. |
| `docs/repository-folders.md` | Folder guide | Per-folder responsibilities, important files, and current caveats for every source folder. |
| `docs/analysis/` | Review output | Point-in-time algorithm and design reviews: the remediation plan's finding register, external-agent design analysis, and the pulsar tooling-bug list. |
| `docs/examples/` | Sample output | One committed pulsar sonification (`psr_b0329_54_sonification.wav`), produced by the agent loop. The only generated file in the repository. |

The consolidated extraction record in `docs/extraction.md` captures provenance,
severed framework dependencies, known parity behaviors, dependency notes, and
verification already performed for every extracted algorithm package.

## Repository Shape

```text
Kepler/
  pyproject.toml                 # Python package metadata and dependencies
  uv.lock                        # uv lockfile for reproducible installs
  package.json                   # TypeScript toolchain metadata
  tsconfig.json                  # TypeScript compiler smoke-check config
  CONTRIBUTING.md                # contribution guidelines
  AGENTS.md                      # repository guidelines for agentic contributors
  docs/
    README.md                    # documentation map + lifecycle
    extraction.md                # master algorithm extraction record
    tool-architecture.md         # master package architecture
    repository-folders.md        # per-folder guide
    pulsar-tool-pipeline.md      # the four-stage pulsar tool chain
    analysis/                    # point-in-time algorithm/design reviews
    working/                     # in-progress plans
    examples/                    # one committed sample output
  tools/                         # public Python tool wrappers, runner, shared models
  algorithms/
    wcs/                         # Python WCS extraction from Skynet
    photometry/                  # Python photometry extraction from Skynet
    fieldcal/                    # Python zero-point calibration extraction
    skylib_lite/                 # shared vendored Skylib subset
    catalogs/                    # Python catalog declarations (no network code)
    query/                       # Python remote catalog access (VizieR/SDSS/SIMBAD)
    lightcurve/                  # TypeScript light-curve extraction
    periodogram/                 # TypeScript periodogram extraction
    hrdiagram/                   # TypeScript HR-diagram extraction
  tests/                         # pytest suite (algorithm-preservation + tool smoke)
  data/                          # the data root: fixture frames, recorded
                                 #   reference outputs, and the (untracked)
                                 #   fits_downloads/ archive download root
```

## Getting Started

### Python Setup

Use `uv` to create the virtual environment and install the Python package with
its dependencies:

```bash
uv sync
```

`pyproject.toml` is the installable package metadata and includes the Python
dependencies needed by the split database tools and extracted algorithm modules.
`uv.lock` records the resolved dependency set.

Some extracted runtime paths also require non-Python solver data called out in
`docs/extraction.md`, including astrometry.net index files and local
UCAC4/UCAC5 catalogs.

### Python Entry Points

ADS queries require `ADS_DEV_KEY`. The optional agent loop exposed by
`tools.runner` needs a model backend: `ANTHROPIC_API_KEY` for the default
Anthropic backend, or `KEPLER_MODEL_BACKEND` plus that provider's key (see
[Configuration](#model-backend-configuration)).

The plain Python tools live under `tools`:

```python
from tools.optical import list_optical_frames, resolve_optical_frame
from tools.astrometry import describe_image_wcs
from tools.wcs import solve_astrometry
from tools.catalogs import list_photometric_catalogs, resolve_reference_band
from tools.calibration import solve_zeropoint_from_measurements
from tools.fieldcal_reference import (
    compare_zeropoint_to_reference,
    list_zeropoint_references,
    load_zeropoint_reference,
    replay_catalog_sources,
    replay_field_calibration,
)
from tools.simbad import search_simbad
from tools.vizier import search_vizier
from tools.ned import search_ned
from tools.ads import search_ads, build_literature_review
from tools.mast import search_mast
from tools.mpc import search_mpc
from tools.atnf import search_atnf
from tools.casda import search_casda
from tools.photometry import (
    calibrate_zeropoint,
    list_photometry_targets,
    run_photometry_on_target,
)
from tools.pulsar import load_pulsar_lightcurve, compute_pulsar_periodogram
from tools.hr_diagram import run_full_hr_pipeline, run_full_hr_pipeline_from_catalog
from tools.workspace import describe_artifact, list_artifacts
```

An optional agentic runner is available for wiring these tools into a
tool-use loop:

```bash
ANTHROPIC_API_KEY=... uv run kepler-astro-query "all historical radio data on Cassiopeia A"
```

Advanced callers can still import the extracted algorithm packages directly:

```python
from algorithms.wcs.wcs import solve_wcs
from algorithms.photometry.photometry import run_photometry
from algorithms.photometry.source_extraction import run_source_extraction
from algorithms.fieldcal import perform_field_calibration, calc_solution
from algorithms.query.runner import query_catalogs
from algorithms.query.simbad import resolve_simbad
```

`fieldcal` deliberately does not own WCS, photometry, or catalogs, and it has no
dependency-injection seam to wire: `perform_field_calibration` takes the header,
the image array, and then `wcs`, `catalog_sources`, optional `variable_sources`,
and any extraction/photometry/calibration settings as explicit keyword
arguments. Fetching the catalog rows is the caller's job — `algorithms/fieldcal/`
opens no socket — which is what keeps the zero-point solve runnable with no
network stack installed. In this repo the tool layer is that caller; see
`tools.photometry.calibrate_zeropoint`, and pass it `catalog_fixture=` (or
`catalog_sources=` from `tools.fieldcal_reference.replay_catalog_sources`)
for a fully offline solve.

Catalog metadata and catalog access are separate on purpose. Import
`algorithms.catalogs` for band tables, colour transforms, and provider
vocabularies; it is pure data and pulls in no network stack. Import
`algorithms.query.registry` when you need to actually fetch sources.

## Testing & Validation

Kepler's Python folders are byte-preserving extractions from Skynet, so
`tests/` is not there to check whether the algorithms are *right* — that
question was settled upstream. It checks whether the extraction still does
**exactly what it did before**, including the parts that are wrong. Fixtures
are 39 real PROMPT/Skynet frames and four complete recorded Skynet zero-point
solves; the centerpiece, `test_fieldcal_solution.py`, feeds `calc_solution` the
exact rows Skynet fed it and compares against the exact numbers Skynet
returned, bit-for-bit, on four fields. Known upstream defects are pinned by
name in the suite rather than fixed silently — see `tests/README.md` for the
full list and for what is deliberately not yet covered.

For Python changes, run the same checks CI enforces:

```bash
python3 -m compileall tools algorithms tests
uv run pytest
git diff --check
```

For TypeScript changes, also run (after `npm install` — see
[TypeScript Extracts](#typescript-extracts); `node_modules/` is not in a fresh
checkout, and this is not a CI job):

```bash
npm run typecheck
```

The extraction notes record broader one-off checks such as compile/import smoke
tests, source diffs, and selected behavior checks. Full end-to-end WCS,
photometry, and calibration parity beyond the bundled pytest fixtures still
requires solver binaries and local catalog data.

## Configuration

### Model Backend Configuration

The agent loop's model backend is chosen by a `provider/model` spec, split on
the first slash only. With `KEPLER_MODEL_BACKEND` unset it uses Anthropic.

- `KEPLER_MODEL_BACKEND`: e.g. `anthropic/claude-sonnet-5`, `openai/gpt-4.1`,
  `ollama/qwen3:8b`, `gemini/gemini-2.5-pro`.
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`: the provider key.
- `OPENAI_BASE_URL`: an OpenAI-compatible endpoint. A non-default base URL
  needs its key passed explicitly alongside it — an environment
  `OPENAI_API_KEY` is only sent to `api.openai.com`.
- `OLLAMA_BASE_URL`: defaults to `http://localhost:11434/v1`; no key.

```bash
KEPLER_MODEL_BACKEND=openai/gpt-4.1 OPENAI_API_KEY=... \
  uv run kepler-astro-query "all historical radio data on Cassiopeia A"
```

### Catalog Query Configuration

The remote catalog backends read settings from environment variables:

- `VIZIER_SERVER`: VizieR mirror hostname, defaulting to `vizier.cds.unistra.fr`.
- `VIZIER_CACHE_ENABLED`: whether astroquery caches responses on disk (default on).
- `VIZIER_CACHE_AGE_DAYS`: cache retention, defaulting to 30.

With the cache enabled, query regions are snapped to a fixed grid so that
near-identical fields share a cache entry. This is observable near a field edge —
see `docs/extraction.md`, Query §5.1.

### WCS Configuration

The WCS solver reads backend settings from environment variables:

- `ANET_INDEX_PATH`: astrometry.net index directory or `os.pathsep`-separated directories.
- `ANET_TIMEOUT_S`: astrometry.net low-level solve-attempt limit in seconds (minimum 1).
- `ATLAS_CATALOG_ROOT`: local UCAC4/UCAC5 catalog root for the ATLAS fallback.
- `ATLAS_CATALOG`: catalog name, defaulting to `ucac5`.
- `ATLAS_TIMEOUT_S`: ATLAS matcher timeout in seconds.

The astrometry.net backend also needs a `solve-field` binary on `PATH` or via
the supported `SKYLIB_*` environment overrides documented in
`docs/extraction.md`, WCS.
If neither backend is configured, the package can still import, but end-to-end
plate solving will not produce a solution.

## TypeScript Extracts

`algorithms/lightcurve/`, `algorithms/periodogram/`, and `algorithms/hrdiagram/` contain
framework-free TypeScript source extracted from Astromancer. The root
`package.json` and `tsconfig.json` provide a compiler-only setup for these
modules; there are no runtime npm dependencies.

Install the TypeScript toolchain with npm:

```bash
npm install
```

Run the TypeScript smoke check:

```bash
npm run typecheck
```

The compiler target is ES2022 and includes the DOM library because the preserved
light-curve ingest path still uses browser globals such as `FileReader`.

## Architecture & Further Reading

- `docs/README.md` — the documentation map and the document lifecycle.
- `docs/tool-architecture.md` — the master package architecture: public tools,
  algorithm ownership, future services, runtime policy, and `skylib_lite`
  consolidation.
- `docs/extraction.md` — the consolidated provenance record for every
  extracted algorithm package: source paths, line ranges, severed
  dependencies, parity notes, and verification performed.
- `docs/repository-folders.md` — a per-folder guide to responsibilities,
  important files, and current caveats.
- `docs/pulsar-tool-pipeline.md` — the four-stage pulsar tool chain and the
  extracted Astromancer code behind each stage.
- `docs/analysis/algorithm-remediation-plan.md` — the algorithm-review finding
  register and a proposed rollout for the defects pinned by the test suite.
- `tests/README.md` — what the test suite proves, its markers, and what it
  deliberately does not cover yet.

## Development Notes

- Keep changes narrow and target `dev` unless a maintainer asks otherwise.
- Do not commit API keys, local environment files, downloaded FITS products,
  generated plots, caches, or large astronomy datasets.
- Keep live remote astronomy service calls gated; default checks should remain
  deterministic and bounded.
- Preserve documented legacy-parity behavior in extracted code unless a change
  is explicitly intended to diverge from Skynet or Astromancer.

## Contributing

See `CONTRIBUTING.md` for the current contribution guidance and `AGENTS.md`
for repository guidelines aimed at agentic contributors. `.github/CODEOWNERS`
marks the repository as maintainer-owned; changes to `main` require Code
Owner review.
