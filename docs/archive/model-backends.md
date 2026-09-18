# Model Backends and Provider Port

> [!NOTE] Archived 2026-09-18
> This track is complete and this document is a record, not a plan. Phases
> −1–3 built `tools/llm/` and `tools/agent/`; phases 4–5 became the benchmark
> harness and landed under
> [`../benchmarking/harness.md`](../benchmarking/harness.md). A completion
> audit on 2026-09-18 re-verified the port against the code: all four adapters
> report the capability record section 4.2 specifies, row for row, including
> Gemini's `native_tool_call_ids=False` and `supports_union_types=False`;
> specs split on the first slash only; the manifest is at schema version 2;
> both opt-in markers exist; and no dependency was added. The durable outcome
> is [`../tool-architecture.md`](../tool-architecture.md) section 10.
>
> **Three corrections applied at archive**, each marked inline where it sits:
> the status line below (this block replaces it), `estimated_usd` in section 7,
> and the two test module names in sections 8 and 9 that the console retired.
> Everything else is left as it was written, including the rollout's own
> constraint that `tools/runner.py` keep its path — that was true for the
> duration of this rollout and the document already records who deleted it.

**Status:** Phases −1 through 3 **implemented** (2026-09-09) on
`agent/model-backends-impl`, off `dev` at the maintainer's instruction —
delivered as one branch, one commit per phase. `tools/llm/` and `tools/agent/`
exist; the `tools/runner.py` shim they were first wired into was retired by
the console (`docs/tool-architecture.md` 10.2), and the engine is reached
directly. Phases 4–5 (the benchmark harness) landed 2026-09-13.
**Date:** 2026-09-04, consolidated 2026-09-07, implemented 2026-09-09
**Prerequisites:** None.
**Unblocks:** The headless agent engine every phase of
the Kepler console depends on (now built), and the benchmark
harness of phases 4–5 (now built, under [harness.md](../benchmarking/harness.md)).
**Branch:** implemented on `agent/model-backends-impl`, off `dev` — the
maintainer redirected the base from `main` to `dev` at implementation time
(`dev` carries the current plan doc and the 49-tool registry the design
describes). The original `agent/model-backends` branch carried PR #46
(docs only) and is superseded.
**Consumed by:** the Kepler console (`docs/tool-architecture.md` 10.2), which
drives this port through the headless engine in `tools/agent/`.

Kepler's agent loop is hardwired to one vendor. This document specifies a
provider-neutral model port that puts Ollama, Anthropic, OpenAI-compatible, and
Gemini backends behind one interface, the phased rollout that builds it, and a
benchmark harness — deferred to a later phase — that grades those backends
against each other on the astronomy tool surface this repository already owns.

Two rules govern the whole design:

> The core owns the loop; adapters own the dialect.

> Replay the tools, never the model.

The first keeps one vendor's quirks out of the loop. The second is what makes
benchmarking honest: the model is the thing under test, so model calls are live;
the astronomy services are not under test, so their results are recorded
fixtures. That also keeps every benchmark run offline with respect to SIMBAD,
NED, VizieR, ADS, MAST, MPC, CASDA, and ATNF, which is what the repository's "no
live remote astronomy service calls in default checks" rule requires.

This document is architecture and sequencing. It contains no implementation
code. An agent working a phase reads the contracts here, then writes the code
that satisfies them.

---

## 1. What Exists Today

Established by reading the code, not assumed.

**`tools/runner.py` is the single integration point, and it is Anthropic-shaped
all the way through.** It imports `anthropic`, reads `ANTHROPIC_API_KEY`, opens
a streaming messages call, iterates the text stream, branches on the vendor's
`stop_reason` values, walks the response content for blocks whose type is
`tool_use`, and appends **raw SDK content objects** back into the message list.
The vendor's data model is the loop's data model. `run()` is a single ~160-line
function interleaving five concerns: the model loop, tool dispatch, the
repeated-call cache, session recording, and printing.

**`tools/registry.py` was 23 tools when this design was written, 48 on
2026-09-07, and 49 at implementation (2026-09-09).** The portability finding
holds: no `anyOf`/`oneOf`/`allOf`/`$ref`/`additionalProperties`, one `enum`,
flat objects. Two corrections from the Phase 1a inventory: there are now
**8 scalar-or-null unions, not 2** (4× `["integer","null"]`, 4×
`["number","null"]` — the radio-source tools added the `number` ones), and
arrays are string-, number-, *and* opaque-object-typed, not string-only.
Translating to three other dialects is still tractable.

**The one landmine.** `search_vizier.max_catalogs` (`tools/registry.py:339`) and
`search_mast.max_observations` (`tools/registry.py:380`) are typed as the union
of integer and null, and passing JSON `null` is the *only* way to request
uncapped results. `SYSTEM_PROMPT` spends an entire paragraph on this, including
the confirmed-live failure where a model sends the four-character string `"None"`
instead. This union type is not expressible in Gemini's OpenAPI subset,
constrains OpenAI strict mode, and is exactly the kind of thing small local
models get wrong. It is simultaneously the hardest translation case in the
repository and the single best benchmark probe available. It is treated as both.

**`tools/sessions.py` is already most of a benchmark record.** `AgentSession`
persists the ordered tool-call trace, canonical cache keys, cache-hit counts,
per-call status, warnings, errors, and artifact paths, and it writes on start,
after every tool call, and at every terminal state. It is missing only token
counts, latency, and a grade.

That last point drives a structural decision: **the benchmark is a reader of
session manifests, not a parallel pipeline.** Anything the runner does becomes
gradeable, and manifests from ordinary non-benchmark sessions can be graded
after the fact at no extra cost.

**`tools/artifacts.py` already has the path controls that matter.** Artifact
names are scrubbed to a safe character set, and scoped artifact directories
reject absolute and parent-relative subdirectories. Two gaps exist but are
unreachable today because only tool code sets them: `_write_directory()` joins its
`subdir` argument with no validation, and `reserve_artifact_path()`'s `ext` is
only stripped of leading dots. Requirement S7 keeps
them unreachable.

**There is a second, independent Anthropic caller.**
`tools/claude_photometry_haiku_tool.py` posts directly to the Anthropic messages
endpoint over `requests`. It is out of scope for this document and explicitly
deferred (section 10), not forgotten.

**No evaluation or benchmarking infrastructure exists.** That part is greenfield.

---

## 2. Decisions

| Question | Decision |
| --- | --- |
| How are backends driven? | HTTP/SDK APIs only. Kepler keeps owning the agent loop. |
| Which providers? | Ollama, Anthropic, OpenAI-compatible, Google Gemini. |
| What is graded? | Trajectory, cost/latency/turns, final-answer correctness, protocol robustness. |
| Where do tool results come from? | Recorded fixtures, replayed offline. |
| New dependencies? | **None.** |

### 2.1 Rejected alternatives

**Anthropic's dialect as the internal canonical form.** Smallest diff, but it
permanently bakes `stop_reason` naming, the content-block union, and
`tool_use_id` into the core. Gemini emits no tool-call identifiers at all, so
the shim leaks on the first non-Anthropic backend.

**An abstraction library (LiteLLM or similar).** Least code, rejected on two
grounds. `pyproject.toml` pins every dependency with `==` and CI runs
`uv run --locked`, so a large transitive tree is a real cost in this repository.
More importantly it would hide precisely the protocol differences the
protocol-robustness grader exists to measure — the abstraction would paper over
the measurement.

**CLI agent subprocesses** (`claude`, `codex`, `gemini` binaries driven as child
processes, exposing Kepler tools over MCP). A legitimate architecture and a
plausible future backend, but it moves the agent loop out of this repository and
makes trajectory grading depend on someone else's harness. Deferred; the
`ModelBackend` protocol does not forbid it.

### 2.2 Zero new dependencies

Keep the `anthropic` SDK — already pinned at `0.121.0`, and keeping it is what
lets Phase 0 land without touching the existing test. Implement OpenAI, Ollama,
and Gemini over `httpx`, already pinned at `0.28.1`.
`tools/claude_photometry_haiku_tool.py` sets the raw-HTTP precedent in this
repository already.

Four providers therefore cost three new modules, zero new packages, and no
`uv lock` churn. This is a supply-chain decision as much as an ergonomic one.
The cost is that we own TLS correctness: never disable certificate verification,
always set an explicit timeout, never enable redirect following (section 5, S3).

---

## 3. Layout

| Path | Responsibility |
| --- | --- |
| `tools/llm/__init__.py` | Re-exports the public surface: neutral types, `ModelBackend`, `build_backend`. Import-light — no adapter imports at package level. |
| `tools/llm/types.py` | Neutral message/content/response types and the fault taxonomy. No I/O, no provider names. |
| `tools/llm/base.py` | `ModelBackend` protocol, `Capabilities`, `BackendUnavailableError`, and later `BaseHTTPBackend`. |
| `tools/llm/schema.py` | Tool-schema translation: `to_anthropic`, `to_openai`, `to_gemini`, and the `for_dialect` dispatcher. Pure; no I/O. |
| `tools/llm/validation.py` | `index_schemas` and `validate_tool_call` — pre-dispatch argument validation against a tool's own input schema. Hand-rolled; no `jsonschema`. |
| `tools/llm/factory.py` | `parse_spec` and `build_backend` — `provider/model` spec parsing and backend construction. Owns the credential/endpoint binding rule (S3). |
| `tools/llm/anthropic_backend.py` | `AnthropicBackend` — Anthropic SDK adapter. The only adapter that streams natively. |
| `tools/llm/openai_backend.py` | `OpenAIBackend` — OpenAI Chat Completions over raw `httpx`, and anything compatible. |
| `tools/llm/ollama_backend.py` | `OllamaBackend` — thin `OpenAIBackend` subclass: loopback default, no auth header, `is_available()` probe. |
| `tools/llm/gemini_backend.py` | `GeminiBackend` — Gemini `generateContent` over raw `httpx`. Synthetic call ids, uppercase types. |
| `tools/llm/replay_backend.py` | `ReplayBackend` — replays a recorded model transcript. Test-only; phase 4. |
| `tools/agent/` | The headless loop: `events.py`, `prompt.py`, `engine.py`, later `policy.py`. Built in Phase 0c. |
| `tools/bench/` | Harness code, phases 4–5: `tasks.py`, `fixtures.py`, `graders/{trajectory,efficiency,answer,protocol}.py`, `harness.py`, `report.py`, `cli.py`. |
| `benchmarks/` | The corpus — data, versioned, reviewed. As built: `suites/<suite>/<task-id>.yaml` (one task per file), `fixtures/<tool>.yaml`, `transcripts/`. No `prices.json` — see open question 3. |

**Naming.** `tools/llm/`, not `tools/backends/` — `algorithms/query/binding.py`
already defines a `Backend` class and the collision would be actively
misleading. Not `tools/models/` — `tools/models.py` is the shared Pydantic
result models.

**`benchmarks/` is top-level and deliberately not named `data/`**, which
`.gitignore` swallows. Code stays under `tools/` so `compileall tools algorithms
tests` keeps covering it without a CI change.

---

## 4. The Model Port

### 4.1 Neutral types

`tools/llm/types.py` defines the port's currency. Every type is a **frozen**
dataclass, and every collection field is a **tuple, not a list** — list fields
make a frozen dataclass silently mutable. Callers pass sequences; the type
stores tuples.

| Type | Fields | Notes |
| --- | --- | --- |
| `TextBlock` | `text` | |
| `ThinkingBlock` | `text`, `signature` (default empty) | One run of revealed reasoning. `signature` is the provider's opaque attestation — see 4.8. |
| `ToolCallBlock` | `call_id`, `name`, `arguments` | `arguments` is a parsed mapping, never a JSON string. |
| `ToolResultBlock` | `call_id`, `name`, `content`, `is_error` (default false) | |
| `Block` | union of the four above | |
| `Message` | `role` (`user` or `assistant`), `blocks` | **No `system` role.** |
| `Usage` | `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` | All optional; absent means `None`, never `0`. |
| `ProtocolFault` | `type`, `detail`, `tool_name`, `call_id` | `type` is the `FaultType` literal of section 4.6. |
| `ModelResponse` | `text`, `thinking`, `tool_calls`, `stop_reason`, `usage`, `latency_ms`, `raw_stop_reason`, `faults` | `thinking` and `faults` default to empty, `raw_stop_reason` to `None`. |

`StopReason` is the closed set `end_turn`, `tool_use`, `max_tokens`, `refusal`,
`other`. `raw_stop_reason` preserves the provider's own string verbatim so
nothing is lost from the manifest.

**The system prompt is not a `Message`.** It is a separate argument everywhere,
because Anthropic takes it as a top-level parameter, OpenAI as a `system`-role
message, and Gemini as `systemInstruction`. Modelling it as a message would
force every adapter to special-case index 0. There is no `role="system"`.

**Nothing in this module imports `anthropic`, `httpx`, `openai`, or `google`.**
That is testable and is tested.

**Reasoning is never merged into `text`.** A model's working is a different
kind of claim from its answer — it may contradict the answer — and a consumer
that could not tell them apart would read a discarded hypothesis as a finding.
`ThinkingBlock` is a `Block` and travels in `Message.blocks`, because a
provider that signed its reasoning requires it back (4.8).

### 4.2 The protocol

`ModelBackend` is a `@runtime_checkable` protocol carrying two attributes and
one required method:

- `spec` — the backend's own `provider/model` string, e.g. `ollama/llama3.1:8b`.
- `capabilities` — a frozen `Capabilities` record, section 4.2 below.
- `complete()` — keyword-only: the neutral `messages` history, the
  **already-translated** `tools` payload for this backend's dialect, the
  `system` prompt, `max_tokens`, `temperature` (default `0.0`), and an optional
  `on_text` callback. Returns a `ModelResponse`.

`tools` is the translated dialect payload, **not** `TOOL_SCHEMAS`. Translation
is the caller's job, so adapters stay free of schema logic and every translation
is independently unit-testable.

**`complete()` is the only required method, and it is non-streaming.** Streaming
is a capability flag with a default implementation that calls `complete()` and
emits the text in one chunk. This is a deliberate trade: streaming shapes differ
sharply across the four providers, streaming buys nothing for benchmark
determinism, and requiring it would triple adapter size.

**The `on_text` refinement.** The bare non-streaming signature would lose the
runner's live text printing. Rather than add a second required method,
`complete()` takes a keyword-only `on_text` callback that receives assistant
text as it becomes available. The Anthropic adapter streams into it; every other
adapter calls it exactly once with the finished text. `complete()` remains the
only required method.

`Capabilities` fields:

| Field | Meaning |
| --- | --- |
| `streaming` | Whether the adapter streams natively. |
| `parallel_tool_calls` | Whether several calls can return in one message. |
| `native_tool_call_ids` | **False for Gemini** — the adapter synthesizes ids. |
| `schema_dialect` | One of `json_schema`, `openai_function`, `gemini_openapi`. |
| `supports_union_types` | **False for Gemini.** |
| `max_output_tokens` | The provider's ceiling as this port uses it. |

Per-backend values:

| Backend | streaming | parallel | native ids | dialect | unions | max output |
| --- | --- | --- | --- | --- | --- | --- |
| Anthropic | yes | yes | yes | `json_schema` | yes | 128000 (what the runner passes today) |
| OpenAI | no | yes | yes | `openai_function` | yes | 16384 |
| Ollama | no | yes | yes | `openai_function` | yes | subclass override |
| Gemini | no | yes | **no** | `gemini_openapi` | **no** | 8192 |

`BackendUnavailableError` is the port's one construction-time failure: a missing
credential, or an unreachable local daemon. It names the environment variable at
fault. It is never raised at import time, and never raised when a credential is
passed explicitly.

### 4.3 Backend specs and configuration

Specs are `provider/model`, split on the **first slash only** — a slash, not a
colon, because Ollama model names contain colons, and OpenAI-compatible model
ids can themselves contain slashes (`openai/meta-llama/Llama-3-8b` is provider
`openai`, model `meta-llama/Llama-3-8b`). Recognized providers: `anthropic`,
`openai`, `ollama`, `gemini`. Examples: `ollama/llama3.1:8b`,
`anthropic/claude-opus-5`, `openai/gpt-4.1`, `gemini/gemini-2.5-pro`.

| Variable | Purpose |
| --- | --- |
| `KEPLER_MODEL_BACKEND` | Default backend spec. |
| `ANTHROPIC_API_KEY` | Existing; unchanged. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI and compatible endpoints. |
| `GEMINI_API_KEY` | Gemini. Header only — never a query parameter (S4). |
| `OLLAMA_BASE_URL` | Defaults to loopback port 11434. No auth. |
| `OLLAMA_TIMEOUT_S` | Per-request timeout, default 600 s — a local turn is bounded by the host's hardware, not a provider's SLA. |

**A question about the daemon is not timed like a turn.** `is_available()` and
`installed_models()` use `OLLAMA_PROBE_TIMEOUT_S` (5 s) rather than the 600 s
generation timeout: a daemon answers `/api/tags` at once or it is not
answering, and both are asked from a console with a person waiting at it.
`_client(timeout_s=...)` only ever tightens the bound, never relaxes it, so an
explicitly lower timeout still wins and S3's "an explicit timeout, always"
holds either way.

Resolution order in `build_backend()`, and no other: an explicit argument beats
the environment, which beats the class defaults. Credential and endpoint are
**bound**, not independently settable — see S3. `OPENAI_BASE_URL` counts as a
non-default base URL for S3 purposes, so setting it in the environment does not
pair `OPENAI_API_KEY` to it; pairing requires both to be supplied together.
Whoever changes the endpoint must also choose the key that travels to it.

### 4.4 Schema translation

One pure function per dialect — `to_anthropic`, `to_openai`, `to_gemini` —
taking the registry's tool schemas and returning the dialect payload, with no
I/O so every case is a unit test. `for_dialect` dispatches on a backend's
declared dialect.

| | Anthropic | OpenAI / Ollama | Gemini |
| --- | --- | --- | --- |
| Envelope | `name`, `description`, `input_schema` | a function wrapper: `type: "function"` around `name`, `description`, `parameters` | a list of `functionDeclarations`, each `name`, `description`, `parameters` |
| Types | JSON Schema, lowercase | JSON Schema, lowercase | OpenAPI 3.0 subset, **uppercase** (`STRING`, `INTEGER`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT`) |
| integer-or-null union | pass through | pass through (non-strict) | **rewritten to an `INTEGER` typed as `nullable`** |
| Unsupported keywords | none | none | drop `additionalProperties`, `$ref`, most `format` |
| Call ids | native | native | **none — adapter synthesizes** |
| Arguments arrive as | mapping | **JSON string** (must be parsed) | mapping |

**Input inventory — re-verified against `tools/registry.py` at 49 tools during
Phase 1a (2026-09-09).** No `anyOf`/`oneOf`/`allOf`/`$ref`/`additionalProperties`;
one `enum` (`search_ned.table`); arrays of string (`search_simbad.fields` and
2 more), number (`analyze_source_spectrum.*`), and opaque object
(`solve_zeropoint_from_measurements.*`); **8 scalar-or-null unions** —
`["integer","null"]` on `search_vizier.max_catalogs`,
`search_mast.max_observations`, `plot_field_sed.max_catalogs`,
`identify_radio_sources.max_catalogs`; `["number","null"]` on
`plot_field_sed.{radius_arcsec,max_field_radius_arcmin}` and
`identify_radio_sources.{radius_arcsec,max_field_radius_arcmin}`. Every schema
is a flat object; 11 tools carry no `required` key, and several `list_*` tools
carry an empty `properties` object (which validation reads as "shape
unconstrained"). The golden files under `tests/fixtures/llm/schemas/` are now
the authoritative record; regenerate them on any registry change.

Three requirements the implementer must not negotiate:

1. **The Anthropic translation is not the identity function.** It must copy, so
   a caller cannot mutate `TOOL_SCHEMAS` through the returned value. Test it.
2. **The union is never downgraded.** The Gemini translation rewrites the
   integer-or-null union to a nullable integer — it never emits a plain integer.
   Emitting the plain form would silently destroy the uncapped-query semantic
   `SYSTEM_PROMPT` depends on and would hide the exact failure the benchmark
   exists to measure. **The schema stays faithful; a model's failure to use it
   is a result, not a bug to paper over.** This holds for weak local models too.
3. **OpenAI strict mode is implemented but is not the default.** Strict mode
   requires `additionalProperties: false` and *every* property listed in
   `required`, which would turn optional parameters into mandatory ones — a
   semantic change. Build the strict variant, golden-test it, default it off.

**Gemini needs synthetic call ids.** The adapter assigns `call_0`, `call_1`, …
in the order the `functionCall` parts appear, and maps results back by name and
position. It must assert exactly one `functionResponse` per `functionCall` and
raise a `call_id_mismatch` fault otherwise, because a silent mismatch would
misattribute a tool result to the wrong call and corrupt a trajectory grade — a
wrong number in a benchmark report with nothing to indicate it is wrong. This is
the one place in the adapter where a loud failure is strictly better than a
graceful one.

### 4.5 Message rendering

The neutral history is rendered per provider on every call. Adapters are
stateless; there is no incremental conversation state to drift.

* **Anthropic** — assistant turns become content blocks; a `ToolResultBlock`
  becomes a `user` message carrying a tool-result block keyed by `tool_use_id`.
* **OpenAI / Ollama** — assistant turns carry `tool_calls`; each
  `ToolResultBlock` becomes a `tool`-role message keyed by `tool_call_id`. The
  system prompt becomes a leading `system`-role message.
* **Gemini** — assistant turns become `model`-role content with `functionCall`
  parts; results become `user`-role content with `functionResponse` parts. The
  system prompt goes in `systemInstruction`, never in `contents`.

**Ollama uses the OpenAI-compatible endpoint**, so its backend is a thin
subclass overriding only the default base URL (loopback), the auth header (there
is none — no `Authorization`, ever, even when `OPENAI_API_KEY` is set in the
environment), its `spec`, its output ceiling, and adding an availability probe.
The probe hits Ollama's **native** tags path, not the compatibility prefix, and
returns false on any connection error; `complete()` then raises
`BackendUnavailableError` naming `OLLAMA_BASE_URL` and suggesting `ollama serve`
rather than surfacing a raw connection traceback. Ollama's native chat endpoint
returns tool arguments as an object rather than a JSON string; the compatibility
endpoint is documented to normalize that away. **If the compatibility layer
proves lossy, the native endpoint is the documented fallback** — see section 11,
question 2, which is resolved by measurement in Phase 2b.

### 4.6 Protocol faults

A `ProtocolFault` is a typed, recorded observation — never an exception that
kills the run, unless the loop genuinely cannot continue.

| Fault | Meaning |
| --- | --- |
| `malformed_arguments_json` | The provider's arguments string did not parse. |
| `schema_violation` | Arguments failed validation against the tool's own input schema. |
| `unknown_tool` | Called a name not in `TOOL_FUNCTIONS`. |
| `stringified_null` | Sent `"None"` or `"null"` where JSON `null` was required. |
| `call_id_mismatch` | Result count or ordering did not match the calls. |
| `empty_tool_call` | A tool-use stop reason with no parsable call. |
| `truncated_output` | The provider stopped at the token ceiling mid-call. |

These are what the protocol grader counts. They are also what makes a small
local model's failure legible instead of just "the run crashed."

**The truncation rule is identical in all four adapters** and is implemented
once as a shared helper, not four times: a `max_tokens` stop reason **that
arrived with at least one tool call** records `truncated_output`, because the
arguments may be incomplete and the trajectory is not trustworthy. A `max_tokens`
stop with no tool calls is ordinary truncated prose and records nothing.

### 4.7 What does not change

`tools/runner.py` keeps its path — CI's `repository-shape` job asserts the file
exists — its public signature, and its module-level `TOOL_SCHEMAS` and
`TOOL_FUNCTIONS` globals **read at call time, not import time**. `run()` gains
one optional `backend` keyword. With no backend supplied it constructs the
Anthropic backend and behaves exactly as today.

> **Phase 0 is complete when `tests/test_runner_session.py` passes with zero
> edits to the test file.** If the test needs changing, the refactor changed
> observable behaviour and is wrong.

That test monkeypatches `runner.TOOL_SCHEMAS`, `runner.TOOL_FUNCTIONS`, and the
`anthropic` module entry in `sys.modules` after import, then asserts on the
resulting manifest — which is why the globals must be read inside `run()` and
why the `anthropic` import stays function-local.

**The loop itself moves to `tools/agent/`.** Rather than refactor `run()` in
place and then rewrite the same function when the console arrives, Phase 0c
builds the headless engine directly and leaves `tools/runner.py` as a shim over
it. The gate above is unchanged and still meaningful — it is now the shim's
contract. `SYSTEM_PROMPT` moves verbatim to `tools/agent/prompt.py` and is
re-exported from `tools/runner.py`, so both `runner.SYSTEM_PROMPT` and the
default argument keep resolving. `tools/runner.py` is deleted later, by
the TUI track's phase G, together with the workflow change that
retires the CI assertion — not here.

The engine contract itself — the ten-event union, the approver callable, the
consumers — is described in `docs/tool-architecture.md` section 10, because
that is the document whose interface depends on it. Phase 0c below states what
this port must build against it.

### 4.8 Revealed reasoning

`complete()` takes a second streaming hook, `on_thinking`, on exactly the terms
of `on_text`: a streaming provider calls it per chunk, a one-shot provider once
at the end, and a provider that reveals nothing never calls it. `Capabilities`
gains `thinking`, which describes **the adapter, not the model** — `False`
means this port cannot read that provider's reasoning, not that the model did
not reason.

| Adapter | Where reasoning comes from |
| --- | --- |
| Anthropic | Extended thinking, asked for with `thinking_budget` and streamed as its own event type. Signed. |
| OpenAI-compatible (incl. Ollama) | Whatever the server put in `reasoning_content` or `reasoning`. There is no standard field, so both are read. Unsigned. |
| Gemini | Not read yet. Accepts the hook and never calls it. |

Three consequences worth stating, because each one is a trade rather than a
detail:

**A thinking budget costs `temperature`.** The provider refuses extended
thinking and an explicit temperature together. The adapter drops the
temperature when a budget is set, and `temperature_supported` then reports
`False` — so a benchmark run cannot claim the determinism of 6.5 while asking
for reasoning. Thinking is therefore **off by default** everywhere except the
console, which sets it deliberately.

**A budget that will not fit is not sent.** The provider requires
`max_tokens` to exceed the budget and the budget to clear its own floor
(1024). A caller with a small output ceiling gets no reasoning instead of a
rejected request: reasoning is an improvement on the answer, never a
precondition for one.

**Signed reasoning has to be replayed, and only where it is required.** When
thinking is on, the provider demands the thinking blocks of the turn whose tool
calls are being answered, signature intact, and discards them from every
earlier turn. So the Anthropic renderer emits them for the **last** assistant
message only — sending the rest would put a session's whole reasoning history
on the wire each turn to be thrown away at the other end. A block with no
signature is dropped rather than sent, since an unsigned one is refused. And if
the turn being continued has no signed blocks at all — a session resumed from a
manifest that lost them, or one that began with thinking off — the request is
made **without** thinking rather than failing: a turn with no visible reasoning
is a smaller loss than a turn that errors.

---

## 5. Security Architecture

Nine requirements, from the security review of this design. Each is an
acceptance criterion with a test, not advice. IDs are referenced from the
rollout in section 9.

**Status (2026-09-13):** eight **implemented and tested**, and S1 **retired**
rather than satisfied — the component it confined was removed, so the risk is
eliminated rather than mitigated. S3, S4, S8 and S9
landed in phases −1–3; S1, S2, S5, S6 and S7 landed with the benchmark harness
(phases 4–5), whose architecture and rollout are
[harness.md](../benchmarking/harness.md) — see its section 10 for the test that carries
each one.

| ID | Where | Test |
| --- | --- | --- |
| ~~S1~~ | **Retired.** The component it protected is gone — see below |  |
| S2 | `tools/bench/record.py` — credential scan over the serialized entry, refusing the write | `tests/test_bench_record.py` |
| S5 | `tools/bench/tasks.py`, `tools/bench/fixtures.py` — `yaml.safe_load` only | `tests/test_bench_tasks.py`, `tests/test_bench_fixtures.py` |
| S6 | `tools/bench/tasks.py`, `tools/bench/fixtures.py` — bare names, rejected before resolution and re-checked with `tools.config.within` | both of the above |
| S7 | `tools/bench/fixtures.py` — `path`/`subdir`/`ext` rejected; the shim reserves its own path | `tests/test_bench_fixtures.py` |

### S1 — Retired: there is no model-grader (was HIGH)

This requirement existed for the optional LLM judge: a model asked for a
pass/fail verdict on another model's answer. Tool results are arbitrary
third-party text — ADS abstracts and titles, VizieR catalog descriptions,
SIMBAD notes, NED cells — so a judge that reads them is an oracle taking
instructions from the data it grades, and because fixtures are committed and
replayed, one poisoned capture would corrupt the scoreboard permanently and
invisibly. S1 confined the judge to two strings to keep that unreachable.

**The judge was removed** (`harness.md` 7.5). Every verdict in the harness is
now a deterministic assertion against recorded evidence, and nothing asks a
model whether an answer is correct — so there is no oracle for a poisoned
fixture to reach. The risk is eliminated rather than mitigated, which is why
this requirement is retired rather than reassigned.

`tools/bench/record.py` still flags imperative-looking strings in captured text
(S2). That is a reviewer's checklist, not a boundary, and it stands on its own.

### S2 — Fixtures record responses only (MEDIUM)

Record mode writes live third-party response text into committed files.

* Capture stores **response bodies only**. Request headers and query strings are
  never written — an allowlist of non-sensitive request fields, not a denylist.
* Fixture diffs are reviewed by a human in the PR that adds them. They are
  adversarial input, not test data.
* Capture flags imperative-looking strings in captured text for reviewer
  attention. Advisory, not blocking.
* Test: a capture performed with a credential set must produce a fixture
  containing no substring of that credential.

### S3 — Credential is bound to endpoint (MEDIUM)

*Implemented in Phase 2a: `tools/llm/factory.py` owns the binding rule,
`tools/llm/base.py::BaseHTTPBackend` the transport hardening; tested in
`tests/test_llm_factory.py`.*

Independently settable endpoint and credential is a key-exfiltration primitive,
and the endpoint is the half that travels in a shared benchmark config or a
`--base-url` flag.

* A provider key from the environment is sent **only** to that provider's
  default host. A non-default base URL requires an explicitly paired key;
  without one, no `Authorization` header is sent at all.
* No `Authorization` header over plaintext HTTP except to loopback
  (`127.0.0.1`, `::1`, `localhost`).
* `follow_redirects` stays `False` **explicitly**, even though that is the
  `httpx` default, so a redirect can never carry an auth header cross-host. The
  code carries a comment saying so — a future reader deleting "redundant"
  defaults is the failure mode this guards against.
* Always an explicit timeout. Never disable certificate verification.
* Test: constructing a backend with a non-default base URL and no paired
  credential must not send an `Authorization` header.

### S4 — No credentials in URLs (MEDIUM)

*Implemented in phases 2a/3: header auth only across all four adapters
(`x-goog-api-key` for Gemini), cross-backend sweep in
`tests/test_llm_gemini_backend.py`. The manifest-URL-scrub half (a recorded
`base_url_host` stripped of userinfo) lands with manifest v2 in Phase 4.*

Gemini's REST API accepts a key as a query parameter, which lands in proxy logs,
in `httpx` exception messages (which include the URL), and in any manifest
recording the request.

* Gemini uses the `x-goog-api-key` header exclusively.
* Any recorded base URL is scrubbed of userinfo before reaching a manifest.
* Test: assert no adapter places a credential in a URL, for all four backends.

### S5 — Safe YAML loading, always (HIGH if wrong)

`PyYAML==6.0.3` is already a dependency. Benchmark suites are exactly the kind
of file people fetch from a colleague or a paper repository and run locally, on
a machine holding four provider API keys.

* Task and suite files load through `yaml.safe_load`. Never `yaml.load`.
* Test: a task file containing a Python-object construction tag must raise, not
  execute.

### S6 — Suite and fixture paths are contained (MEDIUM)

A task file referencing a fixture path that escapes the suite root does not
merely read a file — it reads it **into the model's context** as a tool result,
then into the manifest and the report. A shared suite becomes a local-file
exfiltration primitive against whoever runs it.

* Every task-referenced path resolves against the suite root; anything escaping
  it after resolution is rejected.
* Fixture references are relative-only. Absolute paths are an error.
* Test: traversal and absolute-path fixture references are both rejected.

### S7 — Fixtures carry content, never paths (MEDIUM)

`tools/artifacts.py` scrubs artifact *names* well, but its private
`_write_directory()` joins `subdir` unvalidated and `reserve_artifact_path()`'s
`ext` is only stripped of leading dots. Those are safe today only because
tool code sets them.

* The replay layer synthesizes artifact paths itself from the task id and tool
  name. A fixture supplies content and never a path, `subdir`, or `ext`.
* Test: a fixture attempting to set a parent-relative `subdir` is rejected, and
  no file is written outside the artifact root.

### S8 — Validate arguments before dispatch (MEDIUM)

*Implemented in Phase 1b: `tools/llm/validation.py` runs the rule table below
before every dispatch; `AgentSession.record_fault` + the `protocol_faults`
manifest key record what it catches. Tests: `tests/test_llm_validation.py`,
`tests/test_runner_validation.py`.*

`tools/runner.py` dispatches tool functions on model-supplied JSON. Today
Anthropic's server-side schema enforcement plus Python signature binding
constrains that. Four backends removes the first half: local models emit
unconstrained JSON, and Gemini's subset cannot express the integer-or-null union
at all, so the adapter's rewrite widens what arrives.

* Every tool call is validated against that tool's own input schema **before**
  dispatch. A violation is a `schema_violation` fault and an error result
  returned to the model — not an exception, and not a call.
* The string `"None"` is **never** silently coerced to `None`. It is rejected
  and recorded as `stringified_null`. Silent coercion of model output is
  confused-deputy behaviour, and here it would also destroy the benchmark's most
  interesting measurement.
* This is the same validation the protocol grader needs, so the control costs
  nothing extra. It is built in Phase 1, before any non-Anthropic backend
  exists.

**Validation rules, in evaluation order.** Hand-rolled — no `jsonschema`
dependency, and none is needed, because every registry schema is a flat object
with scalar, enum, and array-of-string properties.

| Check | Fault |
| --- | --- |
| Name absent from the schema index | `unknown_tool` |
| Arguments are not a mapping | `schema_violation` |
| A required property is missing | `schema_violation` |
| A property is not in the schema | `schema_violation` |
| Value is `"None"`, `"null"`, `"nil"`, or `"NULL"` in any case, and the property's type list includes null | `stringified_null` |
| Value's JSON type is not in the property's declared type(s) | `schema_violation` |
| Value not in the property's `enum` | `schema_violation` |
| Array element type mismatch | `schema_violation` |

Accept an integer where `number` is declared — JSON has one numeric type and
every provider round-trips a whole number as an int. **Reject a boolean where
`integer` is declared**: Python's `bool` is an `int` subclass, so this needs an
explicit guard.

Two rules that are the whole point:

- **`"None"` is never coerced.** Not to `None`, not to anything. A
  `stringified_null` fault on a null-accepting property is the highest-value
  signal in the whole taxonomy.
- **A fault is a result returned to the model, not an exception.** The runner
  sends back an error result naming the problem and continues the loop. A
  crashed run measures nothing.

### S9 — Fix the stale gitleaks allowlist first (LOW-MEDIUM)

*Implemented in Phase −1: the `kepler/` paths corrected to `tools/`, the
`docs/*.md` and workflow directory wildcards replaced with exact files, a
scoping comment added. `OPENAI_API_KEY`/`GEMINI_API_KEY` added in phases 2a/3
next to their first uses. Probe-verified with the CI's gitleaks image.*

Verified: `.gitleaks.toml` scopes its allowlist of the three
environment-variable *names* `ADS_DEV_KEY`, `ANTHROPIC_API_KEY`, and
`NASA_API_KEY` to `kepler/runner.py` and `kepler/tools/ads.py`. **Both paths are
missing** — the real files are `tools/runner.py` and `tools/ads.py`. Five
further files reference those key names outside any allowlisted path:
`AGENTS.md`, `CLAUDE.md`, `tests/test_runner_session.py`, `tools/registry.py`,
and `tools/claude_photometry_haiku_tool.py`.

`CLAUDE.md` tells contributors to add allowlist entries for new paths, pointing
at a control that is already misaligned. This design adds two more key names.

* Fix the stale **paths**. Do not broaden the regexes: a repository-wide
  `OPENAI_API_KEY` name allowlist would suppress detection of a genuinely leaked
  key value, which is the one thing the scanner exists to catch.
* Ships as its own small PR **ahead** of this work (Phase -1), separate from the
  feature.

### Cost guardrail (not a vulnerability, stated as a design requirement)

A harness looping tasks × models × repeats against paid APIs is a self-inflicted
billing risk, and an injected fixture urging repeated calls makes it
adversarial. Every run carries a spend ceiling and prints a dry-run estimate
before the first live call, alongside the existing `max_turns` bound. Replay
mode makes runaway loops free, which is a second reason it is the default.

---

## 6. Benchmarking — the design summary; see [harness.md](../benchmarking/harness.md)

**This section is the design summary. [harness.md](../benchmarking/harness.md) is the
architecture, the rollout, and what actually shipped** — it was written once
the port landed and the fault taxonomy was real rather than predicted, as this
section said it would be. Where the two disagree, harness.md section 15
enumerates the divergences with reasons; they are not silent. The ones worth
knowing before reading on:

* **Local tools run live.** 6.3 below implies every tool result is replayed;
  replaying `compute_pulsar_periodogram` would replace the measurement with a
  guess about the measurement.
* **`grade` is a separate verb** from `run`, so a grader fix never costs a
  re-spend.
* **There is no cost axis, no price table, and no `estimated_usd`** — see open
  question 3 in section 11, now closed as *not built*.
* **Two headline axes and two diagnostic ones**, not four co-equal ones.
* **Efficiency is three clocks, not one**, and four token classes, not one.

### 6.1 What is measured

Four independent axes, reported as a matrix. **There is no single blended score
by default** — a composite hides which axis failed, and "model A scored 0.72" is
not an actionable result. A weighted composite is available behind an explicit
flag for people who want a leaderboard.

| Axis | Grader | Source |
| --- | --- | --- |
| Trajectory | `trajectory.py` | Manifest tool calls vs. task expectations. |
| Efficiency and cost | `efficiency.py` | Turns, calls, duplicate rate, tokens, latency, estimated USD. |
| Answer correctness | `answer.py` | Deterministic assertions only. |
| Protocol robustness | `protocol.py` | `ProtocolFault` records. |

### 6.2 Task format

A task is a YAML document carrying an id, the prompt, tags, a turn ceiling, a
fixture reference, and an `expect` block. The `expect` block has two halves: a
`trajectory` section carrying `must_call`, `must_not_call`, and per-argument
`arguments` predicates; and an `answer` section carrying `must_match` and
`must_not_match` regexes plus `must_report_artifact_path`. The null probe is an
argument predicate asserting `max_catalogs` was passed as JSON null.

Tasks are seeded directly from the failure modes `SYSTEM_PROMPT` already
documents as confirmed-live: probing VizieR catalogs one at a time instead of
using the category argument, re-issuing an identical failing call, passing a
colloquial name to NED or ATNF, reading a period off rendered audio, presenting
an inline preview as the complete answer, and attributing a specific figure to a
named paper without fetching its abstract. Those paragraphs are an eval suite
that has not been written down as one yet.

### 6.3 Fixtures and matching

Fixtures cannot be keyed on exact arguments — different models pass different
radii, row limits, and spellings for the same task, so exact keying would miss
constantly and measure nothing but argument formatting. A fixture entry names
the tool, a `match` block of loose predicates over the arguments (substring
containment, equality on a discriminating field), and the recorded response.

Entries are tried in order, first match wins, with a per-tool `default` entry and
an explicit `miss_policy`:

* `error` (default) — a miss returns a tool error to the model and records it.
  Honest: the model sees a failure, and the grade reflects the trajectory that
  produced it.
* `synthesize` — return a schema-valid empty result. For tasks where an
  off-script call should not derail the run.
* `record` — capture mode only; performs the live call and appends a new entry
  with a suggested match rule for human review.

Fixture misses are reported per run. A suite with a high miss rate is measuring
its own coverage, not the model, and the report says so.

### 6.4 The four graders

**Trajectory.** Set membership (must-call, must-not-call), ordered subsequence
for pipelines where order is a real dependency — the pulsar chain in particular,
where folding at a wrong period returns a flat profile rather than an error —
and per-argument predicates. Emits passed-over-total checks with a named reason
per failure.

**Efficiency and cost.** Turns to completion, total tool calls, duplicate-call
rate (already available as the cache-hit count in the existing manifest), input
and output tokens, wall-clock per turn, and estimated USD from
`benchmarks/prices.json` — a hand-maintained table carrying a `retrieved_on`
date and an explicit note that it is not fetched. Ollama runs cost zero and report
wall-clock only.

> **As built, this paragraph is three divergences deep** (harness.md 15.3,
> 15.8, 15.9). There is **no cost axis and no `prices.json`**: tokens are the
> measurement and money is the reader's arithmetic, with spending bounded in
> tokens instead. "Wall-clock per turn" became **three clocks reported
> separately** — model time, tool time, wall clock — because tool execution
> dominates wall clock here and an undivided figure ranks models by which
> tools they called. And the token counts stay in **four classes**, because
> `SYSTEM_PROMPT` plus 55 schemas is a large fixed prefix resent every turn and
> folding cache reads into one input number hides a real difference in work
> done.

**Answer correctness.** Deterministic first: regex assertions, numeric
comparison with tolerance, and artifact-path presence checks against an answer
key. **Nothing else** — an optional LLM judge was built here and removed
(`harness.md` 7.5), and with it requirement S1.

**Protocol robustness.** Counts each fault type. Includes a specific
`null_argument_fidelity` check for tasks tagged `null-argument`: JSON null is a
pass, an omitted argument is a partial (a *different* semantic — capped, not
uncapped), and a string is a fault. This is the single most discriminating check
in the suite for small local models, and it exists because of the two union-typed
registry properties.

### 6.5 Determinism

Temperature 0 by default; a fixed seed where the provider supports one; a
repeats option (default 1) for variance, reporting per-axis spread rather than
only a mean. Every knob — backend spec, temperature, seed, suite revision,
fixture revision, price-table date — is recorded in the run
manifest. A run that cannot state its inputs is not a benchmark.

### 6.6 CLI

A `kepler-bench` console script in `pyproject.toml` alongside the existing
`kepler-astro-query`, with three verbs: `run` (a backend against a suite, with
an output directory and an optional repeat count), `record` (live, writes a
fixture for review), and `compare` (renders the matrix across run ids). Reports
render as JSON plus Markdown. **If an HTML report is added later, every model-
and fixture-derived string must be escaped** — it is untrusted text by
construction.

---

## 7. Session Manifest, Schema Version 2

Additive only. Readers must handle v1. `model` stays top-level — the existing
test asserts on it.

Version 2 adds: `schema_version` set to 2; a `backend` object carrying the spec,
provider, a `base_url_host` **scrubbed of userinfo** (S4), and the capability
record; a `usage_totals` object of token counts; a `protocol_faults` list of
turn-stamped fault records; and a `turns` list carrying per-turn latency,
usage, and the provider's raw stop reason.

**Correction (2026-09-18):** this paragraph specified `estimated_usd` in
`usage_totals`. It was never built, and section 6, open question 3 and
[`../benchmarking/harness.md`](../benchmarking/harness.md) sections 8 and 15
all say so — a price is not a property of a session, and writing one into a
durable record freezes a number that ages badly. The implemented
`usage_totals` carries token counts only. This sentence was the one place the
document still disagreed with itself.

The existing note that full tool payloads are omitted stays true: manifests
reference artifact paths, they do not embed results.

**`protocol_faults` lands in Phase 1, not Phase 4.** S8 builds validation in
Phase 1, and a fault that is detected but not recorded is half a control. The
key is added additively while `SESSION_SCHEMA_VERSION` stays at 1; the bump to 2
belongs with the rest of the v2 payload, added in one reviewable change.

---

## 8. Testing

Everything below runs in default `pytest` — offline, deterministic, no API keys,
no daemon.

* **Golden schema translations.** The registry rendered into all four dialects
  (Anthropic, OpenAI, OpenAI strict, Gemini) and asserted byte-stable against
  committed fixtures. Any future change to `tools/registry.py` then shows up as
  a reviewable diff in every dialect at once — including whether it broke
  Gemini. The test module carries a note saying exactly that, plus the
  regeneration command.
* **Adapter round-trips.** Neutral history → provider payload → recorded
  provider response → neutral `ModelResponse`, against captured response
  samples. No network. HTTP adapters are exercised through `httpx`'s mock
  transport, which is part of the already-pinned dependency and lets every
  assertion inspect the real outgoing request.
* **Argument validation (S8).** Schema violations, `"None"`, unknown tools,
  malformed JSON.
* **Graders.** Fed synthetic manifests, including adversarial ones.
* **Harness end-to-end** against `ReplayBackend`, which replays a recorded
  model transcript. Both sides replayed, so the harness itself is CI-testable.
* **Security tests**, one per requirement S1–S8, named for the requirement.

Live provider runs sit behind a new `model_api` marker plus an environment gate
(`KEPLER_TEST_MODEL_API=1`), mirroring the existing `network` convention. Ollama
tests get an `ollama` marker and skip when the daemon is unreachable.
`pyproject.toml` gains both markers and nothing else — **no dependency changes.**

**Correction (2026-09-18):** the gate this rollout kept naming,
`tests/test_runner_session.py`, is now `tests/test_agent_session_manifest.py`
— it drives `run_session` directly and every manifest assertion is unchanged.
`tests/test_runner_validation.py` is gone; its two assertions that the engine's
own tests did not already make moved into them. Both changes belong to the
console's retirement of `tools/runner.py`, not to this rollout, whose phases
ran and passed against the names as written.

CI is unchanged in shape: `compileall`, `pytest`, `repository-shape`. No new
required job, no live calls, no keys in CI.

**How the HTTP adapters take a test transport.** Reaching into a private client
attribute from a test is a smell; prefer giving the shared HTTP base an optional
transport keyword that tests pass and production never does. Decide once, then
use it consistently across all three HTTP adapters.

---

## 9. Rollout

One PR per task, narrow, in order. Documentation, workflow, dependency, and
behaviour changes stay separated per `CLAUDE.md`.

### Status — phases −1 through 3 done (2026-09-09)

Delivered as one branch (`agent/model-backends-impl`), one commit per phase,
each with the full suite green and the Phase 0c gate (an unedited
`tests/test_runner_session.py`) passing.

| Phase | Commit | Outcome |
| --- | --- | --- |
| −1 gitleaks allowlist | `security(gitleaks): fix stale allowlist paths…` | stale `kepler/` paths fixed, directory wildcards removed, probe-verified |
| 0a neutral types + protocol | `feat(llm): neutral model-port types…` | `tools/llm/types.py`, `base.py` |
| 0b Anthropic adapter | `feat(llm): the Anthropic Messages API adapter` | `anthropic_backend.py`, streaming preserved |
| 0c move the loop | `refactor(agent): move the loop into tools/agent/…` | `tools/agent/` engine + events; `runner.py` a shim; gate empty-diff |
| 1a schema translation | `feat(llm): tool-schema translation into all four dialects` | `schema.py` + 4 byte-stable golden files; **8 unions found, not 2** |
| 1b argument validation | `feat(llm): validate tool arguments…before dispatch (S8)` | `validation.py`; `protocol_faults` manifest key (schema still v1) |
| 2a OpenAI + factory + HTTP base | `feat(llm): OpenAI-compatible backend, the factory…(S3, S4)` | `openai_backend.py`, `factory.py`, `BaseHTTPBackend`; markers added |
| 2b Ollama + live check | `feat(llm): Ollama backend, and the live OpenAI-compat measurement` | `ollama_backend.py`; section 11 Q2 measured (below) |
| 3 Gemini | `feat(llm): Gemini backend — synthetic call ids…(S4)` | `gemini_backend.py`; `call_id_mismatch` raises; cross-backend sweep |
| — KEPLER_MODEL_BACKEND wiring | `feat(runner): honor KEPLER_MODEL_BACKEND in the console shim` | the shim builds a spec through `build_backend` when the var is set |
| docs | this commit | this document, `tool-architecture.md` §10, `README.md`, `CLAUDE.md` |

Phases 4–5 — the benchmark harness (section 6) and manifest v2 (section 7),
carrying S1, S2, S5, S6, S7 — landed on 2026-09-13 under
[harness.md](../benchmarking/harness.md); see the phase table below.

### Global constraints

Every phase's requirements implicitly include this section.

- **Zero new dependencies.** No additions to `pyproject.toml`'s dependency list,
  no `uv lock` churn. `jsonschema`, `openai`, `google-generativeai`, `litellm`
  and friends are all forbidden. `httpx==0.28.1` and `PyYAML==6.0.3` are already
  pinned and are the tools for the job.
- **Branch:** `agent/model-backends`, off `main` — at the maintainer's
  instruction. Do not retarget.
- **One PR per task**, narrow.
- **No linter or formatter is configured.** Match the surrounding file's style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88 column soft wrap.
- **Default checks stay offline and deterministic.** Nothing added here may open
  a socket under a plain `uv run pytest`.
- **`tools/runner.py` must keep its path for the duration of this rollout.** CI's
  `repository-shape` job asserts `README.md`, `pyproject.toml`, `uv.lock`,
  `tools/registry.py`, `tools/runner.py`, and `docs/tool-architecture.md` all
  exist. It was deleted by the TUI track's phase G,
  together with the workflow change that retires the assertion.
- **No changes to `algorithms/`.** The extraction contract is untouched by this
  work. Do not edit any file carrying an `# EXTRACTED:` or `# PORTED:` marker.
- **Never disable TLS verification. Never enable redirect following.** Always an
  explicit timeout on every `httpx` call. (S3.)
- **Never place a credential in a URL.** Header auth only, all four providers.
  (S4.)
- **The integer-or-null union is never downgraded** to a plain integer to make a
  weak model's life easier. (Section 4.4.)
- **The string `"None"` is never silently coerced to `None`.** (S8.)
- **`tests/test_tool_registry_coverage.py` enumerates `pkgutil.iter_modules`,
  which yields packages as well as modules.** Adding `tools/agent/` or
  `tools/llm/` requires updating `NOT_TOOL_MODULES` in the same commit or that
  test fails.

### Verification commands

```bash
uv run pytest                             # must be green; offline, no keys
uv run pytest tests/test_runner_session.py -v
python3 -m compileall tools algorithms    # syntax smoke, mirrors CI
git diff --check                          # whitespace
```

### Files this rollout creates

| Path | Phase |
| --- | --- |
| `tools/llm/{__init__,types}.py`, `tests/test_llm_types.py` | 0a |
| `tools/llm/base.py` | 0a |
| `tools/llm/anthropic_backend.py`, `tests/test_llm_anthropic_backend.py`, `tests/fixtures/llm/responses/anthropic_tool_use.json` | 0b |
| `tools/agent/{__init__,events,prompt,engine}.py` | 0c |
| `tools/llm/schema.py`, `tests/test_llm_schema.py`, `tests/fixtures/llm/schemas/{anthropic,openai,openai_strict,gemini}.json` | 1a |
| `tools/llm/validation.py`, `tests/test_llm_validation.py`, `tests/test_runner_validation.py` | 1b |
| `tools/llm/openai_backend.py`, `tools/llm/factory.py`, `tests/test_llm_openai_backend.py`, `tests/test_llm_factory.py`, `tests/fixtures/llm/responses/openai_tool_call.json` | 2a |
| `tools/llm/ollama_backend.py`, `tests/test_llm_ollama_backend.py` | 2b |
| `tools/llm/gemini_backend.py`, `tests/test_llm_gemini_backend.py`, `tests/fixtures/llm/responses/gemini_function_call.json` | 3 |

### Files this rollout modifies

| Path | Change |
| --- | --- |
| `.gitleaks.toml` | Phase -1: correct two stale allowlist paths, add the five real ones. Phases 2a and 3: add `OPENAI_API_KEY` and `GEMINI_API_KEY`, each scoped to the paths that first use it. |
| `tools/runner.py` | Phase 0c: reduced to a shim over `tools/agent/`. Phase 1a: translated schemas. Phase 1b: validation before dispatch. |
| `tests/test_tool_registry_coverage.py` | Phase 0c: add `tools.agent` to `NOT_TOOL_MODULES`. |
| `tools/sessions.py` | Phase 1b: fault recording and a `protocol_faults` manifest key. |
| `pyproject.toml` | Phase 2a: two new pytest markers. **No dependency changes.** |
| `docs/tool-architecture.md`, `README.md`, `CLAUDE.md`, this document | Documentation phase. |

**Deliberately not touched:** `tools/registry.py` — the schemas are the input to
translation, not a subject of it; `tools/claude_photometry_haiku_tool.py` —
deferred by section 10, and renamed with its Anthropic path deleted by
the TUI track's phase C; anything under `algorithms/`.

### Phase -1 — Fix the stale gitleaks allowlist (S9)

Ships first, alone, ahead of the feature. It fixes an already-misconfigured
control; bundling it with an architecture change would bury it.

- [ ] Confirm the misalignment before changing anything: there is no `kepler/`
      directory; `tools/runner.py` and `tools/ads.py` both exist; grepping the
      tree for those three key names lists `AGENTS.md`, `CLAUDE.md`,
      `tests/test_runner_session.py`, `tools/registry.py`,
      `tools/claude_photometry_haiku_tool.py`, `tools/runner.py`, `tools/ads.py`
      and the already-allowlisted documentation and workflow entries. **Record
      the actual output in the PR description** — if it differs, the allowlist
      is adjusted to match reality, not to match this document.
- [ ] Correct the path list so every path that genuinely mentions an allowlisted
      key name is covered, and no path is a wildcard. Add a comment above the
      array recording *why* it is path-scoped: the regexes match variable names,
      and scoping is what keeps a real leaked value detectable.
- [ ] **The two new provider key names are not added here.** They arrive in the
      phase that first writes them, so each addition is reviewed next to its use.
- [ ] Run the scanner over the tree and confirm it is clean. If `gitleaks` is not
      installed locally, push the branch and read the `secret-scan.yml` result —
      do not skip this and do not claim it passed without one of those outputs.
- [ ] **Prove the allowlist is still narrow.** Write a throwaway file at a
      non-allowlisted path containing a plausible fake secret assignment, run the
      scanner, confirm it **is** detected, then delete the file. A clean result
      here means the allowlist got broadened — stop and narrow it.

**Gate:** scanner clean on the tree **and** a probe file at a non-allowlisted
path still detected.

### Phase 0a — Neutral types, fault taxonomy, and the protocol

- [ ] Build `tools/llm/types.py` to section 4.1: frozen dataclasses, tuples not
      lists, the closed stop-reason set, the seven-value fault taxonomy, and no
      `role="system"`.
- [ ] `tools/llm/__init__.py` re-exports the type names with an `__all__` and
      stays import-light, so importing the package never costs an `anthropic` or
      `httpx` import.
- [ ] Build `tools/llm/base.py`: `SchemaDialect`, `Capabilities`,
      `BackendUnavailableError`, and the `ModelBackend` protocol, decorated
      `@runtime_checkable` so conformance is testable and the runner can assert
      on what it was handed.
- [ ] **Do not add a shared HTTP base class yet.** Phase 2a introduces it when
      there are two HTTP adapters to share it; building it now is speculative.

**Tests:** types are frozen; `Message` has no system role; `ModelResponse`
defaults are empty rather than `None`; the types module's source contains no
provider SDK name; `Capabilities` is frozen and complete.

### Phase 0b — The Anthropic adapter

Behaviour requirements — the implementer chooses how, not whether:

1. The API key defaults to `ANTHROPIC_API_KEY`. A missing key raises
   `BackendUnavailableError` naming the variable. Never at import time, and
   never when a key is passed explicitly.
2. The `anthropic` import is **function-local or lazy**, exactly as the runner
   does it today, so importing `tools.llm` stays cheap and the existing test's
   `sys.modules` monkeypatch keeps working.
3. `complete()` streams and forwards each chunk to `on_text` when given, then
   takes the final message. This preserves today's live-printing behaviour byte
   for byte.
4. Message rendering per section 4.5.
5. Stop-reason normalization: end-turn and stop-sequence both map to `end_turn`;
   tool-use, max-tokens, and refusal map to themselves; anything else maps to
   `other`. `raw_stop_reason` always carries the original.
6. `latency_ms` measured with a monotonic clock around the API call.
7. Usage is read from the final message when present; **every field is `None`
   when absent, never `0`**. A fake response object with no usage attribute must
   not raise — the existing test's stand-in responses have none, and Phase 0c
   depends on that still working.
8. A tool-use stop reason whose content yields no tool-use block records an
   `empty_tool_call` fault rather than raising.
9. The `truncated_output` rule of section 4.6, implemented as the shared helper.

Keep the module around 150 lines; past that, the rendering helpers want to be
module-level functions rather than methods. Tests reuse the fake-SDK shape
already proven in `tests/test_runner_session.py`. After this phase the whole
existing suite must still pass — nothing is wired into the runner yet, so a
regression here means an import-time side effect.

### Phase 0c — Move the loop into `tools/agent/`

**This is the phase gate.**

- [ ] Build `tools/agent/prompt.py` — `SYSTEM_PROMPT` **moved verbatim** from
      `tools/runner.py`. It is ~270 lines of confirmed-live failure-mode guidance
      and the source of all eight benchmark seed tasks (section 11, question 4).
      Move it; do not reword it while moving it.
- [ ] Build `tools/agent/events.py` — the ten frozen event dataclasses and their
      union, now described in `docs/tool-architecture.md` section 10. The fault
      event carries this port's `FaultType`, so there is one taxonomy, not two.
- [ ] Build `tools/agent/engine.py` — `run_session()`, which takes the user
      message plus a backend, system prompt, turn ceiling, an approver callable,
      and an optional session, and **returns an iterator of events**.
- [ ] The approver parameter gets a module-level default that allows everything.
      `tools/agent/policy.py` — where the real policy lives — is built by
      the TUI track's phase B. Giving the parameter a default
      now means that phase supplies a policy rather than changing a contract.
- [ ] Reduce `tools/runner.py` to a shim: same signature, plus the optional
      `backend` keyword; it consumes `run_session()`, prints, and returns the
      manifest path.
- [ ] Add `tools.agent` to `NOT_TOOL_MODULES` in the same commit.

**What must not change:**

- The module path `tools/runner.py`, and `main()` plus the `kepler-astro-query`
  console script — both still working at the end of this phase, so nothing
  downstream breaks before the console exists.
- `SYSTEM_PROMPT` re-exported from `tools/runner.py`, so both the module
  attribute and the default argument keep resolving.
- Module-level `TOOL_SCHEMAS` and `TOOL_FUNCTIONS`, **read at call time**.
- The printed console output, the call cache and its `make_cache_key` key
  function, every `record_tool_call`/`record_turn`/`save` call and its ordering,
  and the `scoped_artifacts` context manager wrapping the whole loop.
- The broad exception handler that saves an error manifest and re-raises.
- The missing-key path: the runner prints its "set your key" message and returns
  nothing rather than raising, when no backend is supplied and no key is set.

**What changes:** the `anthropic` import and client construction move into the
adapter; the message list becomes neutral `Message` objects instead of raw SDK
dicts; the streaming block becomes a `complete()` call with the print function
as `on_text`; content-walking becomes iteration over `response.tool_calls`; the
assistant and tool-result appends become neutral messages. With no backend
supplied the runner constructs the Anthropic backend; when one **is** supplied,
the `model` argument is informational and the backend's own model wins, but the
session still records the `model` argument because the existing test asserts on
it.

**Schemas at this stage** pass through unchanged, because the Anthropic dialect
*is* the registry's native shape. Phase 1a introduces translation. Do not do
both at once — this phase's whole value is that its gate is an unedited test.

**Gate:** `git diff --stat HEAD -- tests/test_runner_session.py` is **empty** and
that test passes. Paste that command's output into the PR description. If it
fails, fix the refactor, never the test. The most likely failure modes, in
order: the fake response has no usage attribute; the fake content blocks are
plain namespaces rather than SDK objects, so access must be duck-typed;
`TOOL_SCHEMAS` was captured at import time instead of read inside the call.

### Phase 1a — Schema translation

- [ ] Build `tools/llm/schema.py` to section 4.4: deep-copy the input, then
      transform. Each dialect is a separate top-level function; share only a
      small walk helper if one earns its place. No I/O.
- [ ] Switch the runner to ask the backend for its dialect and translate once
      **before the turn loop**, not per turn.
- [ ] Generate the four golden renderings, commit them, and add a byte-stability
      test. **Read all four generated files before committing them** — they are
      the record of what every provider sees, and this is the check that catches
      a Gemini rewrite that quietly dropped a description or flattened an enum.

The existing gate test monkeypatches the schemas to a single one-tool list with
an empty properties object; the Anthropic translation must handle that with no
`required` key and no properties. If it does not, fix `schema.py` and add the
empty-properties case to its tests.

**Gate:** four golden dialect renderings committed and byte-stable; the gate
test still passes unedited.

### Phase 1b — Argument validation before dispatch (S8)

**The most security-relevant phase.**

- [ ] Build `tools/llm/validation.py` to the rule table in S8: `index_schemas`
      builds the by-name schema index once per run, and `validate_tool_call`
      checks one call against it.
- [ ] Add fault recording to `AgentSession`: a `protocol_faults` list, a
      `record_fault` method taking the turn and the fault, and a
      `protocol_faults` key in the manifest. **Leave `SESSION_SCHEMA_VERSION` at
      1** — see section 7.
- [ ] Wire validation into the loop *before* dispatch. On a fault: record it,
      build the error result, record the tool call with the **real** arguments so
      the trace stays honest, append an error result block, and **continue**.
      Never dispatch, never raise. On no fault, dispatch exactly as today. Also
      record any faults the adapter attached to the response.
- [ ] The existing unknown-tool branch becomes dead once validation runs first.
      **Delete it** rather than leaving two code paths that disagree.
- [ ] Confirm the exact property names against `tools/registry.py` before
      writing the tests — this document quotes them from a read of the file, but
      the file is the truth.

Runner-level tests use a hand-written stub backend passed through the `backend`
keyword — that is what the keyword is for, and it removes the need to fake the
`anthropic` SDK here.

**Gate:** `"None"` is rejected as `stringified_null` and the tool is never
dispatched; the Phase 0c gate test still shows an empty diff.

### Phase 2a — OpenAI-compatible backend and the factory (S3, S4)

- [ ] Introduce `BaseHTTPBackend` in `tools/llm/base.py`, owning the transport
      rules so the remaining HTTP adapters inherit rather than re-implement them.
      Give each explicit setting a comment explaining *why* it is explicit.
- [ ] Build `tools/llm/openai_backend.py` and `tools/llm/factory.py` to sections
      4.2–4.5. Arguments arrive as a JSON string and must be parsed; a parse
      failure is a `malformed_arguments_json` fault with the call dropped — not
      an exception.
- [ ] Add the `model_api` and `ollama` pytest markers to `pyproject.toml`,
      matching the tone of the existing `network` entry: never run by default,
      requiring both the marker selection and an environment gate.
- [ ] Add `OPENAI_API_KEY` to the gitleaks regexes and the four new file paths to
      its path list. Scoped, not broadened — same rule as Phase -1.

Security tests come first, before the protocol tests: the non-default-base-URL
case sends no auth header even with a key in the environment; no auth header
travels over plaintext HTTP to a non-loopback host; redirect following is off;
the timeout is explicit. Factory tests cover first-slash-only spec splitting and
the credential binding rule.

### Phase 2b — Ollama backend and the live compatibility check

- [ ] Build `tools/llm/ollama_backend.py` as a thin subclass per section 4.5 and
      register the provider in the factory.
- [ ] **Reference model: `qwen3:8b`** — reliable tool calling at 8B, which is the
      tier the null probe most needs to discriminate. Record it as a named
      constant — `OLLAMA_REFERENCE_MODEL` — in the test module, so later work
      imports one name rather than hard-coding a string in several places.
- [ ] Offline tests: no `Authorization` header ever, even with a key in the
      environment; the availability probe returns false on connection error;
      `complete()` raises `BackendUnavailableError` naming `OLLAMA_BASE_URL`.
- [ ] **Answer section 11 question 2 by measurement.** With the daemon running
      and the reference model pulled, run a real two-turn tool loop behind the
      `ollama` marker and the environment gate, against stub tool functions, and
      record three findings: 1. **Does the integer-or-null union survive the
      compatibility layer?** Send the real `search_vizier` schema and prompt for
      an uncapped query. Record what the model emits for `max_catalogs`: JSON
      null, an omitted key, or the string `"None"`. All three are valid
      *findings*; only a transport-level rejection of the union is a *failure*.
      2. **Are arguments a JSON string or an object?** Assert which one arrives.
      3. **Do parallel tool calls come back in one message?** Prompt for two
      lookups.
- [ ] Write the three findings into the PR description verbatim. **If the
      compatibility layer proves lossy on any of the three, stop and raise it** —
      the documented fallback is Ollama's native chat endpoint, and taking it is
      a design change that belongs in a decision, not a silent implementation
      choice. Do not record an assumption as a finding.
- [ ] Confirm the live test is **deselected**, not run, under a plain
      `uv run pytest`.

**Gate:** a live `qwen3:8b` completes a tool-using loop, and the three findings
are recorded. Default `pytest` still opens no socket.

### Phase 3 — Gemini backend (S4)

The hardest adapter: a different schema dialect, a different message shape, and
**no tool-call identifiers at all**.

- [ ] Build `tools/llm/gemini_backend.py` on the shared HTTP base, to sections
      4.2–4.5. Arguments arrive as a mapping, not a JSON string.
- [ ] Synthetic call ids per section 4.4, with the one-response-per-call
      assertion and the `call_id_mismatch` fault. This is the one place where a
      loud failure is strictly better than a graceful one.
- [ ] `x-goog-api-key` header exclusively. Never the query parameter.
- [ ] Add `GEMINI_API_KEY` to the gitleaks regexes with its two new paths.
      Scoped, not broadened.
- [ ] Run the cross-backend security sweep over all four adapters.

**Gate:** the integer-or-null union reaches Gemini as a nullable integer; a
result-count mismatch raises `call_id_mismatch`; no credential appears in any
URL, all four backends.

### Documentation phase — its own PR

`CLAUDE.md`: *"Keep PRs narrow; separate documentation, workflow, dependency,
and behavior changes."* Docs land last and alone.

- [ ] Update this document: status to phases -1–3 implemented with the date; the
      rollout marked done phase by phase with PR numbers; S8 and S9 marked
      implemented, S3 and S4 implemented and tested, S1/S2/S5/S6/S7 remaining for
      the benchmark phases.
- [ ] Section 11 question 1: change *provisionally resolved* to *resolved* once
      `qwen3:8b` has actually completed a tool loop. If it could not, say which
      model did and why you switched.
- [ ] Section 11 question 2: **paste Phase 2b's three measured findings
      verbatim** and mark it resolved. If the native fallback was taken, say so
      and why. An assumption recorded as a finding is worse than leaving the
      question open. Question 3 stays open — it belongs to the benchmark phases.
      Questions 4 and 5 were resolved at the design gate and are already written;
      do not rewrite them.
- [ ] `docs/tool-architecture.md`: a subsection describing `tools/llm/` — the two
      governing rules, the spec form, the four environment variables, and the
      fact that `complete()` is the only required method.
- [ ] `README.md`: the `KEPLER_MODEL_BACKEND` variable and a one-line example.
      Write it against the entry point that exists **now**; the console that
      replaces it is retired into place by the TUI track's
      Phase G, which updates this line rather than documenting a script that does
      not exist yet.
- [ ] `CLAUDE.md`: extend *Python domain boundaries* with `tools/llm/` — it owns
      the model port and nothing else; adapters never import `tools/registry.py`
      because translation is the caller's job; nothing under `algorithms/`
      imports it.
- [ ] **Verify every claim against the code before writing it.** The one thing
      worse than undocumented behaviour is documentation that was true when
      written and is now quietly wrong — `CLAUDE.md` already carries the scars of
      stale `EXTRACTION.md` references.

### Phases 4–5 — the benchmark harness — **done (2026-09-13)**

Planned, built and landed under [harness.md](../benchmarking/harness.md), which is the
architecture and the sequencing; this table is the index. Their content is
section 6 plus the manifest v2 payload of section 7, and they carried the
remaining security requirements.

| Phase | Content | Outcome |
| --- | --- | --- |
| **4a** | Manifest v2 + the engine wiring | `schema_version: 2`, `backend`, `usage_totals`, per-turn latency/usage/`raw_stop_reason`, the `artifact_subdir` override. `tests/test_runner_session.py` passed unedited. All four adapters confirmed to populate `latency_ms` and `usage`. |
| **4b** | `ReplayBackend` + the transcript format | `tools/llm/replay_backend.py`; exhaustion raises rather than wrapping. Not reachable from `build_backend`. |
| **4c** | The tool plane and fixture store (S5, S6, S7) | `tools/bench/plane.py` classifies all 55 tools; B1 asserts the plane is closed. |
| **4d** | Record mode (S2) | Credential scan refuses the write; third-party prose flagged for review. |
| **5a** | Task loader, run loop, `kepler-bench run` (S5, S6, B2, B4, B5, B7) | The smoke suite runs end to end offline, no socket, in milliseconds. |
| **5b** | The four graders and `grade` | Three kinds of right answer; four fidelity families; three clocks. |
| **5c** | The matrix and `compare` | Headline axes first; no blended score by default. |
| **5d** | The corpus | 16 tasks over five suites. **The 7.1.9 calibration gate is met** (2026-09-14) for every suite but `smoke`, which is exempt — three backends of different tiers, three repeats, 144 sessions; each suite's `calibration.md` records what its run found. |
| ~~**5e**~~ | ~~The judge (S1)~~ | Built, run once over a full sweep, and removed — see `harness.md` 7.5. S1 retired with it. |

**Not done:** the calibration run. A suite is untrusted until it has been run
against at least three backends of different tiers, and that needs credentials
or a local Ollama daemon. Until then the harness is built and tested but its
answer keys are unvalidated against real models.

Phases -1 through 1 are worth landing regardless of whether any non-Anthropic
backend ever ships: they fix a misconfigured secret-scan control, add argument
validation the current loop lacks, and make every future `registry.py` change
visible in all four dialects.

---

## 10. Non-Goals and Deferred Work

* **`tools/claude_photometry_haiku_tool.py` is not migrated *by this document*.**
  It is a separate raw-HTTP Anthropic caller with its own prompt and its own
  result contract, and folding it in would mix a behaviour change into an
  architecture change. **Resolved 2026-09-07:** the TUI track
  Phase C renames it to `tools/photometry_pipeline.py` and deletes its Anthropic
  path and CLI outright rather than migrating them, since the console supersedes
  the entry point. The ~1,000-line photometry and plotting pipeline it wraps is
  kept — registered tools depend on it. Add a module-level note pointing at
  `tools/llm/` when the documentation phase runs.
* **No CLI-agent or MCP backend.** The protocol permits one; nothing builds one.
* **No streaming for non-Anthropic providers.** The capability flag exists and
  the one-shot `on_text` fallback is used.
* **No serving surface.** Section 7 of `docs/tool-architecture.md` stands:
  serving is optional and every tool must remain callable from plain Python. The
  Kepler console is a local interface, not a server — it opens no port, and
  `tools/agent/` imports no UI package, which a test asserts.
* **No changes to algorithm packages.** This work touches `tools/` only. The
  extraction contract is untouched.
* **No composite score by default.**

---

## 11. Open Questions

Reviewed at the implementation design gate, 2026-09-04; questions 1 and 2
closed by the Phase 2b measurement, 2026-09-09.

**1. Which local models are the reference set?** *Resolved.* The plan's
`qwen3:8b` was not available on the implementation host; the Phase 2b
measurement used **`qwen3.8:27b-mlx`** instead — the same qwen3.x
tool-calling tier — and it completed a live tool-using loop. The name is
`OLLAMA_REFERENCE_MODEL` in `tests/test_llm_ollama_backend.py`, a single
constant later work imports. The frontier tier is still chosen when the
benchmark phases land.

**2. Does the Ollama OpenAI-compatibility endpoint faithfully carry union types
and parallel tool calls?** *Resolved by measurement — the layer is faithful,
so the native chat endpoint fallback was NOT taken.* The Phase 2b live loop
against `qwen3.8:27b-mlx` recorded three findings:

> 1. **Union survival:** prompted for an uncapped query against the real
>    `["integer","null"]` `max_catalogs` schema, the model emitted
>    `max_catalogs` as **JSON `null`**. The union reaches the model intact;
>    no transport-level rejection.
> 2. **Argument form:** tool-call `arguments` arrive as a **JSON string** (the
>    OpenAI wire format), parsed by the adapter — not an object.
> 3. **Parallel calls:** prompted for two lookups, **2 tool calls came back in
>    one assistant message**.

None of the three is lossy, so `OllamaBackend` stays a thin `OpenAIBackend`
subclass over `/v1/chat/completions`.

**3. Is the price table maintainable?** *Closed as **not built** (2026-09-13).*
Not "resolved" — the feature was dropped. There is no cost axis, no
`benchmarks/prices.json`, and no `estimated_usd` in the manifest. A price is
not a property of a session: writing one into a durable record freezes a
number that ages badly, and it would make `tools/sessions.py` — infrastructure
every tool run touches — depend on a benchmark data file needing maintenance
forever. The question it answers is one a reader can answer themselves from the
token counts and their own current pricing page. Spending is *bounded* instead,
in tokens: `--max-tokens` is required for any live backend and is checked
before dispatching each turn. See harness.md sections 5.7 and 15.3.

**4. How large should the seed suite be?** *Resolved: eight tasks, one per
confirmed-live failure mode `SYSTEM_PROMPT` already documents.* Smallest suite
that discriminates, and a four-backend sweep stays cheap. It grows from evidence,
not from a target count.

| # | Failure mode | Probes |
| --- | --- | --- |
| 1 | Probing VizieR catalogs one at a time instead of using the category argument | `must_not_call: list_vizier_catalogs` |
| 2 | Re-issuing an identical failing call | duplicate-call rate (`cache_hit_count`) |
| 3 | Passing a colloquial name to NED | argument predicate on `search_ned` |
| 4 | Passing a colloquial name to ATNF (`"Crab"` matches nothing) | argument predicate on `search_atnf` |
| 5 | Reading a period off rendered audio | ordered subsequence over the pulsar chain |
| 6 | Presenting an inline preview as the complete answer | `must_not_match` on the answer |
| 7 | Attributing a figure to a named paper without fetching its abstract | `must_call: get_paper_abstract` |
| 8 | The null-argument probe (`registry.py:339`, `:380`) | null-argument fidelity |

**5. Should trajectory grading tolerate reasonable alternate paths?** *Resolved:
asymmetrically.* Must-not-call and per-argument predicates are hard failures.
Must-call and ordering produce a reported **trajectory deviation** count —
visible in the matrix, not a failure. This grades the documented failure modes
the seed suite is built from, which are all things a model should *not* do,
without punishing a model that reaches a correct answer by a different valid
route. Enumerating accepted alternate trajectories per task was rejected: every
alternate would have to be written by hand, and the suite would age badly as
model strategies change.

---

## 12. References

* `docs/tool-architecture.md` — the master architecture this design sits under.
* `tools/agent/engine.py`, `tools/agent/prompt.py` — where the loop and
  `SYSTEM_PROMPT` live after Phase 0c moved them out of `tools/runner.py`, and
  the source of the seed benchmark tasks. The shim this rollout refactored was
  retired with `kepler-astro-query` once the console replaced both.
* `tools/registry.py:339`, `:380` — the integer-or-null unions.
* `tools/sessions.py` — the manifest this design extends to v2.
* `tools/artifacts.py` — existing path controls and the two gaps S7 keeps
  unreachable.
* `.gitleaks.toml` — the stale allowlist paths fixed in Phase -1.
* `docs/tool-architecture.md` 10.2 — the console that consumes this port, and the
  owner of the engine contract Phase 0c builds against.
