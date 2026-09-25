# Renaming Kepler to MARS

**Status:** Proposal, 2026-09-25. Names decided by the maintainer: the
distribution and repository are **`skynet-mars`** (§1). The repository is
renamed (`kepler` → `mars-suite` → `skynet-mars`, all on 2026-09-25), and both
earlier names redirect (§3). All
questions in §6 are decided. No phase started; R4 waits for the logo files.
**Prerequisites:** The MCP tool-surface track, complete and archived
(`../archive/mcp-tool-surface.md`), and the maintainer's logo files (§4).
**Unblocks:** Every public surface — package, commands, repository, releases,
docs — carrying the new name before a wider release.

This document is architecture and sequencing. It contains no implementation
code.

> [!note] Written against `mcp-support`
> This plan was measured and written on the `mcp-support` branch at
> `b0388e0`, where the MCP tool-surface track is complete, and committed to
> `dev` ahead of that branch. `mcp-support` has since merged into `dev`, so its
> links into `../archive/` and its references to `tools/mcp/`, `tools/skill/`
> and `tools/paths.py` resolve. The rollout starts from the merged state.

---

## 1. The names

**MARS — MCP Astronomy Research Suite.** Decided 2026-09-25.

| Surface | Name | Why this form |
| --- | --- | --- |
| Brand: prose, titles, README, logo | **MARS**; spelled out once per document as *MCP Astronomy Research Suite* | An acronym. The capitals are what separate it from the planet, which matters in an astronomy tool. |
| Distribution (`pyproject.toml` `name`; the future PyPI release) | **`skynet-mars`** | `mars` is taken on PyPI (an unrelated "Agentic TUI"), and Alibaba's `pymars` imports as `mars`, so the distribution needs a qualifier. The qualifier must add something the acronym does not already say, and `skynet-` adds provenance: the algorithms are extracted from the Skynet Robotic Telescope Network. Rejected: `mars-suite` ("…Research Suite suite", briefly chosen and then dropped), `mars-mcp`, `mars-astro` and `mars-research`, which restate the acronym; `mars-sky` and `mars-observatory`, which read as the planet's sky; `mars-ai`, `unc-mars` and `mars-core`, the runners-up. |
| Repository | **`archon774/skynet-mars`**, renamed 2026-09-25 | Matching the distribution gives one name to search and an obvious install URL. |
| Commands | **`mars`** (the console), **`mars-mcp`**, **`mars-bench`** | Lowercase, per convention. |
| MCP server name (`Implementation.name`, the host's `mcpServers` key) | **`mars`** | |
| Agent skill | **`mars-tools`** | |
| Skill resources | **`mars://skill/...`** | |
| Environment variables | **`MARS_*`** | Capitals are the env-var convention anyway. |
| Per-user home | **`~/.local/share/mars`** (macOS `~/Library/Application Support/mars`, Windows `%LOCALAPPDATA%\mars`), or `MARS_HOME` | |

---

## 2. What "Kepler" means in this repository today

Measured on `mcp-support` at `b0388e0`: 1,234 lines in 228 tracked files.

**None of them refers to the Kepler space telescope.** A search for the
mission, the Kepler Input Catalog, K2, Kepler's laws and "Keplerian" finds
only the project's own name. That is what makes a mechanical rename safe — and
why phase R3 adds a guard. A future tool that queries the Kepler mission's
data must be able to say "Kepler" without a rebrand test objecting, and
nothing may rename it by accident.

The occurrences fall into four classes, and each is treated differently:

| Class | Examples | Treatment |
| --- | --- | --- |
| **Interfaces** people type or configure | `kepler`, `kepler-mcp`, `kepler-bench`; 22 `KEPLER_*` variables (`KEPLER_ARTIFACT_DIR` 26×, `KEPLER_OPTICAL_DATA_DIR` 28×, `KEPLER_MODEL_BACKEND` 21×, …); `~/.local/share/kepler`; `kepler://skill/`; the `kepler-tools` skill; server name `"kepler"`; distribution `kepler` | Renamed, with compatibility where a user could already depend on it (§6.3). |
| **Code identifiers** | `KeplerApp` (78×), `KeplerToolModel` (34×), `KeplerBaseModel` (18×), `KeplerHeader`, `KeplerSDSS` | Renamed. They are this project's own names, not upstream symbols. |
| **Prose** | docstrings, comments, README, `docs/`, `CLAUDE.md`, `AGENTS.md`; the project name inside `algorithms/` provenance comments ("In Kepler the …", "PORTED from the Kepler TypeScript extraction") | Renamed. The `# EXTRACTED: was <symbol>` markers keep their `was <symbol>` part exactly: it names an *upstream* symbol, and the markers are the index of what was cut. |
| **Recorded evidence** | `docs/archive/`, `docs/analysis/` (dated), `docs/benchmarking/report.json` and its figures (which record real paths such as `/home/claude/Kepler/artifacts/...`), the vault's history | **Not rewritten.** A record says what was true when it was made. Each gets a one-line dated note at the top where it would confuse a reader. |

Two generated artefacts change by regeneration, not by hand:
`tests/fixtures/llm/schemas/*.json` (`KEPLER_REGEN_SCHEMA_GOLDEN`) and
`skills/mars-tools/` (`python -m tools.skill`).

---

## 3. Things that already exist outside this repository

- **The repository was renamed from `kepler` to `archon774/mars-suite` on
  2026-09-25**, before `skynet-mars` was chosen, and the redirects were
  verified the same day. `github.com/archon774/kepler` redirects to the new
  repository. The `v0.1.0rc1` wheel and the `data` bundle, requested by their
  old `…/kepler/releases/download/…` URLs, both redirect to GitHub's asset
  host and answer a Range request with `206`, so existing installs still
  fetch and resume. **The second rename, to `archon774/skynet-mars`, was done
  the same day and re-verified.** Both `kepler` and `mars-suite` redirect: the
  repository, the `v0.1.0rc1` wheel, and both `data` bundles, each answering
  `206`. That holds **as long as neither `kepler` nor `mars-suite` is ever
  reused**. The checkout's `origin` points at `skynet-mars`.
- **`v0.1.0rc1` is published** under the distribution name `kepler`, and its
  `bundles.json` pins `https://github.com/archon774/kepler/releases/download/data/…`.
  GitHub redirects a renamed repository's URLs — git remotes, pages and
  **release-asset downloads** — to the new name. So that wheel keeps
  installing and keeps fetching its bundles, **as long as no new repository is
  ever created under the old name `kepler`.** Keep that name unused.
- **The `data` release's assets keep their names and bytes.**
  `kepler-optical-0472c67e2f46.tar` and `kepler-isochrones-12f8359efc78.tar`
  are content identifiers, and `docs/releasing.md` says a published name
  always means the same bytes. MARS's manifest points at the same assets under
  the new repository URL. Nothing is re-uploaded, and old and new wheels share
  one set of bundles.
- **Users' machines** may have `~/.local/share/kepler` (artifacts, fetched
  bundles, downloads), `KEPLER_*` in their shell or host configuration, and a
  host entry launching `kepler-mcp`. §6.3 decides how gently to meet them.
- **The shared vault** (`[[Kepler MCP Tool Surface]]` and related notes) and
  the local checkout directory. Renamed last, through their own workflows.

---

## 4. The logo

The only branding in the repository today is the README banner:
`docs/assets/kepler-banner-{light,dark}.svg`, 880×108, swapped by
`prefers-color-scheme`. The rebrand needs:

| Use | Asset |
| --- | --- |
| README banner | Wide wordmark, **SVG, light and dark** (or PNG at 1760×216) |
| MCP server icon (`Implementation.icons`: `src`, `mime_type`, `sizes`, `theme`), shown by hosts beside the server's name | Square mark, **SVG plus PNG 64×64 and 128×128**, light and dark if needed. It must read at 16–32 px. |
| GitHub social preview (repository settings, not committed) | **PNG 1280×640**, under 1 MB |

Master files — SVG or design source — for the wordmark and the mark, with a
transparent background, let every other size be exported rather than redrawn.

---

## 5. Rollout

Phases **R1–R6**, one PR each against `mcp-support`. Every phase ends with the
default suite green on Python 3.13, with and without `[mcp]`.

### R1 — Identity: the distribution, commands, server and skill

- `pyproject.toml`: `name = "skynet-mars"`, version **`0.1.0rc2`** (§6.4).
  Scripts `mars`, `mars-mcp` and `mars-bench`, with `kepler`, `kepler-mcp`
  and `kepler-bench` kept as deprecated aliases (§6.3). `uv lock`.
- MCP server name `mars`; resources `mars://skill/...`; skill `mars-tools`
  (source unchanged, rendered copy and `.claude/skills/` link renamed).
- The version comes from package metadata, which changes with the
  distribution name. `_package_version()` reads `skynet-mars`.

**Gate:** a wheel named `skynet_mars-…` installs, and `mars-mcp self-test`
passes on it.

### R2 — Environment and paths

- `MARS_*` for every variable, and `MARS_HOME` with the `mars` per-user home.
- Compatibility per §6.3: a `KEPLER_*` value is honoured when its `MARS_*`
  twin is unset, and the server logs a deprecation line naming both.
  A user with `~/.local/share/kepler` and no `mars` home is told, once, what
  to move. Nothing is moved automatically, because a fetched bundle is
  hundreds of megabytes of the user's disk.
- `tests/test_mcp_surface.py`'s roots tests and the `tools.config` tests are
  extended to both names.

**Gate:** an install with only `KEPLER_*` set behaves as it did (per §6.3),
and one with `MARS_*` set ignores `KEPLER_*`.

### R3 — Code identifiers and prose

- Rename `KeplerApp`, `KeplerToolModel`, `KeplerBaseModel`, `KeplerHeader`,
  `KeplerSDSS` and their references, and every prose mention outside the
  records of §2.
- `algorithms/`: the project name in prose only. `# EXTRACTED: was …`
  markers keep their upstream symbol verbatim. No algorithm, constant or
  preserved bug changes. This is the one phase that edits `algorithms/`, and
  its PR says so.
- A **guard test**: no `kepler`, case-insensitive, outside an allowlist. The
  allowlist is the records of §2, the compatibility shims of R2, and a
  documented exemption for the Kepler *mission*, so a future tool can name the
  telescope.

**Gate:** the guard passes, and `git grep -i kepler` returns only allowlisted
paths.

### R4 — Documentation and the logo

- README (banner, title, the MCP section's install lines), `docs/*.md`,
  `CLAUDE.md`, `AGENTS.md`, `docs/installing.md`, `docs/releasing.md`.
- The logo assets of §4 committed under `docs/assets/`, and the square mark
  wired into the server's `Implementation.icons`.
- A dated one-line note at the top of each record in §2 that names the old
  project, saying it was renamed MARS on the date.

**Gate:** no dead links; the banner renders in both schemes; a host shows the
server's icon (or the PR records which hosts ignore `icons`).

### R5 — Repository and release

- ~~**Maintainer action:** rename the repository to `skynet-mars`, and
  confirm that both earlier names redirect.~~ **Done and verified
  2026-09-25** (§3).
- `bundles.json` URLs and every `archon774/kepler` reference move to the new
  repository. The assets stay as they are (§3).
- Tag the first MARS pre-release. The workflow publishes `skynet-mars`.

**Gate:** from a clean container, `pip install "skynet-mars[mcp] @ <release
URL>"`, then `mars-mcp self-test` and `mars-mcp fetch-data optical`.
Separately, `v0.1.0rc1` (`kepler`) still installs and fetches through the
redirect.

### R6 — Outside the repository

- The shared vault: rename `[[Kepler MCP Tool Surface]]` and related notes
  through the vault's own transaction workflow, keeping an alias for the old
  name.
- Optionally, the local checkout directory. It is named in this machine's
  agent memory paths and the vault, so change it deliberately or not at all.

---

## 6. Decisions

All decided by the maintainer on 2026-09-25.

1. **Distribution and repository: `skynet-mars`.** `mars-suite` was chosen
   first, and the repository renamed to it, but it restates the acronym
   ("…Research Suite suite"). `skynet-mars` replaced it the same day, and the
   repository was renamed to it (§3).
2. **The import namespace moves later, in its own track.** `tools` and
   `algorithms` stay top-level packages through this rebrand. They are
   generic enough that another installed project's `tools` package collides
   with them, and moving them under one namespace (`mars.tools`,
   `mars.algorithms`) is the durable fix. But it touches every import, test and
   extraction marker, and it stays reviewable only as a change of its own.
   R3's guard therefore permits no new top-level package.
3. **Kepler names become deprecated aliases for one pre-release** (R2):
   - `KEPLER_*` is honoured when its `MARS_*` twin is unset, and the server
     logs a deprecation line naming both;
   - the `kepler`, `kepler-mcp` and `kepler-bench` commands remain, as aliases
     that print the new name;
   - a leftover `~/.local/share/kepler` with no MARS home is pointed out once
     and never moved.

   All of it is removed in the release after `0.1.0rc2`. Only the
   compatibility shims are allowlisted by R3's guard, and each carries its
   removal version.
4. **The first MARS version is `0.1.0rc2`**, continuing the series: the next
   candidate of the same software, under its new name. Testers compare it
   directly with `0.1.0rc1`. On PyPI, `skynet-mars` and `kepler` are different
   projects, so nothing clashes.
