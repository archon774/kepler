# Installing Kepler and serving its tools

How to put Kepler on a machine that has **no checkout** of this repository,
serve its tools to a coding agent's console over MCP, and add the optional
data. The design behind it is `archive/mcp-tool-surface.md` §3.5 and phases
C3–C7.

## What a wheel contains

| Part | Where | Size |
| --- | --- | ---: |
| `tools/` and `algorithms/` | the wheel | ~4 MB of code |
| **Core data**: the five pulsar scans, the recorded zero-point references, the Afterglow parity fixtures | the wheel, under `tools/_data/` | ~7 MB |
| **Optional bundles**: the optical frame library, the Girardi isochrone grid | fetched on request, `kepler-mcp fetch-data` | 269 MB, 282 MB |
| astrometry.net indexes, the ATLAS UCAC5 catalogue | **never bundled**; operator-supplied | 78 GB, 5.3 GB |

Measured in C7 on a clean Python 3.14 virtual environment: Kepler itself
installs to about 10 MB. The environment as a whole is about **640 MB**,
almost all of it dependencies — `llvmlite` (for `numba`) alone is 168 MB, then
`scipy`, `pandas`, `astropy` and `matplotlib`. `import tools.registry` takes
about 4.5 s the first time (bytecode compilation) and 1.3 s after that.

## Install

**You may need a C compiler.** Two dependencies do not publish pre-built
wheels for every platform, and pip compiles them from source where they are
missing:

| Dependency | Pre-built wheels | Compiles from source on |
| --- | --- | --- |
| `sep` 1.4.1 | Python 3.9–3.13: Linux (x86_64, aarch64), macOS, Windows | **Python 3.14, every platform** |
| `photutils` 3.0.0 | Linux x86_64, macOS, Windows | **Linux aarch64** (ARM servers, Raspberry Pi, Docker on Apple Silicon) |

**Python 3.13 is Kepler's target** — what CI and the release workflow run,
and the newest Python every dependency ships wheels for. Python 3.12 or 3.13
on x86_64 Linux, macOS or Windows needs no compiler. Anywhere else, install
one first: `apt-get install gcc` on Debian or Ubuntu, `dnf
install gcc` on Fedora, or the Xcode command-line tools on macOS. Without one,
pip fails with `Failed building wheel for sep` (or `photutils`) and
`command 'gcc' failed`. Measured on the `v0.1.0rc1` release in a clean
`python:3.14-slim` container on aarch64.

```bash
python3.13 -m venv kepler-env
kepler-env/bin/pip install "kepler[mcp] @ https://github.com/archon774/skynet-mars/releases/download/v<version>/kepler-<version>-py3-none-any.whl"
kepler-env/bin/kepler-mcp self-test
```

`[mcp]` brings the server. Releases are listed at
<https://github.com/archon774/skynet-mars/releases>; Kepler is not on PyPI. A wheel
built with `uv build` in a checkout installs the same way. `kepler-mcp
self-test` launches the installed server as a host would and checks it end to
end; `releasing.md` describes what a release is.

## Register the server with a host

The host launches `kepler-mcp` over stdio. For Claude Code:

```json
{"mcpServers": {"kepler": {"command": "/path/to/kepler-env/bin/kepler-mcp"}}}
```

`kepler-mcp --tools databases,timeseries` (or `KEPLER_MCP_TOOLS`) serves only
those groups: `databases`, `optical`, `timeseries`, `hr`, `radio`. The default
is all 55 tools. At startup the server logs to stderr every root it resolved,
each served group, and whether each data bundle is present. The same facts
reach the model in the server's instructions.

## Where things go

Everything Kepler writes lives under one per-user directory, the **Kepler
home**: `~/.local/share/kepler` on Linux (`$XDG_DATA_HOME` honoured),
`~/Library/Application Support/kepler` on macOS, and `%LOCALAPPDATA%\kepler`
on Windows. `KEPLER_HOME` moves it. Nothing is ever written into the installed
package.

| Directory | What | Override |
| --- | --- | --- |
| `<home>/artifacts/` | every tool's output files, in per-tool subdirectories | `KEPLER_ARTIFACT_DIR` |
| `<home>/fits_downloads/` | `search_mast(download=true)` and `search_casda(download=true)` products | `KEPLER_FITS_DOWNLOAD_DIR`, or `KEPLER_DATA_DIR` (downloads then go to its `fits_downloads/`) |
| `<home>/bundles/optical/`, `<home>/bundles/isochrones/` | fetched data bundles | `KEPLER_OPTICAL_DATA_DIR`, `KEPLER_ISOCHRONE_DIR` |
| `<home>/numba-cache/` | numba's compiled-function cache, which numba would otherwise write into the installed package | `NUMBA_CACHE_DIR` |

Artifacts are never overwritten, even by two servers sharing the directory:
each name is claimed atomically, and a repeated call writes a new file with a
numeric suffix. So the directory grows; clear it yourself when you want to.
`list_artifacts` over MCP returns the newest 100 entries of a directory, and
says how many there are; a relative `directory` (`pulsar`, `vizier`) is taken
inside the artifact directory, and one that climbs out of it (`..`) is refused.

After `kepler-mcp fetch-data`, restart any running `kepler-mcp`: the server
reads its data locations when it starts.

## The optional data bundles

```bash
kepler-mcp fetch-data --list         # size and status of each
kepler-mcp fetch-data optical        # or: isochrones, all
```

Each bundle is one archive whose size and SHA-256 are pinned in the installed
package's own manifest (`tools/mcp/bundles.json`). An installed Kepler accepts
only the exact bytes it was released with. A download that fails partway
resumes from where it stopped when you run the command again. A bundle that is
already installed and verified is left alone. `--from URL_OR_DIR` (or
`KEPLER_BUNDLE_URL`) fetches from a mirror or a local directory instead.

What needs which bundle:

| Tools | Needs |
| --- | --- |
| the pulsar and variable-star chains; `list_zeropoint_references`, `load_zeropoint_reference`, `compare_zeropoint_to_reference` | nothing; core data |
| every database tool (SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS, `resolve_target`) | nothing; remote services |
| `list_optical_frames`, `resolve_optical_frame`, `list_photometry_targets`, `run_photometry_on_target` on a bundled target, `replay_field_calibration`, `calibrate_zeropoint` with `catalog_fixture` | the **optical** bundle |
| `fit_and_compare_hr_diagram`, `run_full_hr_pipeline`, `run_full_hr_pipeline_from_catalog` (the isochrone fit) | the **isochrones** bundle |
| `solve_astrometry` | astrometry.net indexes or a local UCAC catalogue, **operator-supplied** |

Without its bundle, a frame tool says so with the `bundle_not_installed`
warning, naming the command to run. An empty listing is never presented as
the answer.

## Credentials

The server runs as you, with your environment. `ADS_DEV_KEY` enables the ADS
tools (get one at <https://ui.adsabs.harvard.edu/user/settings/token>), and
`CASDA_OPAL_USERNAME` enables CASDA downloads. The server tells the model
whether `ADS_DEV_KEY` is set, never its value.

## Operator-supplied, and what that looks like

Plate solving needs astrometry.net index files (`ANET_INDEX_PATH`) or a local
UCAC catalogue (`ATLAS_CATALOG_ROOT`). They are tens of gigabytes and are
never bundled. Without them, `solve_astrometry` returns its result with a
`solver_unavailable` warning rather than failing. A frame that already has a
WCS still reports it, and every other tool is unaffected.

## Guards that hold on an install

- `solve_astrometry(write_header=true)` refuses to write into the bundled data
  and into a fetched bundle (`refusing_to_modify_fixture`). A header written
  into a bundle frame would silently break its checksum. Downloaded products
  stay writable.
- `list_optical_frames` walks a download root recursively only inside the data
  directory or the Kepler home's own `fits_downloads/`. Pointed anywhere else,
  the root is searched flat and the listing says so.
