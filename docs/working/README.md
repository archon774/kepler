# Working Documents

Plans under active development. They describe intended work, not necessarily the
current codebase. Each document states its **Status**, **Prerequisites**, and
**Unblocks**. A prerequisite marked *satisfied* is retained as provenance; every
other prerequisite must land on `dev` before the dependent implementation starts.

## Plan Index

| Track | Document | Status | Prerequisites | Unblocks |
| --- | --- | --- | --- | --- |
| Model | [model-backends-and-benchmarking.md](model-backends-and-benchmarking.md) | Approved design | None | Model-port implementation and future benchmarking plan |
| Model | [model-port-plan.md](model-port-plan.md) | Approved, implementation pending | Model-backends design | TUI agent engine |
| Optical baseline | [broken-links-remediation-plan.md](broken-links-remediation-plan.md) | Phases 1-4 merged; later phases pending | Stateless optical rollout before remaining work | Local-data tool surface and optical refactor baseline |
| Optical prerequisite | [stateless-optical-tools-architecture.md](stateless-optical-tools-architecture.md) | Approved design | Broken-links Phase 4, satisfied by PR #47 | Stateless rollout |
| Optical prerequisite | [stateless-optical-tools-rollout-plan.md](stateless-optical-tools-rollout-plan.md) | Approved, implementation pending | Broken-links Phase 4, satisfied by PR #47 | Remaining broken-links work and all TUI phases |
| TUI | [tui-harness-design.md](tui-harness-design.md) | Approved design | Model port and stateless optical rollout | TUI implementation plan |
| TUI | [tui-harness-plan.md](tui-harness-plan.md) | Approved, implementation pending | Model port and stateless optical rollout | Textual `kepler` console |

## Implementation Sequence

1. The model port can proceed from its approved design independently.
2. The merged broken-links Phases 1-4 form the optical baseline. Implement and
   merge the stateless optical rollout next.
3. Once the stateless rollout merges, begin the remaining broken-links work and
   any TUI phase. TUI implementation also requires the model port.

The stateless optical documents are deliberately separate from the TUI and
broken-links documents. They preserve the extracted algorithms while removing
the old Skynet batch wrapper. Their rollout must merge before subsequent
broken-links work or any TUI phase begins, so later work never has to support
both processing-run and stateless tool boundaries.

When a plan's work lands, fold the durable outcome into a reference document at
the top level of `docs/`, then delete the plan. Git history preserves completed
plans. See [`../README.md`](../README.md) for how `docs/` is organized.
