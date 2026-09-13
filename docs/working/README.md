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
| Optical | [optical-tools.md](optical-tools.md) | Baseline and stateless phases (S0–S6), P1–P6, and P9 complete; P7–P8 remain | `dev` | P7 needs a recorded full APASS response; P8 needs three recovered NGC 5286 B frames through Git LFS | Remaining local-data and end-to-end field-calibration gaps; the TUI stateless prerequisite is met |
| TUI | [tui-harness.md](tui-harness.md) | Approved; implementation pending | `agent/tui-harness` off `dev` | Model backends phases -1 to 3, and the merged stateless optical rollout | The Textual `kepler` console |

**The model track was implemented on `dev`** (the maintainer redirected the
base from `main`, since `dev` carries the current plan and registry). Phases
−1–3 are done — `tools/llm/` and `tools/agent/` exist; `tools/runner.py` is a
shim over them. The remaining model work is the deferred benchmark harness
(phases 4–5). Every other branch here targets `dev`.

## Start here

**[optical-tools.md](optical-tools.md), the approved closure rollout (phases
P7–P8 remaining).**

The stateless optical boundary and its TUI prerequisite have merged. P1 landed
as PR #57 and P2/P3 together as PR #59, so the documentation reconciliation is
done and no closure phase now blocks another on reference-document conflicts.
The model and TUI tracks retain their own prerequisites. Within the optical
track, start with any P-phase whose files and assets do not overlap with active
work; the phase table in `optical-tools.md` states the coordination constraints.

## Implementation Sequence

1. **The model port can proceed now**, independently. Its phases -1 to 3 build
   `tools/llm/` and the headless engine in `tools/agent/`.
2. **Optical P7–P8 close the remaining broken links.** P1 (pulsar periods),
   P2/P3 (archive loop and documentation reconciliation), P4 (variable-star
   port), P5 (local-grid HR diagram), P6 (WCS controls), and P9 (ATLAS
   validation) have landed. P7 (APASS replay) and P8 (B-frame evidence) remain
   independent at the code level.
3. **The TUI stateless prerequisite is satisfied.** TUI phase A remains owned
   by the model document; TUI phase C may proceed once its model prerequisites
   are complete.

## What can run in parallel

Optical closure phases may run in parallel when their modified files and asset
gates do not overlap. The P2/P3 constraint is discharged — both changed the
reference documents, so they were coordinated into one PR rather than landed
serially. P1's system-prompt edit likewise landed against
`tools/agent/prompt.py`, where model phase 0c moved it.

- **TUI G.1 and G.2 leave CI red between them.** They merge as a stacked pair;
  G.3 follows.

## Lifecycle

When a track's work lands, fold the durable outcome into a reference document at
the top level of `docs/`, then delete the working document. Git history preserves
it. See [`../README.md`](../README.md) for how `docs/` is organized.
