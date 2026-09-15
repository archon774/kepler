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
| Optical | [optical-tools.md](optical-tools.md) | Baseline and stateless phases (S0–S6) complete; P1–P7 complete; P8–P9 remain | `dev` | P8 needs three recovered NGC 5286 B frames through Git LFS; P9 needs operator UCAC data | The two asset-gated evidence gaps (NGC 5286 B from pixels, the ATLAS backend); the TUI stateless prerequisite is met |
| Benchmark | [benchmark.md](benchmark.md) · results: [benchmark-results.md](benchmark-results.md) · full report: [benchmark-report.md](benchmark-report.md) | **Built and swept** — three backends over all 16 tasks, three repeats, 144 sessions | `agent/model-benchmark` off `dev` | Model backends phases -1 to 3 (met) | The model/tool scoreboard; nothing else depends on it |
| TUI | [tui-harness.md](tui-harness.md) | Approved; implementation pending | `agent/tui-harness` off `dev` | Model backends phases -1 to 3, and the merged stateless optical rollout | The Textual `kepler` console |

**The model track was implemented on `dev`** (the maintainer redirected the
base from `main`, since `dev` carries the current plan and registry). Phases
−1–3 are done — `tools/llm/` and `tools/agent/` exist; `tools/runner.py` is a
shim over them. **The benchmark harness is the same track's second half, not a new track.**
Phases 4–5 of the model port are what [benchmark.md](benchmark.md) plans and
what `tools/bench/` now implements; `model-backends.md` section 9 deliberately
left them unplanned until the port landed and the fault taxonomy was real
rather than predicted. The two are one track in two documents —
`model-backends.md` section 6 stays the design summary, `benchmark.md` is the
architecture, the plan, and the record of what shipped. Every other branch here
targets `dev`.

Every phase of the benchmark rollout (4a–4d, 5a–5e) has landed. Eight of
`model-backends.md`'s nine security requirements are implemented and tested;
S1 is **retired** rather than satisfied — it confined the LLM judge, and the
judge was removed (`benchmark.md` §7.5).

**The calibration gate is met.** §7.1.9 makes a suite untrusted until it has
been run against at least three backends of different tiers. Three have now run
all sixteen tasks with three repeats each — `anthropic/claude-sonnet-5`,
`ollama/qwen3.8:27b-mlx` and `ollama/qwen3.5:9b`, 144 sessions. The
per-task results with figures and limits are
[benchmark-results.md](benchmark-results.md); the generated report they select
from is [benchmark-report.md](benchmark-report.md).

Two limits keep this from being a finished track. Three of the four backends
share one schema dialect, so dialect effects are not isolated; and the corpus
was authored while watching the backend that now ranks first, which no test can
fully rule out. Folding the durable outcome into a top-level `docs/` reference
and deleting both working documents should wait for a second dialect.

## Start here

**[optical-tools.md](optical-tools.md), the approved closure rollout (phases
P7–P8 remaining).**

The stateless optical boundary and its TUI prerequisite have merged. P1 landed
as PR #57, P2/P3 together as PR #59, P4 as PR #60, P5 as PR #62, P6 as PR #63
and P7 as PR #64, so every phase that needed only the repository is done. What
remains needs assets the repository does not carry: P8 the three NGC 5286 B
frames, P9 an operator UCAC tree. The model and TUI tracks retain their own
prerequisites; the phase table in `optical-tools.md` states the coordination
constraints.

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
