# Architecture Documents

Foundational documents describing Kepler's package architecture, folder layout,
and design rules.

| Document | Description |
| --- | --- |
| [tool-architecture.md](tool-architecture.md) | Master package architecture: public tool layer, algorithm ownership, runtime policy, validation policy, and non-goals |
| [repository-folders.md](repository-folders.md) | Current-state folder guide — documents every source directory in the repository |

## Extraction Records

The master extraction record for every algorithm package under `algorithms/` lives at
[extraction.md](../extraction.md). It is not here because it spans multiple algorithm packages
and serves as the reference for all extraction work across the project.
