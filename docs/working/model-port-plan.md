# Model Port Implementation Plan (Phases -1 → 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Anthropic-shaped agent loop in `tools/runner.py` with a
provider-neutral model port carrying Anthropic, OpenAI-compatible, Ollama, and
Gemini backends, plus schema translation and pre-dispatch argument validation.

**Architecture:** A `tools/llm/` package owns neutral message/response types and
a `ModelBackend` protocol with one required method, `complete()`. Adapters
translate the neutral history into each provider's dialect on every call and are
stateless. The loop itself moves to `tools/agent/`, which emits typed events as
an iterator; `tools/runner.py` keeps its path and public entry points as a shim
over it, preserving its module-level `TOOL_SCHEMAS`/`TOOL_FUNCTIONS` globals,
gaining one optional `backend=` keyword, and losing every direct reference to the
`anthropic` SDK.

**Tech Stack:** Python 3.14 (project floor: 3.12), `anthropic==0.121.0` (already pinned, kept),
`httpx==0.28.1` (already pinned, used raw for the three new providers),
`pydantic==2.13.4`, `pytest==9.0.3`. **Zero new packages.**

**Spec:** `docs/working/model-backends-and-benchmarking.md` — read sections 1–5 and 8–10
before starting. This plan implements phases **-1 through 3** of that spec's
section 9. Phases 4–5 (manifest v2, fixtures, harness, graders, CLI) are a
separate plan, written after this one lands.

**Status:** Approved; implementation pending.

**Prerequisites:** [model-backends-and-benchmarking.md](model-backends-and-benchmarking.md) is the approved design. No implementation PR must merge first.

**Unblocks:** The headless agent-engine dependency of [tui-harness-plan.md](tui-harness-plan.md). It does not replace the separate stateless optical prerequisite for the TUI.

---

## Global Constraints

Copied from the spec and `CLAUDE.md`. Every task's requirements implicitly
include this section.

- **Zero new dependencies.** No additions to `pyproject.toml`'s `dependencies`
  list, no `uv lock` churn. `jsonschema`, `openai`, `google-generativeai`,
  `litellm` and friends are all forbidden. `httpx==0.28.1` and
  `PyYAML==6.0.3` are already pinned and are the tools for the job.
- **Branch:** `agent/model-backends`, off `main` — at the maintainer's
  instruction. `CLAUDE.md` otherwise defaults to `dev`; do not retarget.
- **One PR per task**, narrow. Documentation, workflow, dependency, and
  behaviour changes stay in separate PRs (`CLAUDE.md`).
- **No linter or formatter is configured.** Match the surrounding file's style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88 column soft wrap.
- **Default checks stay offline and deterministic.** Nothing added by this plan
  may open a socket under a plain `uv run pytest`. Live provider calls sit
  behind a marker plus an environment gate, mirroring the existing `network`
  convention in `pyproject.toml`.
- **`tools/runner.py` must keep its path for the duration of this plan.** CI's
  `repository-shape` job asserts `README.md`, `pyproject.toml`, `uv.lock`,
  `tools/registry.py`, `tools/runner.py`, and `docs/tool-architecture.md` all
  exist. It is deleted later by `tui-harness-plan.md` Task 8, together with the
  workflow change that retires the assertion — not here.
- **No changes to `algorithms/`.** The extraction contract is untouched by this
  work. Do not edit any file carrying an `# EXTRACTED:` or `# PORTED:` marker.
- **Never `verify=False`. Never `follow_redirects=True`.** Always an explicit
  timeout on every `httpx` call. (Spec S3.)
- **Never place a credential in a URL.** Header auth only, all four providers.
  (Spec S4.)
- **The `["integer", "null"]` union is never downgraded** to plain
  `{"type": "integer"}` to make a weak model's life easier. It is the semantic
  that makes uncapped queries possible and the single best benchmark probe in
  the repository. (Spec §4.4.)
- **The string `"None"` is never silently coerced to `None`.** It is rejected
  and recorded as a `stringified_null` fault. (Spec S8.)

### Verification commands

```bash
uv run pytest                             # must be green; offline, no keys
uv run pytest tests/test_runner_session.py -v
python3 -m compileall tools algorithms    # syntax smoke, mirrors CI
git diff --check                          # whitespace
```

### Design refinements this plan makes to the spec

Two places where the spec left a shape underdetermined and this plan settles it.
Both are recorded in Task 2 and Task 11.

1. **`complete()` takes an optional `on_text` callback.** The spec's §4.2
   signature is non-streaming, but `tools/runner.py` prints assistant text as it
   arrives and that behaviour must survive Phase 0. Rather than a second
   required method, `complete()` gains a keyword-only
   `on_text: Callable[[str], None] | None = None`. The Anthropic adapter streams
   natively into it; every other adapter calls it once with the complete text.
   `complete()` remains the only required method, exactly as the spec intends.
2. **`protocol_faults` lands in the manifest in Phase 1, not Phase 4.** Spec S8
   builds validation in Phase 1; a fault that is detected but not recorded is
   half a control. Task 8 adds the `protocol_faults` key additively and leaves
   `SESSION_SCHEMA_VERSION` at `1`. The bump to `2` belongs to the harness plan,
   which adds the rest of the v2 payload at once.

---

## File Structure

**Created by this plan:**

| Path | Responsibility |
| --- | --- |
| `tools/llm/__init__.py` | Re-exports the public surface: neutral types, `ModelBackend`, `build_backend`. |
| `tools/llm/types.py` | Neutral message/content/response dataclasses and the fault taxonomy. No I/O, no provider names. |
| `tools/llm/base.py` | `ModelBackend` protocol, `Capabilities`, and `BaseHTTPBackend` (shared `httpx` client construction, S3/S4 enforcement). |
| `tools/llm/schema.py` | Three pure translation functions, one per dialect. No I/O. |
| `tools/llm/validation.py` | Pre-dispatch argument validation against a tool's own `input_schema`. Hand-rolled; no `jsonschema`. |
| `tools/llm/anthropic_backend.py` | Anthropic SDK adapter. The only adapter that streams natively. |
| `tools/llm/openai_backend.py` | OpenAI Chat Completions over raw `httpx`, and anything compatible. |
| `tools/llm/ollama_backend.py` | Thin `OpenAIBackend` subclass: loopback default, no auth header, `/api/tags` availability probe. |
| `tools/llm/gemini_backend.py` | Gemini `generateContent` over raw `httpx`. Synthetic call ids, uppercase types. |
| `tools/llm/factory.py` | `provider/model` spec parsing and backend construction. Owns the credential/endpoint binding rule (S3). |
| `tests/test_llm_types.py` | Neutral-type invariants. |
| `tests/test_llm_schema.py` | Golden schema translations, all three dialects. |
| `tests/test_llm_validation.py` | S8: every fault type, including `"None"`. |
| `tests/test_llm_anthropic_backend.py` | Anthropic round-trip against captured response samples. |
| `tests/test_llm_openai_backend.py` | OpenAI/Ollama round-trip; S3 and S4 security tests. |
| `tests/test_llm_gemini_backend.py` | Gemini round-trip; synthetic ids, `nullable` rewrite, S4. |
| `tests/test_llm_factory.py` | Spec parsing, credential binding. |
| `tests/fixtures/llm/schemas/{anthropic,openai,openai_strict,gemini}.json` | Committed golden schema renderings. |
| `tests/fixtures/llm/responses/*.json` | Captured provider response samples, hand-written or scrubbed. |

**Modified by this plan:**

| Path | Change |
| --- | --- |
| `.gitleaks.toml` | Task 1: correct two stale allowlist paths, add the five real ones. |
| `tools/runner.py` | Task 5: reduced to a shim over `tools/agent/`. Task 8: validation before dispatch. |
| `tests/test_tool_registry_coverage.py` | Task 5: add `"tools.agent"` to `NOT_TOOL_MODULES`. |
| `tools/sessions.py` | Task 8: `record_fault()` and a `protocol_faults` manifest key. |
| `pyproject.toml` | Task 9: two new pytest markers. **No dependency changes.** |
| `docs/working/model-backends-and-benchmarking.md` | Task 11: status, resolved open questions. |
| `docs/tool-architecture.md`, `README.md`, `CLAUDE.md` | Task 11: describe `tools/llm/`. |

**Also created by this plan (Task 5, per the amendment):** `tools/agent/__init__.py`,
`tools/agent/events.py`, `tools/agent/prompt.py`, `tools/agent/engine.py` — the
headless loop the shim and the TUI both consume.

**Deliberately not touched:** `tools/registry.py` (the schemas are the input to
translation, not a subject of it), `tools/claude_photometry_haiku_tool.py`
(spec §10 defers it; it is renamed and its Anthropic path deleted by
`tui-harness-plan.md` Task 1), anything under `algorithms/`.

---

## Task 1: Fix the stale gitleaks allowlist (Phase -1)

Ships first, alone, ahead of the feature. It fixes an already-misconfigured
control; bundling it with an architecture change would bury it.

**Files:**
- Modify: `.gitleaks.toml:19-20` (the two `kepler/` paths)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. No Python surface.

**Context:** `.gitleaks.toml` allowlists three environment-variable *names* —
`ADS_DEV_KEY`, `ANTHROPIC_API_KEY`, `NASA_API_KEY` — scoped to a path list. Two
entries in that list, `kepler/runner\.py` and `kepler/tools/ads\.py`, name files
that do not exist; the real paths are `tools/runner.py` and `tools/ads.py`. Five
further files mention those names outside any allowlisted path.

**The regexes are not broadened.** A repo-wide name allowlist would suppress
detection of a genuinely leaked `sk-...` value, which is the one thing the
scanner exists to catch. Only paths change. The two new provider key names
(`OPENAI_API_KEY`, `GEMINI_API_KEY`) are **not** added here — they arrive in the
task that first writes them, so each addition is reviewed next to its use.

- [ ] **Step 1: Confirm the misalignment before changing anything**

```bash
ls kepler/ 2>&1                # expect: No such file or directory
ls tools/runner.py tools/ads.py
grep -rln 'ADS_DEV_KEY\|ANTHROPIC_API_KEY\|NASA_API_KEY' \
  --exclude-dir=.git --exclude-dir=.venv .
```

Expected: no `kepler/` directory; both real files present; the grep lists
`AGENTS.md`, `CLAUDE.md`, `tests/test_runner_session.py`, `tools/registry.py`,
`tools/claude_photometry_haiku_tool.py`, `tools/runner.py`, `tools/ads.py` and
the already-allowlisted `README.md`/`docs/`/`.github/workflows/` entries.

Record the actual grep output in the PR description — if it differs from the
above, the allowlist below needs adjusting to match reality, not this plan.

- [ ] **Step 2: Correct the path list**

Replace the `paths` array in `.gitleaks.toml` so every path that genuinely
mentions an allowlisted key name is covered, and no path is a wildcard:

```toml
paths = [
  '''README\.md''',
  '''AGENTS\.md''',
  '''CLAUDE\.md''',
  '''CONTRIBUTING\.md''',
  '''tools/runner\.py''',
  '''tools/ads\.py''',
  '''tools/registry\.py''',
  '''tools/claude_photometry_haiku_tool\.py''',
  '''tests/test_runner_session\.py''',
  '''docs/.*\.md''',
  '''\.github/workflows/.*\.yml''',
]
```

Add a comment above the array recording *why* it is path-scoped: the regexes
match variable names, and scoping is what keeps a real leaked value detectable.

- [ ] **Step 3: Verify the scanner is green and the allowlist actually binds**

```bash
gitleaks detect --config .gitleaks.toml --no-git --redact -v
```

Expected: no findings. If `gitleaks` is not installed locally, push the branch
and read the `secret-scan.yml` workflow result instead — do not skip this step
and do not claim it passed without one of those two outputs in hand.

- [ ] **Step 4: Prove the allowlist is still narrow**

Write a throwaway file at a non-allowlisted path containing a plausible fake
secret assignment, run the scanner, confirm it is **detected**, then delete the
file. This is the check that the fix did not turn into a broadening.

```bash
printf 'ANTHROPIC_API_KEY = "sk-ant-api03-%s"\n' "$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 80)" > /tmp/leak_probe.py
gitleaks detect --config .gitleaks.toml --no-git --redact -v --source /tmp/leak_probe.py
rm -f /tmp/leak_probe.py
```

Expected: a finding is reported for `/tmp/leak_probe.py`. A clean result here
means the allowlist is too broad — stop and narrow it.

- [ ] **Step 5: Commit and open the PR**

```bash
git add .gitleaks.toml
git commit -m "fix(security): correct stale gitleaks allowlist paths

The env-var-name allowlist scoped itself to kepler/runner.py and
kepler/tools/ads.py; neither path exists. The real files are
tools/runner.py and tools/ads.py, and five further files reference the
allowlisted names outside any listed path.

Paths corrected and completed. Regexes deliberately unchanged: they match
variable names, and path scoping is what keeps a genuinely leaked value
detectable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 2: Neutral types and the fault taxonomy (Phase 0a)

**Files:**
- Create: `tools/llm/__init__.py`, `tools/llm/types.py`
- Test: `tests/test_llm_types.py`

**Interfaces:**
- Consumes: nothing.
- Produces — every later task depends on these exact names:

```python
# tools/llm/types.py
StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]

FaultType = Literal[
    "malformed_arguments_json",   # provider's arguments string did not parse
    "schema_violation",           # arguments failed the tool's own input_schema
    "unknown_tool",               # name not in TOOL_FUNCTIONS
    "stringified_null",           # "None"/"null" where JSON null was required
    "call_id_mismatch",           # result count/order did not match the calls
    "empty_tool_call",            # tool_use stop reason with no parsable call
    "truncated_output",           # provider stopped at the token ceiling mid-call
]

@dataclass(frozen=True)
class TextBlock:
    text: str

@dataclass(frozen=True)
class ToolCallBlock:
    call_id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ToolResultBlock:
    call_id: str
    name: str
    content: str
    is_error: bool = False

Block = TextBlock | ToolCallBlock | ToolResultBlock

@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    blocks: tuple[Block, ...]

@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None

@dataclass(frozen=True)
class ProtocolFault:
    type: FaultType
    detail: str
    tool_name: str | None = None
    call_id: str | None = None

@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCallBlock, ...]
    stop_reason: StopReason
    usage: Usage
    latency_ms: int
    raw_stop_reason: str | None = None
    faults: tuple[ProtocolFault, ...] = ()
```

**Design notes the implementer must honour:**

- **The system prompt is not a `Message`.** It is a separate argument
  everywhere. Anthropic takes it top-level, OpenAI as a `system`-role message,
  Gemini as `systemInstruction`; modelling it as a message would force every
  adapter to special-case index 0. There is no `role="system"` in `Message`.
- **Tuples, not lists, in frozen dataclasses.** `list` fields make a `frozen`
  dataclass unhashable-adjacent and silently mutable. The spec's §4.1 sketch
  writes `list`; use `tuple` and let callers pass sequences. This is the one
  deviation from the sketch's literal text and it is deliberate.
- `stop_reason` is the closed normalized set. `raw_stop_reason` preserves the
  provider's own string verbatim so the manifest loses nothing.
- Nothing in this module imports `anthropic`, `httpx`, or any provider name.
  That is testable and is tested below.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_types.py` asserting:

```python
def test_neutral_types_are_frozen():
    block = TextBlock(text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.text = "bye"


def test_message_has_no_system_role():
    # The system prompt is a separate argument, never a message.
    assert "system" not in typing.get_args(Message.__annotations__["role"])


def test_model_response_defaults_are_empty_not_none():
    response = ModelResponse(
        text="", tool_calls=(), stop_reason="end_turn",
        usage=Usage(), latency_ms=0,
    )
    assert response.faults == ()
    assert response.raw_stop_reason is None


def test_types_module_imports_no_provider_sdk():
    source = pathlib.Path("tools/llm/types.py").read_text()
    for forbidden in ("anthropic", "httpx", "openai", "google"):
        assert forbidden not in source
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_llm_types.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'tools.llm'`.

- [ ] **Step 3: Implement `tools/llm/types.py` and `tools/llm/__init__.py`**

Write the dataclasses exactly as specified in the Interfaces block above. Give
the module a docstring explaining that these types are the port's neutral
currency and that adapters translate to and from them on every call.

`tools/llm/__init__.py` re-exports the type names with an `__all__`. Keep it
import-light — no adapter imports at package level, so `import tools.llm` never
costs an `anthropic` or `httpx` import.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_llm_types.py -v && python3 -m compileall tools
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/llm/__init__.py tools/llm/types.py tests/test_llm_types.py
git commit -m "feat(llm): add neutral model-port types and fault taxonomy

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 3: The `ModelBackend` protocol and `Capabilities` (Phase 0a)

**Files:**
- Create: `tools/llm/base.py`
- Test: extend `tests/test_llm_types.py` with a protocol-conformance test

**Interfaces:**
- Consumes: everything from `tools/llm/types.py` (Task 2).
- Produces:

```python
# tools/llm/base.py
SchemaDialect = Literal["json_schema", "openai_function", "gemini_openapi"]

@dataclass(frozen=True)
class Capabilities:
    streaming: bool
    parallel_tool_calls: bool
    native_tool_call_ids: bool      # False for Gemini
    schema_dialect: SchemaDialect
    supports_union_types: bool      # False for Gemini
    max_output_tokens: int

class BackendUnavailableError(RuntimeError):
    """The backend cannot be reached or is not configured."""

@runtime_checkable
class ModelBackend(Protocol):
    spec: str                       # "ollama/llama3.1:8b"
    capabilities: Capabilities

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        system: str,
        max_tokens: int,
        temperature: float = 0.0,
        on_text: Callable[[str], None] | None = None,
    ) -> ModelResponse: ...
```

**`complete()` is the only required method.** `on_text`, when given, receives
assistant text as it becomes available. The Anthropic adapter streams into it;
every other adapter calls it exactly once with the finished text. This is what
lets `tools/runner.py` keep printing text live without a second required method
and without any adapter needing a streaming implementation. Streaming shapes
differ sharply across the four providers, streaming buys nothing for benchmark
determinism, and requiring it would triple adapter size — so it is a capability
flag with a one-shot fallback, per spec §4.2.

`tools` is the **already-translated** dialect payload, not `TOOL_SCHEMAS`.
Translation is the caller's job (Task 6), so adapters stay free of schema logic
and every translation is independently unit-testable.

- [ ] **Step 1: Write the failing test**

```python
def test_capabilities_is_frozen_and_complete():
    caps = Capabilities(
        streaming=False, parallel_tool_calls=True, native_tool_call_ids=True,
        schema_dialect="json_schema", supports_union_types=True,
        max_output_tokens=4096,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.streaming = True


def test_a_minimal_object_satisfies_the_protocol():
    class Stub:
        spec = "stub/model"
        capabilities = Capabilities(
            streaming=False, parallel_tool_calls=False,
            native_tool_call_ids=True, schema_dialect="json_schema",
            supports_union_types=True, max_output_tokens=1024,
        )

        def complete(self, *, messages, tools, system, max_tokens,
                     temperature=0.0, on_text=None):
            return ModelResponse(
                text="ok", tool_calls=(), stop_reason="end_turn",
                usage=Usage(), latency_ms=1,
            )

    assert isinstance(Stub(), ModelBackend)
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_llm_types.py -v
```

Expected: `ImportError` / `ModuleNotFoundError` for `tools.llm.base`.

- [ ] **Step 3: Implement `tools/llm/base.py`**

Define `SchemaDialect`, `Capabilities`, `BackendUnavailableError`, and the
`ModelBackend` protocol as above. Decorate the protocol `@runtime_checkable` so
the conformance test works and so `tools/runner.py` can assert on what it was
handed.

Do **not** add a shared HTTP base class yet — Task 9 introduces
`BaseHTTPBackend` when there are two HTTP adapters to share it. Building it now
would be speculative structure.

- [ ] **Step 4: Run to verify it passes**

```bash
uv run pytest tests/test_llm_types.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tools/llm/base.py tests/test_llm_types.py
git commit -m "feat(llm): add ModelBackend protocol and Capabilities

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 4: The Anthropic adapter (Phase 0b)

**Files:**
- Create: `tools/llm/anthropic_backend.py`
- Test: `tests/test_llm_anthropic_backend.py`
- Test fixture: `tests/fixtures/llm/responses/anthropic_tool_use.json`

**Interfaces:**
- Consumes: `Message`, `ToolCallBlock`, `ToolResultBlock`, `TextBlock`,
  `ModelResponse`, `Usage`, `ProtocolFault` (Task 2); `Capabilities`,
  `ModelBackend`, `BackendUnavailableError` (Task 3).
- Produces:

```python
# tools/llm/anthropic_backend.py
class AnthropicBackend:
    def __init__(self, model: str, *, api_key: str | None = None) -> None: ...
    spec: str            # f"anthropic/{model}"
    capabilities: Capabilities
    def complete(self, *, messages, tools, system, max_tokens,
                 temperature=0.0, on_text=None) -> ModelResponse: ...
```

**Capabilities for this backend:** `streaming=True`,
`parallel_tool_calls=True`, `native_tool_call_ids=True`,
`schema_dialect="json_schema"`, `supports_union_types=True`,
`max_output_tokens=128000` (what `tools/runner.py:241` passes today).

**Behaviour requirements — the implementer chooses how, not whether:**

1. `api_key` defaults to `os.environ["ANTHROPIC_API_KEY"]`. A missing key raises
   `BackendUnavailableError` with a message naming the variable. It must not
   raise at import time and must not raise in `__init__` if a key is passed
   explicitly.
2. The `anthropic` import is **function-local or lazy**, exactly as
   `tools/runner.py:210` does it today, so `import tools.llm` stays cheap and
   the existing test's `sys.modules["anthropic"]` monkeypatch keeps working.
3. `complete()` uses `client.messages.stream(...)` and iterates
   `stream.text_stream`, forwarding each chunk to `on_text` when given, then
   `stream.get_final_message()`. This preserves today's live-printing behaviour
   byte for byte.
4. Message rendering, per spec §4.5: assistant turns become `content` blocks;
   a `ToolResultBlock` becomes a `user` message containing
   `{"type": "tool_result", "tool_use_id": ..., "content": ...}`.
5. `stop_reason` normalization: `end_turn`/`stop_sequence` → `end_turn`,
   `tool_use` → `tool_use`, `max_tokens` → `max_tokens`, `refusal` → `refusal`,
   anything else → `other`. `raw_stop_reason` always carries the original.
6. `latency_ms` is measured with `time.monotonic()` around the API call.
7. `usage` is read from the final message's `usage` when present; every field is
   `None` when absent, never `0`. A fake response object without `usage` must
   not raise — the existing test's `SimpleNamespace` responses have no `usage`
   attribute, and Task 5 depends on that still working.
8. A `tool_use` stop reason whose content yields no `tool_use` block records an
   `empty_tool_call` fault rather than raising.
9. A `max_tokens` stop reason **that arrived with at least one tool call**
   records a `truncated_output` fault: the provider stopped at the ceiling
   mid-call, so the arguments may be incomplete and the trajectory is not
   trustworthy. A `max_tokens` stop with no tool calls is ordinary truncated
   prose and records nothing. This rule is identical in all four adapters —
   implement it once as a shared helper in `tools/llm/types.py` or
   `tools/llm/base.py` rather than four times.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_anthropic_backend.py`. Reuse the fake-SDK shape already
proven in `tests/test_runner_session.py` — a `_FakeStream` with `text_stream`,
`__enter__`/`__exit__`, and `get_final_message()`, injected via
`monkeypatch.setitem(sys.modules, "anthropic", ...)`. Assert:

```python
def test_tool_use_response_becomes_neutral_tool_calls(monkeypatch):
    # final message with one tool_use block -> ModelResponse with one
    # ToolCallBlock carrying id/name/input, stop_reason == "tool_use"

def test_on_text_receives_streamed_chunks_in_order(monkeypatch):
    chunks = []
    ...backend.complete(..., on_text=chunks.append)
    assert chunks == ["Looking up ", "M31."]

def test_tool_result_block_renders_as_user_tool_result(monkeypatch):
    # a Message(role="user", blocks=(ToolResultBlock(...),)) must produce
    # {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ...}]}
    # Inspect the recorded kwargs the fake client captured.

def test_missing_usage_attribute_does_not_raise(monkeypatch):
    # SimpleNamespace(stop_reason="end_turn", content=[]) has no .usage
    assert backend.complete(...).usage.input_tokens is None

def test_unknown_stop_reason_normalizes_to_other_and_keeps_raw(monkeypatch):
    assert response.stop_reason == "other"
    assert response.raw_stop_reason == "some_new_reason"

def test_tool_use_with_no_tool_block_records_empty_tool_call_fault(monkeypatch):
    assert [f.type for f in response.faults] == ["empty_tool_call"]

def test_max_tokens_with_a_partial_tool_call_records_truncated_output(monkeypatch):
    # stop_reason="max_tokens" AND at least one tool_use block present
    assert [f.type for f in response.faults] == ["truncated_output"]

def test_max_tokens_with_no_tool_call_records_nothing(monkeypatch):
    # ordinary truncated prose is not a protocol fault
    assert response.faults == ()

def test_missing_api_key_raises_backend_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BackendUnavailableError):
        AnthropicBackend("claude-sonnet-5").complete(...)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_llm_anthropic_backend.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.llm.anthropic_backend'`.

- [ ] **Step 3: Implement `tools/llm/anthropic_backend.py`**

Satisfy the eight behaviour requirements above. Keep the module under ~150
lines; if it grows past that, the rendering helpers want to be module-level
functions rather than methods.

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_llm_anthropic_backend.py -v && uv run pytest
```

Expected: new tests PASS, **and the whole existing suite still passes** —
nothing has been wired into `tools/runner.py` yet, so a regression here means
an import-time side effect.

- [ ] **Step 5: Commit**

```bash
git add tools/llm/anthropic_backend.py tests/test_llm_anthropic_backend.py
git commit -m "feat(llm): add Anthropic backend adapter

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 5: Move the loop into `tools/agent/` (Phase 0c)

> **AMENDED 2026-09-07.** This task originally refactored the body of `run()` in
> place and preserved `SYSTEM_PROMPT`, `main()`, and the `kepler-astro-query`
> console script. `docs/working/tui-harness-design.md` retires all three, so
> doing that work here would mean rewriting the same function twice. The task now
> **builds `tools/agent/` directly and leaves `tools/runner.py` as a shim.**
>
> **The phase gate is unchanged and still meaningful:**
> `tests/test_runner_session.py` must pass with zero edits — now against the
> shim. If the test needs changing, the extraction changed observable behaviour
> and is wrong.
>
> Everything under "What must not change" below still holds; it is now the
> *shim's* contract rather than `run()`'s. See `tui-harness-design.md` §14.1.

**This is the phase gate.** Spec §4.7:

> **Phase 0 is complete when `tests/test_runner_session.py` passes with zero
> edits to the test file.** If the test needs changing, the refactor changed
> observable behaviour and is wrong.

**Files:**
- Create: `tools/agent/__init__.py`, `tools/agent/events.py`,
  `tools/agent/prompt.py`, `tools/agent/engine.py`
- Modify: `tools/runner.py` (reduced to a shim), `tests/test_tool_registry_coverage.py`
  (add `"tools.agent"` to `NOT_TOOL_MODULES` — `pkgutil.iter_modules` yields
  packages, so the coverage test fails without it)
- Test: `tests/test_runner_session.py` — **read only. Do not edit.**

**Interfaces:**
- Consumes: `AnthropicBackend` (Task 4), neutral types (Task 2),
  `ModelBackend` (Task 3).
- Produces:

```python
# tools/agent/prompt.py — moved verbatim from tools/runner.py:46, not edited
SYSTEM_PROMPT: str

# tools/agent/events.py — the ten frozen event dataclasses and their union.
# Full definitions in docs/working/tui-harness-design.md §4.1.
Event = (SessionStarted | TurnStarted | TextDelta | ToolCallProposed
         | ToolCallStarted | ToolCallFinished | ToolCallDenied
         | ProtocolFault | TurnFinished | SessionFinished)

# tools/agent/engine.py — events out as an iterator, decisions in as a callable
def run_session(
    user_message: str,
    *,
    backend: ModelBackend,
    system: str = SYSTEM_PROMPT,
    max_turns: int = 20,
    approver: Approver = auto_approve,
    session: AgentSession | None = None,
) -> Iterator[Event]: ...

# tools/runner.py — the shim. Same signature as before; prints and returns
# the manifest path by consuming run_session().
def run(
    user_message: str,
    *,
    max_turns: int = 20,
    model: str = "claude-sonnet-5",
    system: str = SYSTEM_PROMPT,
    backend: ModelBackend | None = None,
) -> str | None: ...
```

**`approver` and `auto_approve` are defined in `tools/agent/policy.py`, which
this task does not create** — it is Task 2 of `tui-harness-plan.md`. Until then,
give `run_session` the parameter with a module-level default that returns
"allow", so the signature is stable and the TUI plan only has to supply a real
policy rather than change the contract.

**What must not change:**

- The module path `tools/runner.py` (CI `repository-shape` asserts it). It
  survives this task as a shim and is deleted later, by `tui-harness-plan.md`
  Task 8, alongside the workflow change that retires the assertion.
- `main()` and the `kepler-astro-query` console script — still working at the end
  of this task, so nothing downstream of the port breaks before the TUI exists.
- `SYSTEM_PROMPT` **moves** to `tools/agent/prompt.py` and is re-exported from
  `tools/runner.py` (`from tools.agent.prompt import SYSTEM_PROMPT`) so both
  `runner.SYSTEM_PROMPT` and the default argument keep resolving. Move it
  verbatim: it is ~270 lines of confirmed-live guidance and the source of all
  eight benchmark seed tasks (spec §6.2). Do not reword it while moving it.
- Module-level `TOOL_SCHEMAS` and `TOOL_FUNCTIONS`, **read at call time, not
  import time** — the existing test monkeypatches
  `runner.TOOL_SCHEMAS`/`runner.TOOL_FUNCTIONS` after import and expects the
  loop to see the replacements.
- The printed console output, the call cache, `make_cache_key`, every
  `session.record_tool_call`/`record_turn`/`save` call and its ordering, and the
  `scoped_artifacts` context manager wrapping the whole loop.
- The `except Exception:` handler that saves an `error` manifest and re-raises.
- The missing-key path: `run()` prints the "Set your ANTHROPIC_API_KEY…"
  message and returns `None` rather than raising, when no backend is supplied
  and no key is set.

**What changes:**

- `import anthropic` and the `client = anthropic.Anthropic(...)` construction
  move out of `run()` and into `AnthropicBackend`.
- `messages` becomes `list[Message]` instead of a list of raw SDK dicts.
- The `with client.messages.stream(...)` block becomes
  `backend.complete(messages=..., tools=TOOL_SCHEMAS, system=system,
  max_tokens=128000, on_text=_print_chunk)`.
- `response.content` walking becomes iteration over `response.tool_calls`.
- The `{"role": "assistant", "content": response.content}` append becomes a
  neutral `Message` carrying `TextBlock` + `ToolCallBlock`s; the tool-results
  append becomes a `Message(role="user", blocks=(ToolResultBlock, ...))`.
- `backend=None` constructs `AnthropicBackend(model)`. When a backend **is**
  supplied, `model` is informational only and the backend's own model wins;
  `session.model` still records the `model` argument, because the existing test
  asserts `manifest["model"] == "fake-model"`.

**A note on `tools` at this stage:** Phase 0 passes `TOOL_SCHEMAS` through
unchanged, because the Anthropic dialect *is* the registry's native shape. Task
6 introduces translation and Task 7 switches the runner to
`schema.for_dialect(backend.capabilities.schema_dialect, TOOL_SCHEMAS)`. Do not
try to do both in one task — this one's whole value is that its gate is an
unedited test.

- [ ] **Step 1: Establish the baseline**

```bash
uv run pytest tests/test_runner_session.py -v
git rev-parse HEAD > /tmp/baseline_sha
sha256sum tests/test_runner_session.py
```

Expected: 1 passed. Record the test file's checksum — Step 5 re-checks it.

- [ ] **Step 2: Refactor `run()`**

Rewrite the loop body per "What changes". Extract the per-turn work into a
private helper if it clarifies, but keep `run()`'s signature and return type.

- [ ] **Step 3: Run the gate test**

```bash
uv run pytest tests/test_runner_session.py -v
```

Expected: 1 passed. **If it fails, the refactor is wrong — fix the refactor,
never the test.** The most likely failure modes, in order: the fake response's
`SimpleNamespace` has no `.usage` (Task 4 requirement 7 covers this); the fake
`content` blocks are `SimpleNamespace` not SDK objects, so use duck-typed
`.type`/`.id`/`.name`/`.input` access; `TOOL_SCHEMAS` was captured at import
time instead of read inside `run()`.

- [ ] **Step 4: Run everything**

```bash
uv run pytest && python3 -m compileall tools algorithms && git diff --check
```

- [ ] **Step 5: Prove the test file is untouched**

```bash
git diff --stat HEAD -- tests/test_runner_session.py
```

Expected: **empty output.** Any diff at all means the gate was not met. Paste
this command's output into the PR description.

- [ ] **Step 6: Commit**

```bash
git add tools/runner.py
git commit -m "refactor(runner): drive the agent loop through the model port

The loop no longer imports anthropic or handles SDK content objects; it
builds neutral Message histories and calls ModelBackend.complete(). run()
gains an optional backend= keyword and behaves identically without it.

tests/test_runner_session.py passes unedited, which is the phase gate.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 6: Schema translation, three dialects (Phase 1a)

**Files:**
- Create: `tools/llm/schema.py`
- Test: `tests/test_llm_schema.py`
- Test fixtures: `tests/fixtures/llm/schemas/anthropic.json`,
  `openai.json`, `openai_strict.json`, `gemini.json`

**Interfaces:**
- Consumes: nothing from earlier tasks — this module is pure and standalone.
- Produces:

```python
# tools/llm/schema.py
def to_anthropic(tool_schemas: Sequence[dict]) -> list[dict]: ...
def to_openai(tool_schemas: Sequence[dict], *, strict: bool = False) -> list[dict]: ...
def to_gemini(tool_schemas: Sequence[dict]) -> list[dict]: ...
def for_dialect(dialect: SchemaDialect, tool_schemas: Sequence[dict]) -> list[dict]: ...
```

**No I/O in this module.** Every function is a pure transform, which is what
makes every case a unit test.

**The translation table (spec §4.4):**

| | Anthropic | OpenAI / Ollama | Gemini |
| --- | --- | --- | --- |
| Envelope | `{name, description, input_schema}` | `{type:"function", function:{name, description, parameters}}` | `[{functionDeclarations:[{name, description, parameters}]}]` |
| Types | JSON Schema, lowercase | JSON Schema, lowercase | OpenAPI 3.0 subset, **uppercase** (`STRING`, `INTEGER`, `NUMBER`, `BOOLEAN`, `ARRAY`, `OBJECT`) |
| `["integer","null"]` | pass through | pass through (non-strict) | **rewrite to `{"type": "INTEGER", "nullable": true}`** |
| Unsupported keywords | none | none | drop `additionalProperties`, `$ref`, most `format` |

**Input inventory — verified against `tools/registry.py`, not assumed:** 23
tools; no `anyOf`/`oneOf`/`allOf`/`$ref`/`additionalProperties`; exactly one
`enum` (`search_ned`, line 252); exactly one array-of-string (`search_simbad`,
lines 69–70); exactly two `["integer","null"]` unions (`search_vizier.
max_catalogs` line 339, `search_mast.max_observations` line 380). Every schema
is a flat object. Six tools have no `required` key at all.

**Three requirements the implementer must not negotiate:**

1. **`to_anthropic` is not the identity function.** It must copy, so a caller
   cannot mutate `TOOL_SCHEMAS` through the returned value. Test it.
2. **The union is never downgraded.** `to_gemini` rewrites
   `["integer","null"]` to `{"type": "INTEGER", "nullable": true}` — it never
   emits plain `{"type": "INTEGER"}`. Emitting the plain form would silently
   destroy the uncapped-query semantic `SYSTEM_PROMPT` depends on and would hide
   the exact failure the benchmark exists to measure. **The schema stays
   faithful; a model's failure to use it is a result, not a bug to paper over.**
3. **`strict=True` is implemented but is not the default.** OpenAI strict mode
   requires `additionalProperties: false` and *every* property listed in
   `required`, which would turn optional parameters into mandatory ones — a
   semantic change. Build it, golden-test it, default it off.

- [ ] **Step 1: Write the failing unit tests**

`tests/test_llm_schema.py`, covering each rule in isolation before the goldens:

```python
def test_anthropic_translation_copies_rather_than_aliases():
    out = to_anthropic(TOOL_SCHEMAS)
    out[0]["input_schema"]["properties"].clear()
    assert TOOL_SCHEMAS[0]["input_schema"]["properties"]


def test_openai_envelope_shape():
    out = to_openai(TOOL_SCHEMAS)
    assert out[0]["type"] == "function"
    assert set(out[0]["function"]) == {"name", "description", "parameters"}


def test_openai_non_strict_passes_the_union_through():
    fn = _by_name(to_openai(TOOL_SCHEMAS), "search_vizier")
    assert fn["function"]["parameters"]["properties"]["max_catalogs"]["type"] == [
        "integer", "null",
    ]


def test_openai_strict_requires_every_property():
    fn = _by_name(to_openai(TOOL_SCHEMAS, strict=True), "search_vizier")
    params = fn["function"]["parameters"]
    assert params["additionalProperties"] is False
    assert set(params["required"]) == set(params["properties"])


def test_gemini_uppercases_types():
    decl = _gemini_decl(to_gemini(TOOL_SCHEMAS), "search_atnf")
    assert decl["parameters"]["type"] == "OBJECT"
    assert decl["parameters"]["properties"]["name"]["type"] == "STRING"


def test_gemini_rewrites_the_union_to_nullable():
    decl = _gemini_decl(to_gemini(TOOL_SCHEMAS), "search_vizier")
    prop = decl["parameters"]["properties"]["max_catalogs"]
    assert prop == {
        "type": "INTEGER",
        "nullable": True,
        "description": prop["description"],
    }


def test_gemini_never_emits_a_bare_type_list():
    payload = json.dumps(to_gemini(TOOL_SCHEMAS))
    assert '"type": [' not in payload


def test_gemini_preserves_the_enum_and_the_array_items():
    ned = _gemini_decl(to_gemini(TOOL_SCHEMAS), "search_ned")
    assert ned["parameters"]["properties"]["table"]["enum"]
    simbad = _gemini_decl(to_gemini(TOOL_SCHEMAS), "search_simbad")
    items = simbad["parameters"]["properties"]["fields"]["items"]
    assert items["type"] == "STRING"


def test_for_dialect_dispatches():
    assert for_dialect("json_schema", TOOL_SCHEMAS) == to_anthropic(TOOL_SCHEMAS)
    assert for_dialect("openai_function", TOOL_SCHEMAS) == to_openai(TOOL_SCHEMAS)
    assert for_dialect("gemini_openapi", TOOL_SCHEMAS) == to_gemini(TOOL_SCHEMAS)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_llm_schema.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools.llm.schema'`.

- [ ] **Step 3: Implement `tools/llm/schema.py`**

Deep-copy the input, then transform. Keep each dialect a separate top-level
function; share only a small `_walk` helper if one earns its place.

- [ ] **Step 4: Run to verify the unit tests pass**

```bash
uv run pytest tests/test_llm_schema.py -v
```

- [ ] **Step 5: Add the golden fixtures and their test**

Generate the four renderings, write them to
`tests/fixtures/llm/schemas/`, and add a test asserting byte-stability:

```bash
uv run python -c "
import json, pathlib
from tools.registry import TOOL_SCHEMAS
from tools.llm import schema
out = pathlib.Path('tests/fixtures/llm/schemas'); out.mkdir(parents=True, exist_ok=True)
for name, payload in [
    ('anthropic', schema.to_anthropic(TOOL_SCHEMAS)),
    ('openai', schema.to_openai(TOOL_SCHEMAS)),
    ('openai_strict', schema.to_openai(TOOL_SCHEMAS, strict=True)),
    ('gemini', schema.to_gemini(TOOL_SCHEMAS)),
]:
    (out / f'{name}.json').write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
"
```

```python
@pytest.mark.parametrize(
    "name,render",
    [
        ("anthropic", lambda s: to_anthropic(s)),
        ("openai", lambda s: to_openai(s)),
        ("openai_strict", lambda s: to_openai(s, strict=True)),
        ("gemini", lambda s: to_gemini(s)),
    ],
)
def test_golden_schema_translation_is_byte_stable(name, render):
    expected = json.loads(
        (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    )
    assert render(TOOL_SCHEMAS) == expected
```

**Read the four generated files before committing them.** They are the record
of what every provider sees. This is the check that catches a Gemini rewrite
that quietly dropped a description or flattened an enum.

The point of these goldens: any future change to `tools/registry.py` shows up as
a reviewable diff in every dialect at once — including whether it broke Gemini.
Add a note saying exactly that at the top of `tests/test_llm_schema.py`, with
the regeneration command.

- [ ] **Step 6: Run everything and commit**

```bash
uv run pytest && git diff --check
git add tools/llm/schema.py tests/test_llm_schema.py tests/fixtures/llm/schemas/
git commit -m "feat(llm): translate tool schemas into three provider dialects

Golden renderings of all 23 registry schemas are committed, so a future
registry.py change surfaces as a reviewable diff in every dialect at once.

The [\"integer\",\"null\"] union is rewritten to Gemini's nullable form, never
downgraded to a plain integer: the uncapped-query semantic is load-bearing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 7: Switch the runner to translated schemas (Phase 1a)

Small, but it belongs alone: it is the first commit where a backend's declared
dialect changes what gets sent.

**Files:**
- Modify: `tools/runner.py` (the `tools=` argument to `complete()`)
- Test: `tests/test_runner_session.py` — still read only.

**Interfaces:**
- Consumes: `schema.for_dialect` (Task 6), `backend.capabilities` (Task 3).
- Produces: no new public names.

- [ ] **Step 1: Make the change**

Replace `tools=TOOL_SCHEMAS` with
`tools=schema.for_dialect(backend.capabilities.schema_dialect, TOOL_SCHEMAS)`,
computed **once before the turn loop**, not per turn.

- [ ] **Step 2: Verify the gate test still passes unedited**

```bash
uv run pytest tests/test_runner_session.py -v
git diff --stat HEAD -- tests/test_runner_session.py   # must be empty
```

The existing test monkeypatches `runner.TOOL_SCHEMAS` to a single one-tool list
with an empty `properties` object; `to_anthropic` must handle that without a
`required` key and without properties. If it does not, fix `schema.py`, and add
the empty-properties case to `tests/test_llm_schema.py`.

- [ ] **Step 3: Run everything and commit**

```bash
uv run pytest && python3 -m compileall tools
git add tools/runner.py tests/test_llm_schema.py
git commit -m "feat(runner): render tool schemas into the backend's own dialect

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 8: Argument validation before dispatch (Phase 1b, spec S8)

**The most security-relevant task in this plan.** `tools/runner.py` dispatches
`TOOL_FUNCTIONS[name](**tool_args)` on model-supplied JSON. Today Anthropic's
server-side schema enforcement plus Python signature binding constrains that.
Four backends removes the first half: local models emit unconstrained JSON, and
Gemini's subset cannot express the `["integer","null"]` union at all, so the
adapter's rewrite widens what arrives.

**Files:**
- Create: `tools/llm/validation.py`
- Modify: `tools/runner.py` (validate before dispatch), `tools/sessions.py`
  (record faults)
- Test: `tests/test_llm_validation.py`, and a new
  `tests/test_runner_validation.py`

**Interfaces:**
- Consumes: `ToolCallBlock`, `ProtocolFault`, `FaultType` (Task 2).
- Produces:

```python
# tools/llm/validation.py
def validate_tool_call(
    call: ToolCallBlock,
    schemas_by_name: Mapping[str, dict],
) -> ProtocolFault | None:
    """Return a fault describing why the call is invalid, or None if it is valid."""

def index_schemas(tool_schemas: Sequence[dict]) -> dict[str, dict]:
    """Map tool name -> its input_schema, from registry-shaped schemas."""

# tools/sessions.py
class AgentSession:
    protocol_faults: list[dict[str, Any]]     # new field, defaults to []
    def record_fault(self, *, turn: int, fault: ProtocolFault) -> None: ...
```

**Validation rules, in evaluation order.** Hand-rolled — no `jsonschema`
dependency, and none is needed: all 23 registry schemas are flat objects with
scalar, enum, and array-of-string properties.

| Check | Fault |
| --- | --- |
| Name absent from `schemas_by_name` | `unknown_tool` |
| Arguments are not a `dict` | `schema_violation` |
| A required property is missing | `schema_violation` |
| A property is not in the schema | `schema_violation` |
| Value is `"None"`, `"null"`, `"nil"`, or `"NULL"` (any case) and the property's type list includes `"null"` | `stringified_null` |
| Value's JSON type is not in the property's declared type(s) | `schema_violation` |
| Value not in the property's `enum` | `schema_violation` |
| Array element type mismatch | `schema_violation` |

**Two rules that are the whole point:**

- **`"None"` is never coerced.** Not to `None`, not to anything. It is rejected
  and recorded. Silent coercion of model output is confused-deputy behaviour,
  and here it would also destroy the benchmark's most interesting measurement.
  A `stringified_null` fault on a `null`-accepting property is the highest-value
  signal in the whole taxonomy.
- **A fault is a result returned to the model, not an exception.** The runner
  sends back an error `ToolResult`-shaped payload naming the problem and
  continues the loop. A crashed run measures nothing.

Accept `int` where `number` is declared (JSON has one numeric type and every
provider round-trips `2` as an int). Reject `bool` where `integer` is declared —
Python's `bool` is an `int` subclass and `isinstance(True, int)` is `True`, so
this needs an explicit guard.

- [ ] **Step 1: Write the failing validation tests**

`tests/test_llm_validation.py`, one test per fault, named for the rule:

```python
SCHEMAS = index_schemas(TOOL_SCHEMAS)

def _call(name, **arguments):
    return ToolCallBlock(call_id="c0", name=name, arguments=arguments)


def test_valid_call_returns_none():
    assert validate_tool_call(_call("search_atnf", name="J0534+2200"), SCHEMAS) is None


def test_json_null_is_valid_for_the_union_property():
    call = _call("search_vizier", target="Cas A", category="radio", max_catalogs=None)
    assert validate_tool_call(call, SCHEMAS) is None


def test_string_none_is_a_stringified_null_fault_not_a_coercion():
    call = _call("search_vizier", target="Cas A", max_catalogs="None")
    fault = validate_tool_call(call, SCHEMAS)
    assert fault.type == "stringified_null"
    assert call.arguments["max_catalogs"] == "None"   # untouched, never coerced


@pytest.mark.parametrize("value", ["None", "null", "NULL", "nil", "none"])
def test_every_stringified_null_spelling_is_caught(value):
    call = _call("search_mast", name="M31", max_observations=value)
    assert validate_tool_call(call, SCHEMAS).type == "stringified_null"


def test_unknown_tool_name():
    assert validate_tool_call(_call("search_nothing"), SCHEMAS).type == "unknown_tool"


def test_missing_required_property():
    assert validate_tool_call(_call("search_atnf"), SCHEMAS).type == "schema_violation"


def test_undeclared_property_is_rejected():
    call = _call("search_atnf", name="J0534+2200", __class__="x")
    assert validate_tool_call(call, SCHEMAS).type == "schema_violation"


def test_wrong_scalar_type():
    call = _call("search_atnf", name=42)
    assert validate_tool_call(call, SCHEMAS).type == "schema_violation"


def test_bool_is_not_an_integer():
    call = _call("search_vizier", target="Cas A", max_catalogs=True)
    assert validate_tool_call(call, SCHEMAS).type == "schema_violation"


def test_int_is_accepted_where_number_is_declared():
    call = _call("search_mast", name="M31", radius_arcmin=12)
    assert validate_tool_call(call, SCHEMAS) is None


def test_value_outside_the_enum():
    call = _call("search_ned", name="M31", table="not_a_table")
    assert validate_tool_call(call, SCHEMAS).type == "schema_violation"


def test_array_element_type_mismatch():
    call = _call("search_simbad", name="M31", fields=[1, 2])
    assert validate_tool_call(call, SCHEMAS).type == "schema_violation"
```

Confirm the exact property names against `tools/registry.py` before writing
these — the plan quotes them from a read of the file, but the file is the truth.

- [ ] **Step 2: Run to verify they fail, then implement, then verify they pass**

```bash
uv run pytest tests/test_llm_validation.py -v   # expect ModuleNotFoundError
# implement tools/llm/validation.py
uv run pytest tests/test_llm_validation.py -v   # expect all PASS
```

- [ ] **Step 3: Add `record_fault` to `AgentSession`**

Add a `protocol_faults: list[dict[str, Any]] = field(default_factory=list)`
field, a `record_fault(*, turn, fault)` method appending
`{"turn": turn, "type": fault.type, "detail": fault.detail, "tool_name": ...,
"call_id": ...}`, and a `"protocol_faults"` key in `to_manifest()`.

**Leave `SESSION_SCHEMA_VERSION` at `1`.** The bump to `2` belongs to the
harness plan, which adds the rest of the v2 payload (`backend`, `usage_totals`,
per-turn latency) in one reviewable change. Adding one key additively does not
warrant a version bump on its own, and readers must handle v1 regardless.

- [ ] **Step 4: Wire validation into the runner loop**

In `tools/runner.py`, before the `TOOL_FUNCTIONS.get(tool_name)` dispatch:

1. Call `validate_tool_call(call, _schema_index)` where `_schema_index` is built
   once per `run()` from the call-time `TOOL_SCHEMAS`.
2. On a fault: `session.record_fault(...)`, build the error result payload,
   `session.record_tool_call(...)` it with the real arguments so the trace stays
   honest, append a `ToolResultBlock(is_error=True)`, and **continue the loop**.
   Never dispatch, never raise.
3. On no fault: dispatch exactly as today.
4. Also record any faults the *adapter* attached to `ModelResponse.faults`.

The existing `unknown tool` branch in `run()` becomes dead once validation runs
first. Delete it rather than leaving two code paths that disagree.

- [ ] **Step 5: Write the runner-level test**

`tests/test_runner_validation.py`, following the fake-SDK pattern from
`tests/test_runner_session.py`:

```python
def test_stringified_null_is_recorded_and_the_tool_is_never_called(monkeypatch, tmp_path):
    # A fake backend emits ToolCallBlock(name="fake_lookup",
    # arguments={"limit": "None"}) against a schema declaring
    # {"type": ["integer", "null"]}, then end_turn on the next turn.
    calls = []
    ...
    manifest = json.loads(Path(runner.run(...)).read_text())
    assert calls == []                                    # never dispatched
    assert manifest["protocol_faults"][0]["type"] == "stringified_null"
    assert manifest["tool_calls"][0]["status"] == "error"


def test_a_valid_call_still_dispatches(monkeypatch, tmp_path):
    # regression guard: validation must not reject well-formed calls
```

Use a hand-written stub backend implementing `ModelBackend`, passed via
`run(..., backend=stub)` — that is what the `backend=` keyword is for, and it
removes the need to fake the `anthropic` SDK here.

- [ ] **Step 6: Run everything and commit**

```bash
uv run pytest && python3 -m compileall tools && git diff --check
git diff --stat HEAD -- tests/test_runner_session.py    # still empty
git add tools/llm/validation.py tools/runner.py tools/sessions.py \
        tests/test_llm_validation.py tests/test_runner_validation.py
git commit -m "feat(llm): validate tool arguments against input_schema before dispatch

Closes the gap Anthropic's server-side enforcement used to cover. A schema
violation is a recorded ProtocolFault and an error result returned to the
model, never an exception and never a call.

The string \"None\" is rejected as stringified_null, never coerced to None:
silent coercion of model output is confused-deputy behaviour, and it would
destroy the uncapped-query semantic SYSTEM_PROMPT depends on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 9: OpenAI-compatible backend and the factory (Phase 2a, spec S3/S4)

**Files:**
- Create: `tools/llm/openai_backend.py`, `tools/llm/factory.py`
- Modify: `pyproject.toml` (pytest markers only — **no dependencies**),
  `.gitleaks.toml` (add `OPENAI_API_KEY` scoped to the new paths)
- Test: `tests/test_llm_openai_backend.py`, `tests/test_llm_factory.py`
- Test fixture: `tests/fixtures/llm/responses/openai_tool_call.json`

**Interfaces:**
- Consumes: neutral types (Task 2), `Capabilities`/`BackendUnavailableError`
  (Task 3), `schema.to_openai` (Task 6).
- Produces:

```python
# tools/llm/base.py  (grown in this task)
class BaseHTTPBackend:
    """Shared httpx client construction and the S3/S4 transport rules."""
    def __init__(self, *, base_url: str, api_key: str | None,
                 default_host: str, timeout: float = 120.0) -> None: ...
    def _headers(self) -> dict[str, str]: ...   # subclass supplies auth header
    def _post(self, path: str, payload: dict) -> dict: ...

# tools/llm/openai_backend.py
class OpenAIBackend(BaseHTTPBackend):
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_HOST = "api.openai.com"
    def __init__(self, model: str, *, api_key: str | None = None,
                 base_url: str | None = None) -> None: ...
    spec: str            # f"openai/{model}"
    capabilities: Capabilities
    def complete(self, *, messages, tools, system, max_tokens,
                 temperature=0.0, on_text=None) -> ModelResponse: ...

# tools/llm/factory.py
def parse_spec(spec: str) -> tuple[str, str]:
    """Split 'provider/model' on the FIRST slash only."""

def build_backend(
    spec: str | None = None, *, api_key: str | None = None,
    base_url: str | None = None,
) -> ModelBackend:
    """Construct a backend from a spec, defaulting to $KEPLER_MODEL_BACKEND."""
```

**Capabilities:** `streaming=False`, `parallel_tool_calls=True`,
`native_tool_call_ids=True`, `schema_dialect="openai_function"`,
`supports_union_types=True`, `max_output_tokens=16384`.

**Environment, per spec §4.3.** `build_backend()` resolves in this order and no
other: an explicit argument beats `$OPENAI_BASE_URL`/`$OPENAI_API_KEY`, which
beat the class defaults. `$OPENAI_BASE_URL` is a **non-default base URL for S3
purposes** — setting it in the environment does not pair a credential to it, so
`$OPENAI_API_KEY` alone will not be sent there. Pairing requires both to be set
together, which is exactly the intent S3 encodes: whoever changes the endpoint
must also choose the key that travels to it.

**Spec parsing:** `provider/model`, split on the **first** slash only, because
Ollama model names contain colons and OpenAI-compatible model ids can contain
slashes (`openai/meta-llama/Llama-3-8b` → provider `openai`, model
`meta-llama/Llama-3-8b`). Recognized providers: `anthropic`, `openai`,
`ollama`, `gemini`.

**Message rendering, spec §4.5:** assistant turns carry `tool_calls`; each
`ToolResultBlock` becomes `{"role": "tool", "tool_call_id": ..., "content": ...}`.
The system prompt becomes a leading `{"role": "system", ...}` message.

**Arguments arrive as a JSON string** and must be parsed. A parse failure is a
`malformed_arguments_json` fault attached to `ModelResponse.faults`, with the
call dropped — not an exception.

### The three security rules, each with its test

**S3 — credential is bound to endpoint.** Independently settable endpoint and
credential is a key-exfiltration primitive, and the endpoint is the half that
travels in a shared config or a `--base-url` flag.

- A provider key from the environment is sent **only** to that provider's
  default host. A non-default `base_url` requires an explicitly paired
  `api_key`; without one, no `Authorization` header is sent at all.
- No `Authorization` header over plaintext `http://` **except to loopback**
  (`127.0.0.1`, `::1`, `localhost`).
- `follow_redirects` is set to `False` **explicitly**, even though that is
  httpx's default, so a redirect can never carry an auth header cross-host. Add
  a comment saying so — an explicit default exists to survive a future refactor.

**S4 — no credentials in URLs.** Header auth only. Any base URL recorded
anywhere is scrubbed of `userinfo` first.

**Always an explicit timeout. Never `verify=False`.**

- [ ] **Step 1: Write the failing tests, security cases first**

`tests/test_llm_openai_backend.py`. Use `httpx.MockTransport` — it is part of
the already-pinned `httpx`, needs no new dependency, and lets every assertion
inspect the real outgoing `httpx.Request`.

First, the shared helper the security tests are written against. Define it once,
here; Tasks 10 and 11 import it from this module rather than re-declaring it.

```python
CAPTURED: list[httpx.Request] = []


def _stub_transport(payload: dict | None = None) -> httpx.MockTransport:
    """Record the outgoing request and return a minimal valid response."""

    def handler(request: httpx.Request) -> httpx.Response:
        CAPTURED.append(request)
        return httpx.Response(200, json=payload or _MINIMAL_OPENAI_RESPONSE)

    return httpx.MockTransport(handler)


def _capture(backend, *, payload: dict | None = None) -> httpx.Request:
    """Drive one complete() call through a mock transport, return the request."""
    CAPTURED.clear()
    backend._client = httpx.Client(
        transport=_stub_transport(payload),
        base_url=backend._client.base_url,
        headers=backend._client.headers,
        timeout=backend._client.timeout,
        follow_redirects=False,
    )
    backend.complete(
        messages=[Message(role="user", blocks=(TextBlock(text="hi"),))],
        tools=to_openai(TOOL_SCHEMAS),
        system="You are a test.",
        max_tokens=256,
    )
    return CAPTURED[-1]
```

If swapping `backend._client` like this feels like reaching into a private
attribute — it is, and that is a signal. Prefer giving `BaseHTTPBackend.__init__`
an optional `transport: httpx.BaseTransport | None = None` keyword that the
tests pass and production never does. Decide which, then use it consistently in
Tasks 9, 10, and 11.

Then the security cases:

```python
def test_s3_non_default_base_url_without_paired_key_sends_no_auth_header(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-travel")
    request = _capture(OpenAIBackend("m", base_url="https://evil.example/v1"))
    assert "authorization" not in {k.lower() for k in request.headers}


def test_s3_paired_key_with_non_default_base_url_is_sent():
    request = _capture(
        OpenAIBackend("m", base_url="https://proxy.internal/v1", api_key="sk-paired")
    )
    assert request.headers["authorization"] == "Bearer sk-paired"


def test_s3_no_auth_header_over_plaintext_http_to_a_non_loopback_host():
    with pytest.raises(BackendUnavailableError):
        _capture(OpenAIBackend("m", base_url="http://example.com/v1", api_key="sk-x"))


def test_s3_plaintext_http_to_loopback_is_allowed():
    _capture(OpenAIBackend("m", base_url="http://127.0.0.1:1234/v1", api_key="sk-x"))


def test_s3_follow_redirects_is_false():
    assert OpenAIBackend("m", api_key="k")._client.follow_redirects is False


def test_s3_verify_is_never_disabled():
    source = pathlib.Path("tools/llm").rglob("*.py")
    assert not any("verify=False" in p.read_text() for p in source)


def test_s4_no_credential_appears_in_the_request_url():
    request = _capture(OpenAIBackend("m", api_key="sk-secret-value"))
    assert "sk-secret-value" not in str(request.url)


def test_an_explicit_timeout_is_always_set():
    assert OpenAIBackend("m", api_key="k")._client.timeout.read is not None
```

Then the protocol tests:

```python
def test_tool_call_arguments_json_string_is_parsed()
def test_unparsable_arguments_record_malformed_arguments_json_fault()
def test_tool_result_renders_as_a_tool_role_message()
def test_system_prompt_becomes_a_leading_system_message()
def test_on_text_is_called_once_with_the_whole_text()
def test_finish_reason_tool_calls_normalizes_to_tool_use()
def test_finish_reason_length_normalizes_to_max_tokens()
def test_usage_is_read_from_the_response()
```

And `tests/test_llm_factory.py`:

```python
def test_spec_splits_on_the_first_slash_only():
    assert parse_spec("openai/meta-llama/Llama-3-8b") == (
        "openai", "meta-llama/Llama-3-8b",
    )


def test_ollama_model_names_keep_their_colon():
    assert parse_spec("ollama/llama3.1:8b") == ("ollama", "llama3.1:8b")


def test_unknown_provider_raises_with_the_known_list_in_the_message():
    with pytest.raises(ValueError, match="anthropic"):
        build_backend("acme/model-x")


def test_spec_defaults_to_the_environment(monkeypatch):
    monkeypatch.setenv("KEPLER_MODEL_BACKEND", "openai/gpt-4.1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert build_backend().spec == "openai/gpt-4.1"


def test_a_spec_with_no_slash_is_rejected():
    with pytest.raises(ValueError):
        parse_spec("gpt-4.1")


def test_explicit_base_url_argument_beats_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://from-env.example/v1")
    backend = build_backend(
        "openai/gpt-4.1", base_url="https://explicit.example/v1", api_key="k"
    )
    assert backend._client.base_url.host == "explicit.example"


def test_openai_base_url_from_the_environment_is_treated_as_non_default(monkeypatch):
    # S3: changing the endpoint via the environment does not pair the key to it.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-travel")
    request = _capture(build_backend("openai/gpt-4.1"))
    assert "authorization" not in {k.lower() for k in request.headers}
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_llm_openai_backend.py tests/test_llm_factory.py -v
```

- [ ] **Step 3: Implement `BaseHTTPBackend`, `OpenAIBackend`, and `factory.py`**

`BaseHTTPBackend` owns the transport rules so Tasks 10 and 11 inherit them
rather than re-implementing them. Give it the `verify`/`follow_redirects`/
`timeout` comments explaining *why* each is explicit — a future reader deleting
"redundant" defaults is the failure mode these guard against.

- [ ] **Step 4: Add the pytest markers**

In `pyproject.toml`'s `[tool.pytest.ini_options] markers`, matching the tone of
the existing `network` entry:

```toml
    # Calls a live model provider API. Never runs by default. Requires both
    # `-m model_api` and KEPLER_TEST_MODEL_API=1, plus the provider's key.
    "model_api: hits a live model provider API (opt-in, costs money)",
    # Needs a running Ollama daemon. Skips itself when /api/tags is unreachable.
    "ollama: needs a local Ollama daemon with the reference model pulled",
```

Add `OPENAI_API_KEY` to `.gitleaks.toml`'s `regexes`, and
`tools/llm/openai_backend\.py`, `tools/llm/factory\.py`,
`tests/test_llm_openai_backend\.py`, `tests/test_llm_factory\.py` to its
`paths`. Scoped, not broadened — same rule as Task 1.

- [ ] **Step 5: Run everything and commit**

```bash
uv run pytest && python3 -m compileall tools && git diff --check
git add tools/llm/openai_backend.py tools/llm/factory.py tools/llm/base.py \
        pyproject.toml .gitleaks.toml \
        tests/test_llm_openai_backend.py tests/test_llm_factory.py \
        tests/fixtures/llm/responses/
git commit -m "feat(llm): add OpenAI-compatible backend and the spec factory

Raw httpx, no new dependency. Credentials are bound to their endpoint (S3)
and never travel in a URL (S4); follow_redirects and verify are set
explicitly so a later refactor cannot quietly relax them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 10: Ollama backend and the live compatibility check (Phase 2b)

**Files:**
- Create: `tools/llm/ollama_backend.py`
- Modify: `tools/llm/factory.py` (register the provider),
  `tests/test_llm_openai_backend.py` (Ollama subclass cases)
- Test: `tests/test_llm_ollama_backend.py`

**Interfaces:**
- Consumes: `OpenAIBackend` (Task 9).
- Produces:

```python
class OllamaBackend(OpenAIBackend):
    DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
    DEFAULT_HOST = "127.0.0.1:11434"
    def __init__(self, model: str, *, base_url: str | None = None) -> None: ...
    def is_available(self) -> bool:
        """GET /api/tags; True when the daemon answers."""
```

**A thin subclass, per spec §4.5.** Ollama serves an OpenAI-compatible endpoint
at `/v1/chat/completions`, so the subclass overrides only: the default base URL
(loopback), the auth header (**none — no `Authorization`, ever**), `spec`
(`f"ollama/{model}"`), `capabilities.max_output_tokens`, and it adds
`is_available()`.

`is_available()` probes `/api/tags` (the **native** API path, not `/v1`) and
returns `False` on any connection error. `complete()` raises
`BackendUnavailableError` with a message naming `OLLAMA_BASE_URL` and suggesting
`ollama serve` — a clear failure, never a raw connection traceback.

**Reference model: `qwen3:8b`.** Named in the plan so the acceptance criterion
is knowable before execution: reliable tool calling at 8B, which is the tier the
benchmark most needs to discriminate. Record it as
`OLLAMA_REFERENCE_MODEL = "qwen3:8b"` in the test module so the harness plan can
import one name rather than hard-coding a string in several places.

### Spec §11 Q2 — resolved by measurement, not assumption

> Does the Ollama OpenAI-compatibility endpoint faithfully carry union types and
> parallel tool calls?

The spec assumes yes and requires verification before the native `/api/chat`
fallback is discarded. **Step 4 is that verification.** Its result — whichever
way it goes — gets written into `docs/working/model-backends-and-benchmarking.md` §11 in
Task 12. Do not skip it and do not record an assumption as a finding.

- [ ] **Step 1: Write the offline tests**

```python
def test_ollama_sends_no_authorization_header_even_when_a_key_is_in_the_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-travel")
    request = _capture(OllamaBackend("qwen3:8b"))
    assert "authorization" not in {k.lower() for k in request.headers}


def test_ollama_defaults_to_loopback():
    assert OllamaBackend("qwen3:8b")._client.base_url.host == "127.0.0.1"


def test_spec_is_provider_prefixed():
    assert OllamaBackend("llama3.1:8b").spec == "ollama/llama3.1:8b"


def test_is_available_is_false_when_the_daemon_refuses(monkeypatch):
    # MockTransport raising httpx.ConnectError
    assert OllamaBackend("qwen3:8b").is_available() is False


def test_complete_raises_backend_unavailable_naming_ollama_serve(monkeypatch):
    with pytest.raises(BackendUnavailableError, match="ollama serve"):
        OllamaBackend("qwen3:8b").complete(...)


def test_factory_builds_an_ollama_backend():
    assert isinstance(build_backend("ollama/qwen3:8b"), OllamaBackend)
```

- [ ] **Step 2: Run to verify they fail, implement, verify they pass**

```bash
uv run pytest tests/test_llm_ollama_backend.py -v
```

- [ ] **Step 3: Prepare the live environment**

```bash
ollama serve &                    # daemon is not running by default here
sleep 2
ollama pull qwen3:8b
curl -s http://127.0.0.1:11434/api/tags | head -c 400
```

Expected: `/api/tags` lists `qwen3:8b`.

- [ ] **Step 4: Answer §11 Q2 — the live compatibility probe**

Write `tests/test_llm_ollama_backend.py::test_live_tool_loop`, marked
`@pytest.mark.ollama` and skipping when `is_available()` is `False`, that runs a
real two-turn tool loop through `tools.runner.run(backend=OllamaBackend(...))`
against a stub `TOOL_FUNCTIONS`, and records three specific findings:

1. **Does `["integer","null"]` survive the compatibility layer?** Send
   `search_vizier`'s real schema and prompt for an uncapped query. Record what
   the model emits for `max_catalogs`: JSON `null`, an omitted key, or the
   string `"None"`. All three are valid *findings*; only a transport-level
   rejection of the union is a *failure*.
2. **Are arguments a JSON string or an object?** The native `/api/chat` returns
   an object; the compatibility endpoint is documented to normalize this to a
   string. Assert which one actually arrives.
3. **Do parallel tool calls come back in one message?** Prompt for two lookups.

```bash
KEPLER_TEST_MODEL_API=1 uv run pytest -m ollama tests/test_llm_ollama_backend.py -v -s
```

Write the three findings into the PR description verbatim. **If the
compatibility layer proves lossy on any of the three, stop and raise it** —
the documented fallback is Ollama's native `/api/chat`, and taking it is a
design change that belongs in a decision, not a silent implementation choice.

- [ ] **Step 5: Confirm the default suite is still offline**

```bash
uv run pytest -v | tail -5      # the ollama test must be deselected, not run
uv run pytest --collect-only -q -m "not ollama and not network" | tail -3
```

Expected: the live test does not execute under a plain `uv run pytest`.

- [ ] **Step 6: Commit**

```bash
git add tools/llm/ollama_backend.py tools/llm/factory.py \
        tests/test_llm_ollama_backend.py
git commit -m "feat(llm): add Ollama backend over the OpenAI-compatible endpoint

Thin OpenAIBackend subclass: loopback default, no Authorization header ever,
and an /api/tags probe that degrades to a clear BackendUnavailableError
rather than a connection traceback.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 11: Gemini backend (Phase 3, spec S4)

The hardest adapter: a different schema dialect, a different message shape, and
**no tool-call identifiers at all**.

**Files:**
- Create: `tools/llm/gemini_backend.py`
- Modify: `tools/llm/factory.py`, `.gitleaks.toml` (add `GEMINI_API_KEY`, scoped)
- Test: `tests/test_llm_gemini_backend.py`
- Test fixture: `tests/fixtures/llm/responses/gemini_function_call.json`

**Interfaces:**
- Consumes: `BaseHTTPBackend` (Task 9), `schema.to_gemini` (Task 6).
- Produces:

```python
class GeminiBackend(BaseHTTPBackend):
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_HOST = "generativelanguage.googleapis.com"
    def __init__(self, model: str, *, api_key: str | None = None,
                 base_url: str | None = None) -> None: ...
    spec: str            # f"gemini/{model}"
    capabilities: Capabilities
    def complete(self, *, messages, tools, system, max_tokens,
                 temperature=0.0, on_text=None) -> ModelResponse: ...
```

**Capabilities:** `streaming=False`, `parallel_tool_calls=True`,
`native_tool_call_ids=False`, `schema_dialect="gemini_openapi"`,
**`supports_union_types=False`**, `max_output_tokens=8192`.

**Message rendering, spec §4.5:** assistant turns become `role:"model"` content
with `functionCall` parts; results become `role:"user"` content with
`functionResponse` parts. The system prompt goes in `systemInstruction`, not in
`contents`. Arguments arrive as a `dict`, not a JSON string.

### Synthetic call ids — the correctness-critical part

Gemini emits no call identifiers. The adapter assigns `call_0`, `call_1`, … in
the order the `functionCall` parts appear, and maps results back by name and
position.

**It must assert exactly one `functionResponse` per `functionCall` and raise a
`call_id_mismatch` fault otherwise.** A silent mismatch here would misattribute
a tool result to the wrong call and corrupt a trajectory grade — a wrong number
in a benchmark report with nothing to indicate it is wrong. This is the one
place in the adapter where a loud failure is strictly better than a graceful
one.

### S4 — the header, never the query parameter

Gemini's REST API accepts `?key=`. It must not be used. A key in a URL lands in
proxy logs, in `httpx` exception messages (which include the URL), and in any
manifest recording the request. **`x-goog-api-key` header exclusively.**

- [ ] **Step 1: Write the failing tests**

```python
def test_s4_the_key_is_a_header_and_never_a_query_parameter():
    request = _capture(GeminiBackend("gemini-2.5-pro", api_key="AIza-secret"))
    assert request.headers["x-goog-api-key"] == "AIza-secret"
    assert "AIza-secret" not in str(request.url)
    assert "key=" not in (request.url.query or b"").decode()


def test_s4_all_four_backends_keep_credentials_out_of_urls():
    # parametrized over anthropic (asserted via the SDK's own client kwargs),
    # openai, ollama, gemini


def test_synthetic_call_ids_are_positional():
    response = _complete_with(_two_function_calls())
    assert [c.call_id for c in response.tool_calls] == ["call_0", "call_1"]


def test_results_map_back_by_name_and_position():
    # Two ToolResultBlocks with call_id "call_0"/"call_1" must render as
    # functionResponse parts in that order, each carrying the matching name.


def test_result_count_mismatch_is_a_call_id_mismatch_fault():
    # Three ToolResultBlocks answering two calls
    assert fault.type == "call_id_mismatch"


def test_union_typed_property_reaches_gemini_as_nullable():
    request = _capture(GeminiBackend("gemini-2.5-pro", api_key="k"))
    payload = json.loads(request.content)
    prop = _find_property(payload, "search_vizier", "max_catalogs")
    assert prop == {"type": "INTEGER", "nullable": True, "description": mock.ANY}


def test_system_prompt_goes_to_system_instruction_not_contents():
    payload = json.loads(_capture(...).content)
    assert payload["systemInstruction"]["parts"][0]["text"].startswith("You are")
    assert all(c["role"] != "system" for c in payload["contents"])


def test_assistant_turns_use_the_model_role():
    assert payload["contents"][1]["role"] == "model"


def test_arguments_arrive_as_a_dict_not_a_json_string():
    assert response.tool_calls[0].arguments == {"target": "Cas A"}


def test_finish_reason_normalization():
    # STOP -> end_turn, MAX_TOKENS -> max_tokens, SAFETY -> refusal,
    # anything else -> other, raw preserved
```

- [ ] **Step 2: Run to verify they fail, implement, verify they pass**

```bash
uv run pytest tests/test_llm_gemini_backend.py -v
```

- [ ] **Step 3: Add the allowlist entry**

`GEMINI_API_KEY` to `.gitleaks.toml`'s `regexes`, and
`tools/llm/gemini_backend\.py` plus `tests/test_llm_gemini_backend\.py` to its
`paths`. Scoped, not broadened.

- [ ] **Step 4: Run everything, including the cross-backend security sweep**

```bash
uv run pytest && python3 -m compileall tools && git diff --check
uv run pytest -k "s3_ or s4_" -v      # every security test, all four backends
grep -rn "verify=False\|follow_redirects=True\|key=" tools/llm/
```

Expected: the grep finds nothing but comments explaining why those forms are
avoided.

- [ ] **Step 5: Commit**

```bash
git add tools/llm/gemini_backend.py tools/llm/factory.py .gitleaks.toml \
        tests/test_llm_gemini_backend.py tests/fixtures/llm/responses/
git commit -m "feat(llm): add Gemini backend with synthetic call ids

Gemini emits no tool-call identifiers, so the adapter assigns positional
ids and asserts one functionResponse per functionCall -- a silent mismatch
would misattribute a tool result and corrupt a trajectory grade.

The [\"integer\",\"null\"] union survives as {type: INTEGER, nullable: true};
the key travels in x-goog-api-key, never in the URL (S4).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Task 12: Documentation (its own PR)

`CLAUDE.md`: *"Keep PRs narrow; separate documentation, workflow, dependency,
and behavior changes."* Docs land last and alone.

**Files:**
- Modify: `docs/working/model-backends-and-benchmarking.md`,
  `docs/tool-architecture.md`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything. No code changes in this task.

- [ ] **Step 1: Update the design doc's status and resolved questions**

In `docs/working/model-backends-and-benchmarking.md`:

- Header: `Status: proposed design` → `Status: phases -1--3 implemented; phases
  4--5 pending`, with the date.
- §9 phase table: mark -1 through 3 done, each with its PR number.
- §11: **Q4 and Q5 were resolved at the design gate and are already written
  there — do not rewrite them.** Two entries need your measured results:
  - **Q1** (reference local models): change *provisionally resolved* to
    *resolved* once `qwen3:8b` has actually completed a tool loop in Task 10.
    If it could not, say which model did and why you switched.
  - **Q2** (Ollama compat fidelity): **paste Task 10 Step 4's three measured
    findings verbatim** and mark it resolved. If the native `/api/chat` fallback
    was taken, say so and why. An assumption recorded as a finding here is worse
    than leaving the question open.
  - **Q3** (price table) stays open — it belongs to the harness plan.
- §5: note that S8 and S9 are implemented, S3 and S4 are implemented and tested,
  and S1/S2/S5/S6/S7 remain for the harness plan.
- §4.2: record the `on_text` refinement.

- [ ] **Step 2: Document the port in the architecture docs**

`docs/tool-architecture.md`: a subsection describing `tools/llm/` — the two
governing rules (*the core owns the loop; adapters own the dialect*), the
`provider/model` spec form, the four environment variables, and the fact that
`complete()` is the only required method.

`README.md`: the `KEPLER_MODEL_BACKEND` variable and a one-line example
(`KEPLER_MODEL_BACKEND=ollama/qwen3:8b kepler-astro-query "..."`). That command
is retired by `tui-harness-plan.md` Task 10 in favour of `kepler`; write it as it
stands now and let that task update it, rather than documenting a console script
that does not exist yet.

`CLAUDE.md`: extend the *Python domain boundaries* section with `tools/llm/` —
it owns the model port and nothing else; adapters never import
`tools/registry.py` (translation is the caller's job); nothing under
`algorithms/` imports it.

- [ ] **Step 3: Verify every claim in the docs against the code**

For each statement added, confirm it against the file. The one thing worse than
undocumented behaviour is documentation that was true when written and is now
quietly wrong — `CLAUDE.md` already carries the scars of stale `EXTRACTION.md`
references.

```bash
uv run pytest && python3 -m compileall tools algorithms && git diff --check
```

- [ ] **Step 4: Commit**

```bash
git add docs/ README.md CLAUDE.md
git commit -m "docs: describe the model port and record resolved design questions

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCeUthn9EKVQGevAoMJVir"
```

---

## Phase gates

Each is a hard stop. Do not begin the next phase until its predecessor's gate
produces the stated output.

| Phase | Tasks | Gate |
| --- | --- | --- |
| **-1** | 1 | `gitleaks` clean on the tree **and** a probe file at a non-allowlisted path still detected. |
| **0** | 2–5 | `git diff --stat HEAD -- tests/test_runner_session.py` is **empty** and that test passes. |
| **1** | 6–8 | Four golden dialect renderings committed and byte-stable; `"None"` rejected as `stringified_null` and the tool never dispatched. |
| **2** | 9–10 | A live `qwen3:8b` completes a tool-using loop, and §11 Q2's three findings are recorded. Default `pytest` still opens no socket. |
| **3** | 11 | `["integer","null"]` reaches Gemini as `{"type":"INTEGER","nullable":true}`; a result-count mismatch raises `call_id_mismatch`; no credential in any URL, all four backends. |

## Out of scope for this plan

Deliberately deferred, each to a named place:

- **Phases 4–5** — manifest v2, `ReplayBackend`, the fixture store, the four
  graders, the CLI, and the report. A separate plan, written once this one
  lands and the fault taxonomy is real rather than predicted.
- **`tools/claude_photometry_haiku_tool.py`** — a second, independent raw-HTTP
  Anthropic caller with its own prompt and result contract. Spec §10 defers it;
  add a module-level note pointing at `tools/llm/` when Task 12 runs.
- **CLI-agent and MCP backends** — the protocol permits one; nothing here builds
  one.
- **Streaming for non-Anthropic providers** — the capability flag exists and the
  one-shot `on_text` fallback is used.
- **Any change under `algorithms/`** — the extraction contract is untouched.
