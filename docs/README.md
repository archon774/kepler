# Kepler Documentation

The top level of `docs/` holds the **reference documents** — the ones that
describe how Kepler is built and how it works. They track the code and are
updated when the code changes.

| Document | What it covers |
| --- | --- |
| [tool-architecture.md](tool-architecture.md) | The master package architecture: the public tool layer, algorithm-package ownership, shared models and artifacts, `skylib_lite` consolidation, runtime and validation policy, and the non-goals. |
| [extraction.md](extraction.md) | The master extraction record: one section per algorithm package, with exact upstream provenance (source path, line ranges, per-file diff fidelity), every severed dependency, the preserved parity quirks, and the verification actually performed. |
| [repository-folders.md](repository-folders.md) | A current-state guide to every source folder in the repository — responsibilities, important files, and caveats. |
| [pulsar-tool-pipeline.md](pulsar-tool-pipeline.md) | The four-stage pulsar tool chain (light curve → periodogram → fold → sonify): why the stage order is a dependency, each stage's extracted Astromancer provenance, result contracts, and where output goes. |

## Subdirectories

| Directory | Contents |
| --- | --- |
| [`analysis/`](analysis/README.md) | Point-in-time review and external-research output. Dated. Kept for the "why"; the action items land elsewhere as plans or code. |
| [`working/`](working/README.md) | Plans under active development, one per file. |
| [`examples/`](examples/README.md) | Committed sample output — the deliberate exception to the repository's "no generated files" rule. |

## Document lifecycle

- **Reference docs** (`docs/*.md`) describe the system as it is. Update them in
  the same change that alters the behaviour they describe.
- **`analysis/`** documents are snapshots. They are not kept current against the
  code; they record what a review found on a given date. Trim or delete one when
  it has been fully superseded.
- **`working/`** holds plans that are being executed. When a plan's work lands,
  fold the durable outcome into a reference doc and delete the plan — git history
  preserves it. Completed plans are not meant to accumulate.
- **`examples/`** output is regenerated deliberately and rarely; see that
  directory's README before adding to it.
