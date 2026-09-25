# Releasing Kepler

How a Kepler release is cut, what its version means, and how the optional data
bundles are published and matched to it. The workflow is
`.github/workflows/release.yml`. Installing a release is `installing.md`.

## Versions and tags

- **`pyproject.toml`'s `version` is the version.** A release is the tag
  `v<version>`, exactly: `v0.1.0rc1` for `0.1.0rc1`. The workflow refuses a
  tag that does not match, so a wheel never carries a version its tag
  contradicts.
- **A pre-release** is a [PEP 440](https://peps.python.org/pep-0440/)
  pre-release version: `aN`, `bN`, `rcN` or `.devN`. It is published as a
  GitHub pre-release, for testing — no compatibility promise between one and
  the next. Anything else is published as a release and marked latest.
- **Bump the version, relock, merge, then tag.** Change `version`, run
  `uv lock` (the lockfile records the project's own version), merge that
  change, and push the tag at the merged commit.

## What the workflow does

On a `v*` tag push (or `workflow_dispatch`, which runs everything except
`publish`, as a dry run):

1. **build**:
   - checks the tag against the version;
   - rebuilds `data/optical/` and fails unless it matches `tools/mcp/bundles.json`;
   - builds the wheel and the sdist, and writes `SHA256SUMS`.
2. **verify** runs on a clean runner **with no checkout**, on Python 3.12 (the
   floor) and 3.13, the newest Python every dependency ships wheels for. It
   installs the wheel with `[mcp]` and runs
   `kepler-mcp self-test`. That launches the installed server over stdio and
   detects B0329+54 from a measured period through the protocol.
3. **data** checks that the `data` release holds every archive
   `bundles.json` pins, at the pinned size and SHA-256. It reads GitHub's own
   asset digest.
4. **publish** creates the GitHub release with the wheel, the sdist and
   `SHA256SUMS`, only after **verify** and **data** pass. It is the only job
   with write permission, and only on a tag.

`secret-scan.yml` and `workflow-safety.yml` (actionlint, zizmor) run on the
pull request that changes any workflow, this one included.

## The data release

The two optional bundles are too large for a wheel. They are assets of one
standing GitHub release tagged **`data`**:

| Bundle | Source | Archive |
| --- | --- | --- |
| `optical` | `data/optical/` in this repository (Git LFS pulled) | `kepler-optical-<sha12>.tar` |
| `isochrones` | the operator's Girardi grid, `.npy` files only | `kepler-isochrones-<sha12>.tar` |

**A bundle's version is its content.** Archives are deterministic plain
`.tar` (sorted members, fixed mode, owner and mtime), named by the first 12
hex digits of their SHA-256. The same tree always builds the same file and the
same name.

**A wheel pins its bundles.** `tools/mcp/bundles.json` ships inside the wheel
and records each archive's name, size and SHA-256. `kepler-mcp fetch-data`
downloads that exact archive from the `data` release and rejects any other
bytes. That is how an installed Kepler resolves "which bundle matches me",
with no version negotiation. Old archives stay on the `data` release, so an
older wheel keeps fetching the bundle it was built with.

**Changing a bundle:**

```bash
python -m tools.mcp.bundles optical data/optical dist/bundles
python -m tools.mcp.bundles isochrones /path/to/girardi dist/bundles --include '*.npy'
```

Each prints its manifest entry. Then:

1. Paste the entry into `bundles.json`, with `url` set to
   `https://github.com/archon774/kepler/releases/download/data/<archive>`.
2. Upload the archive: `gh release upload data dist/bundles/<archive>`.
3. Ship the manifest change in the next release.

Never replace an existing asset: a published name always means the same
bytes. `--check` on the build command fails unless the build is exactly the
shipped entry. The workflow runs it for `optical`; `isochrones` is built from
outside the repository, so run it by hand.

## Testing a release

On a machine with no checkout (and a C compiler unless it is Python 3.12 or
3.13 on x86_64 Linux, macOS or Windows; see `installing.md`):

```bash
python3.13 -m venv kepler-env
kepler-env/bin/pip install "kepler[mcp] @ https://github.com/archon774/kepler/releases/download/v<version>/kepler-<version>-py3-none-any.whl"
kepler-env/bin/kepler-mcp self-test
kepler-env/bin/kepler-mcp fetch-data optical      # optional
```

Then register `kepler-env/bin/kepler-mcp` with a host (`installing.md`) and
run a pulsar task through it.
