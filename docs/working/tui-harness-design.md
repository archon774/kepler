# Kepler TUI Agentic Harness

Date: 2026-09-07
Status: design approved 2026-09-07; implementation planned, no code written
Depends on: `model-port-plan.md` phases -1 to 3 (the `tools/llm/` model port).
Amends: `model-port-plan.md` Task 5 (see section 14).
Branch: `agent/tui-harness`, off `dev`.

Kepler has two model-driven entry points and neither is an interface. This
document specifies a Textual TUI that replaces both with a single branded
console, and the headless engine underneath it that makes one loop serve the
TUI, plain Python, and the future benchmark harness alike.

Two rules govern the design:

> The engine emits events; the interface renders them.

> Retire the entry points, not the capability.

The first is what keeps `textual` out of every module that a script or a test
might import. The second is what stops "supersede the old tools" from deleting
a photometry pipeline that 5 files and 48 registered tools depend on.

---

## 1. What Exists Today

Established by reading the code on `dev` at 9c6e913, not assumed.

**`tools/runner.py` is the only real agent loop.** `run()` (`tools/runner.py:316`)
is a single ~160-line function interleaving five concerns: the model loop, tool
dispatch, the repeated-call cache, session recording, and `print()`. Nothing in
it can render to anything but a stream, and nothing in it can pause mid-turn to
ask a question.

**`tools/claude_photometry_haiku_tool.py` is not primarily a model caller.** Of
its 1,270 lines, roughly 270 are the Anthropic path and CLI: `API_URL:320`,
`API_VERSION:321`, `parse_args:324`, `build_claude_prompt:989`,
`call_claude_haiku:1123`, `summarize_results:1145`, `main:1157`. The remaining
~1,000 lines are a photometry and plotting pipeline that the registry depends
on:

| Consumer | Uses |
| --- | --- |
| `tools/photometry.py:41` | `compute_photometry`, `plot_photometry`, `plot_zero_point_solution`, `load_fits_image`, `resolve_fits_path`, `list_bundled_targets`, `magnitude_label_for` |
| `tools/optical.py`, `tests/test_optical_registry.py:121,130` | `resolve_fits_path` |
| `tests/test_photometry_registry_smoke.py:8` | `resolve_fits_path` |
| `tests/test_photometry_tool_smoke.py` | the pipeline, extensively |
| `tools/models.py:228` | specified against `list_bundled_targets()` |

`docs/tool-architecture.md:141` states the relationship outright: "`tools.photometry`
is a thin wrapper reusing `tools.claude_photometry_haiku_tool`'s pipeline, not a
reimplementation." Deleting the file removes `run_photometry_on_target` and
`list_photometry_targets` from the registry -- two of the tools the TUI exists to
call.

**`tools/registry.py` is 48 tools**, up from the 23 recorded in
`model-backends-and-benchmarking.md` section 1; that document predates the
broken-links phases. Golden schema fixtures scale accordingly.

**`tools/sessions.py` already records what a session browser needs**: ordered
tool-call trace, canonical cache keys, cache-hit counts, per-call status,
warnings, errors, and artifact paths, written on start, after every tool call,
and at every terminal state.

**`tools/artifacts.py:40` scopes artifact writes with a `ContextVar`**, not a
module global. A new thread starts with an empty context, so entering
`scoped_artifacts` inside a worker thread is both correct and isolated. This is
what makes the threading model in section 6 safe.

**CI asserts `tools/runner.py` exists.** `.github/workflows/ci.yml:67`, inside
the required `repository-shape` job. Removing the file requires a workflow edit.

**`tests/test_runner_session.py` asserts only `manifest["outcome"] == "end_turn"`**
(line 113). It does not assert that tool exceptions propagate, which is what
makes the error-handling change in section 11 safe.

**`tools/llm/` does not exist.** PR #46 merged the model-port design and plan as
documentation only. Every backend this document assumes is unwritten.

---

## 2. Decisions

| Question | Decision |
| --- | --- |
| TUI framework | Textual, as a hard dependency. |
| Primary job | Astronomy research console. |
| Loop ownership | A headless engine in `tools/agent/`; the TUI is one subscriber. |
| Engine concurrency | Synchronous, run in a Textual thread worker. |
| Artifact display | Tiered: native terminal graphics, half-block floor, path always. |
| Old entry points | Both removed. Capability preserved and re-homed. |
| Backend switching | Launch-time in v1; live switching deferred. |

### 2.1 The zero-dependency rule is scoped, not broken

`model-backends-and-benchmarking.md` section 2.2 forbids new dependencies. That
rule was written for the model port, where it is a supply-chain judgement about
adapter code, and it stands unchanged for `tools/llm/`. It does not survive
contact with a terminal interface: no Python library reproduces the Ink /
Bubble Tea architecture that Claude Code, Gemini CLI, and opencode are built on
except Textual, and the alternatives are pieces of it rather than substitutes --
Rich is a renderer with no runtime, focus, or event loop; `prompt_toolkit` plus
Rich is Aider's stack and yields a REPL rather than an application.

**The rule is hereby scoped to `tools/llm/` and `tools/agent/`.** Both remain
dependency-free. `tools/tui/` is the only package permitted new dependencies,
and it is the only package that may import `textual`.

### 2.2 Rejected alternatives

**Callbacks on `run()`.** Adding `on_text` / `on_tool_call` / `approve_tool`
keywords is the smallest diff. Rejected: `run()` already does too much, a
blocking approval callback fights Textual's async model, and the benchmark
harness would still need a separate path.

**A TUI that owns its own loop.** Async-native, no runner refactor, no merge
risk against the port plan. Rejected: it leaves Kepler with two loops whose
caching, session recording, and fault handling drift apart -- the exact
fragmentation this work exists to end.

**Textual inline mode.** `app.run(inline=True)` renders beneath the prompt
instead of seizing the alt-screen, and is the closer match to how Claude Code
feels. Rejected for this application: it yields a fixed-height region with no
room for the artifact work that is this console's differentiator, it is
unsupported on Windows, and it is Textual's less-trodden path.

**Raw graphics escape sequences instead of `textual-image`.** Would cost zero
additional pins. Rejected: Textual owns the screen and repaints regions, so raw
graphics escapes are clobbered by the next diff. `textual-image` costs exactly
one pin because it reuses the already-pinned `pillow==12.3.0`.

---

## 3. Layout

```text
tools/agent/                 # the headless engine -- imports no UI, no textual
  __init__.py
  events.py                  # frozen event dataclasses; the event union
  engine.py                  # run_session()
  policy.py                  # approval policy table
  prompt.py                  # SYSTEM_PROMPT, moved intact from runner.py:46

tools/tui/                   # the only package that imports textual
  __init__.py
  __main__.py                # console script entry
  app.py                     # the App, layout, keybindings
  commands.py                # slash-command registry
  widgets/                   # transcript, tool node, artifact pane, session list
  render/                    # capability probe, half-block renderer, waveform

tools/photometry_pipeline.py # renamed from claude_photometry_haiku_tool.py
```

**Naming.** `tools/agent/` and `tools/tui/`; neither collides with anything.
The model-port spec already navigated `tools/models.py` and `algorithms/query`'s
`Backend` class; these add no new collisions.

---

## 4. The Engine Contract

**Events flow out as an iterator; decisions flow in as a callable.** A generator
that receives decisions through `.send()` was considered and rejected: splitting
the directions keeps the event stream pure, trivially testable, and directly
consumable by the benchmark harness.

```python
def run_session(
    user_message: str,
    *,
    backend: ModelBackend,          # tools/llm/, port phases 0-3
    system: str = SYSTEM_PROMPT,
    max_turns: int = 20,
    approver: Approver = auto_approve,
    session: AgentSession | None = None,
) -> Iterator[Event]: ...
```

### 4.1 The event union

```python
SessionStarted(session_id, manifest_path, backend_spec, model)
TurnStarted(turn)
TextDelta(text)                                  # streamed assistant text
ToolCallProposed(call_id, name, arguments)
ToolCallStarted(call_id, name, arguments, cache_hit)
ToolCallFinished(call_id, name, result, artifacts, duration_ms)
ToolCallDenied(call_id, name, reason)
ProtocolFault(turn, type, detail)                # the port's fault taxonomy
TurnFinished(turn, stop_reason, usage, latency_ms)
SessionFinished(outcome, manifest_path)
```

All frozen dataclasses. `ProtocolFault` carries the `FaultType` literal defined
by the model port, so the TUI renders faults the port already detects rather
than inventing a second taxonomy.

### 4.2 Consumers

| Consumer | Shape |
| --- | --- |
| `tools/runner.py` shim | Iterate and print. Byte-identical output to today. |
| `tools/tui/` | Iterate on a worker thread, `post_message` each event. |
| Benchmark harness (port phases 4-5) | Iterate and record. Trajectory data for free. |

### 4.3 Preserved behaviour

The engine keeps two behaviours that are load-bearing in `run()` today:

* **The repeated-call cache** keyed by `make_cache_key` (`tools/sessions.py`).
  The comment at `tools/runner.py:348` records why: a model was observed
  re-issuing an identical failing call across turns.
* **`session.save()` after every tool call**, so a killed run still leaves a
  readable manifest.

---

## 5. Approval

```python
class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"     # persists for the session

Approver = Callable[[ToolCallProposed], Decision]
```

`auto_approve` is the default and returns `ALLOW`, so the shim and any plain
Python caller behave exactly as today.

`tools/agent/policy.py` holds a table keyed by tool name, tagging each tool
`slow`, `keyed`, or `writes`. The default policy asks before running anything so
tagged and auto-runs pure lookups:

| Tag | Tools | Default |
| --- | --- | --- |
| `slow` | `run_full_hr_pipeline`, `run_full_hr_pipeline_from_catalog`, `extract_photometry_from_fits`, `run_photometry_on_target` | ask |
| `keyed` | `search_ads`, `get_paper_abstract`, `get_citing_papers`, `get_referenced_papers`, `build_literature_review` | ask |
| `writes` | `sonify_pulsar`, `plot_pulsar`, `plot_field_sed` | ask |
| untagged | the remaining lookups | auto |

**The table lives in `policy.py`, not in `registry.py`.** Adding fields to the
tool schemas would change the golden schema renderings that port phase 1 commits
as byte-stable fixtures in four dialects; a UI concern would start producing
diffs in the benchmark's own baseline.

A denied call returns an error result to the model rather than aborting the
turn, matching how the port's S8 treats schema violations.

---

## 6. Threading

The engine is synchronous. Textual runs it in `@work(thread=True)` and each
event reaches the UI thread through `post_message`. `scoped_artifacts` is
entered inside the worker, where the `ContextVar` is correctly isolated
(section 1).

Approval crosses back the other way: the approver blocks the worker on a
`threading.Event` while the UI thread renders a modal and sets the answer. The
engine never learns a UI exists; it called a function that took a while to
return.

This is what keeps the interface alive while `run_photometry_on_target` blocks
for minutes, without making the engine async and unusable from plain Python --
which `docs/tool-architecture.md` section 7 requires ("A Python caller must be
able to import and call every tool without running a server").

---

## 7. The Interface

**Full-screen, single column.** A research console reads best as one
conversation you scroll. Artifact and session browsers are modal screens on
keybindings and slash commands, so they get the whole terminal when invoked and
cost nothing when not.

```text
+- Kepler ------------------------- anthropic/claude-opus-5 -+
|                                                            |
|  transcript: assistant text, streamed                      |
|  v search_vizier(target="Cas A", category="radio")  1.2s ok |
|      max_catalogs: null                                    |
|      -> 47 catalogs - VIII/85A, VIII/1, ...                |
|  > run_photometry_on_target(...)            [spin] 47.3s   |
|                                                            |
+------------------------------------------------------------+
| > ask something, or /help                                  |
+------------------------------------------------------------+
| turn 3/20 - 12.4k tok - 6 artifacts - ^A artifacts ^S sessions|
+------------------------------------------------------------+
```

### 7.1 Tool call rendering

Each call is a collapsible transcript node. The live state is the point.

* **Running** -- spinner and a ticking elapsed timer. A four-minute plate solve
  must look like progress, not a hang.
* **Finished** -- duration, status glyph, a `cached` marker when the call cache
  hit, artifact chips for anything written.
* **Expanded** -- full arguments, syntax-highlighted result JSON (Rich plus the
  already-pinned Pygments), artifact previews inline.
* **Denied** -- rendered distinctly, showing the error result returned to the
  model.

---

## 8. Slash Commands

Commands are **UI-level and never reach the model**. A line beginning with `/`
is intercepted by the input widget, matched against the registry in
`tools/tui/commands.py`, and dispatched to a handler. Anything else is sent to
the engine as a user message.

* `//` at the start of a line escapes to a literal leading slash, for the rare
  message that genuinely starts with one.
* An unknown command renders an inline error and is **not** forwarded to the
  model. Silently sending `/sessions` to an LLM because of a typo would waste a
  turn and confuse the transcript.
* Tab completes command names and, where a command declares a completer,
  its arguments.

The registry is declarative -- name, aliases, help text, handler, optional
argument completer -- so `/help` is generated rather than maintained, and every
command is testable headlessly.

| Command | Effect |
| --- | --- |
| `/help` | List commands. Generated from the registry. |
| `/artifacts` | Artifact browser modal for the current session. |
| `/sessions` | Session history browser modal. |
| `/resume <id>` | Resume a session, seeding history from its manifest. |
| `/status` | Backend, model, turn, token usage, session id, artifact directory, detected graphics tier. |
| `/tools [filter]` | Browse the 48 registered tools and their schemas. |
| `/approve [tool] [ask\|always\|never]` | View or change the approval policy. |
| `/prompt` | View the active system prompt. |
| `/new` | Start a fresh session. |
| `/quit` | Exit. |

`/status` reports token usage and cost when the manifest carries them and omits
those rows otherwise, so it degrades cleanly before port phase 4 lands.

**Deferred:** `/backend` for live switching (section 15).

---

## 9. Artifact Rendering

A capability probe at startup, cached for the session: `KITTY_WINDOW_ID` and
`TERM=xterm-kitty`, `TERM_PROGRAM=iTerm.app`, then a Sixel Device Attributes
query under a short timeout.

Inside the transcript, `textual-image` renders Kitty, iTerm2, and Sixel natively
and falls back to half-blocks itself. **The half-block path via Pillow is the
guaranteed floor** and composes with Textual perfectly, being nothing but
coloured characters. Artifact path plus an open-externally action is available
at every tier.

WAV sonifications render as a braille waveform with a play action shelling out
to `ffplay`, `aplay`, or `afplay`. The waveform is presentational only:
`docs/extraction.md` (Pulsar Sonification section 7.2) records that synthesis
ignores sample timestamps, so a period must never be read off rendered audio.
The folded-profile plot beside it is the scientific artifact.

---

## 10. Dependencies

Eight new pins, resolved against the existing lockfile rather than estimated:

```text
textual==8.2.8          rich==15.0.0            markdown-it-py==4.2.0
mdurl==0.1.2            linkify-it-py==2.2.0    mdit-py-plugins==0.6.1
platformdirs==4.11.7    textual-image==0.13.2
```

`pygments==2.20.0`, `pillow==12.3.0`, and `typing-extensions==4.16.0` are
already pinned at compatible versions and do not move. `pyproject.toml` pins with
`==` and CI runs `uv run --locked`, so this lands with a regenerated `uv.lock` in
its own dependency PR (phase D).

---

## 11. Error Handling

| Failure | Behaviour |
| --- | --- |
| Ollama not running | The port's `/api/tags` probe reports "backend unavailable"; the TUI offers another backend. Never a connection traceback. |
| Missing API key | A configuration screen, not an exit. |
| Tool raises | The engine catches it, emits `ToolCallFinished` with an error result, and feeds that back to the model. |
| Protocol fault | A `ProtocolFault` event renders a fault badge; the run continues. |
| Model stream fails mid-turn | Session saved with `outcome="error"`, transcript preserved, manifest path shown. |

The third row is a **deliberate divergence** from `tools/runner.py`, which today
lets a tool exception propagate out of `run()`. It is consistent with the port's
S8 treatment of schema violations ("an error result returned to the model -- not
an exception"), and section 1 establishes that no test depends on the current
behaviour. It is called out here so review treats it as a behaviour change
rather than an implementation detail.

---

## 12. Entry Point Migration

| Today | After |
| --- | --- |
| `kepler-astro-query` -> `tools.runner:main` | removed |
| `python3 tools/claude_photometry_haiku_tool.py` | removed |
| -- | `kepler` -> `tools.tui.__main__:main` |
| `tools/runner.py` | shim during migration, then deleted |
| `SYSTEM_PROMPT` (`tools/runner.py:46`) | `tools/agent/prompt.py`, unchanged |
| Haiku tool's Anthropic path and CLI | deleted |
| Haiku tool's ~1,000-line pipeline | `tools/photometry_pipeline.py` |

**`SYSTEM_PROMPT` moves intact.** It is ~270 lines of confirmed-live failure-mode
guidance, `model-backends-and-benchmarking.md` section 6.2 names it as the source
of all eight benchmark seed tasks, and `algorithms/hrdiagram_py/literature.py:7`
and `tools/hr_diagram.py:202` cite it in comments.

**Deleting `tools/runner.py` requires editing `.github/workflows/ci.yml:67`.**
Per `CLAUDE.md`, workflow changes ship separately from behaviour changes, so
phase G is at least two PRs.

Documentation referencing the removed entry points and updated in phase G:
`README.md` (lines 59, 90, 93, 99, 105, 122-124, 151-152, 235, 261), `AGENTS.md`
(11, 44), `CLAUDE.md` (63, 226), `docs/tool-architecture.md` (141, 329),
`docs/repository-folders.md` (74), `docs/examples/README.md` (63, 93),
`tools/sessions.py:1`, `tools/registry.py:4`.

---

## 13. Testing

Everything below runs in default `pytest` -- offline, deterministic, no API keys,
no daemon, no terminal.

* **Engine.** A fake backend drives a two-turn tool loop; the test asserts the
  exact event sequence. This is the primary contract test.
* **Approval.** `DENY` produces `ToolCallDenied`, returns an error result to the
  model, and -- the assertion that matters -- the tool function is never called.
* **Slash commands.** Registry dispatch, `//` escaping, unknown-command handling,
  and the assertion that no command text is ever forwarded to the engine.
* **TUI.** Textual's `run_test()` pilot drives keypresses headlessly and asserts
  widget state. The interface is genuinely CI-testable.
* **Rendering.** The capability probe against faked environments; the half-block
  renderer against a committed 4x4 PNG with byte-stable expected output.
* **Migration.** After phase C, the existing photometry tests pass against the
  renamed module unchanged in substance.

CI keeps its shape: `compileall`, `pytest`, `repository-shape`. No new job.
`ci.yml:67` drops `test -f tools/runner.py` and gains `tools/agent/engine.py`
and `tools/tui/app.py`.

---

## 14. Phases

One narrow PR each; documentation, workflow, dependency, and behaviour changes
stay separated per `CLAUDE.md`.

| Phase | Content | Done when |
| --- | --- | --- |
| **A** | `tools/agent/`: events, engine, `SYSTEM_PROMPT` moved. `runner.py` becomes a shim. | `tests/test_runner_session.py` passes **unedited**. |
| **B** | Approval policy and approver wiring. | A denied call never dispatches. |
| **C** | `photometry_pipeline.py` rename, 5 import sites, docs. | Suite green. Independent of A and B. |
| **D** | Textual dependency (8 pins, `uv lock`) and TUI skeleton: transcript, streaming, tool tree, status bar, slash-command registry with `/help`, `/status`, `/tools`, `/prompt`, `/approve`, `/new`, `/quit`. | A real session runs end to end. |
| **E** | Artifact rendering: probe, tiers, and `/artifacts`. | Half-block path green in CI. |
| **F** | Session browser and resume: `/sessions` and `/resume`. | A resumed session continues a prior trace. |
| **G** | Retire entry points: delete `runner.py`, `ci.yml` edit, `pyproject` scripts, documentation sweep. | Nothing references the removed entry points. |

**Phase G is the point of no return and is deliberately last.** Every earlier
phase leaves a working `kepler-astro-query`, so the TUI can be used and judged
before the old surface is removed.

### 14.1 Amendment to `model-port-plan.md` Task 5

Task 5 of the approved model-port plan refactors the body of `run()` in place and
explicitly preserves `SYSTEM_PROMPT`, `main()`, and the `kepler-astro-query`
console script -- all of which phase G then deletes.

**Task 5 should instead build `tools/agent/` directly and leave `tools/runner.py`
as a shim delegating to it.** The gate is unchanged and still meaningful:
`tests/test_runner_session.py` must pass unedited, now against the shim.

The amendment is a scheduling decision, not a design change, and either answer
leaves the same end state:

* **Accepted** -- phase A below is absorbed into the port's Task 5 and does not
  ship as its own PR. The TUI work starts at phase B.
* **Declined** -- Task 5 refactors `run()` in place as written, and phase A
  ships afterwards as its own PR, extracting the engine from the just-refactored
  function. `run()` is then rewritten twice, which is the cost of declining.

The port plan's other tasks are unaffected either way.

---

## 15. Non-Goals and Deferred Work

* **Live backend switching.** The backend is chosen at launch from
  `KEPLER_MODEL_BACKEND`, a flag, or the config screen. `/backend` and the
  capability-difference warnings -- notably that Gemini's OpenAPI subset cannot
  express the `["integer", "null"]` union `search_vizier.max_catalogs` needs --
  are follow-on work.
* **The pulsar stage-order guardrail.** Surfacing the light curve -> periodogram
  -> period -> fold -> sonify dependency with `peak_confidence` and `pulse_snr`
  inline is deferred. The stage order remains documented in `CLAUDE.md` and
  `docs/pulsar-tool-pipeline.md`.
* **No serving surface.** `docs/tool-architecture.md` section 7 stands. A TUI is
  a local interface, not a server; nothing here exposes a port.
* **No benchmark harness.** Port phases 4-5 own that. This design makes the
  engine a usable input to it and no more.
* **No changes to `algorithms/`.** The extraction contract is untouched.
* **No Windows-specific work.** Textual runs on Windows; the abandoned inline
  mode would not have.

---

## 16. Open Questions

1. **Does `textual-image` handle Textual's repaint cycle cleanly at the sizes
   Kepler's plots use?** Resolved by measurement in phase E against a real
   periodogram PNG. If it does not, the fallback is decided rather than silent:
   half-blocks in the transcript, native protocols only in a suspended
   full-screen view.
2. **Is a 4x4 PNG a stable enough golden for the half-block renderer across
   Pillow patch releases?** Phase E decides between a byte-stable golden and a
   structural assertion.
3. **Should `/resume` replay artifacts into the transcript, or reference them?**
   Replaying re-renders every image on resume, which is slow for a long session.
   Leaning toward referencing, with `/artifacts` as the way back in.

---

## 17. References

* `docs/working/model-backends-and-benchmarking.md` -- the model port this design
  consumes; sections 4.2, 4.6, and S8 in particular.
* `docs/working/model-port-plan.md` -- phases -1 to 3; Task 5 amended by section 14.1.
* `docs/tool-architecture.md` section 7 -- the runtime policy that keeps the
  engine synchronous and importable.
* `tools/runner.py:46`, `:316` -- `SYSTEM_PROMPT` and the loop being replaced.
* `tools/artifacts.py:40` -- the `ContextVar` that makes the thread worker safe.
* `tools/claude_photometry_haiku_tool.py:320-1157` -- the Anthropic path being
  deleted, and by omission the pipeline being kept.
* `.github/workflows/ci.yml:67` -- the assertion phase G must edit.
