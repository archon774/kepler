# Kepler TUI Agentic Harness

**Status:** Design approved; phases B–F complete, plus the backend switching
that section 15 had deferred and the `kepler` console script from G.1. The rest
of phase G — retiring `tools/runner.py` and its console script — remains.
**Date:** 2026-09-07
**Prerequisites:** [model-backends.md](model-backends.md) phases -1 to 3, and the
merged stateless optical rollout from [optical-tools.md](optical-tools.md).
**Unblocks:** The Textual `kepler` console and the retirement of both legacy
entry points.
**Branch:** `agent/tui-harness`, off `dev`. `CLAUDE.md` defaults to `dev`; do not
retarget to `main`.

Kepler has two model-driven entry points and neither is an interface. This
document specifies a Textual TUI that replaces both with a single branded
console, the headless engine underneath it that makes one loop serve the TUI,
plain Python, and the future benchmark harness alike, and the phased rollout that
builds them.

Two rules govern the design:

> The engine emits events; the interface renders them.

> Retire the entry points, not the capability.

The first is what keeps `textual` out of every module a script or a test might
import. The second is what stops "supersede the old tools" from deleting a
photometry pipeline that five files and the registry depend on.

This document is architecture and sequencing. It contains no implementation
code. An agent working a phase reads the contracts here, then writes the code
that satisfies them.

---

## 1. What Exists Today

Established by reading the code on `dev`, not assumed.

**`tools/runner.py` is the only real agent loop.** `run()` is a single ~160-line
function interleaving five concerns: the model loop, tool dispatch, the
repeated-call cache, session recording, and printing. Nothing in it can render to
anything but a stream, and nothing in it can pause mid-turn to ask a question.

**`tools/photometry_pipeline.py` is a reusable photometry and plotting
pipeline, not a model caller.** Phase C moved the former module with history,
removed its Anthropic path and CLI, and retained the pipeline the registry
depends on:

| Consumer | Uses |
| --- | --- |
| `tools/photometry.py` | `compute_photometry`, `plot_photometry`, `plot_zero_point_solution`, `load_fits_image`, `resolve_fits_path`, `list_bundled_targets`, `magnitude_label_for` |
| `tools/optical.py`, `tests/test_optical_registry.py` | `resolve_fits_path` |
| `tests/test_photometry_registry_smoke.py` | `resolve_fits_path` |
| `tests/test_photometry_tool_smoke.py` | the pipeline, extensively |
| `tools/models.py` | specified against `list_bundled_targets()` |

`docs/tool-architecture.md` states the relationship outright: `tools.photometry`
is a thin wrapper reusing that pipeline, not a reimplementation. Deleting the
file removes two of the tools the TUI exists to call.

**`tools/registry.py` is 48 tools** at the time this design was written, and
**49** after PR #47 added `solve_astrometry` — verified 2026-09-07. It was 23 when
[model-backends.md](model-backends.md) recorded it; that document predates the
broken-links phases. Golden schema fixtures scale accordingly.

**`tools/sessions.py` already records what a session browser needs**: the ordered
tool-call trace, canonical cache keys, cache-hit counts, per-call status,
warnings, errors, and artifact paths, written on start, after every tool call,
and at every terminal state.

**`tools/artifacts.py` scopes artifact writes with a `ContextVar`**, not a module
global. A new thread starts with an empty context, so entering the scoped-artifact
manager inside a worker thread is both correct and isolated. This is what makes
the threading model in section 6 safe.

**CI asserts `tools/runner.py` exists**, inside the required `repository-shape`
job. Removing the file requires a workflow edit.

**`tests/test_runner_session.py` asserts only that the manifest outcome is
`end_turn`.** It does not assert that tool exceptions propagate, which is what
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
| Backend switching | Launch-time **and live**, through `/backend`. The
deferral in section 15 was lifted — see 8.1. |

### 2.1 The zero-dependency rule is scoped, not broken

[model-backends.md](model-backends.md) section 2.2 forbids new dependencies. That
rule was written for the model port, where it is a supply-chain judgement about
adapter code, and it stands unchanged for `tools/llm/`. It does not survive
contact with a terminal interface: no Python library reproduces the Ink /
Bubble Tea architecture that Claude Code, Gemini CLI, and opencode are built on
except Textual, and the alternatives are pieces of it rather than substitutes —
Rich is a renderer with no runtime, focus, or event loop; `prompt_toolkit` plus
Rich is Aider's stack and yields a REPL rather than an application.

**The rule is hereby scoped to `tools/llm/` and `tools/agent/`.** Both remain
dependency-free. `tools/tui/` is the only package permitted new dependencies, and
the only package that may import `textual`.

### 2.2 Rejected alternatives

**Callbacks on `run()`.** Adding text, tool-call, and approval keywords is the
smallest diff. Rejected: `run()` already does too much, a blocking approval
callback fights Textual's async model, and the benchmark harness would still need
a separate path.

**A TUI that owns its own loop.** Async-native, no runner refactor, no merge risk
against the model port. Rejected: it leaves Kepler with two loops whose caching,
session recording, and fault handling drift apart — the exact fragmentation this
work exists to end.

**Textual inline mode.** Rendering beneath the prompt instead of seizing the
alt-screen is the closer match to how Claude Code feels. Rejected for this
application: it yields a fixed-height region with no room for the artifact work
that is this console's differentiator, it is unsupported on Windows, and it is
Textual's less-trodden path.

**Raw graphics escape sequences instead of `textual-image`.** Would cost zero
additional pins. Rejected: Textual owns the screen and repaints regions, so raw
graphics escapes are clobbered by the next diff. `textual-image` costs exactly one
pin because it reuses the already-pinned `pillow`.

---

## 3. Layout

| Path | Responsibility |
| --- | --- |
| `tools/agent/__init__.py` | Package marker. Imports no UI. |
| `tools/agent/events.py` | The ten frozen event dataclasses and the `Event` union. |
| `tools/agent/engine.py` | `run_session()`. |
| `tools/agent/policy.py` | `Decision`, `RiskTag`, `TOOL_RISK`, `Approver`, `auto_approve`, `risk_tags`, `needs_confirmation`, `SessionPolicy`, `policy_approver`. No UI. |
| `tools/agent/prompt.py` | `SYSTEM_PROMPT`, moved intact from `tools/runner.py`. |
| `tools/tui/__init__.py` | Package marker. Exports nothing heavy. |
| `tools/tui/__main__.py` | Console-script entry: argument parsing, `launch_spec`, backend construction, application launch. |
| `tools/tui/app.py` | `KeplerApp`: layout, keybindings, the engine thread worker, the approval modal, `resume_session`. |
| `tools/tui/commands.py` | `Command`, `COMMANDS`, `Parsed`, `parse_input`, `resolve`, `help_text`. No Textual imports beyond types. |
| `tools/tui/backends.py` | `BackendChoice`, `CHOICES`, `resolve_spec`, `open_backend`, `describe_choices`, `unavailable_message`. The UI-facing half of backend selection. No Textual. |
| `tools/tui/widgets/header.py` | `KeplerHeader` — the titled frame, and the live backend spec inside it. |
| `tools/tui/widgets/transcript.py` | `Transcript`, with a single `handle_event` entry point; assistant text and tool nodes. |
| `tools/tui/widgets/tool_node.py` | `ToolNode` — one collapsible tool call, with `start()`, `finish()`, and `deny()`. |
| `tools/tui/widgets/artifacts.py` | Artifact browser modal screen. |
| `tools/tui/widgets/sessions.py` | `SessionBrowser` modal screen, and `history_from_manifest`. |
| `tools/tui/render/capability.py` | `GraphicsTier` and `detect_tier` — the terminal graphics capability probe. |
| `tools/tui/render/image.py` | `render_halfblocks` — the half-block PNG renderer; native-protocol delegation. |
| `tools/tui/render/waveform.py` | `render_waveform` — braille waveform for WAV artifacts. |
| `tools/photometry_pipeline.py` | Renamed from `claude_photometry_haiku_tool.py`, Anthropic path removed. |

**`tools/agent/` imports no UI code, no `textual`, and no `rich`.** A test asserts
this. It is what keeps every tool callable from plain Python per
`docs/tool-architecture.md` section 7.

**Naming.** `tools/agent/` and `tools/tui/`; neither collides with anything. The
model port already navigated `tools/models.py` and `algorithms/query`'s `Backend`
class; these add no new collisions.

---

## 4. The Engine Contract

**Events flow out as an iterator; decisions flow in as a callable.** A generator
receiving decisions through `.send()` was considered and rejected: splitting the
directions keeps the event stream pure, trivially testable, and directly
consumable by the benchmark harness.

`run_session()` takes the user message, and keyword-only: the backend (from
`tools/llm/`), the system prompt defaulting to `SYSTEM_PROMPT`, a turn ceiling
defaulting to 20, an approver defaulting to the allow-everything one, and an
optional session. It returns an iterator of events.

### 4.1 The event union

Ten frozen dataclasses:

| Event | Fields |
| --- | --- |
| `SessionStarted` | `session_id`, `manifest_path`, `backend_spec`, `model` |
| `TurnStarted` | `turn` |
| `TextDelta` | `text` — streamed assistant text |
| `ToolCallProposed` | `call_id`, `name`, `arguments` |
| `ToolCallStarted` | `call_id`, `name`, `arguments`, `cache_hit` |
| `ToolCallFinished` | `call_id`, `name`, `result`, `artifacts`, `duration_ms` |
| `ToolCallDenied` | `call_id`, `name`, `reason` |
| `ProtocolFault` | `turn`, `type`, `detail` |
| `TurnFinished` | `turn`, `stop_reason`, `usage`, `latency_ms` |
| `SessionFinished` | `outcome`, `manifest_path` |

`ProtocolFault` carries the `FaultType` literal defined by the model port, so the
TUI renders faults the port already detects rather than inventing a second
taxonomy.

**These are built by [model-backends.md](model-backends.md) Phase 0c**, not here.
That document owns the engine's construction; this one owns its interface.

### 4.2 Consumers

| Consumer | Shape |
| --- | --- |
| `tools/runner.py` shim | Iterate and print. Byte-identical output to today. |
| `tools/tui/` | Iterate on a worker thread, posting each event to the UI thread. |
| Benchmark harness (model-port phases 4–5) | Iterate and record. Trajectory data for free. |

### 4.3 Preserved behaviour

The engine keeps two behaviours that are load-bearing in `run()` today:

* **The repeated-call cache**, keyed by `make_cache_key` in `tools/sessions.py`.
  The comment in the runner records why: a model was observed re-issuing an
  identical failing call across turns.
* **Saving the session after every tool call**, so a killed run still leaves a
  readable manifest.

---

## 5. Approval

`Decision` is a string enum of three values: `ALLOW`, `DENY`, and `ALLOW_ALWAYS`
(which persists for the session). `Approver` is any callable taking a
`ToolCallProposed` and returning a `Decision`. The default, `auto_approve`,
returns `ALLOW`, so the shim and any plain-Python caller behave exactly as today.

`tools/agent/policy.py` holds `TOOL_RISK`, a table keyed by tool name tagging each
tool with a `RiskTag` — `slow`, `keyed`, or `writes` — plus `risk_tags` and
`needs_confirmation` to read it, and `SessionPolicy`, which wraps an `ask`
callable and remembers `ALLOW_ALWAYS` answers for the rest of the session.

| Tag | Tools | Default |
| --- | --- | --- |
| `slow` | `run_full_hr_pipeline`, `run_full_hr_pipeline_from_catalog`, `extract_photometry_from_fits`, `run_photometry_on_target` | ask |
| `keyed` | `search_ads`, `get_paper_abstract`, `get_citing_papers`, `get_referenced_papers`, `build_literature_review` | ask |
| `writes` | `sonify_pulsar`, `plot_pulsar`, `plot_field_sed` | ask |
| untagged | the remaining lookups | auto |

**The table lives in `policy.py`, not in `registry.py`.** Adding fields to the
tool schemas would change the golden schema renderings that model-port phase 1a
commits as byte-stable fixtures in four dialects; a UI concern would start
producing diffs in the benchmark's own baseline.

A denied call returns an error result to the model rather than aborting the turn,
matching how the port's S8 treats schema violations. **The assertion that matters
is that the tool function is never called.**

---

## 6. Threading

The engine is synchronous. Textual runs it in a thread worker and each event
reaches the UI thread through `post_message`, wrapped in a Textual `Message`
subclass. **Alias Textual's `Message` on import** — `tools.llm.types.Message` is
the neutral message type and the bare name collides. `scoped_artifacts` is entered
inside the worker, where the `ContextVar` is correctly isolated (section 1).

Approval crosses back the other way: the approver blocks the worker on a
`threading.Event` while the UI thread renders a modal and sets the answer. The
engine never learns a UI exists; it called a function that took a while to return.

This is what keeps the interface alive while a photometry run blocks for minutes,
without making the engine async and unusable from plain Python — which
`docs/tool-architecture.md` section 7 requires ("A Python caller must be able to
import and call every tool without running a server").

---

## 7. The Interface

**Full-screen, single column.** A research console reads best as one conversation
you scroll. Artifact and session browsers are modal screens on keybindings and
slash commands, so they get the whole terminal when invoked and cost nothing when
not.

The screen is a titled frame carrying the backend spec, a scrolling transcript of
assistant text and tool-call nodes, an input line prompting for a question or a
slash command, and a status bar showing turn count against the ceiling, token
usage, artifact count, and the artifact- and session-browser keybindings.

The titled frame is `KeplerHeader`, docked at the top from the moment the
application mounts: the wordmark as its border title, the tagline and the live
`provider/model` spec on its one inner row. It replaces Textual's stock
`Header`, which carried the same two strings in a single unbranded bar.

Three rows, and a Textual border rather than drawn box characters, so the frame
follows the terminal width and the active theme. **The wordmark is
letter-spaced rather than drawn in block capitals**: block capitals need five
rows to stay legible, and in a console that is one scrolling conversation every
row the header keeps is a row of transcript nobody can see.

**The backend spec belongs in the header, not only in the status bar.** It is
the one piece of session identity a person must not misread — a transcript
looks identical whether Anthropic or a local Ollama model produced it — and
since 8.1 it can change mid-session, so it is re-rendered on every switch.

### 7.1 Tool call rendering

Each call is a collapsible transcript node. The live state is the point.

* **Running** — spinner and a ticking elapsed timer. A four-minute plate solve
  must look like progress, not a hang.
* **Finished** — duration, status glyph, a cached marker when the call cache hit,
  artifact chips for anything written.
* **Expanded** — full arguments, syntax-highlighted result JSON (Rich plus the
  already-pinned Pygments), artifact previews inline.
* **Denied** — rendered distinctly, showing the error result returned to the
  model.

---

## 8. Slash Commands

Commands are **UI-level and never reach the model**. A line beginning with a slash
is intercepted by the input widget, matched against the registry, and dispatched
to a handler. Anything else is sent to the engine as a user message.

* A doubled leading slash escapes to a literal one, for the rare message that
  genuinely starts with a slash.
* An unknown command renders an inline error and is **not** forwarded to the
  model. Silently sending a mistyped command to an LLM would waste a turn and
  pollute the transcript.
* Tab completes command names and, where a command declares a completer, its
  arguments.

The registry is declarative — name, aliases, help text, handler, optional argument
completer — so `help_text()` is generated from `COMMANDS` rather than maintained,
and every command is testable headlessly. `parse_input` yields a `Parsed` of one
of three kinds: `message`, `command` (with its `args`), or `unknown`. `resolve`
maps a name or alias to its `Command`.

| Command | Effect |
| --- | --- |
| `/help` | List commands. Generated from the registry. |
| `/artifacts` | Artifact browser modal for the current session. |
| `/sessions` | Session history browser modal. |
| `/resume <id>` | Resume a session, seeding history from its manifest. |
| `/status` | Backend, model, turn, token usage, session id, artifact directory, detected graphics tier. |
| `/backend [name\|spec] [model]` | List the offered backends, or switch to one. See 8.1. |
| `/tools [filter]` | Browse the registered tools and their schemas. |
| `/approve [tool] [ask\|always\|never]` | View or change the approval policy. |
| `/prompt` | View the active system prompt. |
| `/new` | Start a fresh session. |
| `/quit` | Exit. |

`/status` reports token usage and cost when the manifest carries them and omits
those rows otherwise, so it degrades cleanly before the port's manifest v2 lands.

### 8.1 `/backend` — selecting the model

Section 15 deferred this and section 2 said "launch-time in v1". Both are
superseded: the backend is selectable from inside the session.

`tools/tui/backends.py` holds the short list a person picks from —
`anthropic` (default model `claude-sonnet-5`, reads `ANTHROPIC_API_KEY`) and
`ollama` (default `qwen3.8:27b-mlx`, reads `OLLAMA_BASE_URL`, no key).
`/backend` with
no arguments describes both and marks the running one. `/backend anthropic`
expands to that provider's default model; `/backend ollama llama3.1:8b` and
`/backend ollama/llama3.1:8b` both name a model explicitly.

It owns **none** of the construction rules. Credential and endpoint binding
stays in `tools/llm/factory.py` (S3): this module hands it a spec and
interprets the failure. A full `provider/model` spec is therefore passed
through untouched, so the two providers the factory recognizes but this console
does not list — `openai`, `gemini` — remain reachable by spec.

Four properties make the command safe to offer mid-session:

* **Probe before swap, in two steps.** Anthropic fails fast, at construction,
  when its key is missing. Ollama does not, and fails in *two* different ways,
  both mid-turn. A backend pointed at a daemon that is not running builds
  perfectly and raises a connection error several seconds into the first
  question, after the transcript already shows a turn starting. And **a daemon
  that is up is not a daemon that has your model**: Ollama answers an unknown
  one with a 404 from `/v1/chat/completions`, arriving as a bare
  `httpx.HTTPStatusError` at exactly the same point. Section 11 requires
  "never a connection traceback", so `open_backend` checks both —
  `is_available()` for the service, then `installed_models()` for the model —
  and the session's backend is replaced only after both pass. A failed
  listing returns `()`, which means "could not ask" and is deliberately not
  read as "holds nothing"; it never becomes a refusal to run.

  The second check was added after the first live run against a working
  daemon, which is also the run that found the default model wrong (8.2).
* **A failed switch changes nothing.** The message names what to do *and*
  which backend is still answering, so it never reads as a session that has
  lost its model. One wording, `unavailable_message`, shared with the
  launcher.
* **Never mid-turn.** `run_session()` was handed the backend by value when the
  turn started; swapping it while that turn runs would retitle the header for
  a turn the old backend is still finishing. The guard rides on
  `_session_running()`, the session worker phase F already tracks for resume —
  set on the UI thread inside `run_prompt`, *before* the worker starts. That
  ordering is the point: a flag set inside the worker is still `False` during
  the one moment the guard exists to cover, and phase F's prompt-disable rides
  on the same fact, so the two cannot drift apart.
* **The header follows.** `KeplerHeader.set_backend` runs on every switch.

### 8.2 The Ollama default model

`qwen3.8:27b-mlx`, not [model-backends.md](model-backends.md)'s planned
`qwen3:8b`. Phase 2b could not find `qwen3:8b` on its measurement host and
standardised on `qwen3.8:27b-mlx` — it is `tests/test_llm_ollama_backend.py`'s
`OLLAMA_REFERENCE_MODEL` and what every [benchmark.md](benchmark.md) sweep
ran. `README.md`'s `ollama/qwen3:8b` example was the stale plan value, and was
where this console's default was first taken from; it now names the model the
daemon actually holds.

A live daemon confirmed it: eleven models installed, none of them `qwen3:8b`,
and `/backend ollama` refused with the model listing rather than a traceback.
A default nobody has installed makes the bare, most natural form of the
command fail for everyone.

### 8.3 Which key, and where it comes from

`tools/config.py` gained `load_dotenv()`: a dependency-free reader that merges
`KEY=value` lines from the repository's untracked `.env` into `os.environ`
before the factory reads it. `tools/llm/` is unchanged and still reads only the
environment — this puts the file's contents *into* that environment, rather
than teaching the port a second source.

**The real environment always wins.** A variable already set is left alone, so
`ANTHROPIC_API_KEY=… kepler` still overrides the file and a test's
`monkeypatch.setenv` is not silently undone. A missing or unreadable file is
not an error.

Nothing is interpolated: `$HOME` in a value stays four characters, because a
credential is not a shell word. A line carrying no `=` is read through a table
of self-identifying provider prefixes — today just `sk-ant-` →
`ANTHROPIC_API_KEY` — because a hand-written `.env` often holds the key and
nothing else. An OpenAI `sk-` is deliberately *not* in that table: several
services mint keys with it, so the prefix names no one provider.

`open_backend` re-reads the file, so a key added while the console is open
takes effect on the next `/backend` without a restart.

### 8.4 Launch-time selection

`launch_spec()` resolves in one order and no other: the `--backend` flag, then
`KEPLER_MODEL_BACKEND`, then the first offered choice. The flag accepts a bare
name (`--backend ollama`); the environment variable does not, because it is the
model port's own contract and `tools/runner.py` and the benchmark harness read
it identically.

An unset variable now opens the console on Anthropic rather than refusing. That
is a consequence of 8.1: the backend is no longer a decision a person is stuck
with for the session, so an unset variable should not be a usage error printed
at someone who has not seen the interface yet. A console that genuinely cannot
be configured exits **2** — it is launched from shells and scripts, and
reporting success after printing "cannot use" to stderr is how a wrapper ends
up believing a session ran.

---

## 9. Artifact Rendering

`detect_tier` runs at startup, cached for the session: it checks
`KITTY_WINDOW_ID` and `TERM=xterm-kitty`, then `TERM_PROGRAM=iTerm.app`, then
issues a Sixel device-attributes query under a short timeout. The resulting
`GraphicsTier` is one of `KITTY`, `ITERM2`, `SIXEL`, or `HALFBLOCK`.

Inside the transcript, `textual-image` renders Kitty, iTerm2, and Sixel natively
and falls back to half-blocks itself. **The half-block path via Pillow is the
guaranteed floor** and composes with Textual perfectly, being nothing but coloured
characters. The artifact path plus an open-externally action is available at every
tier.

### 9.1 The image library is imported on use, not on launch

`textual_image.widget` probes the terminal for its cell size **at import time**,
and the probe divides by the column count `TIOCGWINSZ` reports. A tty that
reports no size at all — a pty a wrapper opened without setting one — makes
that division raise `ZeroDivisionError` from inside a third-party import. It
had `tools/tui/widgets/artifacts.py` at module scope, and `app.py` imports the
browser, so the failure killed `kepler` before the first frame: a traceback
where the header should be, from a library the session may never use.

`_native_image()` imports it on first use instead, and a probe that fails there
falls back to half-blocks rather than to an error — the native protocol is an
improvement on the floor described above, never a requirement. Found by
launching the real console script under an unsized pty; a sized one never
reaches it, which is why nothing before this had.

WAV sonifications render as a braille waveform with a play action shelling out to
`ffplay`, `aplay`, or `afplay`. **The waveform is presentational only:**
`docs/extraction.md` (Pulsar Sonification section 7.2) records that synthesis
ignores sample timestamps, so a period must never be read off rendered audio. The
folded-profile plot beside it is the scientific artifact.

---

## 10. Dependencies

Eight new pins, resolved against the existing lockfile rather than estimated:

| Pin | Pin |
| --- | --- |
| `textual==8.2.8` | `rich==15.0.0` |
| `markdown-it-py==4.2.0` | `mdurl==0.1.2` |
| `linkify-it-py==2.2.0` | `mdit-py-plugins==0.6.1` |
| `platformdirs==4.11.7` | `textual-image==0.13.2` |

`pygments==2.20.0`, `pillow==12.3.0`, and `typing-extensions==4.16.0` are already
pinned at compatible versions and **do not move**. `pyproject.toml` pins with `==`
and CI runs `uv run --locked`, so this lands with a regenerated `uv.lock` in its
own dependency PR (phase D.1) and nowhere else.

`pytest-asyncio` is **not** added. Textual's headless pilot is async, but driving
the coroutine on an event loop from a small test helper costs four lines and keeps
the dependency count at eight, which is a constraint rather than a preference.

---

## 11. Error Handling

| Failure | Behaviour |
| --- | --- |
| Ollama not running | The port's availability probe reports "backend unavailable"; the TUI offers another backend. Never a connection traceback. |
| Missing API key | A configuration screen, not an exit. |
| Tool raises | The engine catches it, emits a finished event carrying an error result, and feeds that back to the model. |
| Protocol fault | A fault event renders a fault badge; the run continues. |
| Model stream fails mid-turn | Session saved with an error outcome, transcript preserved, manifest path shown. |

The third row is a **deliberate divergence** from `tools/runner.py`, which today
lets a tool exception propagate out of `run()`. It is consistent with the port's
S8 treatment of schema violations — an error result returned to the model, not an
exception — and section 1 establishes that no test depends on the current
behaviour. It is called out here so review treats it as a behaviour change rather
than an implementation detail.

---

## 12. Entry Point Migration

| Today | After |
| --- | --- |
| `kepler-astro-query` → `tools.runner:main` | removed |
| `python3 tools/claude_photometry_haiku_tool.py` | removed |
| — | `kepler` → `tools.tui.__main__:main` — **registered**, ahead of the rest of G.1 |
| `tools/runner.py` | shim during migration, then deleted |
| `SYSTEM_PROMPT` in `tools/runner.py` | `tools/agent/prompt.py`, unchanged |
| The photometry tool's Anthropic path and CLI | deleted |
| The photometry tool's ~1,000-line pipeline | `tools/photometry_pipeline.py` |

**`SYSTEM_PROMPT` moves intact.** It is ~270 lines of confirmed-live failure-mode
guidance, [model-backends.md](model-backends.md) section 6.2 names it as the
source of all eight benchmark seed tasks, and both
`algorithms/hrdiagram_py/literature.py` and `tools/hr_diagram.py` cite it in
comments.

**Deleting `tools/runner.py` requires editing `.github/workflows/ci.yml`.** Per
`CLAUDE.md`, workflow changes ship separately from behaviour changes, so phase G
is at least two PRs.

Documentation referencing the removed entry points, updated in phase G.3:
`README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/tool-architecture.md`,
`docs/repository-folders.md`, `docs/examples/README.md`, and the module docstrings
of `tools/sessions.py` and `tools/registry.py`. Every one was located by grep
against `dev`; **re-run the grep before editing** in case the tree moved.

---

## 13. Testing

Everything below runs in default `pytest` — offline, deterministic, no API keys,
no daemon, no terminal.

* **Engine.** A fake backend drives a two-turn tool loop; the test asserts the
  exact event sequence. This is the primary contract test.
* **Approval.** A denial produces a denied event, returns an error result to the
  model, and — the assertion that matters — the tool function is never called.
* **No-UI-import.** `tools.agent` imports no UI package. Asserted directly.
* **Slash commands.** Registry dispatch, escaping, unknown-command handling, and
  the assertion that no command text is ever forwarded to the engine.
* **TUI.** Textual's headless pilot drives keypresses and asserts widget state.
  The interface is genuinely CI-testable.
* **Rendering.** The capability probe against faked environments; the half-block
  renderer against a committed 4×4 PNG with byte-stable expected output.
* **Backend selection.** `tests/test_llm_ollama_backend.py` covers
  `installed_models()` against a mock transport, including that an unaskable
  daemon yields `()` rather than an empty inventory.
  `tests/test_tui_backends.py` covers the `.env` reader
  (quoting, `export`, comments, the bare-key line, and that the environment
  always wins), spec resolution, and both probe outcomes — `open_backend` takes
  its builder as a keyword argument precisely so no adapter is constructed and
  no socket is opened. `tests/test_tui_app.py` covers the switch through the
  pilot: the header retitles, a refused backend leaves the session on the one
  that answers, and a switch attempted while a worker runs in the `engine`
  group is refused without building anything.
* **Entry point.** `tests/test_tui_app.py` reads `pyproject.toml` and pins the
  `kepler` script at `tools.tui.__main__:main`, and drives `main()` with an
  empty `argv` to assert a bare invocation reaches the app on the default
  backend. Both are worth pinning because `argparse` prints `usage: kepler`
  whether or not the script is registered, so a dropped entry produces help
  text for a command that does not exist rather than any failure.
* **Launch robustness.** `tests/test_tui_artifacts.py` asserts by AST that the
  artifact browser imports nothing from `textual_image` at module scope
  (section 9.1), and that a native-image widget which cannot be built falls
  back to half-blocks rather than to an error message.
* **Migration.** After the rename, the existing photometry tests pass against the
  renamed module unchanged in substance.

CI keeps its shape: `compileall`, `pytest`, `repository-shape`. No new job. The
shape job drops its `tools/runner.py` assertion and gains `tools/agent/engine.py`
and `tools/tui/app.py`.

---

## 14. Rollout

One narrow PR per task; documentation, workflow, dependency, and behaviour
changes stay separated per `CLAUDE.md`.

| Phase | Content | Done when |
| --- | --- | --- |
| **A** | `tools/agent/`: events, engine, `SYSTEM_PROMPT` moved. `runner.py` becomes a shim. **Owned by [model-backends.md](model-backends.md) Phase 0c — not a PR of this rollout.** | `tests/test_runner_session.py` passes **unedited**. |
| **B** | Approval policy and approver wiring. | **Complete** — a denied call never dispatches. |
| **C** | `photometry_pipeline.py` rename, consumer imports, docs. | **Complete** — `72d0bd7`; suite green. |
| **D** | Textual dependency (eight pins, regenerated lockfile) and the TUI: application shell, slash-command registry, transcript, streaming, tool tree, status bar. | **Complete** — a real session runs end to end. |
| **E** | Artifact rendering: probe, tiers, and the artifact browser. | **Complete** — half-block path green in CI. |
| **E.1** | The titled header, and `/backend` selection over `.env`-backed Anthropic or a local Ollama daemon. Lifts the section 15 deferral. | **Complete and verified live** — `/backend ollama` switched a running session onto `ollama/qwen3.8:27b-mlx` and completed a two-turn tool-calling loop to `end_turn` in 464 s. A switch never lands on a backend that cannot answer, and a refused one leaves the session untouched. |
| **F** | Session browser and resume. | **Complete** — a resumed session continues a prior trace. |
| **G** | Retire entry points: delete the shim, edit the workflow, update the console scripts, sweep the documentation. | Nothing references the removed entry points. |

**Sequencing.** Phase A is a dependency, not work here. **Phase C is independent
of A, B, and the model port entirely** once the stateless optical rollout has
merged, so it ships first among this rollout's PRs while the port is still in
progress. B precedes D because the application shell wires an approver. G is last.

**Phase G is the point of no return and is deliberately last.** Every earlier
phase leaves a working `kepler-astro-query`, so the TUI can be used and judged
before the old surface is removed. **Do not start G until the TUI has actually
been used against a real backend.**

### Global constraints

Every phase inherits these.

- **The zero-dependency rule is scoped, not lifted.** `tools/llm/` and
  `tools/agent/` take no new dependencies. `tools/tui/` is the only package that
  may, and the only package that may import `textual`.
- **`tools/agent/` never imports `tools/tui/`, `textual`, or `rich`.** A test
  asserts this (phase B).
- **Branch:** `agent/tui-harness`, off `dev`. Do not retarget to `main`.
- **One PR per task**, narrow.
- **No linter or formatter is configured.** Match the surrounding file's style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88 column soft wrap.
- **Default checks stay offline and deterministic.** Nothing added here may open a
  socket under a plain `uv run pytest`, and nothing may require a real terminal.
  Textual's pilot is headless.
- **No changes to `algorithms/`.** The extraction contract is untouched. Do not
  edit any file carrying an `# EXTRACTED:` or `# PORTED:` marker.
- **`tests/test_tool_registry_coverage.py` enumerates `pkgutil.iter_modules`,
  which yields packages as well as modules.** Verified. Every phase that adds
  `tools/agent/`, `tools/tui/`, or `tools/photometry_pipeline.py` **must** update
  `NOT_TOOL_MODULES` in the same commit or that test fails.
- **`SYSTEM_PROMPT` is never rewritten in passing.** Move it; do not edit it.
- **The stateless optical boundary is retained.** Phase C must not preserve,
  recreate, or rename processing-run or batch orchestration.

### Verification commands

```bash
uv run pytest                             # must be green; offline, no keys
python3 -m compileall tools algorithms    # syntax smoke, mirrors CI
git diff --check                          # whitespace
uv run pytest tests/test_tool_registry_coverage.py -v
```

### Files this rollout creates

| Path | Phase |
| --- | --- |
| `tools/agent/policy.py`, `tests/test_agent_policy.py`, `tests/test_agent_no_ui_imports.py` | B |
| `tools/photometry_pipeline.py` (renamed) | C |
| `tools/tui/{__init__,__main__,app}.py`, `tests/test_tui_app.py` | D.1 |
| `tools/tui/commands.py`, `tests/test_tui_commands.py` | D.2 |
| `tools/tui/widgets/{__init__,transcript,tool_node}.py` | D.3 |
| `tools/tui/render/{__init__,capability,image,waveform}.py`, `tools/tui/widgets/artifacts.py`, `tests/test_tui_render.py`, `tests/fixtures/tui/probe_4x4.png` | E |
| `tools/tui/widgets/sessions.py`, `tests/test_tui_sessions.py` | F |

### Files this rollout modifies

| Path | Change |
| --- | --- |
| `tools/claude_photometry_haiku_tool.py` | C: renamed; Anthropic path and CLI deleted. |
| `tools/photometry.py`, `tools/optical.py` | C: import path. |
| `tests/test_photometry_tool_smoke.py` | C: import path; the CLI subprocess test removed. |
| `tests/test_photometry_registry_smoke.py`, `tests/test_optical_registry.py` | C: import path. |
| `tests/test_tool_registry_coverage.py` | B, C, D.1, G.1: `NOT_TOOL_MODULES`. |
| `pyproject.toml` | D.1: eight pins. G.1: console scripts. |
| `uv.lock` | D.1: regenerated. |
| `.github/workflows/ci.yml` | G.2: drop `tools/runner.py`, add the new paths. |
| `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/*.md` | G.3: documentation sweep. |

**Deliberately not touched:** `tools/registry.py` — adding risk tags to the
schemas would change the golden schema fixtures the model port commits in four
dialects; anything under `algorithms/`.

### Phase C — Rename the photometry pipeline and delete the Anthropic path

Ships as the first TUI-scoped PR, after the stateless optical rollout merges. It
removes the repository's second Anthropic caller.

- [x] **Record the current state first** so the diff is checkable: run the four
      affected test files, and grep for the old module name. The original audit
      expected `tools/photometry.py`, `tools/optical.py`, and three test files;
      the Phase C audit found additional optical-test and source-docstring
      references, which were migrated in the same commit.
- [x] Rename the module **with history preserved** (`git mv`), then update every
      import site.
- [x] Delete exactly these and nothing else:

      | Symbol | Why |
      | --- | --- |
      | `API_URL`, `API_VERSION` | The raw Anthropic endpoint. |
      | `parse_args()` | The retired CLI. |
      | `build_claude_prompt()` | Builds the Anthropic request body. |
      | `call_claude_haiku()` | Posts to the Anthropic API. |
      | `main()` and its entry guard | The retired CLI. |
      | `import argparse`, `import requests` | Now unused. |
- [x] **`summarize_results` and `render_credits_card` are NOT deleted.** Both
      are non-LLM — a numeric summary and a matplotlib credits card — and both
      are used by the photometry smoke test. Verified before this was written.
- [x] Replace the module docstring so the module's name and its contents agree.
- [x] Remove `test_check_only_cli_resolves_bundled_subject`, which runs the
      module as a subprocess with `--check-only` — a CLI that no longer exists —
      along with any imports it alone needed. **Its coverage is not lost** —
      path resolution for a bundled subject is already asserted by the registry
      smoke test and the optical registry test. Confirm that by grep before
      deleting.
- [x] Update `NOT_TOOL_MODULES` to name the renamed module, with a comment saying
      its public surface is re-exported through `tools.optical` and
      `tools.photometry`.

The module keeps every symbol it exported except the six deleted ones.

### Phase B — Approval policy

- [ ] Build `tools/agent/policy.py` to section 5: `Decision`, `RiskTag`,
      `TOOL_RISK`, `Approver`, `auto_approve`, `risk_tags`, `needs_confirmation`,
      `SessionPolicy`, and `policy_approver`.
- [ ] `SessionPolicy`'s `ask` blocks on a `threading.Event` while the UI thread
      renders a modal (section 6). A test asserts every tagged tool is a real
      registered tool, so the table cannot drift from the registry. The engine's
      approver default is unchanged, so the shim and every plain-Python caller
      behave exactly as today.
- [ ] Add the test asserting `tools.agent` imports no UI package.
- [ ] Update `NOT_TOOL_MODULES`.

**Gate:** a denied call never dispatches — assert the tool function was not
called, not merely that an error came back.

### Phase D.1 — Textual dependency and the application shell

**This is the dependency PR.** The lockfile is regenerated here and nowhere else.

- [ ] Add the eight pins in alphabetical position. Do not move `pygments`,
      `pillow`, or `typing-extensions`.
- [ ] Regenerate the lockfile and confirm nothing else moved. **If the diff moves
      an unrelated pin, stop and report it** rather than committing a silent
      upgrade.
- [ ] Build the package marker, `KeplerApp` in `tools/tui/app.py`, and
      `tools.tui.__main__.main()`: argument parsing, backend construction, and
      launching the app.
- [ ] Drive the headless pilot from a small event-loop helper rather than adding
      `pytest-asyncio` (section 10).
- [ ] Update `NOT_TOOL_MODULES` with `tools.tui` — the console is not a tool
      surface.

### Phase D.2 — The slash-command registry

- [ ] Build `tools/tui/commands.py` to section 8: the frozen command record with
      name, help text and aliases; the registry; the three-kinded parse result;
      and the parse, resolve, and help-text functions.
- [ ] **Import nothing from Textual** — the registry is plain Python so it is
      testable without a pilot.

**Gate:** escaping works, an unknown command is an error rather than a message,
and no command text is ever forwarded to the engine.

### Phase D.3 — Transcript and tool-call nodes

**This is where the engine is actually driven.**

- [ ] Build `Transcript.handle_event(event)`, and `ToolNode(call_id, name,
      arguments)` with `start()`, `finish(result, artifacts, duration_ms)`, and
      `deny(reason)` carrying the states of section 7.1.
- [ ] Run the engine in a thread worker; forward each event to the UI thread with
      `post_message`; block the approver on a `threading.Event` while the modal is
      up (section 6).

### Phase E — Artifact rendering

- [ ] Create the committed 4×4 PNG golden fixture.
- [ ] Build `detect_tier`, `render_halfblocks`, and `render_waveform`, plus the
      artifact browser modal over `tools.workspace.list_artifacts`.
- [ ] Half-blocks are the guaranteed floor; native protocols go through
      `textual-image`.
- [ ] The waveform is presentational only — carry the note from section 9 into the
      code, so nobody reads a period off it.

**Gate:** the half-block path is green in CI.

### Phase F — Session browser and resume

- [x] Build `SessionBrowser` over `tools.workspace.list_sessions()` and
      `describe_session`, listing id, timestamp, model, outcome, and turn count,
      with enter bound to `KeplerApp.resume_session`.
- [x] Build `history_from_manifest`, seeding the engine's message history from a
      manifest's recorded neutral history via `tools.sessions.read_session_manifest`.
      Resume validates a bounded provider message grammar (paired known tool
      calls and results) before forwarding anything to a backend. Legacy text
      manifests retain the original-user/assistant-turn fallback.
- [x] **Resume references artifacts rather than replaying them** (section 16,
      question 3): re-rendering every image on resume is slow for a long session,
      and the artifact browser is the way back to them.

`tools/sessions.py` already records everything the browser needs.

### Phase G.1 — Retire the old entry points (code)

- [x] **Register `kepler` → `tools.tui.__main__:main`.** Split out and landed
      early, on its own, because it is the only *additive* step in this phase:
      the console had no command at all, and the argument parser's `prog` was
      already `kepler`, so `--help` printed usage for a name that did not
      exist. Adding the entry beside the two existing scripts leaves CI green
      and the shim intact, so it carries none of the ordering hazard below.
      Verified by launching the installed script under a pty: the header, the
      prompt, and the footer draw, and `ctrl+q` exits cleanly.
- [ ] **Confirm the shim has no remaining callers.** The grep should find only the
      console script in `pyproject.toml`, the session test, and the coverage
      allowlist. **Anything else must be migrated before continuing.**
- [ ] Retarget the session test at the engine — rename the file, switch the
      import, and change the call site from calling the shim to iterating
      `run_session`. **The manifest assertions stay exactly as they are.** If
      any needs changing, the engine diverged from the shim and that is a bug in
      Phase A, not here.
- [ ] Delete the shim and remove `kepler-astro-query`, leaving the `kepler`
      entry already registered above as the only one.
- [ ] Drop the stale `tools.runner` entry from `NOT_TOOL_MODULES`. Leaving it is
      harmless but it names a module that no longer exists — exactly the class of
      stale reference this work exists to remove.

**CI will be red at this commit**, because the shape job still asserts
`tools/runner.py` exists. Phase G.2 fixes that.

### Phase G.2 — Update the repository-shape gate

A workflow change, kept in its own PR per `CLAUDE.md`.

- [ ] In the `repository-shape` job, remove `tools/runner.py` and add
      `tools/agent/engine.py` and `tools/tui/app.py` — the files whose
      disappearance should fail the build.
- [ ] Verify the workflow still parses with `actionlint`, or rely on
      `workflow-safety.yml` if it is not installed locally.

**Ordering hazard, stated in both phases:** G.1 and G.2 leave CI red between
them. **They must merge as a stacked pair; do not leave G.1 on `dev` overnight
without G.2.**

### Phase G.3 — Documentation sweep

Its own PR, per the separation rule. Re-run the grep before editing.

| File | Change |
| --- | --- |
| `README.md` | Replace both agent surfaces with one `kepler` console; drop the key-only framing, since the backend is now selectable. |
| `AGENTS.md` | `uv run kepler`; note `KEPLER_MODEL_BACKEND`. |
| `CLAUDE.md` | Update the `repository-shape` file list; replace "the optional `tools.runner` Anthropic loop" with the console and its backend selection. |
| `docs/tool-architecture.md` | Point at `tools.photometry_pipeline`; say the console persists the manifest. |
| `docs/repository-folders.md` | Rename in the folder guide; add `tools/agent/` and `tools/tui/` rows. |
| `docs/examples/README.md` | The example transcript was produced by the agent loop; update the command shown. |
| `tools/sessions.py`, `tools/registry.py` | Module docstrings: `tools.agent` is the consumer. |

- [ ] **Fold this document into a reference document and delete it.**
      `docs/working/README.md` states the lifecycle: when a plan's work lands,
      the durable outcome moves into a reference document at the top level of
      `docs/` and the working document goes. Add a section to
      `docs/tool-architecture.md` describing `tools/agent/` and `tools/tui/` —
      the event contract, the approval policy, and the threading model — then
      delete this file and remove its row from `docs/working/README.md`.

---

## 15. Non-Goals and Deferred Work

* ~~**Live backend switching.**~~ **Shipped in E.1** — see 8.1. What remains
  deferred is the narrower piece: **capability-difference warnings** when a
  switch changes what the session can express. Gemini's OpenAPI subset cannot
  represent the integer-or-null union `search_vizier.max_catalogs` needs, and
  Ollama's adapter declares `streaming=False` where Anthropic's does not, so the
  transcript stops filling in mid-turn after a switch to it. Neither is
  announced today; both are visible in `Capabilities` and could be diffed
  across a switch.
* **The pulsar stage-order guardrail.** Surfacing the light curve → periodogram →
  period → fold → sonify dependency with `peak_confidence` and `pulse_snr` inline
  is deferred. The stage order remains documented in `CLAUDE.md`
  and `docs/pulsar-tool-pipeline.md`.
* **No serving surface.** `docs/tool-architecture.md` section 7 stands. A TUI is a
  local interface, not a server; nothing here exposes a port.
* **No benchmark harness.** Model-port phases 4–5 own that. This design makes the
  engine a usable input to it and no more.
* **No changes to `algorithms/`.** The extraction contract is untouched.
* **No Windows-specific work.** Textual runs on Windows; the abandoned inline mode
  would not have.

**Two places where a modal screen is specified in prose rather than in detail**,
deliberately: the artifact browser and the session browser are thin modal
subclasses over functions this document does specify — the half-block renderer,
the waveform renderer, history reconstruction, and the existing workspace listing
tools. The behaviour that could regress silently lives in those functions and is
tested there.

---

## 16. Open Questions

1. **Does `textual-image` handle Textual's repaint cycle cleanly at the sizes
   Kepler's plots use?** Resolved by measurement in phase E against a real
   periodogram PNG. If it does not, the fallback is decided rather than silent:
   half-blocks in the transcript, native protocols only in a suspended
   full-screen view.
2. **Is a 4×4 PNG a stable enough golden for the half-block renderer across
   Pillow patch releases?** Phase E decides between a byte-stable golden and a
   structural assertion.
3. **Should resume replay artifacts into the transcript, or reference them?**
   *Resolved: reference them.* Replaying re-renders every image on resume, which
   is slow for a long session; the artifact browser is the way back in. Recorded
   here because phase F implements the answer.

---

## 17. References

* [model-backends.md](model-backends.md) — the model port this design consumes
  (sections 4.2, 4.6, and S8 in particular), and the owner of Phase A.
* [optical-tools.md](optical-tools.md) — the stateless optical rollout that must
  merge before phase C.
* `docs/tool-architecture.md` section 7 — the runtime policy that keeps the engine
  synchronous and importable, and the document phase G.3 folds this one into.
* `tools/runner.py` — `SYSTEM_PROMPT` and the loop being replaced.
* `tools/artifacts.py` — the `ContextVar` that makes the thread worker safe.
* `tools/photometry_pipeline.py` — the retained reusable pipeline; its former
  Anthropic path and CLI were removed in Phase C.
* `.github/workflows/ci.yml` — the assertion phase G.2 must edit.
* `docs/extraction.md` (Pulsar Sonification section 7.2) — why the waveform is
  presentational only.
