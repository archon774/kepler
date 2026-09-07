# Model Backends and Benchmarking

Date: 2026-09-04
Status: design approved; implementation pending
Prerequisites: None.
Unblocks: [model-port-plan.md](model-port-plan.md) and the model dependency of the [tui-harness-plan.md](tui-harness-plan.md).
Plan: `docs/working/model-port-plan.md` covers phases -1--3
(the model port). Phases 4--5 (the benchmark harness) get their own plan,
written once the port lands and the fault taxonomy is real rather than
predicted.
Branch: `agent/model-backends` (off `main`, at the maintainer's instruction;
`CLAUDE.md` otherwise defaults to `dev`)
Consumed by: `docs/working/tui-harness-design.md` — the Kepler console, which
drives this port through the headless engine in `tools/agent/`. That design
amends this one in two places, both marked inline: §4.7 (the loop moves to
`tools/agent/`; `tools/runner.py` becomes a shim and is later deleted) and §10
(the second Anthropic caller is no longer deferred).

Kepler's agent loop is hardwired to one vendor. This document specifies a
provider-neutral model port that puts Ollama, Anthropic, OpenAI-compatible, and
Gemini backends behind one interface, and a benchmark harness that grades them
against each other on the astronomy tool surface this repository already owns.

Two rules govern the whole design:

> The core owns the loop; adapters own the dialect.

> Replay the tools, never the model.

The first keeps one vendor's quirks out of `tools/runner.py`. The second is what
makes benchmarking honest: the model is the thing under test, so model calls are
live; the astronomy services are not under test, so their results are recorded
fixtures. That also keeps every benchmark run offline with respect to SIMBAD,
NED, VizieR, ADS, MAST, MPC, CASDA, and ATNF, which is what the repository's
"no live remote astronomy service calls in default checks" rule requires.

---

## 1. What Exists Today

Established by reading the code, not assumed.

**`tools/runner.py` is the single integration point, and it is Anthropic-shaped
all the way through.** It imports `anthropic`, reads `ANTHROPIC_API_KEY`, calls
`client.messages.stream(...)`, iterates `stream.text_stream`, branches on
`response.stop_reason in {"end_turn", "tool_use"}`, walks `response.content` for
blocks with `.type == "tool_use"`, and appends **raw SDK content objects** back
into `messages`. The vendor's data model is the loop's data model.

**`tools/registry.py` was 23 tools when this was written and is 48 as of
2026-09-07** — the broken-links phases added the local-data tools. The
portability finding is unchanged and was re-checked at 48. No
`anyOf`, no `oneOf`, no `allOf`, no `$ref`, no `additionalProperties`. One
`enum`, one array-of-string, 23 flat objects. Translating it to three other
schema dialects is tractable — with exactly one exception, below.

**The one landmine.** `search_vizier.max_catalogs` (`tools/registry.py:339`) and
`search_mast.max_observations` (`tools/registry.py:380`) are typed
`{"type": ["integer", "null"]}`, and passing JSON `null` is the *only* way to
request uncapped results. `SYSTEM_PROMPT` spends an entire paragraph on this,
including the confirmed-live failure where a model sends the four-character
string `"None"` instead. This union type is not expressible in Gemini's OpenAPI
subset, constrains OpenAI strict mode, and is exactly the kind of thing small
local models get wrong. It is simultaneously the hardest translation case in the
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

**`tools/artifacts.py` already has the path controls that matter.**
`_safe_stem()` scrubs artifact names to `[A-Za-z0-9_.-]` and `scoped_artifacts()`
rejects absolute and `..` subdirectories. Two gaps exist but are unreachable
today because only tool code sets them: `_write_directory()` joins its `subdir`
argument with no validation, and `reserve_artifact_path()`'s `ext` is only
`lstrip('.')`-ed. Section 5 keeps them unreachable.

**There is a second, independent Anthropic caller.**
`tools/claude_photometry_haiku_tool.py` posts directly to
`https://api.anthropic.com/v1/messages` over `requests`. It is out of scope for
this design and explicitly deferred (section 10), not forgotten.

**No evaluation or benchmarking infrastructure exists.** This is greenfield.

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
The cost is that we own TLS correctness: never `verify=False`, always an
explicit timeout, never `follow_redirects=True` (section 5, S3).

---

## 3. Layout

```text
tools/llm/                    # the model port
  __init__.py
  types.py                    # neutral message / content / response types
  base.py                     # ModelBackend protocol, Capabilities, Usage
  schema.py                   # tool-schema translation, one function per dialect
  factory.py                  # backend spec parsing and construction
  anthropic_backend.py
  openai_backend.py           # OpenAI Chat Completions, and anything compatible
  ollama_backend.py           # thin subclass of the above
  gemini_backend.py
  replay_backend.py           # replays a recorded model transcript; test-only

tools/bench/                  # harness code
  __init__.py
  tasks.py                    # task model and loader
  fixtures.py                 # fixture store, matching, record mode
  graders/
    __init__.py
    trajectory.py
    efficiency.py
    answer.py
    protocol.py
  harness.py                  # run one task against one backend
  report.py                   # aggregate manifests into a comparison matrix
  cli.py

benchmarks/                   # the corpus (data, versioned, reviewed)
  suites/core/*.yaml
  fixtures/*.json
  prices.json
```

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

```python
@dataclass(frozen=True)
class TextBlock:      text: str
@dataclass(frozen=True)
class ToolCallBlock:  call_id: str; name: str; arguments: dict
@dataclass(frozen=True)
class ToolResultBlock: call_id: str; name: str; content: str; is_error: bool = False

@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    blocks: list[TextBlock | ToolCallBlock | ToolResultBlock]

@dataclass(frozen=True)
class Usage:
    input_tokens: int | None; output_tokens: int | None
    cache_read_tokens: int | None = None; cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None

@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: list[ToolCallBlock]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]
    usage: Usage
    latency_ms: int
    raw_stop_reason: str | None      # provider's own string, for the record
    faults: list[ProtocolFault]      # adapter-detected problems, see 4.6
```

The system prompt is **not** a `Message`. It is a separate argument, because
Anthropic takes it as a top-level parameter, OpenAI as a `system`-role message,
and Gemini as `systemInstruction`. Modelling it as a message would force every
adapter to special-case index 0.

`stop_reason` is normalized to a closed set; `raw_stop_reason` preserves the
provider's own string so nothing is lost from the manifest.

### 4.2 The protocol

```python
class ModelBackend(Protocol):
    spec: str                    # "ollama/llama3.1:8b"
    capabilities: Capabilities

    def complete(
        self, *, messages: list[Message], tools: list[dict],
        system: str, max_tokens: int, temperature: float = 0.0,
    ) -> ModelResponse: ...
```

**`complete()` is the only required method, and it is non-streaming.** Streaming
is a capability flag with a default implementation that calls `complete()` and
emits the text in one chunk. This is a deliberate trade: streaming shapes differ
sharply across the four providers, streaming buys nothing for benchmark
determinism, and requiring it would triple adapter size. The Anthropic adapter
still streams natively so interactive `tools.runner` behaviour is unchanged.

```python
@dataclass(frozen=True)
class Capabilities:
    streaming: bool
    parallel_tool_calls: bool
    native_tool_call_ids: bool        # False for Gemini
    schema_dialect: Literal["json_schema", "openai_function", "gemini_openapi"]
    supports_union_types: bool        # False for Gemini
    max_output_tokens: int
```

### 4.3 Backend specs and configuration

Specs are `provider/model`. A slash, not a colon, because Ollama model names
contain colons: `ollama/llama3.1:8b`, `anthropic/claude-opus-5`,
`openai/gpt-4.1`, `gemini/gemini-2.5-pro`.

| Variable | Purpose |
| --- | --- |
| `KEPLER_MODEL_BACKEND` | Default backend spec. |
| `ANTHROPIC_API_KEY` | Existing; unchanged. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI and compatible endpoints. |
| `GEMINI_API_KEY` | Gemini. Header only — never a query parameter (S4). |
| `OLLAMA_BASE_URL` | Defaults to `http://127.0.0.1:11434`. No auth. |

Credential and endpoint are **bound**, not independently settable — see S3.

### 4.4 Schema translation

One pure function per dialect, `translate(tool_schemas) -> list[dict]`, with no
I/O so every case is a unit test.

| | Anthropic | OpenAI / Ollama | Gemini |
| --- | --- | --- | --- |
| Envelope | `{name, description, input_schema}` | `{type:"function", function:{name, description, parameters}}` | `{functionDeclarations:[{name, description, parameters}]}` |
| Types | JSON Schema, lowercase | JSON Schema, lowercase | OpenAPI 3.0 subset, **uppercase** (`STRING`, `INTEGER`, `OBJECT`) |
| `["integer","null"]` | pass through | pass through (non-strict) | **rewrite to `{type:"INTEGER", nullable:true}`** |
| Unsupported keywords | none | none | drop `additionalProperties`, `$ref`, most `format` |
| Call ids | native (`id`) | native (`id`) | **none — adapter synthesizes** |
| Arguments arrive as | `dict` | **JSON string** (must be parsed) | `dict` |

Two consequences worth stating plainly.

**Gemini needs synthetic call ids.** The adapter assigns `call_0`, `call_1`, …
in the order the `functionCall` parts appear, and maps results back by
name-and-position. It asserts exactly one `functionResponse` per `functionCall`
and raises a protocol fault otherwise, because a silent mismatch here would
misattribute a tool result to the wrong call and corrupt a trajectory grade.

**OpenAI strict mode is not used in v1.** Strict mode requires
`additionalProperties: false` and *every* property listed in `required`, which
changes the tool semantics — optional parameters would become mandatory. The
translator gains a `strict=True` variant covered by a golden test, but the
default is non-strict.

**The union type is never downgraded for weak models.** It would be easy to emit
plain `{"type":"integer"}` for Ollama so small models stop choking. That would
silently destroy the uncapped-query semantic the system prompt depends on and
would hide the exact failure the benchmark is built to measure. The schema stays
faithful; the model's failure to use it is a *result*, not a bug to paper over.

### 4.5 Message rendering

The neutral history is rendered per provider on every call. Adapters are
stateless; there is no incremental conversation state to drift.

* **Anthropic** — assistant turns become `content` blocks; `ToolResultBlock`
  becomes a `user` message of `{type:"tool_result", tool_use_id, content}`.
* **OpenAI / Ollama** — assistant turns carry `tool_calls`; each
  `ToolResultBlock` becomes `{role:"tool", tool_call_id, content}`.
* **Gemini** — assistant turns become `role:"model"` content with `functionCall`
  parts; results become `role:"user"` content with `functionResponse` parts.

**Ollama uses the OpenAI-compatible endpoint** (`/v1/chat/completions`), so
`OllamaBackend` is a thin subclass overriding the default base URL, sending no
`Authorization` header, and adding an availability probe against `/api/tags`
that degrades to a clear "backend unavailable" rather than a connection
traceback. Ollama's native `/api/chat` returns tool arguments as an object
rather than a JSON string; the compatibility endpoint normalizes that away. If
the compatibility layer proves lossy in Phase 2, the native endpoint is the
documented fallback.

### 4.6 Protocol faults

A `ProtocolFault` is a typed, recorded observation — never an exception that
kills the run, unless the loop genuinely cannot continue.

| Fault | Meaning |
| --- | --- |
| `malformed_arguments_json` | OpenAI/Ollama `arguments` string did not parse. |
| `schema_violation` | Arguments failed validation against the tool's `input_schema`. |
| `unknown_tool` | Called a name not in `TOOL_FUNCTIONS`. |
| `stringified_null` | Sent `"None"` or `"null"` where JSON `null` was required. |
| `call_id_mismatch` | Result count or ordering did not match the calls. |
| `empty_tool_call` | A tool-use stop reason with no parsable call. |
| `truncated_output` | Provider stopped at the token ceiling mid-call. |

These are what the protocol grader counts. They are also what makes a small
local model's failure legible instead of just "the run crashed."

### 4.7 What does not change

`tools/runner.py` keeps its path — CI's `repository-shape` job asserts the file
exists — its public signature, and its module-level `TOOL_SCHEMAS` and
`TOOL_FUNCTIONS` globals read at call time. `run()` gains one optional keyword:

```python
def run(user_message, *, max_turns=20, model="claude-sonnet-5",
        system=SYSTEM_PROMPT, backend=None) -> str | None
```

With `backend=None` it constructs the Anthropic backend and behaves exactly as
today. `tests/test_runner_session.py` monkeypatches `runner.TOOL_SCHEMAS`,
`runner.TOOL_FUNCTIONS`, and `sys.modules["anthropic"]`, then asserts on the
resulting manifest.

> **Phase 0 is complete when `tests/test_runner_session.py` passes with zero
> edits to the test file.** If the test needs changing, the refactor changed
> observable behaviour and is wrong.

---

## 5. Security Architecture

Nine requirements, from the security review of this design. Each is an
acceptance criterion with a test, not advice. IDs are referenced from the phase
plan in section 9.

### S1 — The judge never sees untrusted content (HIGH)

The optional LLM judge emits a pass/fail verdict. Tool results are arbitrary
third-party text: ADS abstracts and titles, VizieR catalog descriptions, SIMBAD
notes, NED cells. A judge that reads tool results is an oracle taking
instructions from the data it grades — and because fixtures are committed and
replayed, one poisoned capture corrupts the scoreboard permanently and
invisibly.

* The judge receives **only** the task's answer key and the final answer text.
  It never receives tool results, the trajectory, or the system prompt.
* Its output is parsed as a strict structured verdict. Unparseable output is an
  **error**, never a pass.
* The verdict is reported in its own column and is **never** blended into the
  deterministic score.
* Deterministic assertions are primary; the judge is advisory and opt-in.
* Test: a fixture whose text contains an injection string must not change the
  judge's verdict, because it must never reach it.

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

Independently settable endpoint and credential is a key-exfiltration primitive,
and the endpoint is the half that travels in a shared benchmark config or a
`--base-url` flag.

* A provider key is sent only to that provider's default host, or to a base URL
  explicitly paired with its own `--api-key`.
* No `Authorization` header over plaintext `http://` except to loopback.
* `follow_redirects` stays `False` (httpx's default) **explicitly**, so a
  redirect can never carry an auth header cross-host.
* Test: constructing a backend with a non-default base URL and no paired
  credential must not send an `Authorization` header.

### S4 — No credentials in URLs (MEDIUM)

Gemini's REST API accepts `?key=`, which lands in proxy logs, in httpx exception
messages (which include the URL), and in any manifest recording the request.

* Gemini uses the `x-goog-api-key` header exclusively.
* Any recorded base URL is scrubbed of `userinfo` before reaching a manifest.
* Test: assert no adapter places a credential in a URL, for all four backends.

### S5 — `yaml.safe_load`, always (HIGH if wrong)

`PyYAML==6.0.3` is already a dependency. Benchmark suites are exactly the kind
of file people fetch from a colleague or a paper repository and run locally, on
a machine holding four provider API keys.

* Task and suite files load through `yaml.safe_load`. Never `yaml.load`.
* Test: a task file containing `!!python/object/apply:os.system` must raise, not
  execute.

### S6 — Suite and fixture paths are contained (MEDIUM)

A task file referencing `fixtures: ../../../../home/user/.ssh/id_rsa` does not
merely read a file — it reads it **into the model's context** as a tool result,
then into the manifest and the report. A shared suite becomes a local-file
exfiltration primitive against whoever runs it.

* Every task-referenced path resolves against the suite root; anything escaping
  it after resolution is rejected.
* Fixture references are relative-only. Absolute paths are an error.
* Test: traversal and absolute-path fixture references are both rejected.

### S7 — Fixtures carry content, never paths (MEDIUM)

`tools/artifacts.py` scrubs artifact *names* well, but `_write_directory()`
joins `subdir` unvalidated and `reserve_artifact_path()`'s `ext` is only
`lstrip('.')`-ed. Those are safe today only because tool code sets them.

* The replay layer synthesizes artifact paths itself from the task id and tool
  name. A fixture supplies content and never a path, `subdir`, or `ext`.
* Test: a fixture attempting to set `subdir: "../../.ssh"` is rejected, and no
  file is written outside the artifact root.

### S8 — Validate arguments before dispatch (MEDIUM)

`tools/runner.py` dispatches `TOOL_FUNCTIONS[name](**tool_args)` on
model-supplied JSON. Today Anthropic's server-side schema enforcement plus
Python signature binding constrains that. Four backends removes the first half:
local models emit unconstrained JSON, and Gemini's subset cannot express the
`["integer","null"]` union at all, so the adapter's rewrite widens what arrives.

* Every tool call is validated against that tool's own `input_schema` **before**
  dispatch. A violation is a `schema_violation` fault and an error result
  returned to the model — not an exception, and not a call.
* The string `"None"` is **never** silently coerced to `None`. It is rejected
  and recorded as `stringified_null`. Silent coercion of model output is
  confused-deputy behaviour, and here it would also destroy the benchmark's most
  interesting measurement.
* This is the same validation the protocol grader needs, so the control costs
  nothing extra. It is built in Phase 1, before any non-Anthropic backend
  exists.

### S9 — Fix the stale gitleaks allowlist first (LOW-MEDIUM)

Verified: `.gitleaks.toml` scopes its env-var-name allowlist to
`kepler/runner.py` and `kepler/tools/ads.py`. **Both paths are missing** — the
real files are `tools/runner.py` and `tools/ads.py`. Five further files
reference those key names outside any allowlisted path: `AGENTS.md`,
`CLAUDE.md`, `tests/test_runner_session.py`, `tools/registry.py`, and
`tools/claude_photometry_haiku_tool.py`.

`CLAUDE.md` tells contributors to add allowlist entries for new paths, pointing
at a control that is already misaligned. This design adds two more key names.

* Fix the stale **paths**. Do not broaden the regexes: a repo-wide
  `OPENAI_API_KEY` regex allowlist would suppress detection of a genuinely
  leaked `sk-...` value, which is the one thing the scanner exists to catch.
* Ships as its own small PR **ahead** of this work (Phase -1), separate from the
  feature.

### Cost guardrail (not a vulnerability, stated as a design requirement)

A harness looping tasks × models × repeats against paid APIs is a self-inflicted
billing risk, and an injected fixture urging repeated calls makes it
adversarial. Every run carries a spend ceiling and prints a dry-run estimate
before the first live call, alongside the existing `max_turns` bound. Replay
mode makes runaway loops free, which is a second reason it is the default.

---

## 6. Benchmarking

### 6.1 What is measured

Four independent axes, reported as a matrix. **There is no single blended score
by default** — a composite hides which axis failed, and "model A scored 0.72" is
not an actionable result. A weighted composite is available behind an explicit
flag for people who want a leaderboard.

| Axis | Grader | Source |
| --- | --- | --- |
| Trajectory | `trajectory.py` | Manifest `tool_calls` vs. task expectations. |
| Efficiency and cost | `efficiency.py` | Turns, calls, duplicate rate, tokens, latency, estimated USD. |
| Answer correctness | `answer.py` | Deterministic assertions; optional judge. |
| Protocol robustness | `protocol.py` | `ProtocolFault` records. |

### 6.2 Task format

```yaml
id: vizier-uncapped-radio
prompt: "Give me every radio catalog entry VizieR has for Cassiopeia A."
tags: [vizier, uncapped, null-argument]
max_turns: 8
fixtures: fixtures/vizier-uncapped-radio.json
expect:
  trajectory:
    must_call: [search_vizier]
    must_not_call: [list_vizier_catalogs]   # documented failure mode
    arguments:
      - tool: search_vizier
        where:
          category: radio
          max_catalogs: null                # the null probe
  answer:
    must_report_artifact_path: true
    must_match: ['VIII/\d+']
    must_not_match: ['(?i)preview']         # must not present preview as the whole answer
```

Tasks are seeded directly from the failure modes `SYSTEM_PROMPT` already
documents as confirmed-live: probing VizieR catalogs one at a time instead of
using `category=`, re-issuing an identical failing call, passing a colloquial
name to NED or ATNF, reading a period off rendered audio, presenting an inline
preview as the complete answer, and attributing a specific figure to a named
paper without fetching its abstract. Those paragraphs are an eval suite that
has not been written down as one yet.

### 6.3 Fixtures and matching

Fixtures cannot be keyed on exact arguments — different models pass different
radii, row limits, and spellings for the same task, so exact keying would miss
constantly and measure nothing but argument formatting.

```json
{
  "tool": "search_vizier",
  "match": {"target": {"contains": "Cas"}, "category": "radio"},
  "response": { "...recorded ToolResult..." }
}
```

Entries are tried in order, first match wins, with a per-tool `default` entry
and an explicit `miss_policy`:

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

**Trajectory.** Set membership (`must_call`, `must_not_call`), ordered
subsequence for pipelines where order is a real dependency — the pulsar chain in
particular, where folding at a wrong period returns a flat profile rather than
an error — and per-argument predicates. Emits `passed/total` checks with a named
reason per failure.

**Efficiency and cost.** Turns to completion, total tool calls, duplicate-call
rate (already available as `cache_hit_count` in the existing manifest), input
and output tokens, wall-clock per turn, and estimated USD from
`benchmarks/prices.json` — a hand-maintained table carrying a `retrieved_on`
date and an explicit note that it is not fetched. Ollama runs cost zero and
report wall-clock only.

**Answer correctness.** Deterministic first: regex assertions, numeric
comparison with tolerance, and artifact-path presence checks against an answer
key. The optional judge is opt-in, routed through the same model port so it can
be a local Ollama model — free, offline, and consistent with replay. Its model
is pinned in the run config and recorded in the report. Constrained by S1.

**Protocol robustness.** Counts each `ProtocolFault` type. Includes a specific
`null_argument_fidelity` check for `null-argument`-tagged tasks: JSON `null` is
a pass, an omitted argument is a partial (a *different* semantic — capped, not
uncapped), and a string is a fault. This is the single most discriminating check
in the suite for small local models, and it exists because of
`tools/registry.py:339`.

### 6.5 Determinism

Temperature 0 by default; a fixed seed where the provider supports one;
`--repeats k` (default 1) for variance, reporting per-axis spread rather than
only a mean. Every knob — backend spec, temperature, seed, suite revision,
fixture revision, price-table date, judge model — is recorded in the run
manifest. A run that cannot state its inputs is not a benchmark.

### 6.6 CLI

```bash
kepler-bench run --backend ollama/llama3.1:8b --suite core --out artifacts/bench/<run_id>/
kepler-bench run --backend anthropic/claude-opus-5 --suite core --repeats 3
kepler-bench record --task vizier-uncapped-radio      # live, writes a fixture for review
kepler-bench compare <run_id> <run_id> [...]          # the matrix
```

A console script in `pyproject.toml` alongside the existing
`kepler-astro-query`. Reports render as JSON plus Markdown. **If an HTML report
is added later, every model- and fixture-derived string must be escaped** — it
is untrusted text by construction.

---

> **Amended 2026-09-07 by `tui-harness-design.md` §14.1.** The loop described
> above moves to `tools/agent/`, which emits typed events as an iterator and
> takes approval decisions as a callable. `tools/runner.py` keeps its path as a
> shim over that engine — the phase gate is unchanged, the same test must pass
> unedited — and is deleted once the console replaces it. `SYSTEM_PROMPT` moves
> to `tools/agent/prompt.py` verbatim and is re-exported from `tools/runner.py`.

---

## 7. Session Manifest, Schema Version 2

Additive only. Readers must handle v1. `model` stays top-level — the existing
test asserts `manifest["model"] == "fake-model"`.

```jsonc
{
  "schema_version": 2,
  "model": "llama3.1:8b",
  "backend": {
    "spec": "ollama/llama3.1:8b",
    "provider": "ollama",
    "base_url_host": "127.0.0.1:11434",   // scrubbed of userinfo, S4
    "capabilities": { }
  },
  "usage_totals": {"input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0},
  "protocol_faults": [{"turn": 2, "type": "stringified_null", "detail": "..."}],
  "turns": [{"turn": 1, "latency_ms": 0, "usage": { }, "raw_stop_reason": "..."}]
}
```

The existing note that full tool payloads are omitted stays true: manifests
reference artifact paths, they do not embed results.

---

## 8. Testing

Everything below runs in default `pytest` — offline, deterministic, no API keys,
no daemon.

* **Golden schema translations.** `TOOL_SCHEMAS` rendered into all four dialects
  and asserted byte-stable against committed fixtures. Any future change to
  `tools/registry.py` then shows up as a reviewable diff in every dialect at
  once — including whether it broke Gemini.
* **Adapter round-trips.** Neutral history → provider payload → recorded
  provider response → neutral `ModelResponse`, against captured response
  samples. No network.
* **Argument validation (S8).** Schema violations, `"None"`, unknown tools,
  malformed JSON.
* **Graders.** Fed synthetic manifests, including adversarial ones.
* **Harness end-to-end** against `ReplayBackend`, which replays a recorded model
  transcript. Both sides replayed, so the harness itself is CI-testable.
* **Security tests**, one per requirement S1–S8, named for the requirement.

Live provider runs sit behind a new `model_api` marker plus an env gate,
mirroring the existing `network` convention. Ollama tests get an `ollama` marker
and skip when `/api/tags` is unreachable. `pyproject.toml` gains both markers.

CI is unchanged in shape: `compileall`, `pytest`, `repository-shape`. No new
required job, no live calls, no keys in CI.

---

## 9. Phases

One PR each, narrow, in order. Documentation, workflow, dependency, and
behaviour changes stay separated per `CLAUDE.md`.

| Phase | Content | Done when |
| --- | --- | --- |
| **-1** | Fix stale `.gitleaks.toml` paths (S9). | Allowlist paths exist; secret-scan green. |
| **0** | Neutral types, `ModelBackend`, Anthropic adapter, `runner.py` refactor. | **`tests/test_runner_session.py` passes unedited.** |
| **1** | Schema translation, all four dialects, golden fixtures. Argument validation and fault taxonomy (S8). | Golden tests green; `"None"` rejected and recorded. |
| **2** | OpenAI-compatible and Ollama adapters (S3, S4). | A local Ollama model completes a tool-using loop. |
| **3** | Gemini adapter: uppercase types, `nullable` rewrite, synthetic call ids (S4). | `["integer","null"]` survives as `nullable`; id mismatch raises a fault. |
| **4** | Manifest v2, `ReplayBackend`, fixture store and matching (S2, S6, S7). | v1 manifests still readable; traversal rejected. |
| **5** | Harness, four graders, record mode, CLI, report, docs (S1, S5). | Full suite runs offline against `ReplayBackend` in CI. |

Phases -1 through 1 are worth landing regardless of whether any non-Anthropic
backend ever ships: they fix a misconfigured secret-scan control, add argument
validation the current loop lacks, and make every future `registry.py` change
visible in all four dialects.

---

## 10. Non-Goals and Deferred Work

* **`tools/claude_photometry_haiku_tool.py` is not migrated *by this plan*.** It
  is a separate raw-HTTP Anthropic caller with its own prompt and its own result
  contract, and folding it in would mix a behaviour change into an architecture
  change. **Resolved 2026-09-07:** `tui-harness-plan.md` Task 1 renames it to
  `tools/photometry_pipeline.py` and deletes its Anthropic path and CLI outright
  rather than migrating it, since the console supersedes the entry point. The
  ~1,000-line photometry and plotting pipeline it wraps is kept — two registered
  tools depend on it.
* **No CLI-agent or MCP backend.** The protocol permits one; nothing builds one.
* **No streaming for non-Anthropic providers.** Capability flag exists; the
  default fallback is used.
* **No serving surface.** Section 7 of `docs/tool-architecture.md` stands:
  serving is optional and every tool must remain callable from plain Python. The
  Kepler console added by `tui-harness-design.md` is a local interface, not a
  server — it opens no port, and `tools/agent/` imports no UI package, which a
  test asserts.
* **No changes to algorithm packages.** This design touches `tools/` only. The
  extraction contract is untouched.
* **No composite score by default.**

---

## 11. Open Questions

Reviewed at the implementation design gate, 2026-09-04. Two are resolved
outright, one provisionally, and two remain open — each named against the plan
that will close it.

**1. Which local models are the reference set?** *Provisionally resolved.*
`qwen3:8b` is the small tier — reliable tool calling at 8B, which is the tier
the `null` probe most needs to discriminate. It is named once, in
`tests/test_llm_ollama_backend.py::OLLAMA_REFERENCE_MODEL`, so the harness
imports a name rather than a literal. The frontier tier is chosen when the
harness plan lands and there is something to compare against.

**2. Does the Ollama OpenAI-compatibility endpoint faithfully carry union types
and parallel tool calls?** *Open — resolved by measurement.* Model-port plan
Task 10 Step 4 runs a live `qwen3:8b` loop and records three findings: what the
model emits for a union-typed `max_catalogs`, whether arguments arrive as a JSON
string or an object, and whether parallel calls return in one message. If the
compatibility layer proves lossy, the native `/api/chat` endpoint is the
documented fallback and taking it is a decision, not a silent implementation
choice.

**3. Is the price table maintainable?** *Open — belongs to the harness plan.*
A stale `prices.json` produces confident wrong cost numbers. Leaning toward
keeping estimated USD but printing the `retrieved_on` date in every report
header, so a reader can discount a stale figure rather than trust it.

**4. How large should the seed suite be?** *Resolved: eight tasks, one per
confirmed-live failure mode `SYSTEM_PROMPT` already documents.* Smallest suite
that discriminates, and a four-backend sweep stays cheap. It grows from
evidence, not from a target count.

| # | Failure mode | Probes |
| --- | --- | --- |
| 1 | Probing VizieR catalogs one at a time instead of using `category=` | `must_not_call: list_vizier_catalogs` |
| 2 | Re-issuing an identical failing call | duplicate-call rate |
| 3 | Passing a colloquial name to NED | argument predicate on `search_ned` |
| 4 | Passing a colloquial name to ATNF (`"Crab"` matches nothing) | argument predicate on `search_atnf` |
| 5 | Reading a period off rendered audio | ordered subsequence over the pulsar chain |
| 6 | Presenting an inline preview as the complete answer | `must_not_match` on the answer |
| 7 | Attributing a figure to a named paper without fetching its abstract | `must_call: get_paper_abstract` |
| 8 | The `null`-argument probe (`registry.py:339`, `:380`) | `null_argument_fidelity` |

**5. Should trajectory grading tolerate reasonable alternate paths?**
*Resolved: asymmetrically.* `must_not_call` and per-argument predicates are hard
failures. `must_call` and ordering produce a reported **trajectory deviation**
count — visible in the matrix, not a failure. This grades the documented failure
modes the seed suite is built from, which are all things a model should *not*
do, without punishing a model that reaches a correct answer by a different valid
route. Enumerating accepted alternate trajectories per task was rejected: every
alternate would have to be written by hand, and the suite would age badly as
model strategies change.

---

## 12. References

* `docs/tool-architecture.md` — the master architecture this design sits under.
* `tools/runner.py` — the loop being refactored; `SYSTEM_PROMPT` is the source
  of the seed benchmark tasks.
* `tools/registry.py:339`, `:380` — the `["integer","null"]` union.
* `tools/sessions.py` — the manifest this design extends to v2.
* `tools/artifacts.py:53`, `:158`, `:176`, `:186` — existing path controls and
  the two gaps S7 keeps unreachable.
* `.gitleaks.toml` — the stale allowlist paths fixed in Phase -1.
