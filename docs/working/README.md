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

Grouped by what has to have landed first. Everything in a group is concurrent
with everything else in it.

**Nothing landed yet — start both now:**

| Concurrent | Why it is safe |
| --- | --- |
| The whole **model** track ‖ the whole **optical** stateless rollout (S0–S6) | Separate branches off separate bases, and near-disjoint footprints: `tools/llm/` and `tools/agent/` against `algorithms/wcs\|fieldcal\|photometry/` and the optical tools. The one interaction is `SYSTEM_PROMPT` moving to `tools/agent/prompt.py` in model phase 0c — and the only phase that edits it, optical Phase 5, is blocked behind the stateless rollout anyway and carries a locate-before-editing step. |
| Model **phase -1** ‖ anything at all | It touches `.gitleaks.toml` and nothing else. Ship it first and alone; it fixes an already-misconfigured control. |

**After model phase 2a lands:**

| Concurrent | Caveat |
| --- | --- |
| Model **phase 2b** (Ollama) ‖ model **phase 3** (Gemini) | Both are built on the shared HTTP base that 2a introduces, and they own different adapter modules. Both register a provider in `factory.py` and add a key name to `.gitleaks.toml`, so expect two small conflicts. |

**After the stateless optical rollout merges:**

| Concurrent | Caveat |
| --- | --- |
| Optical **Phase 5** (curated pulsar periods) ‖ optical **Phase 6** (archive loop and docs) | Disjoint but for `tools/models.py`, where they add fields to different models — `PulsarScan` and `OpticalFrameList`. |
| TUI **Phase C** (photometry-pipeline rename) ‖ the rest of the model track | Phase C is independent of TUI phases A and B and of the model port entirely; it ships first among the TUI PRs while the port is still in progress. |

**After TUI phase D.1 lands:**

| Concurrent | Caveat |
| --- | --- |
| TUI **Phase E** (artifact rendering) ‖ TUI **Phase F** (session browser and resume) | Separate render and widget modules; both add a modal and a keybinding to `app.py`. |

**Deliberately serial — do not parallelize:**

- **Optical S0 → S6.** One pull request, phases as commits, and the branch is
  not merged partway through. Each removal step requires its consumers migrated
  first, so the order is a dependency.
- **Model 1a then 1b.** Both follow phase 0c and both edit `tools/runner.py`.
- **TUI G.1 then G.2.** CI is red between them; they merge as a stacked pair.
  G.3 follows.

## Lifecycle

When a track's work lands, fold the durable outcome into a reference document at
the top level of `docs/`, then delete the working document. Git history preserves
it. See [`../README.md`](../README.md) for how `docs/` is organized.
