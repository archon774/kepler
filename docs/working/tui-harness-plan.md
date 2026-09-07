# Kepler TUI Harness Implementation Plan (Phases B-G)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `kepler-astro-query` and the standalone photometry script with a
single Textual console (`kepler`) driving the headless engine in `tools/agent/`.

**Architecture:** `tools/agent/` emits typed events as an iterator and takes
approval decisions as a callable; it imports no UI code. `tools/tui/` is the only
package that imports `textual`, and runs the synchronous engine inside a Textual
thread worker, forwarding each event to the UI thread with `post_message`.

**Tech Stack:** Python 3.14 (project floor: 3.12), `textual==8.2.8`, `textual-image==0.13.2`,
`rich==15.0.0` (+4 transitive), `pillow==12.3.0` (already pinned),
`pytest==9.0.3`. Eight new pins, confined to `tools/tui/`.

**Spec:** `docs/working/tui-harness-design.md` -- read sections 4-9 and 11-14
before starting.

**Phase A is not in this plan.** It is `model-port-plan.md` Task 5, amended to
build `tools/agent/{events,prompt,engine}.py` and leave `tools/runner.py` as a
shim. That amendment is recorded in this plan's section "Phase A dependency"
below and in `tui-harness-design.md` section 14.1.

**Status:** Approved; implementation pending.

**Prerequisites:** [model-port-plan.md](model-port-plan.md) phases -1 to 3, and the merged [stateless-optical-tools-rollout-plan.md](stateless-optical-tools-rollout-plan.md).

**Unblocks:** The Textual `kepler` console and retirement of its legacy entry points.

---

## Global Constraints

Copied from the spec and `CLAUDE.md`. Every task's requirements implicitly
include this section.

- **The zero-dependency rule is scoped, not lifted.** `tools/llm/` and
  `tools/agent/` take no new dependencies. `tools/tui/` is the only package that
  may, and the only package that may import `textual`.
- **`tools/agent/` never imports `tools/tui/`, `textual`, or `rich`.** A test
  asserts this (Task 2, Step 6). It is what keeps every tool callable from plain
  Python per `docs/tool-architecture.md` section 7.
- **Branch:** `agent/tui-harness`, off `dev`. `CLAUDE.md` defaults to `dev`; do
  not retarget to `main`.
- **One PR per task**, narrow. Documentation, workflow, dependency, and behaviour
  changes stay in separate PRs (`CLAUDE.md`).
- **No linter or formatter is configured.** Match the surrounding file's style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88 column soft wrap.
- **Default checks stay offline and deterministic.** Nothing added by this plan
  may open a socket under a plain `uv run pytest`, and nothing may require a real
  terminal. Textual's `run_test()` pilot is headless.
- **No changes to `algorithms/`.** The extraction contract is untouched. Do not
  edit any file carrying an `# EXTRACTED:` or `# PORTED:` marker.
- **`tests/test_tool_registry_coverage.py` enumerates `pkgutil.iter_modules`,
  which yields packages as well as modules.** Verified. Every task that adds
  `tools/agent/`, `tools/tui/`, or `tools/photometry_pipeline.py` MUST update
  `NOT_TOOL_MODULES` in the same commit or that test fails.
- **`SYSTEM_PROMPT` is never rewritten in passing.** It is ~270 lines of
  confirmed-live failure-mode guidance and the source of all eight benchmark seed
  tasks (`model-backends-and-benchmarking.md` section 6.2). Move it; do not edit it.

### Verification commands

```bash
uv run pytest                             # must be green; offline, no keys
python3 -m compileall tools algorithms    # syntax smoke, mirrors CI
git diff --check                          # whitespace
uv run pytest tests/test_tool_registry_coverage.py -v
```

---

## Phase A dependency

Every task from Task 2 onward requires `tools/agent/` to exist, providing:

```python
# tools/agent/events.py
SessionStarted(session_id, manifest_path, backend_spec, model)
TurnStarted(turn)
TextDelta(text)
ToolCallProposed(call_id, name, arguments)
ToolCallStarted(call_id, name, arguments, cache_hit)
ToolCallFinished(call_id, name, result, artifacts, duration_ms)
ToolCallDenied(call_id, name, reason)
ProtocolFault(turn, type, detail)
TurnFinished(turn, stop_reason, usage, latency_ms)
SessionFinished(outcome, manifest_path)
Event = SessionStarted | TurnStarted | ... | SessionFinished

# tools/agent/engine.py
def run_session(
    user_message: str, *, backend, system=SYSTEM_PROMPT, max_turns=20,
    approver=auto_approve, session=None,
) -> Iterator[Event]: ...

# tools/agent/prompt.py
SYSTEM_PROMPT: str          # moved verbatim from tools/runner.py:46
```

**Task 1 is independent of Phase A** and of the model port entirely. It ships
first, while the port is still in progress.

---

## File Structure

**Created by this plan:**

| Path | Responsibility |
| --- | --- |
| `tools/agent/policy.py` | Tool risk tags, `Decision`, `Approver`, `auto_approve`, `policy_approver`. No UI. |
| `tools/tui/__init__.py` | Package marker. Exports nothing heavy. |
| `tools/tui/__main__.py` | Console-script entry: argument parsing, backend construction, `KeplerApp().run()`. |
| `tools/tui/app.py` | The `App`: layout, keybindings, the engine thread worker, approval modal. |
| `tools/tui/commands.py` | Slash-command registry and dispatch. No Textual imports beyond types. |
| `tools/tui/widgets/transcript.py` | Scrollable transcript; assistant text and tool nodes. |
| `tools/tui/widgets/tool_node.py` | One collapsible tool call: spinner, timer, result, artifacts. |
| `tools/tui/widgets/artifacts.py` | Artifact browser modal screen. |
| `tools/tui/widgets/sessions.py` | Session history browser modal screen. |
| `tools/tui/render/capability.py` | Terminal graphics capability probe. |
| `tools/tui/render/image.py` | Half-block PNG renderer; native-protocol delegation. |
| `tools/tui/render/waveform.py` | Braille waveform for WAV artifacts. |
| `tools/photometry_pipeline.py` | Renamed from `claude_photometry_haiku_tool.py`, Anthropic path removed. |
| `tests/test_agent_policy.py` | Risk tags, decisions, the approver contract. |
| `tests/test_agent_no_ui_imports.py` | `tools.agent` imports no UI package. |
| `tests/test_tui_commands.py` | Slash-command registry, `//` escaping, unknown commands. |
| `tests/test_tui_app.py` | Textual `run_test()` pilot over the app. |
| `tests/test_tui_render.py` | Capability probe and half-block renderer. |
| `tests/fixtures/tui/probe_4x4.png` | Committed 4x4 PNG golden for the renderer. |

**Modified by this plan:**

| Path | Change |
| --- | --- |
| `tools/claude_photometry_haiku_tool.py` | Task 1: renamed; Anthropic path and CLI deleted. |
| `tools/photometry.py:41` | Task 1: import path. |
| `tools/optical.py` | Task 1: import path. |
| `tests/test_photometry_tool_smoke.py` | Task 1: import path; CLI subprocess test removed. |
| `tests/test_photometry_registry_smoke.py:8` | Task 1: import path. |
| `tests/test_optical_registry.py:121,130` | Task 1: import path. |
| `tests/test_tool_registry_coverage.py` | Tasks 1, 2, 3, 8: `NOT_TOOL_MODULES`. |
| `pyproject.toml` | Task 3: eight pins. Task 8: console scripts. |
| `uv.lock` | Task 3: regenerated. |
| `.github/workflows/ci.yml:67` | Task 9: drop `tools/runner.py`, add the new paths. |
| `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/*.md` | Task 10: documentation sweep. |

**Deliberately not touched:** `tools/registry.py` (adding risk tags to the schemas
would change the golden schema fixtures port phase 1 commits in four dialects),
anything under `algorithms/`.

---

## Task 1: Rename the photometry pipeline and delete the Anthropic path

Ships as the first TUI-scoped PR, after the stateless optical rollout merges. It
is independent of the model port and of Phase A once that prerequisite is
satisfied, and it removes the repository's second Anthropic caller. It must
retain the stateless tool boundary rather than preserving or reintroducing
processing-run or batch orchestration.

**Files:**
- Rename: `tools/claude_photometry_haiku_tool.py` -> `tools/photometry_pipeline.py`
- Modify: `tools/photometry.py:41`, `tools/optical.py`,
  `tests/test_photometry_tool_smoke.py`, `tests/test_photometry_registry_smoke.py:8`,
  `tests/test_optical_registry.py:121,130`, `tests/test_tool_registry_coverage.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `tools.photometry_pipeline` exporting every symbol the old module
  exported **except** `API_URL`, `API_VERSION`, `parse_args`,
  `build_claude_prompt`, `call_claude_haiku`, `main`.

**Context.** Of 1,270 lines, only ~270 are the Anthropic path and CLI. The rest is
a photometry and plotting pipeline that `tools/photometry.py` imports seven
symbols from and that two registered tools depend on. `docs/tool-architecture.md:141`
documents the relationship. The rename makes the module name honest; the deletion
removes the second raw-HTTP Anthropic caller that
`model-backends-and-benchmarking.md` section 10 deferred.

**`summarize_results` and `render_credits_card` are NOT deleted.** Both are
non-LLM (a numeric summary and a matplotlib credits card) and both are used by
`tests/test_photometry_tool_smoke.py:19,22`. Verified before writing this task.

- [ ] **Step 1: Record the current state so the diff is checkable**

```bash
uv run pytest tests/test_photometry_tool_smoke.py tests/test_photometry_registry_smoke.py \
  tests/test_optical_registry.py tests/test_tool_registry_coverage.py -q
grep -rn 'claude_photometry_haiku_tool' --include='*.py' tools/ tests/
```

Expected: all four test files green; the grep lists exactly `tools/photometry.py`,
`tools/optical.py`, and the three test files. If the grep finds more, add them to
Step 3 rather than following this plan blindly.

- [ ] **Step 2: Rename the module with history preserved**

```bash
git mv tools/claude_photometry_haiku_tool.py tools/photometry_pipeline.py
```

- [ ] **Step 3: Update every import site**

```bash
grep -rl 'claude_photometry_haiku_tool' --include='*.py' tools/ tests/ \
  | xargs sed -i 's/claude_photometry_haiku_tool/photometry_pipeline/g'
grep -rn 'claude_photometry_haiku_tool' --include='*.py' tools/ tests/
```

Expected: the second grep prints nothing.

- [ ] **Step 4: Delete the Anthropic path and the CLI**

In `tools/photometry_pipeline.py`, delete exactly these, and nothing else:

| Symbol | Why |
| --- | --- |
| `API_URL`, `API_VERSION` | The raw Anthropic endpoint. |
| `parse_args()` | The retired CLI. |
| `build_claude_prompt()` | Builds the Anthropic request body. |
| `call_claude_haiku()` | Posts to the Anthropic API. |
| `main()` and the `if __name__ == "__main__":` block | The retired CLI. |
| `import argparse`, `import requests` | Now unused. |

Keep `summarize_results` and `render_credits_card`.

Replace the module docstring with:

```python
"""FITS photometry and plotting pipeline.

Loads a FITS image, runs source extraction and photometry through
``algorithms.photometry``, resolves a zero point, and renders the plots.

``tools.photometry`` and ``tools.optical`` are the registered tool wrappers over
this module; this is the implementation they share, not a reimplementation of it
(``docs/tool-architecture.md`` section 2).

Formerly ``tools/claude_photometry_haiku_tool.py``. The Claude summarisation path
and its ``argparse`` CLI were removed when the TUI became the only model-driven
entry point; see ``docs/working/tui-harness-design.md`` section 12.
"""
```

- [ ] **Step 5: Remove the CLI subprocess test**

`tests/test_photometry_tool_smoke.py::test_check_only_cli_resolves_bundled_subject`
(line 84) runs the module as a subprocess with `--check-only`. The CLI it tests no
longer exists, so the test goes with it. Delete that function and the now-unused
`subprocess` and `sys` imports if nothing else in the file uses them.

Its coverage is not lost: `resolve_fits_path` resolving a bundled subject is
already asserted by `tests/test_photometry_registry_smoke.py:8` and
`tests/test_optical_registry.py:121,130`. Confirm that before deleting:

```bash
grep -n 'resolve_fits_path' tests/test_photometry_registry_smoke.py tests/test_optical_registry.py
```

- [ ] **Step 6: Update the module-coverage allowlist**

In `tests/test_tool_registry_coverage.py`, `NOT_TOOL_MODULES`, replace the
`tools.claude_photometry_haiku_tool` entry:

```python
    # The shared photometry/plotting implementation; its public surface is
    # re-exported through tools.optical and tools.photometry instead.
    "tools.photometry_pipeline",
```

- [ ] **Step 7: Verify**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
grep -rn 'ANTHROPIC_API_KEY' tools/photometry_pipeline.py    # expect: nothing
git diff --check
```

Expected: suite green; no `ANTHROPIC_API_KEY` reference remains in the renamed
module, so it needs no `.gitleaks.toml` allowlist entry.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(tools): rename the photometry pipeline, drop its Claude path

claude_photometry_haiku_tool.py was ~270 lines of Anthropic call and CLI
wrapped around ~1,000 lines of photometry and plotting that
tools/photometry.py imports seven symbols from and two registered tools
depend on. The name described the smaller half.

Renamed to tools/photometry_pipeline.py and deleted the Anthropic path:
API_URL, API_VERSION, build_claude_prompt, call_claude_haiku, parse_args,
and main. summarize_results and render_credits_card are numeric and
plotting helpers, not LLM code, and are kept.

The --check-only CLI smoke test goes with the CLI; resolve_fits_path
coverage remains in test_photometry_registry_smoke and
test_optical_registry.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Approval policy (Phase B)

**Files:**
- Create: `tools/agent/policy.py`
- Test: `tests/test_agent_policy.py`, `tests/test_agent_no_ui_imports.py`
- Modify: `tests/test_tool_registry_coverage.py`

**Interfaces:**
- Consumes: `tools.agent.events.ToolCallProposed` (Phase A).
- Produces:

```python
class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"

RiskTag = Literal["slow", "keyed", "writes"]
TOOL_RISK: dict[str, frozenset[RiskTag]]
Approver = Callable[[ToolCallProposed], Decision]

def auto_approve(proposed: ToolCallProposed) -> Decision: ...
def risk_tags(tool_name: str) -> frozenset[RiskTag]: ...
def needs_confirmation(tool_name: str) -> bool: ...
class SessionPolicy:
    def __init__(self, *, ask: Callable[[ToolCallProposed], Decision]) -> None: ...
    def __call__(self, proposed: ToolCallProposed) -> Decision: ...
```

**Context.** The engine's `approver` defaults to `auto_approve`, so the
`tools/runner.py` shim and every plain-Python caller behave exactly as today. The
TUI passes a `SessionPolicy` whose `ask` blocks on a `threading.Event` while the
UI thread renders a modal.

The risk table lives here and **not** in `tools/registry.py`: adding fields to the
tool schemas would change the golden schema renderings that model-port phase 1
commits as byte-stable fixtures in four dialects, so a UI concern would start
producing diffs in the benchmark's baseline.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_policy.py`:

```python
"""Approval policy for tool dispatch.

The engine asks before running anything slow, keyed, or writing; everything
else runs unattended. See docs/working/tui-harness-design.md section 5.
"""

from __future__ import annotations

import pytest

from tools.agent.events import ToolCallProposed
from tools.agent.policy import (
    Decision,
    SessionPolicy,
    auto_approve,
    needs_confirmation,
    risk_tags,
)


def _proposed(name: str) -> ToolCallProposed:
    return ToolCallProposed(call_id="c0", name=name, arguments={})


def test_auto_approve_allows_everything() -> None:
    assert auto_approve(_proposed("run_full_hr_pipeline")) is Decision.ALLOW


def test_slow_tools_need_confirmation() -> None:
    assert needs_confirmation("run_full_hr_pipeline")
    assert "slow" in risk_tags("run_full_hr_pipeline")


def test_keyed_tools_need_confirmation() -> None:
    assert needs_confirmation("search_ads")
    assert "keyed" in risk_tags("search_ads")


def test_pure_lookups_run_unattended() -> None:
    assert not needs_confirmation("resolve_target")
    assert risk_tags("resolve_target") == frozenset()


def test_an_unknown_tool_is_untagged_and_runs() -> None:
    """A tool added to the registry without a policy entry must not block."""
    assert not needs_confirmation("a_tool_nobody_tagged")


def test_session_policy_asks_only_for_tagged_tools() -> None:
    asked: list[str] = []

    def ask(proposed: ToolCallProposed) -> Decision:
        asked.append(proposed.name)
        return Decision.ALLOW

    policy = SessionPolicy(ask=ask)
    assert policy(_proposed("resolve_target")) is Decision.ALLOW
    assert policy(_proposed("search_ads")) is Decision.ALLOW
    assert asked == ["search_ads"]


def test_allow_always_is_remembered_for_the_session() -> None:
    calls: list[str] = []

    def ask(proposed: ToolCallProposed) -> Decision:
        calls.append(proposed.name)
        return Decision.ALLOW_ALWAYS

    policy = SessionPolicy(ask=ask)
    assert policy(_proposed("search_ads")) is Decision.ALLOW_ALWAYS
    assert policy(_proposed("search_ads")) is Decision.ALLOW
    assert calls == ["search_ads"], "the second call must not ask again"


def test_deny_is_not_remembered() -> None:
    """A denial is per-call. Denying once must not silently deny forever."""
    def ask(proposed: ToolCallProposed) -> Decision:
        return Decision.DENY

    policy = SessionPolicy(ask=ask)
    assert policy(_proposed("search_ads")) is Decision.DENY
    assert policy(_proposed("search_ads")) is Decision.DENY


@pytest.mark.parametrize(
    "tool_name",
    [
        "run_full_hr_pipeline",
        "run_full_hr_pipeline_from_catalog",
        "extract_photometry_from_fits",
        "run_photometry_on_target",
        "search_ads",
        "get_paper_abstract",
        "get_citing_papers",
        "get_referenced_papers",
        "build_literature_review",
        "sonify_pulsar",
        "plot_pulsar",
        "plot_field_sed",
    ],
)
def test_every_tagged_tool_is_a_real_registered_tool(tool_name: str) -> None:
    """A typo in the risk table would silently stop guarding a tool."""
    from tools.registry import TOOL_FUNCTIONS

    assert tool_name in TOOL_FUNCTIONS
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_agent_policy.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'tools.agent.policy'`.

- [ ] **Step 3: Implement the policy**

Create `tools/agent/policy.py`:

```python
"""Which tool calls need a human decision before they run.

The engine's default approver allows everything, so plain-Python callers and
the tools.runner shim behave exactly as they did before approval existed. An
interactive front end passes a SessionPolicy instead.

The risk table lives here rather than on the tool schemas in tools/registry.py
on purpose: the schemas are rendered into four provider dialects and committed
as byte-stable golden fixtures by the model port, so adding a UI concern to
them would produce diffs in the benchmark's own baseline.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Literal

from tools.agent.events import ToolCallProposed

__all__ = [
    "Approver",
    "Decision",
    "RiskTag",
    "SessionPolicy",
    "TOOL_RISK",
    "auto_approve",
    "needs_confirmation",
    "risk_tags",
]

RiskTag = Literal["slow", "keyed", "writes"]


class Decision(StrEnum):
    """What to do with a proposed tool call."""

    ALLOW = "allow"
    DENY = "deny"
    #: Allow, and stop asking for this tool for the rest of the session.
    ALLOW_ALWAYS = "allow_always"


Approver = Callable[[ToolCallProposed], Decision]

#: Tools that get a confirmation prompt by default.
#:
#: ``slow``  -- runs for tens of seconds to minutes.
#: ``keyed`` -- needs ADS_DEV_KEY and consumes a rate-limited quota.
#: ``writes`` -- produces an artifact file.
#:
#: A tool absent from this table is untagged and runs unattended. That default
#: is deliberate: a tool added to the registry without a policy entry must not
#: silently start blocking the loop.
TOOL_RISK: dict[str, frozenset[RiskTag]] = {
    "run_full_hr_pipeline": frozenset({"slow", "writes"}),
    "run_full_hr_pipeline_from_catalog": frozenset({"slow", "writes"}),
    "extract_photometry_from_fits": frozenset({"slow"}),
    "run_photometry_on_target": frozenset({"slow", "writes"}),
    "search_ads": frozenset({"keyed"}),
    "get_paper_abstract": frozenset({"keyed"}),
    "get_citing_papers": frozenset({"keyed"}),
    "get_referenced_papers": frozenset({"keyed"}),
    "build_literature_review": frozenset({"keyed"}),
    "sonify_pulsar": frozenset({"writes"}),
    "plot_pulsar": frozenset({"writes"}),
    "plot_field_sed": frozenset({"writes"}),
}


def risk_tags(tool_name: str) -> frozenset[RiskTag]:
    """Return the risk tags for ``tool_name``, empty when untagged."""

    return TOOL_RISK.get(tool_name, frozenset())


def needs_confirmation(tool_name: str) -> bool:
    """Whether ``tool_name`` is asked about before it runs."""

    return bool(risk_tags(tool_name))


def auto_approve(proposed: ToolCallProposed) -> Decision:
    """Allow every call. The engine default, and the shim's behaviour."""

    return Decision.ALLOW


class SessionPolicy:
    """Ask about tagged tools, remembering ``ALLOW_ALWAYS`` for the session."""

    def __init__(self, *, ask: Approver) -> None:
        self._ask = ask
        self._always: set[str] = set()

    def __call__(self, proposed: ToolCallProposed) -> Decision:
        if not needs_confirmation(proposed.name):
            return Decision.ALLOW
        if proposed.name in self._always:
            return Decision.ALLOW

        decision = self._ask(proposed)
        if decision is Decision.ALLOW_ALWAYS:
            self._always.add(proposed.name)
        return decision
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_agent_policy.py -v
```

Expected: PASS, all cases.

- [ ] **Step 5: Update the module-coverage allowlist**

`tools/agent` is a package, and `pkgutil.iter_modules` yields packages. Without
this, `tests/test_tool_registry_coverage.py` fails. Add to `NOT_TOOL_MODULES`:

```python
    # The agent loop and its approval policy; not a tool surface.
    "tools.agent",
```

- [ ] **Step 6: Write the import-purity test**

Create `tests/test_agent_no_ui_imports.py`:

```python
"""tools.agent must stay importable without any UI package installed.

docs/tool-architecture.md section 7: "A Python caller must be able to import and
call every tool without running a server." The engine is the part most likely to
grow a UI dependency by accident, so the boundary is asserted rather than
documented.
"""

from __future__ import annotations

import subprocess
import sys

FORBIDDEN = ("textual", "rich", "textual_image")


def test_importing_tools_agent_pulls_in_no_ui_package() -> None:
    code = (
        "import sys; import tools.agent.policy, tools.agent.events;"
        f"leaked=[m for m in {FORBIDDEN!r} if m in sys.modules];"
        "print(','.join(leaked))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "", (
        f"tools.agent imported a UI package: {completed.stdout.strip()}"
    )
```

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add tools/agent/policy.py tests/test_agent_policy.py \
  tests/test_agent_no_ui_imports.py tests/test_tool_registry_coverage.py
git commit -m "feat(agent): approval policy for slow, keyed, and writing tools

The engine now takes an approver. The default allows everything, so the
runner shim and plain-Python callers are unchanged; an interactive front
end passes a SessionPolicy that asks about tagged tools and remembers
ALLOW_ALWAYS for the session.

The risk table lives in tools/agent/policy.py rather than on the tool
schemas: registry.py's schemas are rendered into four dialects and
committed as byte-stable golden fixtures by the model port, so a UI
concern on them would diff the benchmark baseline.

An untagged tool runs unattended, so adding a tool to the registry
without a policy entry cannot silently block the loop.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Textual dependency and the application shell (Phase D.1)

**Files:**
- Modify: `pyproject.toml`, `uv.lock`, `tests/test_tool_registry_coverage.py`
- Create: `tools/tui/__init__.py`, `tools/tui/__main__.py`, `tools/tui/app.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: `tools.agent.engine.run_session`, `tools.agent.policy.SessionPolicy`.
- Produces: `KeplerApp` (a `textual.app.App`), `tools.tui.__main__.main()`.

**Context.** This is the dependency PR. `pyproject.toml` pins with `==` and CI runs
`uv run --locked`, so the lockfile is regenerated here and nowhere else.

- [ ] **Step 1: Add the pins**

In `pyproject.toml`, insert into `dependencies` in alphabetical position:

```toml
    "linkify-it-py==2.2.0",
    "markdown-it-py==4.2.0",
    "mdit-py-plugins==0.6.1",
    "mdurl==0.1.2",
    "platformdirs==4.11.7",
    "rich==15.0.0",
    "textual==8.2.8",
    "textual-image==0.13.2",
```

`pygments==2.20.0`, `pillow==12.3.0`, and `typing-extensions==4.16.0` are already
pinned at compatible versions. Do not move them.

- [ ] **Step 2: Regenerate the lockfile and confirm nothing else moved**

```bash
uv lock
git diff --stat uv.lock
uv run python -c "import textual, textual_image, rich; print(textual.__version__)"
```

Expected: `uv.lock` changes; `8.2.8` prints. If the diff moves an unrelated pin,
stop and report it rather than committing a silent upgrade.

- [ ] **Step 3: Write the failing test**

Create `tests/test_tui_app.py`:

```python
"""Headless coverage of the Kepler TUI shell.

Textual's run_test() pilot drives the app with no real terminal, so this runs in
the default suite alongside everything else.
"""

from __future__ import annotations

import pytest

from tools.tui.app import KeplerApp


@pytest.mark.asyncio
async def test_the_app_starts_and_shows_the_prompt() -> None:
    app = KeplerApp(backend=None, backend_spec="none/none")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#prompt") is not None
        assert app.query_one("#transcript") is not None
        assert app.query_one("#status") is not None


@pytest.mark.asyncio
async def test_the_status_bar_names_the_backend() -> None:
    app = KeplerApp(backend=None, backend_spec="ollama/qwen3:8b")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "ollama/qwen3:8b" in app.query_one("#status").renderable_text
```

- [ ] **Step 4: Run it to verify it fails**

```bash
uv run pytest tests/test_tui_app.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'tools.tui'`.

- [ ] **Step 5: Add the asyncio marker**

Textual's `run_test()` is async. `pytest-asyncio` is **not** a dependency and this
plan adds none beyond the eight. Use Textual's own synchronous bridge instead:
replace the `@pytest.mark.asyncio` decorators with a helper that drives the
coroutine on an event loop.

At the top of `tests/test_tui_app.py`, replace the decorator usage with:

```python
import asyncio


def run_async(coro) -> None:
    asyncio.run(coro)


def test_the_app_starts_and_shows_the_prompt() -> None:
    async def scenario() -> None:
        app = KeplerApp(backend=None, backend_spec="none/none")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#prompt") is not None
            assert app.query_one("#transcript") is not None
            assert app.query_one("#status") is not None

    run_async(scenario())
```

Apply the same shape to the second test. Keeping the dependency count at eight is
a Global Constraint; adding `pytest-asyncio` to avoid four lines of boilerplate
would break it.

- [ ] **Step 6: Implement the shell**

Create `tools/tui/__init__.py`:

```python
"""The Kepler terminal console.

The only package in this repository permitted to import ``textual``. Everything
it drives lives in ``tools.agent`` and is importable without it.
"""

from __future__ import annotations

__all__ = ["KeplerApp"]


def __getattr__(name: str) -> object:
    # Imported lazily so `import tools.tui` stays cheap for anything that only
    # wants the console-script entry point.
    if name == "KeplerApp":
        from tools.tui.app import KeplerApp

        return KeplerApp
    raise AttributeError(name)
```

Create `tools/tui/app.py`:

```python
"""The Kepler TUI application shell."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Static

__all__ = ["KeplerApp"]


class KeplerApp(App[None]):
    """A full-screen astronomy research console."""

    TITLE = "Kepler"

    CSS = """
    #transcript { height: 1fr; overflow-y: auto; padding: 0 1; }
    #prompt { dock: bottom; }
    #status { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        ("ctrl+a", "artifacts", "Artifacts"),
        ("ctrl+s", "sessions", "Sessions"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, *, backend: object, backend_spec: str) -> None:
        super().__init__()
        self._backend = backend
        self._backend_spec = backend_spec

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(id="transcript")
        yield Static(self._status_line(), id="status")
        yield Input(placeholder="ask something, or /help", id="prompt")
        yield Footer()

    def _status_line(self) -> str:
        return f"{self._backend_spec} - turn 0/20"
```

Create `tools/tui/__main__.py`:

```python
"""Console-script entry point for the Kepler TUI."""

from __future__ import annotations

import argparse
import os
import sys

__all__ = ["main"]

DEFAULT_BACKEND_ENV = "KEPLER_MODEL_BACKEND"


def main() -> int:
    parser = argparse.ArgumentParser(prog="kepler", description="Kepler console.")
    parser.add_argument(
        "--backend",
        default=os.environ.get(DEFAULT_BACKEND_ENV, "anthropic/claude-sonnet-5"),
        help="provider/model spec, e.g. ollama/qwen3:8b (default: $%s)"
        % DEFAULT_BACKEND_ENV,
    )
    args = parser.parse_args()

    from tools.llm.factory import build_backend
    from tools.tui.app import KeplerApp

    try:
        backend = build_backend(args.backend)
    except Exception as error:  # noqa: BLE001 -- reported, not swallowed
        print(f"kepler: cannot start backend {args.backend!r}: {error}", file=sys.stderr)
        return 1

    KeplerApp(backend=backend, backend_spec=args.backend).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/test_tui_app.py -v
```

Expected: PASS.

- [ ] **Step 8: Update the module-coverage allowlist**

Add to `NOT_TOOL_MODULES` in `tests/test_tool_registry_coverage.py`:

```python
    # The terminal console; not a tool surface.
    "tools.tui",
```

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add pyproject.toml uv.lock tools/tui tests/test_tui_app.py \
  tests/test_tool_registry_coverage.py
git commit -m "feat(tui): Textual application shell

Adds the eight pins the console needs and the app shell they support.
tools/tui is the only package permitted to import textual; tools/agent
and tools/llm stay dependency-free, which tests/test_agent_no_ui_imports
asserts.

Tests drive the app through Textual's run_test() pilot on a plain
asyncio.run bridge rather than adding pytest-asyncio, keeping the new
dependency count at the eight this change budgets for.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: The slash-command registry (Phase D.2)

**Files:**
- Create: `tools/tui/commands.py`
- Test: `tests/test_tui_commands.py`
- Modify: `tools/tui/app.py`

**Interfaces:**
- Consumes: nothing from Textual; the registry is plain Python so it is testable
  without a pilot.
- Produces:

```python
@dataclass(frozen=True)
class Command:
    name: str
    help: str
    aliases: tuple[str, ...] = ()

COMMANDS: dict[str, Command]

@dataclass(frozen=True)
class Parsed:
    kind: Literal["message", "command", "unknown"]
    text: str                  # message body, or the command name
    args: str = ""

def parse_input(raw: str) -> Parsed: ...
def resolve(name: str) -> Command | None: ...
def help_text() -> str: ...
```

**Context.** Commands are UI-level and must never reach the model. A mistyped
`/sessons` that gets forwarded to an LLM wastes a turn and pollutes the
transcript, so an unknown command is an error rather than a message. `//` escapes
to a literal leading slash.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tui_commands.py`:

```python
"""Slash-command parsing.

Commands never reach the model. See docs/working/tui-harness-design.md section 8.
"""

from __future__ import annotations

import pytest

from tools.tui.commands import COMMANDS, Parsed, help_text, parse_input, resolve


def test_a_plain_line_is_a_message() -> None:
    assert parse_input("what is Cas A") == Parsed(kind="message", text="what is Cas A")


def test_a_known_command_parses() -> None:
    assert parse_input("/status") == Parsed(kind="command", text="status")


def test_a_command_keeps_its_arguments() -> None:
    parsed = parse_input("/resume 20260907T101500Z_abc123")
    assert parsed == Parsed(
        kind="command", text="resume", args="20260907T101500Z_abc123"
    )


def test_an_unknown_command_is_not_a_message() -> None:
    """A typo must not be forwarded to the model as a prompt."""
    parsed = parse_input("/sessons")
    assert parsed.kind == "unknown"
    assert parsed.text == "sessons"


def test_a_double_slash_escapes_to_a_literal_message() -> None:
    assert parse_input("//status is fine") == Parsed(
        kind="message", text="/status is fine"
    )


def test_a_bare_slash_is_a_message() -> None:
    assert parse_input("/") == Parsed(kind="message", text="/")


def test_leading_whitespace_does_not_hide_a_command() -> None:
    assert parse_input("   /status").kind == "command"


def test_an_empty_line_is_a_message() -> None:
    assert parse_input("   ") == Parsed(kind="message", text="")


def test_aliases_resolve_to_the_same_command() -> None:
    assert resolve("q") is resolve("quit")


@pytest.mark.parametrize(
    "name",
    [
        "help", "artifacts", "sessions", "resume", "status",
        "tools", "approve", "prompt", "new", "quit",
    ],
)
def test_every_specified_command_exists(name: str) -> None:
    assert name in COMMANDS


def test_help_text_is_generated_from_the_registry() -> None:
    """/help must not be a hand-maintained list that drifts."""
    rendered = help_text()
    for name in COMMANDS:
        assert f"/{name}" in rendered
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_tui_commands.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'tools.tui.commands'`.

- [ ] **Step 3: Implement the registry**

Create `tools/tui/commands.py`:

```python
"""Slash commands for the Kepler console.

Commands are interface actions and never reach the model. An unknown command is
reported inline rather than forwarded: silently sending a mistyped "/sessons" to
a provider would spend a turn and put a nonsense prompt in the transcript.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["COMMANDS", "Command", "Parsed", "help_text", "parse_input", "resolve"]


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    aliases: tuple[str, ...] = ()


_COMMAND_LIST = (
    Command("help", "List these commands.", ("?",)),
    Command("artifacts", "Browse artifacts written by this session."),
    Command("sessions", "Browse saved sessions."),
    Command("resume", "Resume a saved session by id."),
    Command("status", "Backend, model, turn, usage, session, graphics tier."),
    Command("tools", "Browse the registered tools and their schemas."),
    Command("approve", "View or change the approval policy for a tool."),
    Command("prompt", "View the active system prompt."),
    Command("new", "Start a fresh session."),
    Command("quit", "Exit Kepler.", ("q", "exit")),
)

COMMANDS: dict[str, Command] = {command.name: command for command in _COMMAND_LIST}

_ALIASES: dict[str, Command] = {
    alias: command for command in _COMMAND_LIST for alias in command.aliases
}


@dataclass(frozen=True)
class Parsed:
    kind: Literal["message", "command", "unknown"]
    text: str
    args: str = ""


def resolve(name: str) -> Command | None:
    """Return the command for ``name`` or one of its aliases."""

    return COMMANDS.get(name) or _ALIASES.get(name)


def parse_input(raw: str) -> Parsed:
    """Classify one line of user input."""

    line = raw.strip()
    if not line:
        return Parsed(kind="message", text="")
    # "//" escapes a message that genuinely starts with a slash.
    if line.startswith("//"):
        return Parsed(kind="message", text=line[1:])
    if not line.startswith("/") or line == "/":
        return Parsed(kind="message", text=line)

    name, _, args = line[1:].partition(" ")
    command = resolve(name)
    if command is None:
        return Parsed(kind="unknown", text=name)
    return Parsed(kind="command", text=command.name, args=args.strip())


def help_text() -> str:
    """Render /help from the registry, so it cannot drift from the commands."""

    width = max(len(command.name) for command in _COMMAND_LIST)
    lines = [
        f"  /{command.name.ljust(width)}  {command.help}"
        for command in _COMMAND_LIST
    ]
    return "Commands:\n" + "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_tui_commands.py -v
```

Expected: PASS, all cases.

- [ ] **Step 5: Wire the input widget to the parser**

In `tools/tui/app.py`, add the submit handler:

`Input` is already imported at module scope by Task 3; add only the method.

```python
    def on_input_submitted(self, event: Input.Submitted) -> None:
        from tools.tui.commands import help_text, parse_input

        event.input.value = ""
        parsed = parse_input(event.value)
        if parsed.kind == "unknown":
            self._write(f"Unknown command: /{parsed.text}. Try /help.")
            return
        if parsed.kind == "command":
            self._dispatch(parsed.text, parsed.args)
            return
        if parsed.text:
            self._send_to_engine(parsed.text)
```

Add a `_dispatch` that handles `help`, `status`, `prompt`, `tools`, `approve`,
`new`, and `quit` now; `artifacts`, `sessions`, and `resume` raise a
"not yet available" notice until Tasks 6 and 7 land.

- [ ] **Step 6: Add the pilot test for dispatch**

Append to `tests/test_tui_app.py`:

```python
def test_an_unknown_command_never_reaches_the_engine() -> None:
    async def scenario() -> None:
        app = KeplerApp(backend=None, backend_spec="none/none")
        sent: list[str] = []
        async with app.run_test() as pilot:
            app._send_to_engine = lambda text: sent.append(text)
            await pilot.click("#prompt")
            await pilot.press(*"/sessons")
            await pilot.press("enter")
            await pilot.pause()
        assert sent == [], "a mistyped command was forwarded to the model"

    run_async(scenario())


def test_help_renders_without_touching_the_engine() -> None:
    async def scenario() -> None:
        app = KeplerApp(backend=None, backend_spec="none/none")
        sent: list[str] = []
        async with app.run_test() as pilot:
            app._send_to_engine = lambda text: sent.append(text)
            await pilot.click("#prompt")
            await pilot.press(*"/help")
            await pilot.press("enter")
            await pilot.pause()
        assert sent == []

    run_async(scenario())
```

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add tools/tui/commands.py tools/tui/app.py tests/test_tui_commands.py \
  tests/test_tui_app.py
git commit -m "feat(tui): slash-command registry

Ten commands, declared once and dispatched from a table, so /help is
generated rather than maintained. Commands are interface actions and
never reach the model: an unknown command renders an error instead of
being forwarded, because a mistyped /sessons sent to a provider spends a
turn and leaves nonsense in the transcript. // escapes a message that
genuinely starts with a slash.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Transcript and tool-call nodes (Phase D.3)

**Files:**
- Create: `tools/tui/widgets/__init__.py`, `tools/tui/widgets/transcript.py`,
  `tools/tui/widgets/tool_node.py`
- Modify: `tools/tui/app.py`
- Test: `tests/test_tui_app.py`

**Interfaces:**
- Consumes: every event in `tools.agent.events`; `tools.agent.policy.SessionPolicy`.
- Produces: `Transcript.handle_event(event)`, `ToolNode(call_id, name, arguments)`
  with `start()`, `finish(result, artifacts, duration_ms)`, `deny(reason)`.

**Context.** This is where the engine is actually driven. The engine is
synchronous and runs in `@work(thread=True)`; each event reaches the UI thread
through `post_message`. Approval crosses back the other way: the approver blocks
the worker on a `threading.Event` while the UI renders a modal.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tui_app.py`:

```python
from tools.agent.events import (
    SessionStarted, ToolCallFinished, ToolCallStarted, TurnStarted,
)


def test_tool_events_render_a_node_with_status() -> None:
    async def scenario() -> None:
        app = KeplerApp(backend=None, backend_spec="none/none")
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript")
            transcript.handle_event(
                SessionStarted(
                    session_id="s1", manifest_path="/tmp/m.json",
                    backend_spec="none/none", model="fake",
                )
            )
            transcript.handle_event(TurnStarted(turn=1))
            transcript.handle_event(
                ToolCallStarted(
                    call_id="c1", name="search_simbad",
                    arguments={"target": "Cas A"}, cache_hit=False,
                )
            )
            await pilot.pause()
            node = transcript.node_for("c1")
            assert node is not None
            assert node.state == "running"

            transcript.handle_event(
                ToolCallFinished(
                    call_id="c1", name="search_simbad",
                    result={"status": "ok"}, artifacts=(), duration_ms=1200,
                )
            )
            await pilot.pause()
            assert transcript.node_for("c1").state == "finished"

    run_async(scenario())


def test_a_cached_call_is_marked_as_such() -> None:
    async def scenario() -> None:
        app = KeplerApp(backend=None, backend_spec="none/none")
        async with app.run_test() as pilot:
            transcript = app.query_one("#transcript")
            transcript.handle_event(
                ToolCallStarted(
                    call_id="c2", name="search_simbad",
                    arguments={"target": "Cas A"}, cache_hit=True,
                )
            )
            await pilot.pause()
            assert transcript.node_for("c2").cache_hit is True

    run_async(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_tui_app.py -v -k tool_events
```

Expected: FAIL, `AttributeError` on `handle_event` or `node_for`.

- [ ] **Step 3: Implement `ToolNode`**

Create `tools/tui/widgets/tool_node.py`:

```python
"""One tool call in the transcript.

A four-minute plate solve must read as progress rather than a hang, so a running
node carries a live elapsed timer and only settles when the engine says so.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from textual.reactive import reactive
from textual.widgets import Static

__all__ = ["ToolNode"]

State = Literal["running", "finished", "denied", "error"]

_GLYPH = {"running": "*", "finished": "ok", "denied": "denied", "error": "error"}


class ToolNode(Static):
    """A collapsible record of one tool call."""

    state: reactive[State] = reactive[State]("running")
    elapsed_ms: reactive[int] = reactive(0)
    expanded: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        cache_hit: bool = False,
    ) -> None:
        super().__init__()
        self.call_id = call_id
        self.tool_name = name
        self.arguments = arguments
        self.cache_hit = cache_hit
        self.result: dict[str, Any] | None = None
        self.artifacts: tuple[str, ...] = ()

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._tick)
        self._render()

    def _tick(self) -> None:
        if self.state == "running":
            self.elapsed_ms += 100
            self._render()

    def finish(
        self, *, result: dict[str, Any], artifacts: tuple[str, ...], duration_ms: int
    ) -> None:
        self.result = result
        self.artifacts = artifacts
        self.elapsed_ms = duration_ms
        self.state = "error" if result.get("status") == "error" else "finished"
        self._timer.stop()
        self._render()

    def deny(self, reason: str) -> None:
        self.result = {"status": "denied", "reason": reason}
        self.state = "denied"
        self._timer.stop()
        self._render()

    def _summary(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items())
        marker = " cached" if self.cache_hit else ""
        seconds = self.elapsed_ms / 1000
        arrow = "v" if self.expanded else ">"
        return (
            f"{arrow} {self.tool_name}({args})  "
            f"{seconds:.1f}s {_GLYPH[self.state]}{marker}"
        )

    def _render(self) -> None:
        body = self._summary()
        if self.expanded and self.result is not None:
            body += "\n" + json.dumps(self.result, indent=2, default=str)[:2000]
        self.update(body)
```

- [ ] **Step 4: Implement `Transcript`**

Create `tools/tui/widgets/transcript.py`:

```python
"""The scrolling conversation: assistant text and tool nodes."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from tools.agent import events as ev
from tools.tui.widgets.tool_node import ToolNode

__all__ = ["Transcript"]


class Transcript(VerticalScroll):
    """Renders the engine's event stream."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._nodes: dict[str, ToolNode] = {}
        self._assistant: Static | None = None

    def node_for(self, call_id: str) -> ToolNode | None:
        return self._nodes.get(call_id)

    def write_line(self, text: str) -> None:
        self.mount(Static(text))
        self.scroll_end(animate=False)

    def handle_event(self, event: ev.Event) -> None:
        match event:
            case ev.SessionStarted():
                self.write_line(f"session {event.session_id}")
            case ev.TurnStarted():
                self._assistant = Static("")
                self.mount(self._assistant)
            case ev.TextDelta():
                if self._assistant is not None:
                    self._assistant.update(
                        str(self._assistant.renderable) + event.text
                    )
                    self.scroll_end(animate=False)
            case ev.ToolCallStarted():
                node = ToolNode(
                    call_id=event.call_id,
                    name=event.name,
                    arguments=event.arguments,
                    cache_hit=event.cache_hit,
                )
                self._nodes[event.call_id] = node
                self.mount(node)
                self.scroll_end(animate=False)
            case ev.ToolCallFinished():
                node = self._nodes.get(event.call_id)
                if node is not None:
                    node.finish(
                        result=event.result,
                        artifacts=event.artifacts,
                        duration_ms=event.duration_ms,
                    )
            case ev.ToolCallDenied():
                node = self._nodes.get(event.call_id)
                if node is not None:
                    node.deny(event.reason)
            case ev.ProtocolFault():
                self.write_line(f"[fault] {event.type}: {event.detail}")
            case ev.SessionFinished():
                self.write_line(f"[{event.outcome}] {event.manifest_path}")
```

- [ ] **Step 5: Drive the engine from a thread worker**

In `tools/tui/app.py`, replace `_send_to_engine`:

```python
import threading

from textual import work
from textual.message import Message as TextualMessage

from tools.agent.engine import run_session
from tools.agent.events import ToolCallProposed
from tools.agent.policy import Decision, SessionPolicy


class EngineEvent(TextualMessage):
    """One tools.agent event, forwarded from the worker to the UI thread.

    Aliased as TextualMessage because tools.llm.types.Message is the neutral
    conversation type and the two would otherwise shadow each other in a file
    that touches both.
    """

    def __init__(self, event: object) -> None:
        super().__init__()
        self.event = event


    def _send_to_engine(self, text: str) -> None:
        self._run_engine(text)

    @work(thread=True, exclusive=True)
    def _run_engine(self, text: str) -> None:
        policy = SessionPolicy(ask=self._ask_blocking)
        for event in run_session(
            text, backend=self._backend, approver=policy
        ):
            self.post_message(EngineEvent(event))

    def _ask_blocking(self, proposed: ToolCallProposed) -> Decision:
        """Called on the worker thread; blocks until the UI thread answers."""
        answered = threading.Event()
        box: list[Decision] = []

        def on_answer(decision: Decision) -> None:
            box.append(decision)
            answered.set()

        self.call_from_thread(self._show_approval_modal, proposed, on_answer)
        answered.wait()
        return box[0]

    def on_engine_event(self, message: EngineEvent) -> None:
        self.query_one("#transcript").handle_event(message.event)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/test_tui_app.py -v
```

Expected: PASS.

- [ ] **Step 7: Verify and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add tools/tui tests/test_tui_app.py
git commit -m "feat(tui): transcript and live tool-call nodes

The engine runs in a Textual thread worker and each event reaches the UI
through post_message, so the interface stays responsive while a plate
solve blocks for minutes. A running node carries a live elapsed timer
for the same reason.

Approval crosses back the other way: the approver blocks the worker on a
threading.Event while the UI thread renders the modal, so the engine
never learns a UI exists.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Artifact rendering (Phase E)

**Files:**
- Create: `tools/tui/render/__init__.py`, `tools/tui/render/capability.py`,
  `tools/tui/render/image.py`, `tools/tui/render/waveform.py`,
  `tools/tui/widgets/artifacts.py`, `tests/fixtures/tui/probe_4x4.png`
- Test: `tests/test_tui_render.py`

**Interfaces:**
- Consumes: `PIL.Image`, `tools.workspace.list_artifacts`.
- Produces:

```python
class GraphicsTier(StrEnum):
    KITTY = "kitty"
    ITERM2 = "iterm2"
    SIXEL = "sixel"
    HALFBLOCK = "halfblock"

def detect_tier(env: Mapping[str, str] | None = None) -> GraphicsTier: ...
def render_halfblocks(path: Path, *, max_cols: int) -> str: ...
def render_waveform(path: Path, *, cols: int) -> str: ...
```

**Context.** Half-blocks are the guaranteed floor and compose with Textual
perfectly, being nothing but coloured characters. Native protocols go through
`textual-image`. The `docs/extraction.md` Pulsar Sonification section 7.2 note
applies: synthesis ignores sample timestamps, so the waveform is presentational
and a period must never be read from it.

- [ ] **Step 1: Create the golden fixture**

```bash
mkdir -p tests/fixtures/tui
uv run python -c "
from PIL import Image
img = Image.new('RGB', (4, 4))
img.putdata([
    (255,0,0),(0,255,0),(0,0,255),(255,255,255),
    (0,0,0),(255,0,0),(0,255,0),(0,0,255),
    (255,255,0),(0,255,255),(255,0,255),(128,128,128),
    (10,20,30),(40,50,60),(70,80,90),(100,110,120),
])
img.save('tests/fixtures/tui/probe_4x4.png')
"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_tui_render.py`:

```python
"""Terminal graphics capability detection and the half-block floor."""

from __future__ import annotations

from pathlib import Path

from tools.tui.render.capability import GraphicsTier, detect_tier
from tools.tui.render.image import render_halfblocks

FIXTURE = Path(__file__).parent / "fixtures" / "tui" / "probe_4x4.png"


def test_kitty_is_detected_from_its_window_id() -> None:
    assert detect_tier({"KITTY_WINDOW_ID": "1"}) is GraphicsTier.KITTY


def test_kitty_is_detected_from_term() -> None:
    assert detect_tier({"TERM": "xterm-kitty"}) is GraphicsTier.KITTY


def test_iterm2_is_detected_from_term_program() -> None:
    assert detect_tier({"TERM_PROGRAM": "iTerm.app"}) is GraphicsTier.ITERM2


def test_a_plain_terminal_falls_back_to_halfblocks() -> None:
    assert detect_tier({"TERM": "xterm-256color"}) is GraphicsTier.HALFBLOCK


def test_an_empty_environment_falls_back_to_halfblocks() -> None:
    """Detection must never raise; the floor is always reachable."""
    assert detect_tier({}) is GraphicsTier.HALFBLOCK


def test_halfblocks_render_two_rows_per_line() -> None:
    """A 4x4 image is two text rows of four columns."""
    rendered = render_halfblocks(FIXTURE, max_cols=4)
    lines = rendered.splitlines()
    assert len(lines) == 2
    assert rendered.count("▀") == 8


def test_halfblocks_respect_the_column_budget() -> None:
    rendered = render_halfblocks(FIXTURE, max_cols=2)
    for line in rendered.splitlines():
        assert line.count("▀") <= 2
```

- [ ] **Step 3: Run it to verify it fails**

```bash
uv run pytest tests/test_tui_render.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'tools.tui.render'`.

- [ ] **Step 4: Implement the capability probe**

Create `tools/tui/render/capability.py`:

```python
"""Which terminal graphics protocol this terminal supports.

Detection is environment-only and never raises: the half-block floor works
everywhere, so an undetectable terminal degrades rather than failing. A Sixel
Device Attributes query is deliberately not issued here -- it requires reading
from the tty, which Textual owns once the app is running.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

__all__ = ["GraphicsTier", "detect_tier"]


class GraphicsTier(StrEnum):
    KITTY = "kitty"
    ITERM2 = "iterm2"
    SIXEL = "sixel"
    HALFBLOCK = "halfblock"


def detect_tier(env: Mapping[str, str] | None = None) -> GraphicsTier:
    """Return the best graphics tier ``env`` advertises."""

    source = os.environ if env is None else env
    if source.get("KITTY_WINDOW_ID") or source.get("TERM") == "xterm-kitty":
        return GraphicsTier.KITTY
    if source.get("TERM_PROGRAM") in {"iTerm.app", "WezTerm"}:
        return GraphicsTier.ITERM2
    if "sixel" in source.get("TERM", ""):
        return GraphicsTier.SIXEL
    return GraphicsTier.HALFBLOCK
```

- [ ] **Step 5: Implement the half-block renderer**

Create `tools/tui/render/image.py`:

```python
"""Render an image as coloured half-blocks.

One text cell carries two pixels: the upper half is the foreground colour and
the lower half the background, so a text row is two image rows. This is the
guaranteed floor -- it is ordinary coloured text, so it composes with Textual's
repaint cycle where a raw graphics escape sequence would be clobbered.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

__all__ = ["render_halfblocks"]

UPPER_HALF = "▀"


def render_halfblocks(path: str | Path, *, max_cols: int = 80) -> str:
    """Return ``path`` as Rich-markup half-block text, at most ``max_cols`` wide."""

    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        cols = min(max_cols, width)
        rows = max(1, round(height * cols / width / 2)) * 2
        image = image.resize((cols, rows), Image.Resampling.LANCZOS)
        pixels = image.load()

    lines: list[str] = []
    for y in range(0, rows - 1, 2):
        parts: list[str] = []
        for x in range(cols):
            top = pixels[x, y]
            bottom = pixels[x, y + 1]
            parts.append(
                f"[rgb({top[0]},{top[1]},{top[2]}) "
                f"on rgb({bottom[0]},{bottom[1]},{bottom[2]})]{UPPER_HALF}[/]"
            )
        lines.append("".join(parts))
    return "\n".join(lines)
```

- [ ] **Step 6: Implement the waveform renderer**

Create `tools/tui/render/waveform.py`:

```python
"""A braille waveform for WAV artifacts.

Presentational only. docs/extraction.md (Pulsar Sonification section 7.2)
records that synthesis ignores sample timestamps, so a period must never be
read off rendered audio -- the folded-profile plot beside it is the scientific
artifact.
"""

from __future__ import annotations

import wave
from array import array
from pathlib import Path

__all__ = ["render_waveform"]

_BARS = " ▁▂▃▄▅▆▇█"


def render_waveform(path: str | Path, *, cols: int = 72) -> str:
    """Return a single-line amplitude envelope for a WAV file."""

    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        width = handle.getsampwidth()

    if width != 2 or not frames:
        return ""
    samples = array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % 2])
    if not samples:
        return ""

    bucket = max(1, len(samples) // cols)
    peaks = [
        max(abs(v) for v in samples[i : i + bucket])
        for i in range(0, len(samples), bucket)
    ][:cols]
    ceiling = max(peaks) or 1
    return "".join(_BARS[min(len(_BARS) - 1, p * len(_BARS) // (ceiling + 1))] for p in peaks)
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest tests/test_tui_render.py -v
```

Expected: PASS.

- [ ] **Step 8: Add the `/artifacts` modal**

Create `tools/tui/widgets/artifacts.py` as a `ModalScreen` listing
`tools.workspace.list_artifacts()` output, rendering the selected entry with
`render_halfblocks` for images and `render_waveform` for `.wav`, and binding
`o` to open externally via `xdg-open` / `open`. Wire `/artifacts` and `ctrl+a`
in `app.py` to push it.

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add tools/tui tests/test_tui_render.py tests/fixtures/tui/probe_4x4.png
git commit -m "feat(tui): tiered artifact rendering

Half-blocks are the guaranteed floor: ordinary coloured text, so they
survive Textual's repaint cycle where raw graphics escapes would be
clobbered. Native Kitty/iTerm2/Sixel goes through textual-image where the
terminal advertises it.

WAV artifacts get a braille envelope only. docs/extraction.md (Pulsar
Sonification 7.2) records that synthesis ignores sample timestamps, so a
period must never be read from rendered audio.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Session browser and resume (Phase F)

**Files:**
- Create: `tools/tui/widgets/sessions.py`
- Modify: `tools/tui/app.py`
- Test: `tests/test_tui_sessions.py`

**Interfaces:**
- Consumes: `tools.workspace.list_sessions`, `tools.workspace.describe_session`,
  `tools.sessions.read_session_manifest`.
- Produces: `SessionBrowser` (a `ModalScreen`),
  `tools.tui.app.KeplerApp.resume_session(session_id)`.

**Context.** `tools/sessions.py` already records everything the browser needs.
Resume seeds the engine's message history from a manifest's recorded turns.

Per `tui-harness-design.md` section 16 question 3, **resume references artifacts
rather than replaying them**: re-rendering every image on resume is slow for a
long session, and `/artifacts` is the way back to them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tui_sessions.py`:

```python
"""Session browsing and resume."""

from __future__ import annotations

import json
from pathlib import Path

from tools.tui.widgets.sessions import history_from_manifest


def _manifest(tmp_path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "session_id": "20260907T101500Z_abc123",
        "user_message": "what is Cas A",
        "model": "fake-model",
        "outcome": "end_turn",
        "turns": [
            {"turn": 1, "stop_reason": "tool_use", "assistant_text": "Looking."},
            {"turn": 2, "stop_reason": "end_turn", "assistant_text": "It is a remnant."},
        ],
        "tool_calls": [
            {
                "sequence": 1, "turn": 1, "tool_name": "search_simbad",
                "arguments": {"target": "Cas A"}, "status": "ok",
            }
        ],
    }
    path = tmp_path / "session_manifest.json"
    path.write_text(json.dumps(payload))
    return path


def test_history_starts_with_the_original_user_message(tmp_path: Path) -> None:
    history = history_from_manifest(_manifest(tmp_path))
    assert history[0].role == "user"
    assert "Cas A" in history[0].blocks[0].text


def test_history_carries_every_recorded_assistant_turn(tmp_path: Path) -> None:
    history = history_from_manifest(_manifest(tmp_path))
    texts = [
        block.text
        for message in history
        if message.role == "assistant"
        for block in message.blocks
    ]
    assert texts == ["Looking.", "It is a remnant."]


def test_a_v2_manifest_is_readable(tmp_path: Path) -> None:
    """Manifest v2 arrives with model-port phase 4; v1 readers must not break."""
    path = tmp_path / "session_manifest.json"
    payload = json.loads(_manifest(tmp_path).read_text())
    payload["schema_version"] = 2
    payload["usage_totals"] = {"input_tokens": 10, "output_tokens": 5}
    path.write_text(json.dumps(payload))
    assert history_from_manifest(path)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_tui_sessions.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'tools.tui.widgets.sessions'`.

- [ ] **Step 3: Implement `history_from_manifest` and the browser**

Create `tools/tui/widgets/sessions.py` with:

```python
"""Browse and resume saved sessions."""

from __future__ import annotations

import json
from pathlib import Path

from tools.llm.types import Message, TextBlock

__all__ = ["SessionBrowser", "history_from_manifest"]


def history_from_manifest(path: str | Path) -> list[Message]:
    """Rebuild a neutral message history from a saved session manifest.

    Reads schema_version 1 and 2. Tool results are not replayed -- the engine's
    own call cache is empty on resume, so a repeated call re-runs rather than
    returning a stale recorded result.
    """

    payload = json.loads(Path(path).read_text())
    history: list[Message] = [
        Message(role="user", blocks=(TextBlock(text=payload["user_message"]),))
    ]
    for turn in payload.get("turns", []):
        text = turn.get("assistant_text")
        if text:
            history.append(
                Message(role="assistant", blocks=(TextBlock(text=text),))
            )
    return history
```

Then add a `SessionBrowser(ModalScreen)` listing `tools.workspace.list_sessions()`
with id, timestamp, model, outcome, and turn count, binding `enter` to resume.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_tui_sessions.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire `/sessions` and `/resume`**

In `app.py`, replace the "not yet available" notices for `sessions` and `resume`
with `push_screen(SessionBrowser())` and `resume_session(args)`.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
git diff --check
git add tools/tui/widgets/sessions.py tools/tui/app.py tests/test_tui_sessions.py
git commit -m "feat(tui): session browser and resume

tools/sessions.py already recorded everything a browser needs. /sessions
lists them; /resume seeds the engine's history from a manifest's turns.

Resume references artifacts rather than replaying them, per the design's
open question 3: re-rendering every image on resume is slow for a long
session and /artifacts is the way back. Tool results are not replayed
either, so a repeated call re-runs rather than returning a stale one.

Reads manifest schema_version 1 and 2.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: Retire the old entry points -- code (Phase G.1)

**Files:**
- Delete: `tools/runner.py`
- Modify: `pyproject.toml`, `tests/test_tool_registry_coverage.py`,
  `tests/test_runner_session.py` -> renamed
- Test: `tests/test_agent_session.py` (renamed from `test_runner_session.py`)

**Interfaces:**
- Consumes: `tools.agent.engine.run_session`.
- Produces: the `kepler` console script only.

**Context.** The point of no return, and deliberately last: every earlier task
leaves `kepler-astro-query` working, so the TUI can be judged before the old
surface is removed. **Do not start this task until the TUI has actually been used
against a real backend.**

- [ ] **Step 1: Confirm the shim has no remaining callers**

```bash
grep -rn 'tools\.runner\|tools/runner\|kepler-astro-query' \
  --include='*.py' --include='*.toml' tools/ tests/ pyproject.toml
```

Expected: `pyproject.toml`'s console script, `tests/test_runner_session.py`, and
`tests/test_tool_registry_coverage.py`'s `NOT_TOOL_MODULES`. Anything else must be
migrated before continuing.

- [ ] **Step 2: Retarget the session test at the engine**

```bash
git mv tests/test_runner_session.py tests/test_agent_session.py
sed -i 's/from tools import runner/from tools.agent import engine/; s/\brunner\./engine./g' \
  tests/test_agent_session.py
```

Then change the call site from `runner.run(...)` to iterating `run_session(...)`:

```python
    manifest_path = None
    for event in engine.run_session("a question", backend=fake_backend):
        if isinstance(event, SessionFinished):
            manifest_path = event.manifest_path
```

The manifest assertions, including `manifest["outcome"] == "end_turn"` and
`manifest["model"] == "fake-model"`, stay exactly as they are. If any of them
needs changing, the engine diverged from the shim and that is a bug in Phase A,
not in this step.

- [ ] **Step 3: Delete the shim and its console script**

```bash
git rm tools/runner.py
```

In `pyproject.toml`, replace the `[project.scripts]` block:

```toml
[project.scripts]
kepler = "tools.tui.__main__:main"
```

- [ ] **Step 4: Drop the stale coverage entry**

Remove `"tools.runner",` from `NOT_TOOL_MODULES` in
`tests/test_tool_registry_coverage.py`. Leaving it is harmless but it names a
module that no longer exists, which is exactly the class of stale reference this
work exists to remove.

- [ ] **Step 5: Verify**

```bash
uv run pytest -q
python3 -m compileall tools algorithms
uv run kepler --help
grep -rn 'tools\.runner\|kepler-astro-query' --include='*.py' tools/ tests/
```

Expected: suite green; `kepler --help` prints usage; the grep prints nothing.
**CI will still fail at this commit** — `.github/workflows/ci.yml:67` asserts
`tools/runner.py` exists, and Task 9 is what fixes that. The two ship together as
a stacked pair.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat!: retire kepler-astro-query for the kepler console

tools/runner.py has been a shim over tools/agent/ since the model port.
Deleting it leaves one model-driven entry point instead of three.

test_runner_session.py is renamed to test_agent_session.py and retargeted
at run_session(); every manifest assertion is unchanged, which is what
demonstrates the engine kept the shim's observable behaviour.

CI's repository-shape job still asserts tools/runner.py exists and fails
at this commit; the workflow change ships as its own PR immediately after,
per CLAUDE.md's separation rule.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Update the repository-shape gate (Phase G.2)

**Files:**
- Modify: `.github/workflows/ci.yml:60-67`

**Context.** A workflow change, kept in its own PR per `CLAUDE.md`. It must merge
immediately after Task 8 -- CI is red in between, which is why they are a stacked
pair rather than one PR.

- [ ] **Step 1: Update the assertion list**

In `.github/workflows/ci.yml`, in the `repository-shape` job:

```yaml
      - name: Check required project files
        run: |
          test -f README.md
          test -f pyproject.toml
          test -f uv.lock
          test -f docs/tool-architecture.md
          test -f tools/registry.py
          test -f tools/agent/engine.py
          test -f tools/tui/app.py
```

`tools/runner.py` is removed; the engine and the app take its place as the files
whose disappearance should fail the build.

- [ ] **Step 2: Verify the workflow still parses**

```bash
actionlint .github/workflows/ci.yml || echo "actionlint not installed; rely on workflow-safety.yml"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: assert the engine and console instead of the retired runner

tools/runner.py was deleted in the preceding commit. The repository-shape
job now guards tools/agent/engine.py and tools/tui/app.py, which are the
files whose disappearance should fail the build.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Documentation sweep (Phase G.3)

**Files:**
- Modify: `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/tool-architecture.md`,
  `docs/repository-folders.md`, `docs/examples/README.md`, `tools/sessions.py:1`,
  `tools/registry.py:4`

**Context.** Its own PR, per `CLAUDE.md`'s separation rule. Every line below was
located by grep against `dev`; re-run the grep before editing in case the tree
moved.

- [ ] **Step 1: Find every stale reference**

```bash
grep -rn 'kepler-astro-query\|tools\.runner\|tools/runner\|claude_photometry_haiku' \
  --include='*.md' --include='*.py' . | grep -v '\.git/\|\.venv/\|docs/working/'
```

- [ ] **Step 2: Update each site**

| File | Change |
| --- | --- |
| `README.md:59-60,90,93-105,122-124,151-152,235,261` | Replace both agent surfaces with one `kepler` console; drop the `ANTHROPIC_API_KEY`-only framing, since the backend is now selectable. |
| `AGENTS.md:11,44` | `uv run kepler`; note `KEPLER_MODEL_BACKEND`. |
| `CLAUDE.md:63,226` | Update the `repository-shape` file list; replace "the optional `tools.runner` Anthropic loop" with the console and its backend selection. |
| `docs/tool-architecture.md:141,329` | Point at `tools.photometry_pipeline`; say the console persists the manifest. |
| `docs/repository-folders.md:74` | Rename in the folder guide; add `tools/agent/` and `tools/tui/` rows. |
| `docs/examples/README.md:63,93` | The example transcript was produced by the agent loop; update the command shown. |
| `tools/sessions.py:1` | Docstring: "for `tools.agent`". |
| `tools/registry.py:4` | Docstring: "`tools.agent` is the only consumer". |

- [ ] **Step 3: Fold the design into a reference document**

`docs/working/README.md` states the lifecycle: when a plan's work lands, fold the
durable outcome into a reference document and delete the plan. Add a section to
`docs/tool-architecture.md` describing `tools/agent/` and `tools/tui/` -- the
event contract, the approval policy, and the threading model -- then delete
`docs/working/tui-harness-design.md` and `docs/working/tui-harness-plan.md` and
remove both rows from `docs/working/README.md`.

- [ ] **Step 4: Verify and commit**

```bash
grep -rn 'kepler-astro-query\|claude_photometry_haiku' --include='*.md' . \
  | grep -v '\.git/\|\.venv/'
uv run pytest -q
git diff --check
git add -A
git commit -m "docs: describe the console, retire the old entry points

README, AGENTS, CLAUDE and the docs tree still described two agent
surfaces gated on ANTHROPIC_API_KEY. There is one now, and its backend is
selectable.

Folds the TUI design into docs/tool-architecture.md and deletes both
working plans, per the lifecycle in docs/working/README.md.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review notes

Run after the plan is written, before execution starts.

**Spec coverage.** Every section of `tui-harness-design.md` maps to a task:
section 4 (engine contract) -> Phase A in `model-port-plan.md` Task 5;
section 5 (approval) -> Task 2; section 7 (interface) -> Tasks 3 and 5;
section 8 (slash commands) -> Task 4; section 9 (artifacts) -> Task 6;
section 10 (dependencies) -> Task 3; section 11 (error handling) -> Tasks 2 and 5;
section 12 (migration) -> Tasks 1, 8, 9, 10; section 13 (testing) -> every task;
section 14 (phases) -> the task order.

**Known gap, deliberate.** Task 6 Step 8 and Task 7 Step 3 describe the modal
screens in prose rather than full code, because both are thin `ModalScreen`
subclasses over functions this plan does specify in full
(`render_halfblocks`, `render_waveform`, `history_from_manifest`,
`tools.workspace.list_artifacts`, `list_sessions`). The behaviour that could
regress silently is in the specified functions and is tested there.

**Type consistency.** `Decision`, `Approver`, `SessionPolicy`, `GraphicsTier`,
`Parsed`, `Command`, `ToolNode.state`, and `history_from_manifest` are each
defined once and used with the same signature everywhere they appear.

**Ordering hazard.** Tasks 8 and 9 leave CI red between them. That is stated in
both tasks. They must merge as a stacked pair; do not leave Task 8 on `dev`
overnight without Task 9.
