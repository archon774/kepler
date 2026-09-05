# Research Documents

Analysis, planning, and domain-specific studies that inform Kepler's development.

| Document | Description |
| --- | --- |
| [algorithm-remediation-plan.md](algorithm-remediation-plan.md) | Four-part algorithm review output: 109 actionable findings, 7 blockers, and a five-wave rollout plan for bug fixes with targeted tests |
| [applicable-designs.md](applicable-designs.md) | Cross-referenced analysis of six external astrophysics-AI-agent systems and three benchmark papers; lists specific file-level changes applicable to Kepler |
| [pulsar-tool-pipeline.md](pulsar-tool-pipeline.md) | Architecture for the four-stage pulsar pipeline (light curve → periodogram → folding → sonification), including extracted Astromancer provenance, result contracts, and known issues |

## Related Documents

- [extraction.md](../extraction.md) — Master extraction record for all `algorithms/` packages. The research docs above reference it heavily; it is the source of truth for extraction boundaries and preserved quirks.
- [tool-architecture.md](../architecture/tool-architecture.md) — Defines tool and algorithm package boundaries that these research documents operate within.
