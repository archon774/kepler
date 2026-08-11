# Contributing

Kepler is early-stage astronomy tooling. Keep pull requests narrow and target
`dev` unless a maintainer asks for a different base branch.

## Pull Requests

- Separate documentation, workflow, dependency, and behavior changes when practical.
- Do not commit API keys, local environment files, downloaded FITS products,
  archive dumps, generated plots, caches, or large astronomy datasets.
- Keep remote astronomy service calls out of default checks unless they are
  explicitly gated as live tests.
- Include provenance and bounded-output considerations when changing tool
  behavior.

## Local Checks

Run the smallest relevant checks before opening a PR:

```bash
python3 -m compileall kepler catalogs
git diff --check
```

As the package structure grows, replace these smoke checks with package install,
lint, type-check, and unit-test commands.

## Code Ownership

`.github/CODEOWNERS` marks the repository as maintainer-owned. Branch rules
should require Code Owner review for changes to `main`.
