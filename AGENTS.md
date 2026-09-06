# Repository Guidelines

## Project Structure & Module Organization

Kepler is a staging area for extracted astronomy algorithms. Public Python tools live in `tools/`, including one thin tool per astronomy database/archive (SIMBAD, NED, VizieR, ATNF, ADS, MAST, MPC, CASDA) plus local pipelines (photometry, pulsar, HR-diagram, radio sources). Extracted/ported Python algorithms live in `algorithms/wcs/`, `algorithms/photometry/`, `algorithms/fieldcal/`, `algorithms/catalogs/`, `algorithms/query/`, `algorithms/skylib_lite/` (a shared vendored Skylib subset), `algorithms/pulsar/` (a TypeScript port), `algorithms/hrdiagram_py/` (a TypeScript port plus a new optimizer), and `algorithms/radio/` (new first-party capability, no upstream equivalent). Framework-free TypeScript algorithms live in `algorithms/lightcurve/`, `algorithms/periodogram/`, and `algorithms/hrdiagram/`; these have a root `package.json`/`tsconfig.json` for `tsc --noEmit` typechecking only — no build, bundle, test step, or runtime. Provenance, dependencies, and parity notes are consolidated in `docs/extraction.md` (one section per domain) rather than per-folder `EXTRACTION.md` files, which no longer exist. Documentation is organized under `docs/`: reference documents at the top level, point-in-time reviews in `docs/analysis/`, and active plans in `docs/working/`; `docs/README.md` is the map. Root files include `pyproject.toml`, `uv.lock`, `README.md`, and `CONTRIBUTING.md`.

## Build, Test, and Development Commands

- `uv sync`: create/update the Python 3.12 environment from `pyproject.toml` and `uv.lock`.
- `uv run pytest`: the test suite (see Testing Guidelines below) — no network access by default.
- `uv run kepler-astro-query "<question>"`: run the optional agentic loop over the `tools` schemas (requires `ANTHROPIC_API_KEY`).
- `python3 -m compileall tools algorithms`: syntax smoke test.
- `npm run typecheck`: `tsc --noEmit` over the TypeScript algorithm folders (not a CI job; run by hand when touching a `.ts` file).
- `git diff --check`: catch trailing whitespace and patch formatting issues before review.

CI (`.github/workflows/ci.yml`) gates `compileall`, `uv run --locked pytest`, and a `repository-shape` check. `secret-scan.yml` and `workflow-safety.yml` run separately.

End-to-end WCS, photometry, and field calibration runs require external FITS data, native astronomy dependencies, solver binaries, and local catalog data — see `docs/extraction.md` for what's documented per domain.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and keep public interfaces typed where practical. Preserve existing Pydantic model patterns in `schemas.py` files and keep extracted legacy behavior unless a change intentionally diverges. Use 2-space indentation in TypeScript and keep modules framework-free; avoid reintroducing Angular, RxJS, Highcharts, or browser-only code unless the target package requires it. Prefer clear snake_case for Python files/functions and kebab-case or domain-qualified names already used by TypeScript files, such as `variable-lightcurve.algorithms.ts`.

## Testing Guidelines

`tests/` holds the suite (see `tests/README.md` for full coverage notes and
gaps). It is algorithm-preservation testing, not general correctness
testing: it pins bit-exact parity against recorded upstream output and pins
known bugs rather than fixing them. Markers: `network` (needs
`KEPLER_TEST_NETWORK=1`, never runs by default), `slow` (real-frame source
extraction/photometry, included by default), `solver_data` (needs
astrometry.net indexes or a local UCAC tree, self-skips when absent). Add the
smallest relevant test when touching an executable path. Keep live remote
astronomy service calls gated and deterministic by default. Do not rely on
downloaded catalogs, FITS products, generated plots, or caches as committed
fixtures.

## Commit & Pull Request Guidelines

Recent history uses short, imperative commit subjects such as `Use uv for dependency management` and `Document repository folder layout`, with merge commits from focused branches. Keep PRs narrow and target `dev` unless maintainers request another base. Fill out the PR template with `Summary`, `Validation`, and `Notes`; include linked issues, reviewer context, and screenshots only when relevant.

## Security & Configuration Tips

Never commit API keys, local environment files, large astronomy datasets, archive dumps, or generated artifacts. `ANTHROPIC_API_KEY` is required only for `tools.runner`'s optional agentic loop; `ADS_DEV_KEY` is required for `tools.ads` (literature search and reviews) — get one from https://ui.adsabs.harvard.edu/user/settings/token. Workflow changes should remain narrow and pass the secret-scan and workflow-safety jobs.
