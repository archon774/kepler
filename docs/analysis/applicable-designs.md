# External Astro-Agent Design Practice Applied to Kepler

Date: 2026-08-11
Status: proposal, with the session-manifest item implemented in `tools.runner`

This document reads Kepler's current architecture (`docs/tool-architecture.md`, `CLAUDE.md`,
`tools/`, `algorithms/`) against how six external astrophysics-AI-agent systems and three
benchmark/study papers are built, and lists what is directly applicable. It is not a survey —
it exists to turn outside practice into specific, file-level changes, or to explicitly say
where Kepler already does the thing and no change is needed.

Every claim about Kepler below was checked against the current repository state on
2026-08-11, not against the original 2026-08-10 design-only migration plan. Some
things the original design intended have since shipped differently than planned —
that is noted where it matters.

---

## 1. Sources

External research (astrophysics-agent tooling, researched 2026-08-11):

- **Kosmos** (Mitchener et al., arXiv:2511.02824) — general-purpose long-horizon AI scientist;
  a structured world model shared between a data-analysis agent and a literature-search agent
  is what lets it stay coherent over 12-hour, 200-rollout sessions.
- **ASTER** (Panek et al., arXiv:2603.26953) — exoplanet-atmosphere agent toolkit on the
  Orchestral AI framework; explicit, inspectable, provider-agnostic control flow as a direct
  reaction against opaque autonomous loops.
- **Cmbagent** (Laverick et al., arXiv:2412.00431 + arXiv:2604.09621) — multi-agent cosmology
  pipeline-builder; its fully autonomous run lost to expert humans on the FAIR Universe
  Challenge, a human-guided run won it.
- **StarWhisper Telescope** (Wang et al., arXiv:2412.06412) — LLM-agent framework running live
  on a 10-telescope network; the only source with real hardware and 10 months of production
  iteration behind it.
- **Astro MCP** (`github.com/SandyYuan/astro_mcp`) — MCP server unifying `astroquery`-backed
  access to 40+ astronomical databases behind a small set of high-level tools.
- **Astronomy AI Toolkit** (`github.com/rudrathegreat/Astronomy-AI-Toolkit`) — composes
  existing third-party MCP servers (ads, arxiv, astronomy-catalogs, jupyter) into a
  Claude-Code-targeted research-copilot skill, rather than building a new server.
- **ResearchBench** and **ReplicationBench** (ICML 2025 ML4ASTRO workshop; arXiv:2510.24591) —
  two independently built benchmarks that both put frontier agents under ~20% on end-to-end
  astrophysics research tasks, both attributing the gap to multi-step *integration* failure,
  not any single missing tool.
- **AI Cosplaying as Astrophysicists** (arXiv:2603.29039) — 12,960-episode synthetic study:
  no AI-assistance style universally beats unassisted work; confidently-wrong output on
  derivation-heavy physics is the worst failure mode, and verifying agent output is itself
  real labor.
- **Stargazer** (arXiv:2604.15664) — model-fitting benchmark; agents can produce a
  statistically good fit that recovers the *wrong physical parameters* — a distinct failure
  mode from integration failure: the tool looks like it succeeded.

Full synthesis, with contradictions and open questions: the `claude-obsidian` wiki's
`wiki/resources/Astrophysics-AI-Agent-Tools/Astrophysics-AI-Agent-Tools.md` (this repo does
not depend on that vault; it is cited here only for provenance).

---

## 2. Where Kepler Already Matches External Practice

No change needed here — listed so the rest of this document doesn't re-argue settled ground.

| External practice | Kepler equivalent |
|---|---|
| ASTER's explicit, inspectable control flow (vs. an opaque agent loop) | The `tools/` → `algorithms/` split itself: tools are thin, algorithms are frozen, and every severed dependency is marked inline with `# EXTRACTED: was <symbol>`. |
| Astro MCP's high-level tools (`search_objects`, not raw API passthrough) | `tools/registry.py` ships one schema per database (`search_simbad`, `search_atnf`, `search_vizier`, …) instead of one dispatcher with a `database` enum — already a step past what Astro MCP does. |
| Astro MCP's per-source plugin isolation (new survey doesn't touch core logic) | `algorithms/query/` imports `algorithms/catalogs/`, never the reverse (`CLAUDE.md`, "Python domain boundaries"). Adding a catalog means adding a declaration plus a query binding, not touching `fieldcal`. |
| Cmbagent's "human-guided beats fully autonomous" finding | `tools.runner`'s agent loop is explicitly optional (`docs/tool-architecture.md` §7: "Serving is optional. A Python caller must be able to import and call every tool without running a server.") — the tools are designed to be called by a human, a script, or an agent equally. |
| AI Cosplaying's "verification is real labor, make it cheap" | `tools/runner.py`'s `SYSTEM_PROMPT` already encodes a specific, previously observed failure (an agent attributing a fabricated decline-rate figure to a real paper by name) and a structural mitigation: quote `get_paper_abstract`/`search_ads` text before stating a number, or say explicitly the figure is unverified. This is the single closest thing in Kepler to Kosmos-style grounding discipline, and it is already shipped, not proposed. |
| Preserving rather than silently "fixing" known-wrong behavior | The entire extraction contract (`CLAUDE.md`, "The extraction contract"): documented parity quirks like `_clear_wcs_solution_fields`'s silent no-op are deliberate and must not be "fixed" outside an explicit divergence task. `docs/analysis/algorithm-remediation-plan.md` treats every finding as "provenance, not permission" (§4) before touching it. |

---

## 3. Applicable Change: Close the Warning/Error Contract

**External practice.** Astro MCP and Astronomy AI Toolkit both work because a calling agent
can rely on one predictable response shape across every provider. ASTER's whole design
argument is that inspectable structure beats prose. AI Cosplaying's finding is that
*ambiguous* output — not wrong output, ambiguous output — is what an agent (or a human
verifying it) fails on.

**Current state in Kepler, checked 2026-08-11.**

- `tools/models.py` defines two different warning shapes in the same file:
  `ToolResult.warnings: list[str]` (free text) is what every database tool in `tools/`
  actually returns, while `WcsSummary`, `CatalogSummary`, `ReferenceBandResolution`, and
  `ZeropointSolution` all use `warnings: list[ToolWarning]` (structured `code` + `message`).
  Only `WcsSummary`/`CatalogSummary`/etc. are machine-filterable by `code`; `ToolResult`
  warnings are not, and `ToolResult` is what most of `tools/` (SIMBAD, NED, VizieR, ATNF,
  MAST, MPC, CASDA, ADS) returns.
- `ToolError.code` is typed `str`, unconstrained — but a `grep` across every `tools/*.py`
  file today finds exactly **three** distinct values in use: `invalid_input` (20 call sites),
  `provider_unavailable` (13), `dependency_missing` (1). The vocabulary is already small and
  stable in practice; it just isn't declared as one.
- `ToolResult.warnings` is populated in exactly one place across all of `tools/`
  (`tools/simbad.py`, the "bibcode found but no abstract text is on file" case) — meaning the
  structured-vs-free-text inconsistency has not yet caused a real problem, but nothing stops
  the next database tool from inventing a fourth string-shaped warning convention.

**Recommendation.**

1. Promote `ToolError.code` from `str` to `Literal["invalid_input", "provider_unavailable", "dependency_missing"]` now, while the vocabulary is genuinely closed at three values. This is a same-day, non-behavior-changing type tightening — every existing call site already uses one of the three.
2. Change `ToolResult.warnings` from `list[str]` to `list[ToolWarning]`, matching every other result model in the same file. One call site (`tools/simbad.py`) needs updating.
3. Do not invent new codes speculatively. Add one only when a tool needs to distinguish a case a caller would act on differently — the same discipline `CATALOGS` vs `CATALOG_OPTIONS` already follows (two registries, kept apart, because merging them "silently changes which reference band a narrowband or unfiltered image calibrates against," `docs/extraction.md`, "Catalogs" §4, "The two registries are not redundant").

This is the highest-leverage, lowest-risk item in this document: it costs a few hours, touches no algorithm code, and is the direct precondition for §4 below.

> **Correction, 2026-09-23 (phase C2 of `docs/archive/mcp-tool-surface.md`).** The
> two counts above are wrong as of `dev`, and recommendation 1 was not taken as
> written. An AST scan of `tools/` and `algorithms/` finds **41** distinct
> `ToolError` codes, not three: the three named here are the ones built as
> `{"code": ..., "message": ...}` dict literals in the class-R database tools,
> and the other 38 are constructed through `ToolError(code=...)` — including six
> sites that pass a code held in a variable, which no `Literal` could satisfy.
> `ToolResult.warnings` likewise had fifteen call sites across seven modules, not
> one. Recommendations 2 and 3 shipped as written; recommendation 1 shipped as a
> **declared, test-enforced vocabulary** (`tools/codes.py`,
> `tests/test_tool_codes.py`) rather than a `Literal`, for the reasons recorded
> in that module's docstring. The dated analysis above is left intact.

---

## 4. Applicable Change: Link Preserved-Defect Findings to Runtime Warnings

**External practice.** Stargazer's failure mode — a statistically fine result that recovers
the wrong physical parameters — is exactly what happens when a tool call succeeds by its own
contract but is silently wrong by the domain's contract. AI Cosplaying's finding is the same
thing from the human side: verifying agent output is expensive, so anything that can be
surfaced automatically should be.

**Current state in Kepler.** `docs/analysis/algorithm-remediation-plan.md` already does the hard part:
it classifies every one of 110 findings across `wcs/`, `photometry/`+`fieldcal/`,
`catalogs/`+`query/`, and the TypeScript algorithms into finding classes, and separates
**"Silent — wrong science, no signal"** from **"Loud — but catastrophic"** (§5). That
classification is exactly the information a calling agent needs at the moment it calls the
tool that has the defect — but today it lives only in a document, not in the tool's return
value. An agent (or a human) has to already know to go read `docs/analysis/algorithm-remediation-plan.md`
before calling `describe_image_wcs` to learn that `_clear_wcs_solution_fields` can leave stale
`ra`/`dec`/`pixel_scale`/`rotation` values on a failed solve.

**Recommendation.** For every "Silent — wrong science, no signal" finding in
`docs/analysis/algorithm-remediation-plan.md` §5 that is reachable from a public `tools/` function
(not every algorithms-level finding needs this — only the ones a tool caller can actually
trigger), add a `ToolWarning` with a stable `code` at the point in the relevant `tools/*.py`
wrapper where the condition is detectable, even before the underlying algorithm bug is fixed.
Two concrete examples already named in the remediation plan and the wiki-page provenance:

- `tools/astrometry.py`: if a solve returns no solution, the tool result should carry a
  `code` that distinguishes "no astrometric solution found" from "solver backend not
  configured" (see §6 below — these are currently the same undifferentiated case).
- Any `tools/catalogs.py` path that resolves an ambiguous filter spelling (the APASS
  `H_alpha` vs `Halpha` divergence named in the wiki-page provenance) should return both
  candidate resolutions plus a warning, not silently pick one.

This turns `docs/analysis/algorithm-remediation-plan.md` from a document a human must separately
consult into runtime signal a calling agent gets for free on the call that matters, without
requiring the underlying fix (which stays gated behind the plan's own "every fix needs a
targeted test" rule, §2).

---

## 5. Applicable Change: Optional MCP Surface

**External practice.** Astro MCP and Astronomy AI Toolkit both standardize on MCP
specifically because it decouples the tool surface from any one model vendor — that is also
ASTER's stated reason for building on a provider-agnostic framework instead of hand-rolling
model-specific tool-calling.

**Current state in Kepler.** `tools/registry.py` already expresses every tool as a
name/description/JSON-schema triple — which is structurally almost identical to an MCP tool
definition. But `tools/runner.py` wires that registry directly to the `anthropic` Python SDK
(`import anthropic`, `client.messages.stream(...)`), and `pyproject.toml` depends on
`anthropic==0.121.0` with no `mcp` dependency anywhere in the repository. The only way to
call Kepler's tools today through an agent loop is Anthropic's Messages API specifically, via
the `kepler-astro-query` CLI entry point, gated on `ANTHROPIC_API_KEY`.

**Recommendation.** Add an MCP server as a second, optional consumer of
`tools.registry.TOOL_SCHEMAS`/`TOOL_FUNCTIONS` — not a replacement for `tools.runner`, and not
a required dependency for anyone using `tools/` as a plain Python library. Concretely:

- A new `tools/mcp_server.py` (or a separate `kepler-mcp` optional dependency group in
  `pyproject.toml`, matching how `ADS_DEV_KEY`/`ANTHROPIC_API_KEY` are already treated as
  optional, feature-gated credentials) that translates each `TOOL_SCHEMAS` entry into an MCP
  tool definition and dispatches to the same `TOOL_FUNCTIONS` mapping `tools.runner` already
  uses.
- This keeps `docs/tool-architecture.md`'s own non-goal intact — "No mandatory serving
  framework" — because it is generated from the existing tool functions and models rather
  than becoming a second design surface. §7 of that document already anticipates exactly
  this: "If a serving surface is added later, generate it from the same tool functions and
  models rather than designing the package around a server."
- This is what actually gets Kepler in front of the MCP-native tools this research found
  (Claude Code, Cursor, and any other MCP host), instead of only the bespoke Anthropic-loop
  CLI.

Sequencing: do this after §3 (structured warnings), because MCP tool results should carry
the same `code`-bearing warning/error shape — otherwise the MCP surface inherits the
free-text inconsistency on day one.

---

## 6. Applicable Change: Persist the Agent-Loop Call Cache as a Session Artifact

**External practice.** Kosmos's central architectural bet is a structured world model shared
across agents in one session, specifically to avoid losing coherence over many tool calls.
ResearchBench and ReplicationBench both independently found that current agents' main failure
mode on real astrophysics research tasks is *integration* across steps, not any single tool
call — which is the same problem at a smaller scale.

**Prior state, checked 2026-08-11.** `tools/runner.py` already had a primitive version of this: a
`call_cache: dict[str, dict]` keyed by `tool_name + json.dumps(tool_args, sort_keys=True)`,
added specifically because "the model can re-issue an exactly identical tool call... across
turns, presumably not recognizing a prior result as still current" (comment, `tools/runner.py`
around the cache definition). It is real, evidence-based engineering — the comment cites a
transcript where this actually happened. But it was scoped to one `run()` call: it died with
the process, and nothing downstream of a session (a human reviewing what an agent did, or a
second agent picking up the same research task later) can see what was called, in what order,
with what results.

**Implemented.** `tools.runner.run()` now creates a session id, scopes artifacts written by
tool calls under `artifacts/sessions/<session_id>/...`, and writes a
`session_manifest.json` at session start, after each tool call, and when the loop ends
(`end_turn`, `max_turns`, or exception). The manifest records tool name, arguments,
cache-hit status, result status/count, warnings/errors, and artifact paths. Current manifests
also preserve the complete neutral conversation — prompts and tool arguments/results — for
safe provider-context resume, while the diagnostic trace itself still omits full result
payloads. The files are local, sensitive records: POSIX session directories are `0700` and
manifests `0600`; resume rejects a manifest above 1 MiB or history above 256 KiB (128 messages,
256 blocks, and 64 KiB per field). Exact context is intentionally not redacted; remove the
session artifact directory when it should no longer be retained.
`tools.workspace.list_sessions()` and `tools.workspace.describe_session()` expose those
manifests for later review without re-running remote queries. This is the minimum version of
the Kosmos-style shared-state idea, using Kepler's existing local artifact model rather than
adopting a cross-agent world-model architecture wholesale.

---

## 7. Applicable Change: Ship `backend_unavailable` vs `no_solution`

**External practice.** Stargazer's failure mode again: a WCS call that returns cleanly but
carries no solution looks, from outside, identical to a call that couldn't run at all. An
agent (or a human) cannot tell "this frame has no astrometric solution" (a real scientific
result) from "the solver isn't installed" (an environment problem) without inspecting
configuration directly.

**Current state in Kepler.** `CLAUDE.md` names this explicitly: "Both WCS backends degrade to
'unavailable' rather than failing, so imports succeed and solves simply return no solution
when the data is absent. This is why full parity has never been validated here." A repository
`grep` for `no_solution`, `backend_unavailable`, or `unavailable` across `algorithms/wcs/*.py`
and `tools/astrometry.py` returns nothing — this was named as the wiki-page snapshot's
"biggest correctness win" on 2026-08-10 but has not shipped in `algorithms/wcs/wcs.py` or
`tools/astrometry.py` as of this reading.

**Recommendation.** Before spending effort on the Afterglow-parity numeric validation run
that both `CLAUDE.md` and `docs/analysis/algorithm-remediation-plan.md` list as outstanding, ship this
distinction first — it is a precondition for that validation being trustworthy. A parity run
against reference FITS that silently treats "backend not configured" and "genuinely no
solution" as the same outcome cannot tell you which one it validated. Concretely: probe
solver configuration (`ANET_INDEX_PATH`, `ATLAS_CATALOG_ROOT`, local UCAC4/UCAC5 presence)
before attempting a solve, and have `tools/astrometry.py` return a `ToolError` with
`code="dependency_missing"` (already in the closed vocabulary from §3) naming the specific
missing configuration, distinct from a `WcsSummary` with `has_wcs=False` for a genuine
no-solution result.

---

## 8. Deliberately Not Recommended

**A shared base class per data-source tool, matching Astro MCP's plugin pattern.** Astro MCP
uses inheritance because it has one server process serving many sources. Kepler's `tools/`
already gets the same practical benefit — every provider tool takes bounded arguments, writes
a full-data artifact via `tools/artifacts.py`, returns a bounded `preview`, and reports
`status` from the same four-value set (`ok`/`partial`/`not_found`/`error`) — through
convention plus the shared `ToolResult` model, not inheritance. Introducing a base class now
would be a large mechanical refactor across every file in `tools/` for a benefit (enforcing a
shape that already holds in practice) §3's `Literal` typing gets more cheaply. Revisit only if
a future provider tool actually breaks the convention.

**Narrowing `tools/`'s database surface.** Astronomy AI Toolkit's lesson is "compose existing
servers instead of rebuilding them." Kepler's `tools/` already covers SIMBAD, NED, VizieR,
ATNF, MAST, MPC, CASDA, and ADS directly rather than delegating to something like Astro MCP —
that was a deliberate choice already made, not an oversight to correct. It is, in effect,
Kepler independently arriving at Astro MCP's own scope (broad multi-database access) while
additionally owning the algorithmic kernels (WCS/photometry/field-cal) that Astro MCP does
not have. Undoing that now would be a regression, not an application of external practice.

**Adopting Cmbagent's or Kosmos's multi-agent orchestration wholesale.** Both are
domain-agnostic *agent* architectures. Kepler is explicitly a tool collection, not an
orchestration framework (`docs/tool-architecture.md` §9, "No orchestration framework"). The
applicable part of both — human-guided beats fully autonomous; persistent state beats
re-deriving context — is captured narrowly in §6 above without importing either project's
actual agent-loop machinery.

---

## 9. Suggested Sequencing

Ordered by dependency, not by external-source importance:

1. §3 (structured warning/error contract) — touches `tools/models.py` and one call site.
   Everything else below assumes this exists.
2. §7 (`backend_unavailable` vs `no_solution`) — precondition for the Afterglow-parity
   validation run already on the backlog; small, scoped to `algorithms/wcs/` and
   `tools/astrometry.py`.
3. §4 (link remediation-plan findings to runtime warnings) — incremental, one finding at a
   time, no fixed end state; start with the two examples named above.
4. §6 (persist the call cache as a session artifact) — additive, `tools/runner.py` and
   `tools/artifacts.py` only, no model changes.
5. §5 (optional MCP surface) — largest single addition; do last so it inherits the closed
   warning/error vocabulary and the session-manifest pattern instead of shipping ahead of them.

None of these require touching `algorithms/` — they are all `tools/`-layer or documentation
changes, consistent with `docs/tool-architecture.md`'s own rule that "Tool and architecture
work should not silently change numerical behavior or fix algorithm bugs."
