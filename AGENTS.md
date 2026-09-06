# Repository Guidelines

## Project Structure & Module Organization

Kepler is an early-stage astronomy tooling workspace with independent extracted modules. Public Python tools live in `tools/`, including one thin tool per astronomy database/archive (SIMBAD, NED, VizieR, ATNF, ADS, MAST, MPC, CASDA). Extracted Python algorithms live in `algorithms/wcs/`, `algorithms/photometry/`, `algorithms/fieldcal/`, `algorithms/catalogs/`, and `algorithms/query/`, with provenance, dependencies, and parity notes recorded per package in `docs/extraction.md`. Framework-free TypeScript algorithms live in `algorithms/lightcurve/`, `algorithms/periodogram/`, and `algorithms/hrdiagram/`. Root files include `pyproject.toml`, `uv.lock`, `README.md`, `CONTRIBUTING.md`, and documentation under `docs/` — reference docs (`tool-architecture.md`, `extraction.md`, `repository-folders.md`, `pulsar-tool-pipeline.md`) at the top level, `docs/analysis/` for review output, `docs/working/` for in-progress plans; `docs/README.md` is the map.

## Build, Test, and Development Commands

- `uv sync`: create/update the Python 3.12 environment from `pyproject.toml` and `uv.lock`.
- `uv run kepler-astro-query "<question>"`: run the optional agentic loop over the `tools` schemas (requires `ANTHROPIC_API_KEY`).
- `python3 -m compileall tools algorithms`: current CI syntax smoke test.
- `git diff --check`: catch trailing whitespace and patch formatting issues before review.

End-to-end WCS, photometry, and field calibration runs require external FITS data, native astronomy dependencies, solver binaries, and local catalog data documented per package in `docs/extraction.md`.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and keep public interfaces typed where practical. Preserve existing Pydantic model patterns in `schemas.py` files and keep extracted legacy behavior unless a change intentionally diverges. Use 2-space indentation in TypeScript and keep modules framework-free; avoid reintroducing Angular, RxJS, Highcharts, or browser-only code unless the target package requires it. Prefer clear snake_case for Python files/functions and kebab-case or domain-qualified names already used by TypeScript files, such as `variable-lightcurve.algorithms.ts`.

## Testing Guidelines

There is no dedicated test suite yet. Run the lightweight checks above for every change and add the smallest relevant smoke check when touching executable paths. Keep live remote astronomy service calls gated and deterministic by default. Do not rely on downloaded catalogs, FITS products, generated plots, or caches as committed fixtures.

## Commit & Pull Request Guidelines

Recent history uses short, imperative commit subjects such as `Use uv for dependency management` and `Document repository folder layout`, with merge commits from focused branches. Keep PRs narrow and target `dev` unless maintainers request another base. Fill out the PR template with `Summary`, `Validation`, and `Notes`; include linked issues, reviewer context, and screenshots only when relevant.

## Security & Configuration Tips

Never commit API keys, local environment files, large astronomy datasets, archive dumps, or generated artifacts. `ANTHROPIC_API_KEY` is required only for `tools.runner`'s optional agentic loop; `ADS_DEV_KEY` is required for `tools.ads` (literature search and reviews) — get one from https://ui.adsabs.harvard.edu/user/settings/token. Workflow changes should remain narrow and pass the secret-scan and workflow-safety jobs.
