# Working Documents

Plans under active development. They describe intended work, not necessarily the
current codebase. Each document states its **Status**, **Prerequisites**, and
**Unblocks**.

There is **one document per track**. Each states the problem, the architecture
that answers it, and the phased rollout that gets there — a track's design and
its action plan are the same document, and neither carries implementation code.
They are architecture and sequencing for an agent to work through; the agent
writes the code.

## Index

| Track | Document | Status | Prerequisites | Unblocks |
| --- | --- | --- | --- | --- |
| Model | [model-backends.md](model-backends.md) | Approved; implementation pending | None | The headless agent engine the TUI depends on; the deferred benchmark harness |
| Optical | [optical-tools.md](optical-tools.md) | Baseline phases merged; stateless rollout pending; later broken-links phases blocked behind it | None outstanding — the stateless rollout's prerequisite merged as PR #47 | The remaining broken-links phases and every TUI phase |
| TUI | [tui-harness.md](tui-harness.md) | Approved; implementation pending | Model backends phases -1 to 3, and the merged stateless optical rollout | The Textual `kepler` console |

## Implementation Sequence

1. **The model port can proceed now**, independently. Its phases -1 to 3 build
   `tools/llm/` and the headless engine in `tools/agent/`.
2. **The stateless optical rollout is the next optical step.** The merged
   broken-links phases 1–4 are its baseline. It must merge before the remaining
   broken-links phases or any TUI phase begins, so later work never has to
   support both the processing-run and the stateless tool boundary.
3. **Once the stateless rollout merges**, the remaining broken-links phases and
   the TUI phases are unblocked. TUI phase A is owned by the model document;
   TUI phase C additionally requires the stateless rollout.

## Lifecycle

When a track's work lands, fold the durable outcome into a reference document at
the top level of `docs/`, then delete the working document. Git history preserves
it. See [`../README.md`](../README.md) for how `docs/` is organized.
