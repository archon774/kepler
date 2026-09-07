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

| Track | Document | Status | Branch base | Prerequisites | Unblocks |
| --- | --- | --- | --- | --- | --- |
| Model | [model-backends.md](model-backends.md) | Approved; implementation pending | `agent/model-backends` off **`main`** | None | The headless agent engine the TUI depends on; the deferred benchmark harness |
| Optical | [optical-tools.md](optical-tools.md) | Baseline phases merged; stateless rollout pending; later broken-links phases blocked behind it | `agent/remove-processing-run-architecture` off `dev` | None outstanding — the stateless rollout's prerequisite merged as PR #47 | The remaining broken-links phases and every TUI phase |
| TUI | [tui-harness.md](tui-harness.md) | Approved; implementation pending | `agent/tui-harness` off `dev` | Model backends phases -1 to 3, and the merged stateless optical rollout | The Textual `kepler` console |

**The model track branches off `main`, not `dev`,** at the maintainer's
instruction. Every other branch here targets `dev`, which is what `CLAUDE.md`
otherwise requires. Do not retarget either one.

## Start here

**[optical-tools.md](optical-tools.md), the stateless rollout (phases S0–S6).**

Two tracks are unblocked today — model and optical — and they can run at the
same time (see below). If only one is being worked, optical is the one to pick,
because it gates strictly more: the stateless rollout unblocks both the
remaining broken-links phases *and* every TUI phase, while the model port
unblocks only the TUI. TUI work starts when the later of the two finishes, so
optical sits on more paths. It is also the only track that touches
`algorithms/` under the extraction contract, with a parity gate on every phase
and six review checkpoints — starting it early gives that review the time it
needs.

The TUI track cannot start at all until both of its prerequisites have merged.

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

## What can run in parallel

**One pairing, and nothing else: the whole model track alongside the whole
optical stateless rollout (phases S0–S6).**

They are safe to run at once because they sit on separate branches off separate
bases and their footprints are near-disjoint — `tools/llm/` and `tools/agent/`
against `algorithms/wcs|fieldcal|photometry/` and the optical tools. The one
interaction is `SYSTEM_PROMPT` moving to `tools/agent/prompt.py` in model phase
0c, and the only phase that edits it, optical Phase 5, is blocked behind the
stateless rollout anyway and carries a locate-before-editing step.

**Everything else is serial.** Within a track, phases run in the order their
document gives them, and no other pair of tracks overlaps. Two ordering hazards
are worth naming here because they are easy to get wrong:

- **Optical S0 → S6 is a single pull request**, phases as commits, and the
  branch is not merged partway through. Each removal step requires its consumers
  migrated first, so the order is a dependency rather than a convention.
- **TUI G.1 and G.2 leave CI red between them.** They merge as a stacked pair;
  G.3 follows.

## Lifecycle

When a track's work lands, fold the durable outcome into a reference document at
the top level of `docs/`, then delete the working document. Git history preserves
it. See [`../README.md`](../README.md) for how `docs/` is organized.
