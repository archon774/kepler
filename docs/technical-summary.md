# Kepler Technical Summary

**Status:** current-state reference
**Verified against:** `dev` at `43247d2` on 2026-09-21

Kepler is an astronomy capability library with an optional LLM-driven console
and model-evaluation harness. It lets a Python caller, script, notebook, or
agent use the same small public functions for astronomy research and data
reduction. It is deliberately **not** an orchestration framework or a required
web service: the console is one consumer of the tool layer, and every public
tool remains directly importable from Python.

The project combines algorithms extracted from production Skynet and
Astromancer systems with a thin, typed tool surface. Its working boundary is
**Astropy-native inside, JSON-and-artifact-native outside**: scientific code
operates on astronomy-native values, while callers receive compact typed
summaries, warnings/errors, and paths to larger local artifacts.

## Delivered architecture

```text
Python callers, scripts, notebooks        Textual `kepler` console       `kepler-bench`
              \                                  |                          /
               \                                 |                         /
                +------------------------ tools/agent --------------------+
                                  |                 |
                           tools/llm          tools/registry
                         provider adapters       55 public tools
                                                    |
                                             tools/*.py wrappers
                                                    |
                                           algorithms/* packages
```

- **Public tool layer.** The registry maps 55 schemas to the same ordinary
  Python functions that non-agent callers use. Tools validate and normalize
  inputs, keep responses bounded, return structured failures instead of
  propagating routine runtime errors, and put large tables, FITS products,
  plots, and audio on disk as artifacts.
- **Algorithm layer.** Domain packages own the scientific behavior; tools do
  not reimplement numerical work. The major packages cover WCS/plate solving,
  source extraction and aperture photometry, field calibration, catalog
  declarations and querying, pulsar analysis, HR-diagram fitting, variable
  stars, and radio-source spectral fitting.
- **Agent layer.** `tools/agent/` supplies a bounded, headless tool-use loop.
  It is separate from the user interface, supports approval decisions,
  validates proposed calls before dispatch, avoids repeated identical calls,
  records session manifests, and limits a run to 20 turns.
- **Model port.** `tools/llm/` isolates provider dialects behind neutral types
  and adapters for Anthropic, OpenAI-compatible services, Ollama, and Gemini.
  The agent core owns the loop; adapters translate requests, responses, and
  schemas.
- **Two harnesses over one loop.** The Textual console makes a run interactive
  and inspectable; the benchmark harness makes it reproducible and gradeable.
  Neither changes the scientific tools or algorithms.

For the detailed ownership and dependency rules, see
[tool-architecture.md](tool-architecture.md) and
[architecture-layers.md](architecture-layers.md).

## Completed astronomy capability work

### Preserved algorithm foundation

Kepler has extracted the relevant Python algorithms from Skynet and the
framework-free TypeScript algorithms from Astromancer. Extraction is a
preservation task rather than a rewrite: upstream constants, calculations,
comments, and known behavior are retained, and severed framework dependencies
are marked in the source. The shared `algorithms/skylib_lite/` package
consolidates the local Skylib subset used by the optical code.

The repository also includes clearly labelled intentional departures from that
model: a Python pulsar port, a Python HR-diagram port plus optimizer, and new
radio-source fitting/matching capability. Provenance, extraction boundaries,
and deliberately preserved quirks are recorded domain by domain in
[extraction.md](extraction.md).

### Optical analysis and calibration

The optical stack now includes FITS-frame discovery, WCS description and
bounded plate-solving, source extraction, aperture photometry, catalog-source
matching, reference-band resolution, variable-star rejection, and photometric
zero-point solving. Public tools expose both normal local workflows and
recorded offline replays of field-calibration ground truth. The replay path can
exercise selection and solving against recorded APASS/VSX responses without a
network connection.

### Catalog, archive, and literature access

Kepler supplies a split remote tool surface for SIMBAD, NED, VizieR, ATNF,
ADS, MAST, MPC, CASDA, and SIMBAD-backed target resolution. It keeps catalog
declarations separate from the network-query layer, bounds inline results, and
writes complete remote results as local artifacts. This supports catalog and
archive discovery without making provider behavior part of the default test
suite.

### Local scientific pipelines

- **Pulsars:** load a scan, calculate a Lomb–Scargle periodogram, fold a pulse
  profile, plot stages, and sonify the result. The documented stage order
  prevents treating an audio rendering as a period measurement.
- **HR diagrams:** extract sources from a supplied FITS frame or begin from a
  cluster name, obtain Gaia/literature inputs where needed, select members,
  fit distance/extinction/age, compare to literature, and emit a plot. The
  Python optimizer is new functionality beyond the Astromancer extraction.
- **Radio sources:** identify sources in a radio FITS frame using radio
  catalogs, gather their NED spectra, fit spectral-index or log-parabola
  models, and produce a labelled field SED plot.
- **Variable stars:** the repository includes a parity port for light-curve,
  periodogram, and folding work alongside the general pulsar chain.

The four-stage pulsar contract is documented in
[pulsar-tool-pipeline.md](pulsar-tool-pipeline.md); the folder-level inventory
is in [repository-folders.md](repository-folders.md).

## Completed agent, console, and evaluation work

The project has moved beyond a collection of callable astronomy routines while
keeping those routines independent of the model layer:

- The `kepler` command launches a Textual console with a live transcript,
  tool-call status, approval prompts for risky work, artifact previews, session
  browsing/resume, slash commands, cancellation, and live backend selection.
- Session manifests preserve each run's turns, tool calls, artifacts, and cache
  hits under `artifacts/sessions/`, allowing later inspection without replaying
  a model.
- The `kepler-bench` harness measures models over the same registry. It runs
  deterministic local tools live, replays remote providers from fixtures, and
  grades against recorded evidence rather than asking a second model to judge
  the first.
- The completed benchmark sweep exercised 16 tasks across three backends and
  three repeats (144 sessions). Its results are useful evidence about this
  tool surface, not a general ranking of language models; documented corpus
  and schema-dialect limits remain in force.

See [benchmarking/README.md](benchmarking/README.md) for the reproducible
benchmark material and [architecture-layers.md](architecture-layers.md) for
the separation between tools, turn-taking, and harness responsibilities.

## Validation and operating policy

Validation is designed to protect extraction fidelity and make routine checks
safe to run locally:

- The default suite is offline, deterministic, and keyless. Network tests are
  explicitly marked and require `KEPLER_TEST_NETWORK=1`; solver-data tests
  self-skip when their local catalogs are unavailable.
- Tests use 42 real PROMPT/Skynet optical frames and four recorded Skynet
  zero-point solves. Preservation tests compare selected behavior bit-for-bit,
  including documented upstream defects rather than silently changing them.
- CI compiles Python, runs `uv run --locked pytest`, and checks the required
  repository shape. TypeScript packages are framework-free and receive a
  manual `npm run typecheck` check; they have no runtime test harness.
- External astrometry indexes, a UCAC catalog tree, and the Girardi isochrone
  grid are intentionally operator-provided rather than vendored. Tools report
  structured limitations when those optional assets are absent.

The 2026-09-18 completion audit recorded in
[working/README.md](working/README.md) reports that the then-active tracks had
landed and re-verified the default suite at 2,575 passing and 44 skipped tests.
Run the current suite before relying on that point-in-time count.

## Current project position

Kepler is now a documented, installable astronomy tool collection with a
completed optical rollout, provider-neutral model port, interactive console,
and calibrated benchmark track. Its strongest guarantees are local execution
boundaries, extraction provenance, recorded scientific baselines, and
deterministic default validation.

The MCP tool-surface track has landed. `kepler-mcp` serves all 55 tools over
stdio to a coding agent's own console on a machine with no checkout, with the
agent skill as its instructions and resources. A wheel carries the core data,
and `kepler-mcp fetch-data` installs checksum-pinned optional bundles.
`v0.1.0rc1` is published as a pre-release. See
[tool-architecture.md](tool-architecture.md) section 10.3,
[installing.md](installing.md), and the track record in
[archive/mcp-tool-surface.md](archive/mcp-tool-surface.md).

It does not claim that every remote provider workflow is continuously tested,
that preserved upstream behavior is scientifically correct, or that the
benchmark is a model-independent leaderboard. Those limits are intentional,
visible, and documented alongside the corresponding code and evidence.

## Further reading

| Need | Start with |
| --- | --- |
| System ownership and policies | [tool-architecture.md](tool-architecture.md) |
| Layer boundaries and control flow | [architecture-layers.md](architecture-layers.md) |
| Source provenance and parity decisions | [extraction.md](extraction.md) |
| Folder and tool inventory | [repository-folders.md](repository-folders.md) |
| Pulsar pipeline contract | [pulsar-tool-pipeline.md](pulsar-tool-pipeline.md) |
| Benchmark design, evidence, and limits | [benchmarking/README.md](benchmarking/README.md) |
