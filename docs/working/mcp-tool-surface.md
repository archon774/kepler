# The MCP Tool Surface and the Agent Skill

**Status:** Proposal. No phase has started.
**Date:** 2026-09-18
**Prerequisites:** None architectural. Phase C2 is a stated precondition of
phase C3, from [`../analysis/applicable-designs.md`](../analysis/applicable-designs.md)
§3 and §5.
**Unblocks:** Kepler's tools become callable from a console this repository
does not own, running on a machine where **this repository is not installed**.
**Scope:** a fourth consumer of `tools/registry.py`; the result contract that
survives the caller losing access to the filesystem the tools write to; and
the skill that teaches a model which tool to reach for and which results are
silently wrong. Nothing under `algorithms/` changes. Nothing in
`tools/agent/`, `tools/llm/`, `tools/tui/` or `tools/bench/` is retired.

This document is architecture and sequencing. It contains no implementation
code. An agent working a phase reads the contracts here, then writes the code
that satisfies them.

---

## 1. Three instruments, divided by where Kepler is installed

Everything Kepler ships today assumes the caller is standing in the
repository. That assumption is load-bearing in more places than it looks, and
this track is about the case where it does not hold.

| Instrument | For | Kepler installed where the caller runs? |
| --- | --- | --- |
| `tools/tui/` — the `kepler` console | A **human** at the tools. One model, one session, artifacts rendered in place, `/backend` to switch providers, resume from a session manifest. | **Yes.** It is the entry point that proves the surface works with no third-party host installed at all. |
| `tools/bench/` — `kepler-bench` | Measuring **models** on the tool surface. It ran 144 sessions across four providers, produced [`../benchmarking/report.json`](../benchmarking/report.json), and answered its question. An instrument, not a product; dormant until a new model is worth measuring. | **Yes.** It substitutes `run_session`'s `tool_functions=` mapping and reads fixtures off local disk. |
| **This track** — the MCP servers and the skill | A **coding agent in its own console** — Claude Code, Codex, Cursor — doing astronomy work. | **No, and that is the point.** |

The first two are instruments for someone who already has this checkout. They
stay exactly as they are; this track retires neither, and the obvious
misreading — that an MCP surface replaces the loop — is wrong.

The third case is not a variant of the first two. It is the case where every
local assumption fails at once:

- The tools are not importable, so `uv run python -c "from tools.pulsar import …"`
  is not available and the skill cannot teach it as the normal path.
- **The filesystem the tools write to is not the caller's filesystem.** This is
  the deep one, and section 3.1 is about it.
- The bundled data — the five pulsar scans, the frame library, the recorded
  reference solves, ~175 MB of tracked fixtures — is wherever the *server*
  runs, not wherever the agent runs.
- The credentials (`ADS_DEV_KEY`, `CASDA_OPAL_USERNAME`) are the server's, not
  the client's.
- `SYSTEM_PROMPT` is not delivered by anything, because the loop that carries
  it is not running.

So the track has exactly two deliverables, and under this framing neither is
optional:

1. **The MCP servers** — how the tools are reached at all.
2. **The skill** — how a model knows which to reach for, in what order, and
   which results are wrong without saying so. Because the repository is not
   installed, **the skill has to travel with the servers** (section 3.4).

---

## 2. Why this is already sanctioned

Two existing documents authorise it, and this track does not re-argue them:

- [`../tool-architecture.md`](../tool-architecture.md) §7: *"Serving is
  optional. A Python caller must be able to import and call every tool without
  running a server. If a serving surface is added later, generate it from the
  same tool functions and models rather than designing the package around a
  server."*
- [`../analysis/applicable-designs.md`](../analysis/applicable-designs.md) §5
  recommends exactly this — an optional second consumer of
  `TOOL_SCHEMAS`/`TOOL_FUNCTIONS` — sequenced after §3.

§9's non-goal, *"No mandatory serving framework"*, survives: the servers are
generated from the tool functions and sit on no import path a plain Python
caller touches.

One structural property makes the whole thing cheap. *"One public tool call is
Kepler's execution boundary"* — no run, stage or session object spans two
calls, and no tool writes state another tool reads. There is nothing to bridge.
A stateful surface would have made this track a rewrite; instead it is a
translation.

---

## 3. Decisions

### 3.1 The result contract has to survive a caller who cannot read the disk

Every Kepler tool today returns the same shape: a **bounded inline preview**
plus an **artifact path**, with the full data written to a file.
`../tool-architecture.md` §7 makes it policy — *"large payloads returned as
artifacts plus summaries"* — and it is the right design when the caller shares
the filesystem.

Detach the caller and **the artifact path becomes unusable**. `search_vizier`
returns 2,000 rows to a file the agent cannot open; what actually reaches the
model is ten preview rows and a string naming a path on someone else's
machine. The preview silently becomes the entire result. `SYSTEM_PROMPT`
already warns against exactly this failure in the co-located case — *"do not
present the inline preview as if it were the whole answer"* — and detaching
the filesystem turns that warning into a structural fact.

This is the single largest thing this track has to design, and MCP already
has the mechanism: **resources**. The server publishes each artifact at a URI;
the client fetches content it wants. Concretely:

- Every `ArtifactRef` in a result carries a **resource URI** alongside the
  server-side `path`. The path stays — it is correct and useful in the
  co-located deployment, and it is what the server's own operator sees in
  logs — but it is no longer the only handle.
- Small media come back **inline** where the protocol supports it. A pulsar
  plot PNG and a sonification WAV are the whole point of those tools; a model
  that receives a path to a WAV it cannot open has not heard anything.
- Row-oriented artifacts stay fetchable rather than inlined. `PREVIEW_ROWS`
  defaults to 10 and the caps (`KEPLER_MAX_FRAMES` 200,
  `KEPLER_MAX_CATALOGS` 20, `KEPLER_MAX_OBSERVATIONS` 25) exist to keep a
  result out of a model's context; resources are what let a client ask for
  more without those caps being relaxed.

**This reverses a call made in the previous draft of this track.**
`describe_artifact` and `list_artifacts` (`tools.workspace`) were listed as
the first tools to drop, on the grounds that a coding agent has a filesystem.
Under this framing they are the opposite: with the repository not installed,
they are the **only** enumeration of server-side state a client has. They are
promoted, not dropped.

### 3.2 Configuration must be anchored to the server, not to the process's cwd

A host launches a server with a working directory the server did not choose.
Verified on `dev` at 2026-09-18, `tools/config.py` splits two ways on this:

- `DATA_DIR = env_path(DATA_DIR_ENV, _REPO_ROOT / "data").resolve()` — anchored
  to the package. Correct under any cwd.
- `ARTIFACT_DIR = (env_path(ARTIFACT_DIR_ENV, "artifacts") or Path("artifacts")).resolve()`
  — the default is the **relative** string `"artifacts"`, resolved against the
  process's working directory at import. Launch the server from elsewhere and
  artifacts land in `<wherever the host started>/artifacts`.

The module's own comment explains why it resolves at import — *"a bare
`artifacts/…` silently means something different in each of those"* — and that
reasoning applies with more force here. **The server sets
`KEPLER_ARTIFACT_DIR` explicitly at startup** and does not inherit a cwd-derived
default. The phase that lands it verifies the resolved roots from a launch
outside the repository, not by reading this paragraph.

Two related notes:

- `FITS_DOWNLOAD_DIR` is derived from `DATA_DIR` **at import**; reassigning
  `DATA_DIR` at runtime does not move it. Environment variables are the
  supported way to move them together.
- `tools/artifacts.py`'s `scoped_artifacts` is a `ContextVar` — the one piece
  of implicit state on an otherwise stateless surface. A stdio server serving
  one client sequentially is fine. **Concurrent sessions are out of scope for
  this track**; the server sets no scope, and artifacts land in the configured
  root.

### 3.3 Deployment shapes, and which one makes "not installed" true

| Shape | Transport | Who holds the data and keys | Good for |
| --- | --- | --- | --- |
| **(a) Co-located** — the host launches the server as a subprocess | stdio | The user, on their own machine | The repository *is* installed after all; a developer wiring their own console to their own checkout. The rehearsal case. |
| **(b) Detached** — the server runs where Kepler and its data live; the agent connects over the network | HTTP | An operator, server-side | **The case this track is named for.** The local pipelines work because the data is where the server is; clients hold no credentials and need no 175 MB. |
| **(c) Packaged** — installed from an index and run locally | stdio | The user, after installing | `kepler-databases` only (section 3.6). |

All three are the same server with a different transport, and (a) is how (b)
and (c) get tested. But (b) is the shape that makes the premise true, and it
is what section 3.1's resource contract and section 4's boundary exist for.

The track **builds (a) first and (b) explicitly** (phase C7). (c) is recorded
as available for the databases server and out of scope to package here.

### 3.4 The skill travels with the servers

If the repository is not installed, a skill file living at
`skills/kepler-tools/SKILL.md` in this repository is not on the client's disk
and nothing will ever read it. That single observation decides the design.

**The servers serve the skill.** MCP delivers instructions from the server to
the client at connection time, and exposes further documents as resources.
So:

- Each server's **instructions** carry the cross-tool rules that have no
  per-tool home: the pulsar stage order and PERIOD SOURCING in full, the
  identifier-form table, the sourcing discipline for literature claims, the
  `null`-not-`"None"` rule for uncapping, and — new under this framing — how
  to get at an artifact the client cannot open (section 3.1).
- Longer per-domain references are **resources** the client can read on
  demand, so the always-delivered instructions stay small.

The repository keeps a copy at `skills/kepler-tools/` for the co-located case
and for a human reading it, but that copy is **rendered from the same source**
as the served text, and a test asserts they agree. `.claude/skills/kepler-tools`
is a symlink to it; `AGENTS.md` and `CLAUDE.md` gain one pointer line each.
Those two files are about working *on* the repository, which is a different
axis and stays that way.

**Copies are forbidden.** `CLAUDE.md` already declares the shipped prompt in
`tools/agent/prompt.py` authoritative for period sourcing. A second hand-written
statement of the same rule is a drift bug waiting for the first correction that
lands in one and not the other, and here there would be three surfaces, not two.

### 3.5 What this framing removes from the plan

The previous draft carried a gated phase to migrate per-call guidance out of
`SYSTEM_PROMPT` and into the `tools/registry.py` schema descriptions, on the
grounds that a system prompt is unconditionally present while a skill is
loaded on a trigger and can fall out of context.

**Server instructions are delivered at connection time, unconditionally.**
That is the same guarantee the system prompt had. The migration is therefore
not needed for this surface, and it is **out of scope for this track** — which
is the right outcome, because it also means `report.json`'s 144 sessions stay
comparable to any future benchmark run. It remains available later as an
improvement to the console and the benchmark, on its own terms.

What does *not* go away is the reason the guidance matters. These failures are
silent: a fold at the wrong period returns a flat profile rather than an error;
a fold at a literature period is indistinguishable in shape from a measurement;
a multi-band NED table reported as single-band looks exactly like a single-band
table. `tools/agent/prompt.py` is 337 lines wrapping ~270 lines of prompt its
own docstring describes as *"confirmed live, from real transcripts and direct
API testing, not written speculatively."* That text is the most valuable thing
this track has to deliver, and phase C1 is a rehearsal of whether it works when
a model reads it as instructions rather than as a system prompt.

### 3.6 Several servers, not one, and never a dispatcher

Measured on `dev` at 2026-09-18: `json.dumps(TOOL_SCHEMAS)` over all 55 tools
is **59,170 bytes, roughly 15,000 tokens**. Most hosts load a server's tools
eagerly. Fifteen thousand tokens before any work, in a console already carrying
its own instructions and the user's own repository, is a bad neighbor.

Grouped by workflow:

| Server | Tools | Schema bytes | ≈ tokens | Deployable detached from its data? |
| --- | ---: | ---: | ---: | --- |
| `kepler-databases` — SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS, resolve | 16 | 15,397 | 3,850 | **Yes** — remote services and `httpx`. Shape (c) works. |
| `kepler-optical` — frames, WCS, photometry, field calibration, catalogs, workspace | 16 | 15,242 | 3,810 | No — the frame library and recorded solves are local files. |
| `kepler-timeseries` — the pulsar chain and the variable-star chain | 12 | 12,935 | 3,230 | No — the five bundled scans are local files. |
| `kepler-hr` — both HR-diagram entry points | 8 | 9,808 | 2,450 | Partly — the catalog-only entry point needs no local data. |
| `kepler-radio` — SED fitting and source identification | 3 | 5,788 | 1,450 | Partly. |

A user enabling one or two pays a quarter of the full surface, and the right
column is not a footnote: it decides which deployment shape each server can
take. Each server's description states it plainly rather than leaving a user
to discover that `list_pulsar_scans` enumerates the *server's* scans.

**A dispatcher is not the answer**, and this is settled ground:
[`../analysis/applicable-designs.md`](../analysis/applicable-designs.md) §2
credits Kepler for shipping one schema per database *instead of* one dispatcher
with a `database` enum — *"already a step past what Astro MCP does."*
Collapsing to `query_database(database=…, …)` to save tokens would walk that
back and discard the per-database argument validation that makes the schemas
worth having.

### 3.7 Annotations are generated from `tools/bench/plane.py`

`TOOL_CLASSES` already classifies all 55 tools as local (26), remote (22) or
mixed (7); a test asserts the plane covers the registry, and an unclassified
tool raises rather than defaulting. That is exactly the metadata an MCP surface
needs, already test-enforced.

- `openWorldHint` ← `TOOL_CLASSES[name] != "local"`.
- `readOnlyHint` ← false for tools that write outside the artifact directory —
  `solve_astrometry` writes a solved header back into a FITS file,
  `search_mast(download=true)` fetches products into the download root — true
  otherwise. Under a detached deployment both write on the **server**, which
  section 4.2 covers.
- The seven `"mixed"` entries carry `OFFLINE_PREDICATES`, which are
  per-argument and have no MCP equivalent. Section 4.1.

Read the mapping; never restate it. This makes the existing "classify in the
same commit that registers the tool" invariant load-bearing in a second place.

### 3.8 The dependency decision

The last two tracks held a hard **zero new dependencies** line.
`pyproject.toml` pins every dependency with `==`, CI runs `uv run --locked`,
and there are no optional-dependency groups today.

Two options; the phase that lands C3 picks one in its PR description:

1. **The `mcp` Python SDK, in a new `[project.optional-dependencies]` group.**
   Maintained, handles protocol evolution, and — decisive under this framing —
   brings resources, instructions and an HTTP transport rather than only the
   three methods a minimal client needs. Costs a transitive tree and a lockfile
   change; the phase must show a plain `uv sync` + `uv run --locked pytest` is
   unchanged for someone who never asks for the group.
2. **Hand-rolled stdio JSON-RPC.** `docs/archive/model-backends.md` §2.2 set
   the precedent, implementing three provider adapters over raw `httpx` rather
   than taking `litellm`. Costs owning protocol drift.

**Recommended: (1).** The model-port argument for raw HTTP was that an
abstraction library *"would hide precisely the protocol differences the
protocol-robustness grader exists to measure"* — there is no such measurement
here, so the reasoning does not transfer. And this track needs resources,
instructions and a network transport, which is well past the subset option (2)
made attractive.

---

## 4. What detaching the caller costs

Stated here so a later reader does not discover them as surprises.

### 4.1 Per-argument gating has no MCP equivalent, and detachment makes it worse

`run_session(approver=…)` can refuse a call on its **arguments**.
`tools/bench/plane.py` relies on exactly that: `DEFAULT_BLOCKED` holds
`solve_astrometry` because an all-sky solve is ~285 s against operator assets
not in this repository, and `OFFLINE_PREDICATES` decides the seven mixed tools
per call — `calibrate_zeropoint` is offline only with `catalog_fixture` *and*
`compare_to` together.

MCP host permissions are per **tool**. `search_vizier` is a fine tool with an
expensive argument (`max_catalogs=null`, which the instructions explicitly tell
a model to use for an exhaustive request). Co-located, a user can at least
watch. Detached, the cost lands on the server's operator and the remote service
the query hits, and the user who authorised the tool never sees the argument.

The track **accepts this for the co-located shape and closes it for the
detached one**: phase C7 requires server-side limits that do not depend on a
client approving anything — the existing caps are defaults a model can raise,
and a detached deployment needs a ceiling it cannot.

### 4.2 Writes land on the server

`solve_astrometry` writes a solved header back into a FITS file;
`search_mast(download=true)` writes products into the download root. Detached,
both mutate the server's disk on a client's say-so.

Two existing guards do real work here and must be understood rather than
rediscovered:

- `tools/wcs.py` refuses to write a solved header into a bundled fixture. The
  guard names four tracked subtrees (`afterglow/`, `fieldcal/`, `optical/`,
  `pulsar/`), is pinned to this repository, reads no setting, and **no
  environment variable can switch it off**. A test asserts the tuple matches
  the directories present.
- `tools/config.py`'s `within()`/`safe_resolve()` decide containment on the
  *resolved* path, which is what keeps `tools/optical.py`'s recursive walk of
  the download root from following a symlink out of the tree.

Both were written for a local caller and both hold detached. Phase C7 verifies
that rather than assuming it, and adds nothing that weakens either.

### 4.3 Third-party console sessions are unmeasured

`kepler-bench` grades trajectories by substituting `run_session`'s
`tool_functions=` mapping to replay the 22 remote tools. Under MCP the loop
belongs to the host: there is no substitution seam and no fixture replay. A
Claude Code or Codex session on this surface produces no graded trajectory, and
B2 — *nothing opens a socket under a plain `uv run pytest`* — says nothing
about it, because it is not running under pytest.

The benchmark continues to measure models through Kepler's own loop, which is
the only place it can. **This is a reason the console and the harness stay**,
not a defect in the MCP surface.

### 4.4 The heavy dependencies do not go away, they move

`numba` and `sep` are hard import-time requirements of
`algorithms/skylib_lite`, with no non-numba fallback, and `data/` is ~175 MB of
tracked fixtures. Detaching the client does not remove that weight — it relocates
it to the server, which is the point of shape (b) and the reason only
`kepler-databases` is a candidate for shape (c).

---

## 5. Rollout

Phases are **C0–C8**. C1 is deliberately first and deliberately cheap.

### Global constraints

Every phase's requirements implicitly include this section.

- **Branch:** off `dev`, per `CLAUDE.md`. One PR per phase, narrow.
- **No changes to `algorithms/`.** Do not edit any file carrying an
  `# EXTRACTED:` or `# PORTED:` marker.
- **Nothing in `tools/agent/`, `tools/tui/` or `tools/bench/` is retired or
  reshaped.** `tools/agent/prompt.py` and `tools/registry.py` are **read**, not
  edited, by every phase of this track (section 3.5).
- **`tools/registry.py` stays the single source of truth.** The servers read
  it; they do not maintain a parallel list. A test asserts the union of the
  servers' tool lists equals `{s["name"] for s in TOOL_SCHEMAS}`.
- **Default checks stay offline and deterministic.** Nothing added here may
  open a socket under a plain `uv run pytest`.
- **`tests/test_tool_registry_coverage.py` enumerates `pkgutil.iter_modules`,
  which yields packages as well as modules.** Adding `tools/mcp/` requires
  adding it to `NOT_TOOL_MODULES` in the same commit or that test fails — the
  same way `tools.llm`, `tools.agent` and `tools.bench` are listed.
- **No linter or formatter is configured.** Match the surrounding file's style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88 column soft wrap.
- **The skill has exactly one source** (section 3.4). Every other surface is
  rendered from it or points at it.
- **Never weaken a containment guard** (section 4.2) to make a deployment
  easier.

### Verification commands

```bash
uv run pytest                              # must be green; offline, no keys
python3 -m compileall tools algorithms     # syntax smoke, mirrors CI
uv sync && uv run --locked pytest          # the lockfile is unchanged for
                                           # someone who never asks for the
                                           # optional group (C3)
git diff --check                           # whitespace
```

### Phase C0 — Baseline and inventory

- [ ] Record the schema payload — total bytes, per-module breakdown, and the
      per-server grouping of section 3.6 — **in the PR description**. If it
      differs from the table above, the table is corrected to match reality,
      not the other way round.
- [ ] Confirm `TOOL_CLASSES` still covers the registry and the counts are
      26/22/7. This track reads that classification; a drifted one is a
      blocker, not a footnote.
- [ ] **Reproduce the cwd finding of section 3.2.** Import `tools.config` from
      a directory outside the repository and record the resolved `ARTIFACT_DIR`,
      `DATA_DIR` and `FITS_DOWNLOAD_DIR`. Every later phase depends on this
      being understood rather than assumed.
- [ ] Enumerate every tool whose result contains an `ArtifactRef` and classify
      it as *inline-able media* (plots, audio) or *fetch-on-demand rows*. This
      is C4's input.
- [ ] Inventory where the guidance in `SYSTEM_PROMPT` is currently restated —
      `CLAUDE.md`, `../pulsar-tool-pipeline.md`, tool docstrings — so C1 knows
      what it is consolidating rather than adding to.

**Gate:** counts, payload and resolved roots recorded and matching, or this
document corrected.

### Phase C1 — The skill, rehearsed co-located

The hypothesis test, run in the cheap configuration before any dependency is
added. It asks the question the whole track rests on: **does this guidance work
when a model reads it as instructions rather than receives it as a system
prompt?** If the answer is no, the served-instructions design of C5 has a
different shape, and it is much better to learn that now.

- [ ] Author the skill source: an entry document plus per-domain references
      (databases, pulsar, optical, HR, radio). One source, per section 3.4.
- [ ] Carry the cross-tool rules in full: the pulsar stage order, PERIOD
      SOURCING, the identifier-form table, the sourcing discipline for
      literature claims, and `null`-not-`"None"`.
- [ ] Cite `tools/agent/prompt.py` as the authority for every rule restated, by
      section name.
- [ ] Render the repository copy to `skills/kepler-tools/`;
      `.claude/skills/kepler-tools` → symlink; one pointer line each in
      `AGENTS.md` and `CLAUDE.md`.
- [ ] Add a test asserting the load-bearing invariants appear in **both**
      `SYSTEM_PROMPT` and the skill source: measure-before-compare,
      `peak_fold_snr` over `peak_confidence`, NED's formal-designation
      requirement, MPC's and ATNF's zero name resolution, `null` over `"None"`.
      Drift must fail a test, not wait for a reader.

**Gate:** a fresh agent session, given only the skill and this checkout,
completes a pulsar run end to end and **reports the period's provenance
correctly** — measured versus curated — on both a scan where the blind search
succeeds and one where it does not. Transcript in the PR description. A run
that folds at `curated_period_s` and calls it a detection fails this gate.

### Phase C2 — Close the warning and error contract

The stated precondition of C3
([`../analysis/applicable-designs.md`](../analysis/applicable-designs.md) §5:
*"do this after §3 … otherwise the MCP surface inherits the free-text
inconsistency on day one"*). Verified still open on `dev` at 2026-09-18:
`tools/models.py` has `ToolWarning.code: str` and `ToolError.code: str` both
unconstrained, and `ToolResult.warnings: list[str]` where every other model in
the same file uses `list[ToolWarning]`.

- [ ] Re-grep for the live vocabulary before changing anything. §3 found
      exactly three values — `invalid_input`, `provider_unavailable`,
      `dependency_missing` — and **records the actual counts in the PR**. If a
      fourth has appeared it is declared, not dropped.
- [ ] Promote `ToolError.code` to a `Literal` over the vocabulary grep actually
      finds.
- [ ] Change `ToolResult.warnings` to `list[ToolWarning]`, updating the one
      call site in `tools/simbad.py`.
- [ ] Do not invent codes speculatively. A new code is added when a caller
      would act on it differently.

**Gate:** `uv run pytest` green; the grep output in the PR matches the
`Literal` that landed.

### Phase C3 — The server, generated from the registry, co-located

- [ ] `tools/mcp/` — server construction from `TOOL_SCHEMAS`/`TOOL_FUNCTIONS`.
      Add `tools.mcp` to `NOT_TOOL_MODULES` in the same commit.
- [ ] Pick and justify the dependency option from section 3.8 in the PR. If
      the SDK: a new `[project.optional-dependencies]` group, and demonstrate
      that a plain `uv sync` + `uv run --locked pytest` is unchanged.
- [ ] Results serialise through the Pydantic models already returned; prefer
      structured output where the protocol supports it. C2 is what makes the
      warning and error shapes worth serialising.
- [ ] **Resolve and pin `KEPLER_ARTIFACT_DIR` and `KEPLER_DATA_DIR` at
      startup** (section 3.2). Log the resolved roots at startup; an operator
      must be able to see where artifacts are going without reading code.
- [ ] A test asserting the server's tool list equals the registry's, so a
      registry addition cannot silently miss the surface.
- [ ] `[project.scripts]` entry alongside `kepler` and `kepler-bench`.

**Gate:** a host connects over stdio **from a working directory outside this
repository**, lists tools, and completes one local call (`list_pulsar_scans`)
and one remote call against a real service. Transcript and resolved roots in
the PR. `uv run pytest` green and still socket-free.

### Phase C4 — The detached result contract

Section 3.1. The phase that makes a client without filesystem access a
first-class caller.

- [ ] Publish artifacts as resources: every `ArtifactRef` gains a URI the
      client can read, and the server-side `path` stays alongside it.
- [ ] Return small media inline — pulsar plots and sonification WAVs above all.
      A model handed a path to audio it cannot open has not heard anything.
- [ ] Keep row-oriented artifacts fetch-on-demand. `PREVIEW_ROWS` and the
      `KEPLER_MAX_*` caps are **not** relaxed to compensate; resources are the
      mechanism for wanting more.
- [ ] Promote `describe_artifact` and `list_artifacts` (section 3.1) and say in
      their descriptions that they enumerate the **server's** artifact
      directory.
- [ ] Extend the skill source: how to get at an artifact you cannot open, and
      the standing rule that a preview is a sample and never the answer.

**Gate:** a client with no filesystem access to the server retrieves a full
VizieR result set and plays back a sonification, with the transcript in the PR.
Demonstrating this against a server launched outside the repository is the
test; describing it is not.

### Phase C5 — The skill served with the servers

- [ ] Render each server's instructions from the C1 skill source; the
      always-delivered text stays small.
- [ ] Publish the per-domain references as resources the client reads on
      demand.
- [ ] A test asserting the served text and the `skills/kepler-tools/` copy are
      rendered from the same source and agree.
- [ ] Each server's instructions state its deployment reality: which data it
      reaches, that paths are server-side, and whose credentials are in use.

**Gate:** a fresh agent session against the servers alone — **no checkout, no
skill file on the client** — passes C1's gate: a pulsar run end to end with the
period's provenance reported correctly on both a scan where blind search
succeeds and one where it does not.

### Phase C6 — Split by domain, annotate from the tool plane

- [ ] Five servers per section 3.6, each its own script entry point.
- [ ] Generate `openWorldHint` and `readOnlyHint` from `TOOL_CLASSES` — read the
      mapping, never restate it.
- [ ] Each server's description states whether it is deployable detached from
      its data (section 3.6, right column).
- [ ] A test asserting every registry tool lands in exactly one server, so a new
      tool cannot be registered and orphaned from the surface.
- [ ] Record each server's measured schema payload in the PR.

**Gate:** the five payloads sum to the C0 total, and no server exceeds ~4,000
tokens.

### Phase C7 — Detached deployment and its boundary

The shape the track is named for. **Do not start without the maintainer's
go-ahead on the hosting model** — this is the first phase that puts a listening
socket in front of Kepler.

- [ ] HTTP transport for the servers that want it, with the authentication the
      chosen hosting model requires. No anonymous exposure of a server that can
      write to disk.
- [ ] **Server-side ceilings that a client cannot raise** (section 4.1). The
      existing caps are model-adjustable defaults; a detached deployment needs
      a limit above them that is the operator's, not the model's.
- [ ] Verify the containment guards hold from a detached caller (section 4.2):
      the `tools/wcs.py` fixture-write refusal, and `within()`/`safe_resolve()`
      on the download-root walk. Add a test that a detached call cannot write
      outside the configured roots.
- [ ] Credentials stay server-side and are never echoed into a result. Confirm
      against the redaction policy in `../tool-architecture.md` §7.
- [ ] Document the operator setup: which environment variables, which data must
      be present for which server, what is left unavailable when it is not.

**Gate:** a security review of the pending changes on the branch, plus a
demonstrated detached session that completes a local-data call and is refused a
write outside the configured roots.

### Phase C8 — Documentation outcome

- [ ] `../tool-architecture.md` gains a section for the MCP surface beside §10
      (agent loop), §10.1 (benchmark) and §10.2 (console) — a fourth consumer
      of one registry, with §7's "serving is optional" sentence cited as what
      authorised it, and the detached result contract stated as policy beside
      "large payloads returned as artifacts plus summaries."
- [ ] `../repository-folders.md` gains `tools/mcp/` and `skills/`.
- [ ] `CLAUDE.md` gains the dependency direction — `tools/mcp → tools/registry`,
      and **`tools/mcp/` imports nothing from `tools/agent/` or `tools/llm/`** —
      beside the existing one-way rules.
- [ ] `README.md` documents the servers, both deployment shapes, and how to
      register them with a host.
- [ ] Archive this document per `README.md`'s lifecycle.

**Gate:** `docs/` describes the shipped shape; this document carries its
`Archived` block and moves to `../archive/`.

---

## 6. Files this rollout creates and modifies

| Path | Phase |
| --- | --- |
| The skill source + `skills/kepler-tools/` rendered copy | C1 |
| `.claude/skills/kepler-tools` (symlink) | C1 |
| `tests/test_skill_invariants.py` | C1, extended C5 |
| `tools/mcp/` | C3, extended C4–C7 |
| `tests/test_mcp_surface.py` | C3, extended C4/C6 |

| Path | Change |
| --- | --- |
| `AGENTS.md`, `CLAUDE.md` | C1: one pointer line each. C8: dependency direction. |
| `tools/models.py`, `tools/simbad.py` | C2: the warning/error contract. |
| `tests/test_tool_registry_coverage.py` | C3: `tools.mcp` in `NOT_TOOL_MODULES`. |
| `pyproject.toml` | C3: optional-dependency group and a script entry. C6: four more entries. |
| `docs/tool-architecture.md`, `docs/repository-folders.md`, `README.md` | C8. |

**Deliberately not touched:** anything under `algorithms/`; `tools/tui/`;
`tools/bench/`; `tools/llm/`; `tools/agent/` — including `prompt.py` and
`tools/registry.py`, which this track reads and does not edit (section 3.5).
The CI `repository-shape` job's seven asserted paths all survive; nothing here
deletes `tools/registry.py`, `tools/agent/engine.py` or `tools/tui/app.py`.

---

## 7. Open questions for the maintainer

1. **What is the hosting model for the detached shape?** C7 cannot start
   without it. A server on the development host reachable only over a private
   network is a different design from anything publicly reachable, and the
   authentication requirement follows from the answer, not the other way round.
2. **Which servers actually get deployed detached?** `kepler-databases` is
   portable and could equally be installed locally by each user;
   `kepler-timeseries` and `kepler-optical` are the ones that genuinely need
   the server to hold the data. Deploying only those is a coherent smaller
   scope for C7.
3. **Five servers or fewer?** Section 3.6 groups by workflow. Someone who only
   wants literature search would prefer `kepler-ads` split out of
   `kepler-databases`; someone doing full optical reduction would rather have
   one server than three.
4. **Do the argument-level ceilings of C7 apply co-located too?** They close a
   real gap (section 4.1) but they also cap a human at their own console, which
   is the one caller who should not be capped.
