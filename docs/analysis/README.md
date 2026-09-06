# Analysis

Point-in-time review and external-research output. These documents are **dated**:
each captures what a review found on a given day, not the current state of the
code. Action items from them land as `working/` plans or as code changes — not as
edits here. See [`../README.md`](../README.md) for how `docs/` is organized.

| Document | Description |
| --- | --- |
| [algorithm-remediation-plan.md](algorithm-remediation-plan.md) | Output of a four-part algorithm review (2026-08-10): a register of ~109 findings across every algorithm package, seven blockers, a finding-class taxonomy, and a proposed five-wave rollout. The finding register is the lasting reference; the rollout is a proposal, not a schedule. |
| [applicable-designs.md](applicable-designs.md) | Reads Kepler against six external astrophysics-AI-agent systems and three benchmark papers (2026-08-11) and turns the comparison into specific, file-level recommendations. The session-manifest item has since shipped in `tools.runner`. |

## Related

- [../extraction.md](../extraction.md) — the master extraction record; the analysis here leans on it heavily for extraction boundaries and preserved quirks.
- [../tool-architecture.md](../tool-architecture.md) — the tool and algorithm-package boundaries these documents operate within.
