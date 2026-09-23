# The MCP Tool Surface and the Agent Skill

**Status:** In progress. C0 and C2 complete (§5). C1 is next.
**Date:** 2026-09-18, reconciled 2026-09-23 against the maintainer's answers to §7.
**Prerequisites:** None architectural. Phase C2 is a stated precondition of
phase C3, from [`../analysis/applicable-designs.md`](../analysis/applicable-designs.md)
§3 and §5.
**Unblocks:** Kepler's tools become callable from a console this repository
does not own, on a machine where **this repository is not checked out**.
**Scope:** a fourth consumer of `tools/registry.py`; the skill that teaches a
model which tool to reach for and which results are silently wrong; and the
packaging that puts the tools and their data on a user's own machine. Nothing
under `algorithms/` changes. Nothing in `tools/agent/`, `tools/llm/`,
`tools/tui/` or `tools/bench/` is retired.

This document is architecture and sequencing. It contains no implementation
code. An agent working a phase reads the contracts here, then writes the code
that satisfies them.

> [!important] The hosting model is settled, and it is local
> §7 recorded four open questions for the maintainer. All four are answered as
> of 2026-09-23 and the answers are now decisions, not options:
>
> 1. **Local.** Kepler is **packaged and installed by the user**, data
>    included. There is no Kepler-operated server and no data service.
> 2. **The user installs everything.** Their machine, their disk, their keys.
> 3. **One server, not five.** The five workflow groups survive as a
>    launch-time filter on one server, not as five servers.
> 4. **No HTTP transport and no network authentication.** stdio only. A
>    **GitHub release track** follows the rollout, for testing.
>
> §§1, 3.1, 3.3, 3.6, 4.1 and the phase list are rewritten around this. The
> version that designed for a detached, operator-run server is in git history;
> the reasoning that survives detachment is kept and marked, the reasoning that
> only existed to serve it is deleted rather than left to mislead.

---

## 1. Three instruments, divided by what the caller has

Everything Kepler ships today assumes the caller is standing in the
repository. That assumption is load-bearing in more places than it looks, and
this track is about the case where it does not hold.

| Instrument | For | What the caller has |
| --- | --- | --- |
| `tools/tui/` — the `kepler` console | A **human** at the tools. One model, one session, artifacts rendered in place, `/backend` to switch providers, resume from a session manifest. | **A checkout.** It is the entry point that proves the surface works with no third-party host installed at all. |
| `tools/bench/` — `kepler-bench` | Measuring **models** on the tool surface. It ran 144 sessions across four providers, produced [`../benchmarking/report.json`](../benchmarking/report.json), and answered its question. An instrument, not a product; dormant until a new model is worth measuring. | **A checkout.** It substitutes `run_session`'s `tool_functions=` mapping and reads fixtures off local disk. |
| **This track** — the MCP server and the skill | A **coding agent in its own console** — Claude Code, Codex, Cursor — doing astronomy work. | **An installed package, and no checkout.** |

The first two are instruments for someone who already has this checkout. They
stay exactly as they are; this track retires neither, and the obvious
misreading — that an MCP surface replaces the loop — is wrong.

The third case is not a variant of the first two. **The caller shares the
filesystem** — the server is a subprocess on the user's own machine — so the
artifact-path contract still works, and that is the single largest
simplification the local hosting decision buys. What does not survive is
everything that depended on a *checkout*:

- The tools are not importable from the user's project, so
  `uv run python -c "from tools.pulsar import …"` is not the normal path and
  the skill cannot teach it as one.
- There is no `skills/kepler-tools/SKILL.md` on the client's disk, because
  there is no repository on the client's disk. **The skill has to travel with
  the server** (§3.4). This is the premise that survives the hosting decision
  intact, and it is why C1 and C5 are not optional.
- The bundled data — the five pulsar scans, the frame library, the recorded
  reference solves — has to be *installed*, not *checked out*. The repository
  ships 263 MB of tracked fixtures and **ships none of it in a wheel today**
  (§5, C0). The Girardi isochrone grid `run_full_hr_pipeline` needs is not in
  the repository at all. §3.5 and phase C7 are about this, and it is now the
  hardest problem in the track.
- `SYSTEM_PROMPT` is not delivered by anything, because the loop that carries
  it is not running.

So the track has exactly three deliverables:

1. **The server** — how the tools are reached at all.
2. **The skill** — how a model knows which to reach for, in what order, and
   which results are wrong without saying so.
3. **The package** — how the tools and the data they read get onto a machine
   that has no checkout, and a release track to test that they did.

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

§9's non-goal, *"No mandatory serving framework"*, survives: the server is
generated from the tool functions and sits on no import path a plain Python
caller touches.

One structural property makes the whole thing cheap. *"One public tool call is
Kepler's execution boundary"* — no run, stage or session object spans two
calls, and no tool writes state another tool reads. There is nothing to bridge.
A stateful surface would have made this track a rewrite; instead it is a
translation.

---

## 3. Decisions

### 3.1 The result contract: the path still works, the media does not

Every Kepler tool today returns the same shape: a **bounded inline preview**
plus an **artifact path**, with the full data written to a file.
`../tool-architecture.md` §7 makes it policy — *"large payloads returned as
artifacts plus summaries"* — and it is the right design when the caller shares
the filesystem.

Under the local hosting decision **the caller does share the filesystem.** The
server is a subprocess the host launched on the user's own machine; a coding
agent holds `Read` and `Bash` and can open anything the server wrote. The
artifact path is a working handle, the existing contract stands unchanged, and
a whole phase of resource plumbing that a detached deployment would have
needed does not have to be built. Measured at C0: **36 of 55 tools return an
`ArtifactRef`**, so this is most of the surface.

Two things still need doing, and neither is about filesystem access.

**Media has to come back inline.** Eight tools produce a PNG or a WAV:
`plot_pulsar`, `sonify_pulsar`, `plot_field_sed`, `analyze_source_spectrum`,
`fit_and_compare_hr_diagram`, `run_full_hr_pipeline`,
`run_full_hr_pipeline_from_catalog`, `run_photometry_on_target`. A path to a
plot is second-best even in a host that can read files, and a path to a WAV is
worthless in every host there is: **a model handed a path to audio has not
heard anything.** MCP carries image and audio content in a result; the media
tools use it. This is C4 and it is the only part of the old §3.1 that the
hosting decision left standing at full size.

**Where the artifacts went has to be discoverable.** The artifact directory is
whatever `KEPLER_ARTIFACT_DIR` names, or `artifacts/` beside whatever working
directory the host happened to launch the server from (§3.2). Under a packaged
install the user has no `data/` to look in and no checkout to orient by.
`describe_artifact` and `list_artifacts` (`tools.workspace`) are therefore
**promoted, not dropped** — the previous draft listed them as the first tools
to cut, on the grounds that a coding agent has a filesystem. It does; it does
not have a map. Their descriptions say which directory they enumerate, and the
server logs the resolved root at startup.

Publishing artifacts as MCP **resources** is *available* and is not built here.
It buys a host with no file tools at all, which is not the case this track is
for, and §3.3 no longer contains a deployment where the path fails. Recorded as
a known extension; see §4.3.

Nothing relaxes the caps. `PREVIEW_ROWS` defaults to 10, and
`KEPLER_MAX_FRAMES` (200), `KEPLER_MAX_CATALOGS` (20) and
`KEPLER_MAX_OBSERVATIONS` (25) exist to keep a result out of a model's
context. A client that wants the whole table reads the artifact — which, here,
it can.

### 3.2 Configuration must be anchored to the package, not to the process's cwd

A host launches a server with a working directory the server did not choose —
under the local model, almost always *the user's own project directory*, which
has nothing to do with Kepler. Verified on `dev` at 2026-09-18 and again at
C0 on 2026-09-23, `tools/config.py` splits two ways on this:

- `DATA_DIR = env_path(DATA_DIR_ENV, _REPO_ROOT / "data").resolve()` — anchored
  to the package. Correct under any cwd.
- `ARTIFACT_DIR = (env_path(ARTIFACT_DIR_ENV, "artifacts") or Path("artifacts")).resolve()`
  — the default is the **relative** string `"artifacts"`, resolved against the
  process's working directory at import. C0 reproduced this: importing
  `tools.config` from `/tmp` resolves `ARTIFACT_DIR` to `/tmp/artifacts` while
  `DATA_DIR` stays at the repository.

The module's own comment explains why it resolves at import — *"a bare
`artifacts/…` silently means something different in each of those"* — and that
reasoning applies with more force here. **The server resolves and pins
`KEPLER_ARTIFACT_DIR` at startup** and does not leave it implicit. Whether the
pinned value should be the launch cwd (artifacts land in the user's project,
where their agent is already looking) or a fixed per-user directory is C3's
call; what is not optional is that the server states the answer, logs it, and
reports it through `describe_artifact`/`list_artifacts`.

Two related notes:

- `FITS_DOWNLOAD_DIR` is derived from `DATA_DIR` **at import**; reassigning
  `DATA_DIR` at runtime does not move it. Environment variables are the
  supported way to move them together. Under a packaged install this default
  points *inside the installed package* — see §3.5, which is a blocker, not a
  note.
- `tools/artifacts.py`'s `scoped_artifacts` is a `ContextVar` — the one piece
  of implicit state on an otherwise stateless surface. A stdio server serving
  one client sequentially is fine, and stdio is now the only transport.
  **Concurrent sessions are out of scope**; the server sets no scope, and
  artifacts land in the configured root.

### 3.3 One deployment shape

The previous draft carried three shapes and built two. The hosting answer
leaves one target and one rehearsal:

| Shape | Transport | Who holds the data and keys | Status |
| --- | --- | --- | --- |
| **(a) From a checkout** — the host launches the server out of a development tree | stdio | The developer, on their own machine | **The rehearsal.** How (c) is built and tested; how a Kepler developer wires their own console to their own checkout. C3. |
| **(c) Packaged** — installed by the user, launched by the host | stdio | The user, on their own machine, after installing | **The target.** C7, released for testing in C8. |
| ~~(b) Detached — server over the network, operator-held data~~ | ~~HTTP~~ | ~~An operator~~ | **Deleted.** No HTTP transport, no network authentication, no Kepler-operated service. |

Deleting (b) removes four things from the track, and they are removed rather
than deferred: the HTTP transport, the authentication design, the server-side
ceilings a client could not raise (§4.1), and the credential-isolation
requirement — the keys are the user's own, in the user's own environment,
exactly as they are for the `kepler` console today.

What it adds is §3.5. A detached server was a way of *not* shipping 175 MB and
a 5 GB catalogue to anybody. Local installation means the data problem is now
the user's, which means it is now the packaging's.

### 3.4 The skill travels with the server

This is the premise the hosting decision did **not** touch, and it is worth
being explicit about why: "local" answers *where the server runs*, not *what
the client has*. The client is a coding agent in a user's own project. A skill
file living at `skills/kepler-tools/SKILL.md` in this repository is not on that
disk and nothing will ever read it.

**The server serves the skill.** MCP delivers instructions from the server to
the client at connection time, and exposes further documents as resources. So:

- The server's **instructions** carry the cross-tool rules that have no
  per-tool home: the pulsar stage order and PERIOD SOURCING in full, the
  identifier-form table, the sourcing discipline for literature claims, the
  `null`-not-`"None"` rule for uncapping, and where artifacts are written
  (§3.1).
- Longer per-domain references are **resources** the client can read on
  demand, so the always-delivered instructions stay small. This is the one
  place the track uses resources, and it is content the model needs rather
  than data it might want.

The repository keeps a copy at `skills/kepler-tools/` for the checkout case and
for a human reading it, but that copy is **rendered from the same source** as
the served text, and a test asserts they agree. `.claude/skills/kepler-tools`
is a symlink to it; `AGENTS.md` and `CLAUDE.md` gain one pointer line each.
Those two files are about working *on* the repository, which is a different
axis and stays that way.

**Copies are forbidden.** `CLAUDE.md` already declares the shipped prompt in
`tools/agent/prompt.py` authoritative for period sourcing. A second hand-written
statement of the same rule is a drift bug waiting for the first correction that
lands in one and not the other, and here there would be three surfaces, not two.

### 3.5 The data problem, which local hosting creates

Measured at C0 on 2026-09-23. This is the part of the track the hosting answer
made harder, and it deserves the same scrutiny §3.1 used to get.

| Asset | Size | Where it is now | Shipped in a wheel today? |
| --- | ---: | --- | --- |
| `data/pulsar/` — the five scans | 5.7 MB | Tracked in this repository | **No** |
| `data/fieldcal/` — recorded reference solves | 860 KB | Tracked | **No** |
| `data/afterglow/` — parity fixtures | 160 KB | Tracked | **No** |
| `data/optical/` — the bundled frame library, 43 frames | 257 MB | Tracked | **No** |
| Girardi isochrone grid, 4,308 `.npy` | 364 MB | `/srv/agents/isochrones`, operator-supplied | **No, and not in the repository either** |
| astrometry.net indexes (4200-series, TYCHO2, UCAC5) | 78 GB | Operator-supplied | Never |
| ATLAS UCAC5 catalogue | 5.3 GB | Operator-supplied | Never |

Three findings follow, and each is a C7 requirement rather than a remark.

**Nothing under `data/` is packaged.** There is no `MANIFEST.in`, and
`[tool.setuptools.packages.find]` includes `tools*` and `algorithms*` only, so
`data/` appears in no distribution. A `pip install` of Kepler today yields a
`DATA_DIR` pointing at a directory that does not exist, and every bundled-data
tool — `list_pulsar_scans`, `list_optical_frames`, `list_zeropoint_references`,
`list_variable_star_fixtures` — enumerates nothing.

**Two guards silently stop guarding.** `tools/wcs.py`'s fixture-write refusal
pins `_FIXTURE_ROOT` to `Path(__file__).resolve().parents[1] / "data"`, which
under a wheel is `site-packages/data` — absent, so the guard matches nothing
and the refusal never fires. `FITS_DOWNLOAD_DIR` defaults to
`DATA_DIR / "fits_downloads"`, which under a wheel means
`search_mast(download=true)` writes **into the installed package**, possibly
read-only. Neither is a design flaw; both are correct code written for a
checkout, and both have to be re-anchored for an install. C7 re-anchors them
and re-proves them; §4.2 is the standing rule that it may not weaken them to
do it.

**The package splits into a core and two optional bundles.** 630 MB is past
what belongs in a wheel and past PyPI's per-file limit, but the user's ask —
*small enough to run and deploy locally* — is satisfied by a much smaller core:

- **Core, inside the distribution (~7 MB):** `data/pulsar/`, `data/fieldcal/`,
  `data/afterglow/`. The whole pulsar chain, the field-calibration replay and
  the parity fixtures work on a bare install, with no download and no network.
- **Optional bundles, fetched on demand:** the optical frame library (257 MB)
  and the isochrone grid (364 MB), published as **GitHub release assets** —
  which is also what C8 is for — fetched by a `kepler-mcp fetch-data` command
  into a user-writable directory, checksum-verified, and pointed at by
  `KEPLER_DATA_DIR`/`KEPLER_OPTICAL_DATA_DIR`/`KEPLER_ISOCHRONE_DIR`.
- **Never bundled:** the astrometry.net indexes and the ATLAS catalogue. They
  stay operator-supplied and opt-in exactly as `CLAUDE.md` describes, and
  `solve_astrometry` keeps degrading to "unavailable" when they are absent,
  which it already does correctly.

One thing that looked like a dependency is not: `/srv/agents/catalogs/photometry`
(40 GB — APASS, VSX, Landolt, Stetson) is **read by no Kepler code**. A grep of
`tools/` and `algorithms/` finds no reference to it. It belongs to Skynet's
pipeline, not this one, and it is not a packaging input.

A tool whose data bundle is absent must **say so** rather than return an empty
listing that reads like a real answer. That is the same failure class the whole
skill exists for, and C7 owns it.

### 3.6 One server, with the groups kept as a filter

The measurement that motivated five servers is real and C0 re-confirmed it:
`json.dumps(TOOL_SCHEMAS)` over all 55 tools is **59,280 bytes, roughly 14,800
tokens**. Most hosts load a server's tools eagerly. That is a bad neighbor in a
console already carrying its own instructions and the user's own repository.

But five servers means five entry points, five host registrations, five sets of
instructions to keep in agreement, and five places for a new tool to go
missing — and under local installation they would all be the same process
launched five times off the same disk. **One server.** The grouping survives as
a launch-time filter, not as a product:

- `kepler-mcp` is one script entry and serves all 55 tools by default.
- `kepler-mcp --tools databases,timeseries` (or `KEPLER_MCP_TOOLS`) serves only
  those groups, for a user who wants a quarter of the surface in their context.
- The groups live in **one module** as a declared mapping, and a test asserts
  they partition the registry exactly — every tool in exactly one group, no
  tool in none. That is the invariant the five-server plan was really buying,
  and it is kept.

Measured at C0; the groups and their payloads are unchanged from the original
table, and the 110-byte gap between the parts and the whole is JSON's list
separators, not a miscount:

| Group | Tools | Schema bytes | ≈ tokens | Runs with no data bundle? |
| --- | ---: | ---: | ---: | --- |
| `databases` — SIMBAD, NED, VizieR, ATNF, MAST, MPC, CASDA, ADS, resolve | 16 | 15,397 | 3,850 | **Yes** — remote services and `httpx`. |
| `optical` — frames, WCS, photometry, field calibration, catalogs, workspace | 16 | 15,242 | 3,810 | Partly — field-calibration replay is core; the frame library is an optional bundle. |
| `timeseries` — the pulsar chain and the variable-star chain | 12 | 12,935 | 3,230 | **Yes** — the five scans are core. |
| `hr` — both HR-diagram entry points | 8 | 9,808 | 2,450 | Partly — the catalog-only path needs no local data; the isochrone fit needs the bundle. |
| `radio` — SED fitting and source identification | 3 | 5,788 | 1,450 | Partly. |
| **All** | **55** | **59,280** | **14,800** | |

The right column is not a footnote: it is what the server's instructions have
to tell a model before it calls `run_full_hr_pipeline` on a machine with no
isochrone grid (§3.5).

**A dispatcher is not the answer**, and this is settled ground:
[`../analysis/applicable-designs.md`](../analysis/applicable-designs.md) §2
credits Kepler for shipping one schema per database *instead of* one dispatcher
with a `database` enum — *"already a step past what Astro MCP does."*
Collapsing to `query_database(database=…, …)` to save tokens would walk that
back and discard the per-database argument validation that makes the schemas
worth having. One server is not one tool.

### 3.7 Annotations are generated from `tools/bench/plane.py`

`TOOL_CLASSES` already classifies all 55 tools as local (26), remote (22) or
mixed (7) — re-confirmed at C0 — and a test asserts the plane covers the
registry, with an unclassified tool raising rather than defaulting. That is
exactly the metadata an MCP surface needs, already test-enforced.

- `openWorldHint` ← `TOOL_CLASSES[name] != "local"`.
- `readOnlyHint` ← false for tools that write outside the artifact directory —
  `solve_astrometry` writes a solved header back into a FITS file,
  `search_mast(download=true)` fetches products into the download root — true
  otherwise.
- The seven `"mixed"` entries carry `OFFLINE_PREDICATES`, which are
  per-argument and have no MCP equivalent. §4.1.

Read the mapping; never restate it. This makes the existing "classify in the
same commit that registers the tool" invariant load-bearing in a second place.

### 3.8 The dependency decision

The last two tracks held a hard **zero new dependencies** line.
`pyproject.toml` pins every dependency with `==`, CI runs `uv run --locked`,
and there are no optional-dependency groups today.

Two options; the phase that lands C3 picks one in its PR description:

1. **The `mcp` Python SDK, in a new `[project.optional-dependencies]` group.**
   Maintained, handles protocol evolution, and brings the content types §3.1
   needs for inline media and the resource mechanism §3.4 needs for the skill
   references. Costs a transitive tree and a lockfile change; the phase must
   show a plain `uv sync` + `uv run --locked pytest` is unchanged for someone
   who never asks for the group.
2. **Hand-rolled stdio JSON-RPC.** `docs/archive/model-backends.md` §2.2 set
   the precedent, implementing three provider adapters over raw `httpx` rather
   than taking `litellm`. Costs owning protocol drift.

**Recommended: (1)**, and the local hosting decision strengthens it rather than
weakening it. The argument for hand-rolling in the model port was that an
abstraction library *"would hide precisely the protocol differences the
protocol-robustness grader exists to measure"* — there is no such measurement
here, so the reasoning does not transfer. Dropping HTTP removes one of the
SDK's selling points but not the other two, and a hand-rolled server is one
more thing a **user** would have to have working on their own machine, with no
operator to debug it.

---

## 4. What this surface costs

Stated here so a later reader does not discover them as surprises.

### 4.1 Per-argument gating has no MCP equivalent

`run_session(approver=…)` can refuse a call on its **arguments**.
`tools/bench/plane.py` relies on exactly that: `DEFAULT_BLOCKED` holds
`solve_astrometry` because an all-sky solve is ~285 s against operator assets
not in this repository, and `OFFLINE_PREDICATES` decides the seven mixed tools
per call — `calibrate_zeropoint` is offline only with `catalog_fixture` *and*
`compare_to` together.

MCP host permissions are per **tool**. `search_vizier` is a fine tool with an
expensive argument (`max_catalogs=null`, which the instructions explicitly tell
a model to use for an exhaustive request), and a host that approved the tool
approved every argument with it.

**Local hosting closes most of this by construction, and the track accepts the
rest.** The cost of an expensive call lands on the user who authorised the
tool, on their own machine, in front of them — not on a third party. The
previous draft required server-side ceilings a client could not raise; that
requirement is **deleted**, because it existed to protect an operator from a
client and there is no operator. The existing caps remain what they are:
model-adjustable defaults, documented in the skill, with the `null`-uncapping
rule stated so a model raises them deliberately rather than by accident.

### 4.2 Writes land on the user's disk, through guards written for a checkout

`solve_astrometry` writes a solved header back into a FITS file;
`search_mast(download=true)` writes products into the download root. Two
existing guards do real work here and must be understood rather than
rediscovered:

- `tools/wcs.py` refuses to write a solved header into a bundled fixture. The
  guard names four tracked subtrees (`afterglow/`, `fieldcal/`, `optical/`,
  `pulsar/`), is pinned to this repository, reads no setting, and **no
  environment variable can switch it off**. A test asserts the tuple matches
  the directories present.
- `tools/config.py`'s `within()`/`safe_resolve()` decide containment on the
  *resolved* path, which is what keeps `tools/optical.py`'s recursive walk of
  the download root from following a symlink out of the tree.

Both hold under a checkout. **Neither survives a wheel install unchanged** —
§3.5 shows why: the fixture root resolves into `site-packages`, where there is
no `data/` to protect, and the download root resolves into the install tree.
C7 re-anchors both to wherever the installed data actually is and proves the
refusal still fires from an installed server. The standing rule is that it may
not *weaken* either guard to make installation easier; re-anchoring a guard is
not relaxing it, and the PR says which it did.

### 4.3 Resources are available and unbuilt

§3.1 declines to publish artifacts as MCP resources because the local caller
can read the file. A host with no filesystem tools at all would need them, and
if one turns up the extension is small and additive: an `ArtifactRef` gains a
URI beside its `path`, and nothing about the existing contract changes. It is
recorded here so a later reader knows it was considered and priced, not missed.

### 4.4 Third-party console sessions are unmeasured

`kepler-bench` grades trajectories by substituting `run_session`'s
`tool_functions=` mapping to replay the 22 remote tools. Under MCP the loop
belongs to the host: there is no substitution seam and no fixture replay. A
Claude Code or Codex session on this surface produces no graded trajectory, and
B2 — *nothing opens a socket under a plain `uv run pytest`* — says nothing
about it, because it is not running under pytest.

The benchmark continues to measure models through Kepler's own loop, which is
the only place it can. **This is a reason the console and the harness stay**,
not a defect in the MCP surface.

### 4.5 The heavy dependencies do not go away, they move to the user

`numba` and `sep` are hard import-time requirements of
`algorithms/skylib_lite`, with no non-numba fallback, and `scipy`, `astropy`
and Pydantic v2 are likewise required. A detached server would have carried
that weight for everyone; local installation puts it on each user's machine, as
wheels, at install time. This is a real cost of the hosting decision and C7
measures it: the phase records installed size and cold-import time on a clean
environment, because "small enough to run locally" is a claim that should be
checked rather than assumed.

---

## 5. Rollout

Phases are **C0–C9**. C1 is deliberately first and deliberately cheap.

### Global constraints

Every phase's requirements implicitly include this section.

- **Branch:** off `dev`, per `CLAUDE.md`. One PR per phase, narrow.
- **No changes to `algorithms/`.** Do not edit any file carrying an
  `# EXTRACTED:` or `# PORTED:` marker.
- **Nothing in `tools/agent/`, `tools/tui/` or `tools/bench/` is retired or
  reshaped.** `tools/agent/prompt.py` and `tools/registry.py` are **read**, not
  edited, by every phase of this track.
- **`tools/registry.py` stays the single source of truth.** The server reads
  it; it does not maintain a parallel list. A test asserts the served tool list
  equals `{s["name"] for s in TOOL_SCHEMAS}`.
- **Default checks stay offline and deterministic.** Nothing added here may
  open a socket under a plain `uv run pytest`.
- **`tests/test_tool_registry_coverage.py` enumerates `pkgutil.iter_modules`,
  which yields packages as well as modules.** Adding `tools/mcp/` requires
  adding it to `NOT_TOOL_MODULES` in the same commit or that test fails — the
  same way `tools.llm`, `tools.agent` and `tools.bench` are listed.
- **No linter or formatter is configured.** Match the surrounding file's style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88 column soft wrap.
- **The skill has exactly one source** (§3.4). Every other surface is rendered
  from it or points at it.
- **Never weaken a containment guard** (§4.2) to make installation easier.
  Re-anchoring one is allowed and must be stated as such.

### Verification commands

```bash
uv run pytest                              # must be green; offline, no keys
python3 -m compileall tools algorithms     # syntax smoke, mirrors CI
uv sync && uv run --locked pytest          # the lockfile is unchanged for
                                           # someone who never asks for the
                                           # optional group (C3)
git diff --check                           # whitespace
```

### Phase C0 — Baseline and inventory — **complete, 2026-09-23**

Recorded here rather than in a PR description, because C0 produced no code and
its output is what the rest of this document is written against. Measured on
`dev` at 4e99222.

- [x] **Schema payload.** 55 tools; `json.dumps(TOOL_SCHEMAS)` is **59,280
      bytes**, ~14,800 tokens. The §3.6 group table was **not** corrected: its
      15,397 / 15,242 / 12,935 / 9,808 / 5,788 sum to 59,170, and the 110-byte
      remainder is the 54 `", "` separators plus `[]` of the enclosing JSON
      list. Per module, largest first: `tools.pulsar` 11,022 (7 tools),
      `tools.hr_diagram` 9,808 (8), `tools.radio_sources` 5,788 (3),
      `tools.photometry` 5,517 (3), `tools.ads` 4,301 (4), `tools.vizier`
      3,081 (2), `tools.fieldcal_reference` 2,857 (4), `tools.simbad` 2,557
      (4), `tools.wcs` 2,406 (1), `tools.variable_star` 1,913 (5),
      `tools.optical` 1,680 (2), `tools.ned` 1,575 (1), `tools.mast` 1,104 (1),
      `tools.mpc` 949 (1), `tools.catalogs` 871 (2), `tools.calibration` 825
      (1), `tools.atnf` 787 (1), `tools.casda` 770 (1), `tools.astrometry` 561
      (1), `tools.workspace` 525 (2), `tools.resolve` 273 (1).
- [x] **`TOOL_CLASSES` still covers the registry at 26 local / 22 remote /
      7 mixed, 55 total.** `OFFLINE_PREDICATES` names the seven:
      `calibrate_zeropoint`, `fit_and_compare_hr_diagram`,
      `run_full_hr_pipeline`, `run_full_hr_pipeline_from_catalog`,
      `run_photometry_on_target`, `select_cluster_members`,
      `solve_astrometry`. `DEFAULT_BLOCKED` is `{solve_astrometry}`.
- [x] **The cwd finding of §3.2 reproduces.** Importing `tools.config` with
      cwd `/tmp` and `KEPLER_ARTIFACT_DIR` unset gives
      `ARTIFACT_DIR=/tmp/artifacts`, `DATA_DIR=<repo>/data`,
      `FITS_DOWNLOAD_DIR=<repo>/data/fits_downloads`, `ISOCHRONE_DIR=None`,
      `DEFAULT_MAX_FRAMES=200`. The artifact root follows the host's launch
      directory; the data root does not.
- [x] **`ArtifactRef` inventory.** **36 of 55** tools return a result carrying
      an `ArtifactRef`. Eight can emit *inline-able media* —
      `plot_pulsar` and `analyze_source_spectrum` / `plot_field_sed` /
      `fit_and_compare_hr_diagram` / `run_full_hr_pipeline` /
      `run_full_hr_pipeline_from_catalog` / `run_photometry_on_target` (PNG)
      and `sonify_pulsar` (WAV). The remaining 28 are *fetch-on-demand rows*
      (CSV/ECSV). Formats across `tools/`: 8 `png`, 4 `csv`, 1 `wav`, plus the
      ECSV written through `tools.artifacts.write_table`. This is C4's input.
- [x] **Data inventory for packaging.** Recorded in §3.5, which is new: 263 MB
      tracked under `data/` of which 257 MB is `data/optical/`; 364 MB of
      Girardi isochrones outside the repository; 83 GB of astrometry/ATLAS
      assets that will never be bundled; **no `MANIFEST.in` and no `data/` in
      any distribution today**; the fixture-write guard and the download root
      both re-anchor to `site-packages` under a wheel; and
      `/srv/agents/catalogs/photometry` (40 GB) is referenced by no Kepler
      code and is not a packaging input.
- [x] **Guidance inventory.** `SYSTEM_PROMPT` in `tools/agent/prompt.py` is
      the authority. It is restated in `CLAUDE.md` (PERIOD SOURCING, the
      stage-order dependency, `peak_fold_snr` over `peak_confidence`) and in
      `../pulsar-tool-pipeline.md`, and partially in tool docstrings and
      registry descriptions. C1 consolidates rather than adds a fourth copy.
- [x] **A §3 finding this track inherited is stale, and is corrected here.**
      `../analysis/applicable-designs.md` §3 records that `ToolError.code` had
      *"exactly three values in use (`invalid_input`, `provider_unavailable`,
      `dependency_missing`)"*, and that `ToolResult.warnings` was populated in
      exactly one place. An AST scan of `tools/` and `algorithms/` on
      2026-09-23 finds **41 distinct `ToolError` codes and 34 distinct
      `ToolWarning` codes**, and fifteen `ToolResult.warnings` call sites across
      seven modules. The three §3 names are real but are exactly the codes built
      as `{"code": ..., "message": ...}` **dict literals** in the class-R
      database tools; the other 38 are constructed through `ToolError(code=…)`
      and were not in that grep's view, six of them from a variable rather than
      a literal. Counting one construction form and not the others is how a
      vocabulary of 41 reads as a vocabulary of 3, and it is why C2's scan
      collects all three forms. C2 is rewritten around the real vocabulary, and
      a dated correction is filed against `../analysis/applicable-designs.md`
      §3 itself so the next reader of that document does not act on it.

**Gate:** met. Counts, payload, resolved roots and data inventory recorded
above; §3.5 added and §3.6's table confirmed rather than corrected.

### Phase C1 — The skill, rehearsed from a checkout

The hypothesis test, run in the cheap configuration before any dependency is
added. It asks the question the whole track rests on: **does this guidance work
when a model reads it as instructions rather than receives it as a system
prompt?** If the answer is no, the served-instructions design of C5 has a
different shape, and it is much better to learn that now.

- [ ] Author the skill source: an entry document plus per-domain references
      (databases, pulsar, optical, HR, radio). One source, per §3.4.
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

### Phase C2 — Close the warning and error contract — **complete, 2026-09-23**

The stated precondition of C3
([`../analysis/applicable-designs.md`](../analysis/applicable-designs.md) §5:
*"do this after §3 … otherwise the MCP surface inherits the free-text
inconsistency on day one"*).

**C0 changed this phase's shape.** §3's premise — three codes, therefore a
closed `Literal` — does not survive contact with the code: there are **41**
error codes, 34 warning codes, and six sites that build a code from a variable
(`tools/pulsar.py` re-raising `_LoadError.code` at five call sites, and
`tools/variable_star.py::_error`). A `Literal` over 41 values would be a wide,
brittle edit across a dozen modules that the dynamic sites could not satisfy
anyway, and it would buy a guarantee no caller has asked for. What the MCP
surface actually needs is that the vocabulary be **declared, stable and
non-duplicating**, and that warnings be structured like everything else.

- [x] `ToolResult.warnings` is `list[ToolWarning]`, matching every other model
      in `tools/models.py`. §3 said one call site; there were **fifteen**,
      across `tools/ads.py`, `casda.py`, `mast.py`, `ned.py`,
      `radio_sources.py`, `simbad.py` and `vizier.py`. Each string warning
      gained a code naming what it already said, and no message text changed
      except to rewrap.
- [x] The vocabulary is **declared, not typed**: `tools/codes.py` holds
      `TOOL_ERROR_CODES` (41) and `TOOL_WARNING_CODES` (49, up from 34 as the
      fifteen above became coded), each a one-line meaning.
      `tests/test_tool_codes.py` AST-scans `tools/` and `algorithms/` and fails
      in **both** directions — a code constructed but not declared, and a code
      declared but never raised. It collects all three construction forms
      (direct, dict-literal, and the two module-local helpers that take a code
      positionally), and a fourth assertion fails if a *new* dynamic site
      appears that `_INDIRECT` does not name.
- [x] `tools.codes` added to `NOT_TOOL_MODULES` in the same commit.
- [x] The recorded bench fixtures migrated with it. They carried warnings as
      bare strings with the identifier smuggled into the message prefix —
      `search_atnf.yaml` said so in a comment — because `ToolResult` had
      nowhere to put a code. Fourteen fixture warnings across eleven files now
      carry `{code, message}`, the message text preserved. Grading is
      unaffected: `raised_signal` matched such a prefix as a message substring
      and now matches it as a code, so `report.json`'s 144 sessions stay
      comparable. Three grader docstrings that asserted the old asymmetry were
      corrected; no `tools/bench/` behaviour changed.
- [x] A dated correction filed against `../analysis/applicable-designs.md` §3
      rather than a rewrite of a dated analysis. Recommendation 1 there —
      promote `code` to a `Literal` over three values — was **not** taken:
      41 values, six of them dynamic, is not a closed literal, and the
      reasoning is recorded in `tools/codes.py`'s docstring.
- [x] No code invented speculatively and none merged. Every code added names a
      warning that already existed in prose.

**Gate:** met. `uv run pytest` is green — **2,579 passed, 44 skipped**, still
socket-free — `python3 -m compileall tools algorithms tests` clean, and
`git diff --check` clean. The declared vocabulary matches the AST scan exactly
in both directions, and the scan is a test.

### Phase C3 — The server, generated from the registry, from a checkout

- [ ] `tools/mcp/` — one server, constructed from
      `TOOL_SCHEMAS`/`TOOL_FUNCTIONS`. Add `tools.mcp` to `NOT_TOOL_MODULES`
      in the same commit.
- [ ] Pick and justify the dependency option from §3.8 in the PR. If the SDK:
      a new `[project.optional-dependencies]` group, and demonstrate that a
      plain `uv sync` + `uv run --locked pytest` is unchanged.
- [ ] Results serialise through the Pydantic models already returned; prefer
      structured output where the protocol supports it. C2 is what makes the
      warning and error shapes worth serialising.
- [ ] **Resolve and pin `KEPLER_ARTIFACT_DIR` and `KEPLER_DATA_DIR` at
      startup** (§3.2), and state in the PR which root the artifact directory
      was pinned to and why. Log both at startup; a user must be able to see
      where artifacts are going without reading code.
- [ ] A test asserting the served tool list equals the registry's, so a
      registry addition cannot silently miss the surface.
- [ ] `kepler-mcp` in `[project.scripts]`, alongside `kepler` and
      `kepler-bench`.

**Gate:** a host connects over stdio **from a working directory outside this
repository**, lists tools, and completes one local call (`list_pulsar_scans`)
and one remote call against a real service. Transcript and resolved roots in
the PR. `uv run pytest` green and still socket-free.

### Phase C4 — Media inline, and the artifact directory made discoverable

§3.1, reduced to what the local caller actually needs.

- [ ] Return media inline for the eight tools C0 identified — the pulsar plot
      and sonification above all. A model handed a path to audio it cannot open
      has not heard anything.
- [ ] Leave the `ArtifactRef` contract otherwise as it is: the path works,
      because the caller shares the filesystem. Do not add resource URIs
      speculatively (§4.3).
- [ ] Keep row-oriented artifacts fetch-on-demand. `PREVIEW_ROWS` and the
      `KEPLER_MAX_*` caps are **not** relaxed to compensate.
- [ ] Promote `describe_artifact` and `list_artifacts` and say in their
      descriptions which directory they enumerate and that the server pinned
      it at startup.
- [ ] Extend the skill source: where artifacts are written, that a preview is a
      sample and never the answer, and how to read the full table.

**Gate:** a host connected to a server launched outside this repository
receives a sonification it can play and a plot it can see, and reads a full
VizieR result set off the artifact path. Transcript in the PR.

### Phase C5 — The skill served with the server

- [ ] Render the server's instructions from the C1 skill source; the
      always-delivered text stays small.
- [ ] Publish the per-domain references as resources the client reads on
      demand.
- [ ] A test asserting the served text and the `skills/kepler-tools/` copy are
      rendered from the same source and agree.
- [ ] The instructions state the install's reality: which data bundles are
      present, that artifact paths are local to this machine, and that the
      credentials in use are the user's own.

**Gate:** a fresh agent session against the server alone — **no checkout, no
skill file on the client** — passes C1's gate: a pulsar run end to end with the
period's provenance reported correctly on both a scan where blind search
succeeds and one where it does not.

### Phase C6 — Tool groups and annotations

- [ ] Declare the five groups of §3.6 in one module, with a test asserting they
      partition the registry exactly — every tool in exactly one group.
- [ ] `--tools` / `KEPLER_MCP_TOOLS` filters the served surface to named
      groups; the default is all 55.
- [ ] Generate `openWorldHint` and `readOnlyHint` from `TOOL_CLASSES` — read the
      mapping, never restate it.
- [ ] Each group's documented description states whether it runs with no data
      bundle present (§3.6, right column).
- [ ] Record each group's measured schema payload in the PR against C0's
      numbers.

**Gate:** the five payloads sum to C0's 59,170 (plus the list separators), no
group exceeds ~4,000 tokens, and `--tools databases` serves exactly 16 tools.

### Phase C7 — Packaging, and the data bundles

The phase the hosting decision created. §3.5 is its specification.

- [ ] Ship the core data inside the distribution: `data/pulsar/`,
      `data/fieldcal/`, `data/afterglow/` (~7 MB). A bare install must run the
      whole pulsar chain and the field-calibration replay with no download and
      no network.
- [ ] **Re-anchor the two guards** (§4.2, §3.5) so the fixture-write refusal
      protects the *installed* fixture tree and `FITS_DOWNLOAD_DIR` defaults to
      a user-writable directory rather than the install tree. State in the PR
      that this re-anchored rather than weakened them, and extend the existing
      tests to an installed layout.
- [ ] `kepler-mcp fetch-data` for the optional bundles — the optical frame
      library and the isochrone grid — into a user-writable directory,
      checksum-verified, idempotent, resumable enough to survive a dropped
      connection. It must never write into the installed package.
- [ ] A tool whose bundle is absent **says so**: a declared warning code, not
      an empty listing that reads like a real answer.
- [ ] Verify a clean install end to end: a fresh virtual environment, `pip
      install` the built wheel, launch the server, list tools, run
      `list_pulsar_scans` and one full pulsar chain. **Record installed size
      and cold-import time** (§4.5).
- [ ] Document the setup: which environment variables, which bundle each tool
      needs, what stays operator-supplied and therefore unavailable
      (astrometry.net indexes, ATLAS UCAC5) and what that looks like when it is.

**Gate:** a wheel installed into a clean environment on a machine with no
checkout serves the tools, runs the pulsar chain offline, refuses a write into
its own installed fixture tree, and fetches the optical bundle on request.

### Phase C8 — The GitHub release track

Testing distribution, per the maintainer's answer to §7.4.

- [ ] A release workflow that builds the wheel and the source distribution,
      publishes the optional data bundles as **release assets** with their
      checksums, and attaches both to a tagged pre-release.
- [ ] `secret-scan.yml` and `workflow-safety.yml` cover the new workflow;
      actionlint and zizmor stay green, and the workflow takes the narrowest
      permissions that work.
- [ ] Version and tag policy: what a pre-release means here, and how
      `fetch-data` resolves which bundle version matches an installed Kepler.
      A wheel fetching a mismatched bundle is a silent-wrong-answer bug of
      exactly the kind this track exists to prevent.
- [ ] Install from the release on a machine that is not the development host
      and repeat C7's gate there.

**Gate:** a tagged pre-release from which a tester installs Kepler, registers
the server with their own console, and completes a pulsar run.

### Phase C9 — Documentation outcome

- [ ] `../tool-architecture.md` gains a section for the MCP surface beside §10
      (agent loop), §10.1 (benchmark) and §10.2 (console) — a fourth consumer
      of one registry, with §7's "serving is optional" sentence cited as what
      authorised it.
- [ ] `../repository-folders.md` gains `tools/mcp/` and `skills/`.
- [ ] `CLAUDE.md` gains the dependency direction — `tools/mcp → tools/registry`,
      and **`tools/mcp/` imports nothing from `tools/agent/` or `tools/llm/`** —
      beside the existing one-way rules, plus the data-bundle layout of §3.5.
- [ ] `README.md` documents installing the package, fetching the bundles, and
      registering the server with a host.
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
| `.github/workflows/release.yml` | C8 |

| Path | Change |
| --- | --- |
| `AGENTS.md`, `CLAUDE.md` | C1: one pointer line each. C9: dependency direction and bundle layout. |
| `tools/models.py` + `ads`/`casda`/`mast`/`ned`/`radio_sources`/`simbad`/`vizier` | C2: `ToolResult.warnings` becomes `list[ToolWarning]`; fifteen call sites coded. |
| `tools/codes.py`, `tests/test_tool_codes.py` | C2: the declared vocabulary and its drift scan. |
| `benchmarks/fixtures/*.yaml` | C2: fourteen recorded warnings migrated to `{code, message}`. |
| `tools/bench/graders/__init__.py` | C2: three docstrings correcting the old `list[str]` asymmetry. No behaviour change. |
| `docs/analysis/applicable-designs.md` | C2: a dated correction to §3's "exactly three values". |
| `tests/test_tool_registry_coverage.py` | C2: `tools.codes` in `NOT_TOOL_MODULES`. C3: `tools.mcp`. |
| `pyproject.toml` | C3: optional-dependency group and the `kepler-mcp` entry. C7: package data. |
| `tools/config.py`, `tools/wcs.py` | C7: re-anchor the download root and the fixture-write guard for an installed layout. |
| `docs/tool-architecture.md`, `docs/repository-folders.md`, `README.md` | C9. |

**Deliberately not touched:** anything under `algorithms/`; `tools/tui/`;
`tools/bench/`; `tools/llm/`; `tools/agent/` — including `prompt.py` and
`tools/registry.py`, which this track reads and does not edit.
The CI `repository-shape` job's seven asserted paths all survive; nothing here
deletes `tools/registry.py`, `tools/agent/engine.py` or `tools/tui/app.py`.

---

## 7. The maintainer's answers

Recorded 2026-09-23. These are the decisions §§1, 3.1, 3.3, 3.5, 3.6, 4.1 and
the phase list are written against; they are not open.

1. **Hosting model — local.** The user installs a packaged Kepler containing
   the data it needs. No Kepler-operated server, no data service. The
   consequence is §3.5: the data problem becomes a packaging problem, and it is
   the hardest one left in the track.
2. **Who installs — the user.** Their machine, their disk, their keys. This is
   what deletes the credential-isolation and server-ceiling requirements from
   the old C7 (§4.1).
3. **Server count — one.** Five workflow groups collapse to one server with a
   launch-time `--tools` filter (§3.6). The partition invariant the five-server
   plan was really buying is kept as a test; the five entry points, five host
   registrations and five sets of instructions are not.
4. **Transport — stdio only.** No HTTP, no network authentication. A **GitHub
   release track** follows the rollout for testing, and is now phase C8.

### Still to decide, inside a phase rather than ahead of it

- **C3:** which root the artifact directory pins to — the host's launch
  directory (artifacts land in the user's project, where their agent already
  looks) or a fixed per-user directory (stable, but somewhere they have to be
  told about). Decided in the PR, stated in the server's startup log either way.
- **C3:** the §3.8 dependency choice, recommendation recorded.
- **C7:** whether the optical frame library ships as one 257 MB bundle or is
  split further. Three 30 MB `ngc5286_globular_b` frames are a third of
  `data/optical/` between them.
