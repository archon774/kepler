# Record Stateless Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the optical-tools working document to record the merged S0–S6 rollout accurately and distinguish it from the remaining optical work.

**Architecture:** Keep `docs/working/optical-tools.md` as the source of truth for rollout sequencing. Add a concise merged-outcome record and update the status metadata and S0–S6 task markers without changing the later broken-links roadmap or historical provenance.

**Tech Stack:** Markdown and GitHub PR metadata.

**Spec:** `docs/working/optical-tools.md` section 3 and phases S0–S6; merged PR #52.

## Global Constraints

- Documentation-only follow-up; do not change executable code, tests, or numerical-kernel files.
- State only evidence supported by merged PR #52 and its CI/validation record.
- Preserve historical context and leave the remaining broken-links roadmap intact.
- Target `dev` with a focused PR.

---

### Task 1: Record the merged rollout

**Files:**
- Modify: `docs/working/optical-tools.md`

**Interfaces:**
- Consumes: merged PR #52, phases S0–S6, and the existing remaining-phase dependency notes.
- Produces: accurate status metadata, checked S0–S6 outcomes, and an explicit list of work that remains after the rollout.

- [ ] **Step 1: Verify the merged PR and current document state**

Run: `gh pr view 52 --json state,mergedAt,mergeCommit,url` and inspect the status block plus phases S0–S6 in `docs/working/optical-tools.md`.

Expected: PR #52 is merged into `dev`; the working document still calls the rollout pending and leaves its completed phase tasks unchecked.

- [ ] **Step 2: Update status and rollout outcome prose**

Replace the pending branch/status language with merged PR #52 information. Add a short outcome section that names the delivered stateless boundaries and says later broken-links phases are unblocked, while retaining their own independent scope.

- [ ] **Step 3: Mark completed rollout work and state any remaining validation caveat**

Convert S0–S6 actions delivered by PR #52 to checked items. Preserve the optional solver/network qualification and identify CI as the authoritative full-suite gate rather than claiming unavailable local optional checks ran.

- [ ] **Step 4: Verify the document diff**

Run: `git diff --check` and inspect `git diff -- docs/working/optical-tools.md`.

Expected: only rollout status, completion record, and S0–S6 tracking change; later roadmap phases remain intact.

- [ ] **Step 5: Commit the documentation update**

Run: `git add docs/working/optical-tools.md docs/superpowers/plans/2026-09-09-record-stateless-rollout.md && git commit -m "docs: record stateless rollout completion"`.

