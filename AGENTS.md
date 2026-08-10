# Repository Guidelines

## Project Structure & Module Organization

Kepler is an early-stage astronomy tooling workspace with independent extracted modules. Python source lives in `wcs/`, `photometry/`, and `fieldcal/`, each with an `EXTRACTION.md` describing provenance, dependencies, and parity notes. Framework-free TypeScript algorithms live in `lightcurve/`, `periodogram/`, and `hrdiagram/`; these currently have no `package.json` or `tsconfig.json`. Root files include `database_tools.py`, `pyproject.toml`, `uv.lock`, `README.md`, `CONTRIBUTING.md`, and planning docs under `docs/`.

## Build, Test, and Development Commands

- `uv sync`: create/update the Python 3.12 environment from `pyproject.toml` and `uv.lock`.
- `uv run kepler-database-tool`: run the packaged database prototype entry point.
- `python3 -m py_compile database_tools.py`: current CI syntax smoke test.
- `git diff --check`: catch trailing whitespace and patch formatting issues before review.

End-to-end WCS, photometry, and field calibration runs require external FITS data, native astronomy dependencies, solver binaries, and local catalog data documented in each module's `EXTRACTION.md`.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and keep public interfaces typed where practical. Preserve existing Pydantic model patterns in `schemas.py` files and keep extracted legacy behavior unless a change intentionally diverges. Use 2-space indentation in TypeScript and keep modules framework-free; avoid reintroducing Angular, RxJS, Highcharts, or browser-only code unless the target package requires it. Prefer clear snake_case for Python files/functions and kebab-case or domain-qualified names already used by TypeScript files, such as `variable-lightcurve.algorithms.ts`.

## Testing Guidelines

There is no dedicated test suite yet. Run the lightweight checks above for every change and add the smallest relevant smoke check when touching executable paths. Keep live remote astronomy service calls gated and deterministic by default. Do not rely on downloaded catalogs, FITS products, generated plots, or caches as committed fixtures.

## Commit & Pull Request Guidelines

Recent history uses short, imperative commit subjects such as `Use uv for dependency management` and `Document repository folder layout`, with merge commits from focused branches. Keep PRs narrow and target `dev` unless maintainers request another base. Fill out the PR template with `Summary`, `Validation`, and `Notes`; include linked issues, reviewer context, and screenshots only when relevant.

## Security & Configuration Tips

Never commit API keys, local environment files, large astronomy datasets, archive dumps, or generated artifacts. `ADS_DEV_KEY` and `ANTHROPIC_API_KEY` are required only for the relevant database prototype paths. Workflow changes should remain narrow and pass the secret-scan and workflow-safety jobs.
