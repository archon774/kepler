# Working Documents

Plans under active development. They describe intended work, not necessarily
the current codebase. Each document states its **Status**, **Prerequisites**,
and **Unblocks**.

There is **one document per track**. Each states the problem, the architecture
that answers it, and the phased rollout that gets there — a track's design and
its action plan are the same document, and neither carries implementation code.
They are architecture and sequencing for an agent to work through; the agent
writes the code.

## Index

No track is in flight. Add a plan here when one starts.

## Landed

Every plan this folder has carried has landed. The MCP tool surface's
completion audit (2026-09-25) is in its own `Archived` block. For the others,
a completion audit on 2026-09-18 re-verified each one against `dev`: the default suite is green
(2575 passed, 44 skipped), and the asset-gated evidence — the NGC 5286 B
frames from pixels, the bounded M15 plate solve, the ATLAS backend against the
operator UCAC5 tree, the local Girardi grid — was re-run rather than taken
from the record.

| Track | Where it went | Finished |
| --- | --- | --- |
| MCP tool surface | [`../archive/mcp-tool-surface.md`](../archive/mcp-tool-surface.md); `v0.1.0rc1` published | 2026-09-25 (C9, the last phase) |
| Optical | [`../archive/optical-tools.md`](../archive/optical-tools.md) | 2026-09-16 (P8, the last phase) |
| Model | [`../archive/model-backends.md`](../archive/model-backends.md) | 2026-09-09 (phases −1–3) |
| Benchmark | [`../benchmarking/`](../benchmarking/README.md) — phases 4–5 of the model port, with its results, report and figures | 2026-09-14 (calibration gate) |
| TUI | `../tool-architecture.md` section 10.2; working document deleted, git history has it | 2026-09-18 (phase G) |

## Lifecycle

When a track's work lands:

1. Fold the durable outcome into a reference document at the top level of
   `docs/` — that is the document that stays current against the code.
2. Add an `Archived` block to the plan: when the track finished, what was
   re-verified and how, and any statement in it that the repository has since
   overtaken, marked inline where it sits rather than silently rewritten.
3. Move it to [`../archive/`](../archive/README.md) and add its row there.

A plan whose subject has its own folder — as the benchmark harness has
[`../benchmarking/`](../benchmarking/README.md) — is archived beside its
evidence instead, and `../archive/README.md` says so.

**Archiving is not the same as deleting**, which is what this rule used to say.
Git history preserves a deleted file, but only for someone who already knows it
existed and what it was called; these documents carry reasoning that no
reference document has room for. See `../archive/README.md`.

See [`../README.md`](../README.md) for how `docs/` is organized.
