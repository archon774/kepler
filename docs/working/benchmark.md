# Benchmarking Models on the Kepler Tool Surface

**Status:** **Built and calibrated (2026-09-14).** Every phase of the
section 14 rollout has landed on `agent/model-benchmark`, one commit per phase,
with the full suite green. **§7.1.9's gate is met for every suite but `smoke`**,
which is exempt by construction: three backends of different tiers ran all
sixteen tasks with three repeats each — 144 sessions. Each suite's
`calibration.md` records what its run found, and a test asserts every suite
states a status and names each of its tasks.

What the calibration found is not a clean bill: `fieldcal-offline-solve` is
failed by all three backends, both `optical` tasks are passed by all three and
so discriminate nothing, and five checks were firing on correct answers and had
to be fixed before the numbers meant anything — found by reading the prose with
§11's `answers` verb, not by a second grader. See §14 for the per-phase record
and `benchmark-results.md`, *Reading the answers*, for the sweep.

This is the detailed sequencing [model-backends.md](model-backends.md)
deferred: its section 9 says phases 4–5 "get their own detailed sequencing,
written once the port lands and the fault taxonomy is real rather than
predicted." The port landed on 2026-09-09; the taxonomy is real. This is that
document.
**Date:** 2026-09-13
**Prerequisites:** [model-backends.md](model-backends.md) phases −1–3 —
**met**: `tools/llm/` and `tools/agent/` exist, `tools/runner.py` is a shim,
`validation.py` records faults, and `AgentSession.protocol_faults` persists
them. No optical or TUI phase is a prerequisite.
**Unblocks:** Nothing else in `docs/working/`. This is a leaf track — it
consumes the port and produces a scoreboard.
**Branch:** `agent/model-benchmark`, off `dev`, per the repository default.
**Relationship to [model-backends.md](model-backends.md):** that document's
section 6 stays the *design summary* and its section 9 table stays the phase
index. This document is the architecture and the implementation plan. Where
the two disagree, the divergences are enumerated in section 15 with reasons —
they are not silent.

Kepler owns four model backends, 55 registered tools over 21 modules, a
headless agent loop, a persisted tool-call manifest, and a system prompt that
is already a written record of how models fail on this surface. What it does
not own is any way to answer the question the port was built for: **on this
tool surface, doing this work, which model is actually better, and at what?**

### The two questions

The harness exists to answer two questions about swapping one model for
another on this tool surface, and every axis in section 7 is traceable to one
of them or exists to explain one.

| | Question | Axis | Section |
| --- | --- | --- | --- |
| **Q1** | Does the model change the **quality — the correctness — of the response?** | Answer correctness | 7.1 |
| **Q2** | Does it change **efficiency** — timing per token, turns, tokens used? | Efficiency | 7.2 |

**Q1 is the one that matters**, and it gets the most machinery: section 7.1 is
the longest grader section in this document, because correctness on an
astronomy research surface decomposes into four checkable families
(fabrication, scope inflation, mislabeling, omitted uncertainty) rather than
into a single verdict. Q2 is the price of that correctness, measured in work —
turns taken, tokens spent, and the rate the model produced them at.

Two further axes, **trajectory** (7.3) and **protocol robustness** (7.4), are
diagnostic rather than headline: they do not answer a question of their own,
they explain *why* a model scored as it did on the two that do. A model that
loses Q1 because it never called `get_paper_abstract` and a model that loses it
because it called the right tools and then misreported them are the same number
and different findings; the diagnostic axes are what separate them.

One property of this surface shapes how Q2 is measured, and getting it wrong
produces a confident wrong answer rather than a null result: **Q2 must separate
the model's clock from the tools' clock.** Tool execution dominates wall-clock
here — `run_photometry_on_target` with field calibration is 30-90 s of network,
`compute_pulsar_periodogram` is real compute over a real scan — so an undivided
"time per response" ranks models by *which tools they happened to call*.
Section 7.2 reports three clocks separately and derives timing per token from
one of them.

**Money is not an axis.** No price table ships, no dollar figure is reported,
and `estimated_usd` appears nowhere — see section 15. Spending is *bounded*
rather than measured: section 5.7 is a token budget, a safety control, not a
metric.

Three rules govern the design. The first two are inherited:

> The core owns the loop; adapters own the dialect.

> Replay the tools, never the model.

The third is this document's, and it is the one that makes the harness worth
building rather than merely possible:

> **Replay only what is remote.** Kepler's local pipelines run for real.

The model is under test. The astronomy *services* are not, so they are
recorded and replayed. But Kepler's own algorithms are not under test either —
`tests/` already pins them bit-exact — and replaying them would destroy the
measurement. Folding a pulsar light curve at a wrong period returns a *flat
profile, not an error* (`docs/pulsar-tool-pipeline.md`). That silent failure is
the single richest signal on this surface, and a fixture cannot produce it
without someone deciding in advance what "wrong" looks like. So the pulsar
chain, the optical frame tools, the variable-star fixtures, the recorded
zero-point solves, and the artifact tools all execute their real code against
the repository's own 175 MB of bundled data. They are offline, bounded and
deterministic already. Section 3 classifies all 55 tools and section 5.2 says
how the classification is enforced.

---

## 1. What Exists Today

Established by reading the code on 2026-09-13, not assumed.

**The engine already has the seam the harness needs, and it needs no change to
provide it.** `tools/agent/engine.py::run_session` takes `tool_schemas=` and
`tool_functions=` keywords and defaults them to the live registry read at call
time (`_resolve_registry`). A harness that wants replayed tool results
substitutes the function mapping and changes nothing else. It also accepts a
pre-built `session=`, an `approver=`, and a `backend=`. **Phases 4–5 add no
required argument to `run_session` and do not touch the turn loop** — the only
engine edit in this whole rollout is four lines of manifest-v2 wiring in phase
4a (section 8).

**`tools/sessions.py::AgentSession.to_manifest()` is most of a benchmark
record, and its gaps are precise.** It persists, today: ordered `tool_calls`
with `tool_name`, `arguments`, `cache_key_sha256`, `cache_hit`, `status`,
`count`, `artifacts`, `warnings`, `errors`; a `call_cache` roll-up carrying
`use_count` and `cache_hit_count` per distinct call; `turns` with
`stop_reason` and `tool_call_sequences`; `protocol_faults` turn-stamped with
`type`, `detail`, `tool_name`, `call_id`; `outcome`, `model`, `max_turns`,
`system_prompt_sha256`. It is missing: token counts, per-turn latency, the
backend identity and its capabilities, and — the one that is easy to miss —
**an unbounded final answer**. `_bounded_text` truncates `assistant_text` at
4,000 characters. So model-backends.md's "the benchmark is a reader of session
manifests" is true for four of the five graders and false for the answer
grader, which is why section 5.5 has the harness write `answer.txt` from the
event stream alongside the manifest.

**Per-turn latency and usage exist as types but are unverified end to end.**
`ModelResponse` carries `latency_ms` and `usage`, and `engine.py` already
passes both into the `TurnFinished` event. Whether all four adapters actually
*populate* them was not confirmed when this document was written -- only the
types and the engine's use of them were read. **Phase 4a's first task is to
verify it per adapter**, because Q2 has no data at all if one of them leaves
`latency_ms` at `None`, and a silently absent field would show up as an empty
column rather than as an error.

**Pre-dispatch validation and the fault record are already live.**
`tools/llm/validation.py` runs the S8 rule table before every dispatch;
`engine.py` records the fault, hands the model an error result and continues.
The protocol grader therefore has real data on day one and invents nothing.

**The registry has drifted since the port's Phase 1a inventory, in ways that
matter here.** Phase 1a recorded 49 tools, 8 scalar-or-null unions, **one**
enum and 11 tools with no `required` key. As of today: **55 tools over 21
modules**, still 8 unions (`search_vizier.max_catalogs`,
`search_mast.max_observations`, `plot_field_sed.{radius_arcsec,max_catalogs,
max_field_radius_arcmin}`, `identify_radio_sources.{radius_arcsec,max_catalogs,
max_field_radius_arcmin}`), but **five** enums (`search_ned.table`,
`compute_variable_star_periodogram.variable_star`,
`fold_variable_star_lightcurve.{variable_star,display_periods}`,
`calibrate_zeropoint.catalog_fixture`), 12 tools with no `required`, and 5 with
an empty `properties` object. Six new tools in four days. **Cite tools by
`name.property`, never by `registry.py` line number** — model-backends.md's
`:339`/`:380` citations are already stale. The drift is also the direct
argument for requirement B1 (section 10): a benchmark that silently lets an
unclassified new tool run live is a benchmark that opens a socket mid-run.

**`tests/llm_fakes.py::StubBackend` is ~80% of `ReplayBackend`.** It is a
hand-written `ModelBackend` returning queued `ModelResponse` objects and
forwarding text to `on_text` once. What phase 4b adds is a file-backed
transcript, a `spec`, and a loud exhaustion error.

**`tools/artifacts.py` supplies the write-scoping the harness needs.**
`scoped_artifacts(subdir)` routes every tool's artifact write under a relative
subdirectory and rejects absolute or parent-relative ones; the engine already
wraps the whole session in it. `reserve_artifact_path()` gives the harness a
non-colliding path without writing, which is what S7's "the replay layer
synthesizes artifact paths itself" needs.

**Nothing else exists.** No `tools/bench/`, no `benchmarks/`, no
`kepler-bench`, no `ReplayBackend`, no manifest v2.
That part is greenfield.

---

## 2. Decisions

| Question | Decision |
| --- | --- |
| Where do tool results come from? | Recorded fixtures for remote services; **live execution for Kepler's local pipelines** (section 3). |
| Does the harness change the engine? | No. It substitutes `tool_functions=` and reads the manifest. One additive manifest change in 4a. |
| Is grading coupled to running? | **No.** `run` and `grade` are separate verbs over a run directory, so a grader fix re-grades a past run for free. |
| What is graded? | Four independent axes -- two headline (correctness, efficiency), two diagnostic -- reported as a matrix. No blended score by default. |
| Where does run output go? | Under the artifact root (`artifacts/bench/<run-id>/`), already `.gitignore`d. `benchmarks/` holds inputs only. |
| New dependencies? | **None.** `PyYAML==6.0.3` and `httpx==0.28.1` are pinned already. |
| New CI job? | **No.** The offline end-to-end smoke runs in the default `pytest`. |

### 2.1 Rejected alternatives

**Replaying every tool, including the local ones.** This is what
model-backends.md section 6.3 implies, and it is wrong for this repository. A
fixture for `compute_pulsar_periodogram` means hand-authoring what the
periodogram returns for a period the model chose — so the task author, not the
data, decides whether the model's mistake is visible. The flat-profile failure
mode, the `peak_does_not_fold` warning, the 60 Hz mains artifact at 0.016665 s
and the 2.1–2.2 s red-noise peak are all *real outputs of real code over real
scans*, free and deterministic. Replaying them replaces the measurement with a
guess about the measurement.

**A separate benchmark loop that re-implements the agent turn cycle.**
Rejected for the reason model-backends.md gives for manifests: anything the
runner does should become gradeable. A second loop would drift from the real
one and grade something no user ever runs.

**Grading inside the run loop.** Rejected: it couples a grader bug to a
re-spend. Four paid backends × a suite × repeats is real money, and the first
version of any grader is wrong. `run` produces evidence; `grade` produces
verdicts; `compare` produces the matrix.

**A pass/fail gate in CI over a live model.** Rejected outright. CI stays
offline, deterministic, keyless. The harness's CI presence is an end-to-end
test against `ReplayBackend`, nothing more.

**`jsonschema` for fixture and task validation.** Rejected — zero new
dependencies, and `tools/llm/validation.py` already proves a hand-rolled
checker is enough for these flat schemas.

---

## 3. The Tool Surface Under Test

Kepler's 55 registered tools are not one surface. They are three, and the
harness treats each differently. This classification is data
(`tools/bench/plane.py::TOOL_CLASSES`), it is asserted complete against
`TOOL_FUNCTIONS` by a test (B1), and adding a registry tool without
classifying it is a **test failure**, not a default.

### 3.1 Classification

**Class L — local, deterministic, run live (26 tools).** Offline by
construction; they read the bundled fixture tree and compute.

| Module | Tools |
| --- | --- |
| `tools.pulsar` | `list_pulsar_scans`, `resolve_pulsar_scan`, `load_pulsar_lightcurve`, `compute_pulsar_periodogram`, `fold_pulsar_lightcurve`, `plot_pulsar`, `sonify_pulsar` |
| `tools.variable_star` | `list_variable_star_fixtures`, `resolve_variable_star_fixture`, `load_variable_star_lightcurve`, `compute_variable_star_periodogram`, `fold_variable_star_lightcurve` |
| `tools.optical` | `list_optical_frames`, `resolve_optical_frame` |
| `tools.astrometry` | `describe_image_wcs` |
| `tools.fieldcal_reference` | `list_zeropoint_references`, `load_zeropoint_reference`, `replay_field_calibration`, `compare_zeropoint_to_reference` |
| `tools.catalogs` | `list_photometric_catalogs`, `resolve_reference_band` |
| `tools.calibration` | `solve_zeropoint_from_measurements` |
| `tools.workspace` | `list_artifacts`, `describe_artifact` |
| `tools.photometry` | `list_photometry_targets` |
| `tools.hr_diagram` | `extract_photometry_from_fits` |

**Class R — remote, replayed from fixtures (22 tools).** Every one opens a
socket. None is ever executed by the harness in `run` mode.

| Module | Tools |
| --- | --- |
| `tools.simbad` | `search_simbad`, `search_simbad_measurements`, `search_simbad_bibliography`, `get_paper_abstract` |
| `tools.ads` | `search_ads`, `get_citing_papers`, `get_referenced_papers`, `build_literature_review` |
| `tools.vizier` | `list_vizier_catalogs`, `search_vizier` |
| `tools.ned` | `search_ned` |
| `tools.atnf` | `search_atnf` |
| `tools.mast` | `search_mast` |
| `tools.mpc` | `search_mpc` |
| `tools.casda` | `search_casda` |
| `tools.resolve` | `resolve_target` |
| `tools.radio_sources` | `plot_field_sed`, `identify_radio_sources`, `analyze_source_spectrum` |
| `tools.hr_diagram` | `crossmatch_gaia`, `crossmatch_gaia_by_position`, `get_literature_cluster_params` |

`get_literature_cluster_params` looks local — it returns Cantat-Gaudin &
Anders (2020) parameters — but `algorithms/hrdiagram_py/literature.py` fetches
them through `search_vizier(catalog="J/A+A/640/A1/table1")`. It is class R.
This is exactly the kind of thing a per-module guess gets wrong, which is why
the classification is per *tool* and test-enforced.

**Class M — mixed: local code behind a network-capable argument (7 tools).**
A task must pin the offline path, or the tool is replayed.

| Tool | Offline path | Rule |
| --- | --- | --- |
| `run_photometry_on_target` | `use_field_cal=false` | Live only when the model passes it. Otherwise replayed. |
| `calibrate_zeropoint` | `catalog_fixture="selected_rows"` or `"full_response"` (with `compare_to=`) | Live only when both are present. Otherwise replayed. |
| `solve_astrometry` | needs `ANET_INDEX_PATH`/`ATLAS_CATALOG_ROOT` | **Blocked by default** — the packaged indices do not solve the bundled fixtures (`CLAUDE.md`), and the 4200-series set is an operator asset. Live only under `--enable solve_astrometry`. |
| `select_cluster_members`, `fit_and_compare_hr_diagram` | always local | Class L in practice, but they consume a CSV produced by a class-R crossmatch. Live; their *input* is replayed. |
| `run_full_hr_pipeline`, `run_full_hr_pipeline_from_catalog` | none | Replayed — each wraps a Gaia crossmatch. |

**How class M is decided per call, not per tool.** The dispatcher inspects the
call's arguments against a predicate attached to the classification. This is
the one place the tool plane is argument-sensitive, and it is deliberate:
whether the model *chose* the offline path is itself a graded behaviour
(`run_photometry_on_target`'s `use_field_cal` costs 30–90 s of network time,
and the system prompt tells the model to turn it off when the user only wants
source counts).

### 3.2 What this buys

- **Cheap suites.** The whole pulsar suite costs the model tokens and nothing
  else: no fixture authoring, no fixture review, no staleness.
- **Honest failure.** The flat profile, the `peak_does_not_fold` warning, the
  `listing_truncated` warning, the `ambiguous` error from
  `resolve_optical_frame` when a field was observed in two bands — all arrive
  from the code that produces them in production.
- **A regression tripwire for Kepler itself.** A class-L task whose answer key
  stops matching is either a model getting worse or a tool changing behaviour;
  the manifest says which.

### 3.3 What is out of scope

`solve_astrometry` (asset-gated, see `optical-tools.md` P9),
`tools/claude_photometry_haiku_tool.py` (a second Anthropic caller,
deferred by model-backends.md section 10 and deleted by
the TUI track's phase C), and anything under `algorithms/` — the extraction
contract is untouched by this work.

---

## 4. Layout

| Path | Responsibility |
| --- | --- |
| `tools/bench/__init__.py` | Public surface: `load_suite`, `run_suite`, `grade_run`. Import-light. |
| `tools/bench/tasks.py` | Task and suite loading: `yaml.safe_load` only (S5), path containment (S6), id validation, the `expect` schema. |
| `tools/bench/plane.py` | `TOOL_CLASSES`, the class-M argument predicates, and `build_tool_plane()` — the `{name: callable}` mapping handed to `run_session(tool_functions=...)`. |
| `tools/bench/fixtures.py` | Fixture store: load, match, miss policy, result revalidation (B3), artifact synthesis (S7). |
| `tools/bench/record.py` | Record mode: live capture, credential scan and imperative-string flagging (S2). |
| `tools/bench/harness.py` | The run loop: backend × task × repeat, token budget (B5), run-directory writer. |
| `tools/bench/graders/trajectory.py` | Must-call / must-not-call / ordering / argument predicates. |
| `tools/bench/graders/efficiency.py` | Turns, calls, duplicate rate, tokens, and the three clocks. |
| `tools/bench/graders/answer.py` | Deterministic assertions, and the only thing behind them is recorded evidence. |
| `tools/bench/graders/protocol.py` | Fault counts and `null_argument_fidelity`. |
| `tools/bench/report.py` | Matrix rendering: Markdown and JSON. |
| `tools/bench/answers.py` | The audit verb's reader: the task's prompt beside the model's reply. Offline; consults no model. |
| `tools/bench/cli.py` | `kepler-bench` — `run`, `record`, `grade`, `falsify`, `answers`, `compare`. |
| `tools/bench/sources.py` | Mechanical resolution of an answer key's expected value. No key is ever a hand-typed literal. |
| `tools/bench/falsify.py` | The adversarial pass over the keys themselves. Consults no model; can only accuse. |
| `tools/llm/replay_backend.py` | `ReplayBackend` — replays a recorded model transcript. Test-only. |
| `benchmarks/suites/<suite>/suite.yaml` | Suite manifest: id, description, ordered member task files. |
| `benchmarks/suites/<suite>/<task-id>.yaml` | One task per file — so a corpus diff is reviewable per task. |
| `benchmarks/suites/<suite>/calibration.md` | The 7.1.9 calibration verdicts: which backends the suite was validated against, and what each task discriminated. |
| `benchmarks/fixtures/<tool>.yaml` | Recorded results for one class-R tool. |
| `benchmarks/fixtures/content/<name>.<ext>` | Large recorded artifact bodies, referenced by `content_ref`, never inlined. |
| `benchmarks/transcripts/<name>.json` | Recorded model transcripts for `ReplayBackend`. |
| `artifacts/bench/<run-id>/` | **Output.** Ignored by `.gitignore`'s existing `artifacts/` pattern. |

**`benchmarks/` is top-level, tracked, and inputs only.** Naming it `data/`
would put it in the fixture tree (`CLAUDE.md`: `data/` is deliberately
tracked and deliberately not ignored); putting outputs in it would make every
run a dirty working tree. Code stays under `tools/` so CI's
`compileall tools algorithms tests` keeps covering it with no workflow change.

---

## 5. Architecture

### 5.1 The pipeline

Four stages, each a separate CLI verb over a directory on disk. Every arrow is
a file, so every stage is independently re-runnable and independently
testable.

```
suite + fixtures + backend spec
        │
        │  kepler-bench run           (live model, replayed remote tools,
        ▼                              live local tools)
artifacts/bench/<run-id>/
    run.json                          every knob, recorded
    <backend>/<task>/r<n>/
        session_manifest.json         written by AgentSession, unmodified
        events.jsonl                  the full event stream
        answer.txt                    the final answer, unbounded
        artifacts/                    whatever the tools wrote
        │
        │  kepler-bench grade         (offline, free, repeatable)
        ▼
    grades.json
        │
        │  kepler-bench compare
        ▼
    report.md  report.json            the matrix
```

`record` is the fifth verb and sits outside this flow: it performs live
class-R calls and writes fixture entries for human review.

### 5.2 The tool plane

`build_tool_plane()` returns a mapping covering **every name in
`TOOL_FUNCTIONS`** — not a subset — because `engine.py` passes
`functions.get(call.name)` into `validate_tool_call` as the signature fallback
for empty-`properties` schemas, and a missing name would turn a schema-valid
call into a spurious `unknown_tool` fault. Each entry is one of:

- **the real function**, for class L and for class M when the call's arguments
  pin the offline path;
- **a replay shim**, for class R and unpinned class M;
- **a blocked shim**, for tools the run disables, returning a schema-valid
  error result with code `tool_disabled`.

The replay and blocked shims are built with `functools.wraps(real_function)`,
so `inspect.signature()` follows `__wrapped__` to the real signature and S8's
signature-based fallback keeps working exactly as it does in production. This
is not a nicety: without it, `list_pulsar_scans` and the four other
empty-`properties` tools would stop faulting on junk arguments under replay,
and the protocol grader would report a model as cleaner than it is.

**Resolution is per call, in this order:** disabled by the run → class R →
class M with the offline predicate satisfied → class L → class M unpinned →
(unclassified: impossible, B1).

### 5.3 The fixture store

A fixture file is one class-R tool's recorded results.

```yaml
# benchmarks/fixtures/search_ned.yaml
tool: search_ned
miss_policy: error          # error | synthesize | record
recorded_on: 2026-09-13
entries:
  - id: ngc6334-photometry
    match:
      name: {equals: "NGC 6334"}
      table: {equals: "photometry"}
    response:
      status: ok
      count: 214
      columns: [...]
      preview: [...]                 # ten rows, as the tool returns
      artifact:
        format: ecsv
        row_count: 214
        columns: [...]
        content_ref: ned_ngc6334_photometry.ecsv
  - id: colloquial-name-times-out
    match:
      name: {contains: "cat"}        # case-folded
    response:
      status: error
      errors: [{code: provider_unavailable, message: "..."}]
  - id: default
    match: {}
    response: {status: not_found, count: 0}
```

**Matching is loose on purpose.** Different models pass different radii, row
limits and spellings for the same task; exact-argument keying would miss
constantly and measure nothing but argument formatting. The predicate
vocabulary is deliberately small — `equals`, `contains` (case-folded
substring), `one_of`, `matches` (anchored regex), `present`, `absent`,
`is_null`. Entries are tried in order, first match wins, and a trailing
`{match: {}}` entry is the per-tool default.

**`miss_policy`** is per file, overridable per task:

- `error` (default) — the model gets a tool error with code `fixture_miss` and
  the grade reflects the trajectory that produced it. Honest.
- `synthesize` — a schema-valid empty result of the tool's own return model.
  For tasks where an off-script call should not derail the run.
- `record` — capture mode only.

**Every response is revalidated through the tool's own return model** (B3):
the shim resolves `typing.get_type_hints(real_function)["return"]` and calls
`model_validate()` on the recorded body, trying each member of a union return
(`resolve_pulsar_scan` returns `PulsarScan | PulsarScanList`). A fixture that
has drifted from the model fails at **load**, before a single token is spent —
not at turn 9 of a paid run.

**Artifacts: the fixture carries content, never a path (S7).** A response's
`artifact`/`artifacts` entries carry `format`, `row_count`, `columns` and an
optional `content_ref`. The shim reserves its own path with
`artifacts.reserve_artifact_path(f"{task_id}_{tool_name}", ext=fmt)` inside
the session's `scoped_artifacts` context, copies the `content_ref` body there
if present, and writes the reserved path into the `ArtifactRef`. **A fixture
may not set `path`, `subdir` or `ext`** — the loader rejects all three. This
keeps `_write_directory()`'s unvalidated `subdir` join and
`reserve_artifact_path()`'s loosely-stripped `ext` unreachable, which is the
whole of S7.

Fixture misses are counted per run and printed in the report header. **A suite
with a high miss rate is measuring its own coverage, not the model, and the
report says so** in those words.

### 5.4 `ReplayBackend`

`tools/llm/replay_backend.py` replays a recorded model transcript: a JSON list
of `ModelResponse` payloads (`stop_reason`, `text`, `tool_calls`, `usage`,
`raw_stop_reason`, `faults`). `spec` is `replay/<transcript-name>`;
capabilities are `json_schema`, `streaming=False`, unions supported. It calls
`on_text` once per response, like every non-Anthropic adapter. Running past
the end of the transcript raises `TranscriptExhausted` — loudly, because a
silent wrap-around would make a harness test pass against a loop that never
terminates.

It lives under `tools/llm/` (where model-backends.md's layout table already
reserves its path), not `tools/bench/`, because it is a `ModelBackend` and the
factory may eventually build one. It is never reachable from
`build_backend()`'s recognized providers.

### 5.5 The run record

Per `(backend, task, repeat)` the harness writes:

- **`session_manifest.json`** — `AgentSession`'s own file, unmodified. The
  harness sets `AgentSession.artifact_subdir` (see section 8) so the session's
  artifacts land inside the run directory rather than under
  `artifacts/sessions/<id>/`, which is what makes `must_report_artifact_path`
  checkable against files that are still there when grading runs.
- **`events.jsonl`** — every event, one JSON object per line, in order. This is
  the only record of `ToolCallDenied` and of per-chunk text timing.
- **`answer.txt`** — accumulated `TextDelta` text from the **final** turn,
  unbounded. Necessary because the manifest bounds `assistant_text` at 4,000
  characters and `must_not_match` assertions on a long answer would otherwise
  be evaluated against a truncated one.
- **`error.txt`** — present only when the session raised.

And once per run, **`run.json`**: run id, UTC start/end, backend specs with
capabilities, suite id and the SHA-256 of every task file, fixture file
SHA-256s, `KEPLER_*` environment overrides in force, temperature, seed,
repeats, `max_turns`, the token budget, the host, the `git rev-parse HEAD` of
the repository and whether `benchmarks/` was dirty at launch. **A run that cannot state its inputs is not a benchmark** — the
harness refuses to start if it cannot read the corpus hashes, and stamps
`corpus_dirty: true` (surfaced in the report header) rather than silently
grading against uncommitted tasks.

### 5.6 Determinism and repeats

Temperature 0 by default; a provider seed where one exists, recorded when it
does not. `--repeats N` (default 1) re-runs each task; the report shows
per-axis spread, not only a mean, because a model that passes a trajectory
check two times in three is a different finding from one that passes it always.
Repeats share nothing: a fresh `AgentSession`, a fresh call cache, a fresh
artifact subdirectory.

`ReplayBackend` runs are bit-deterministic end to end, which is what makes the
harness itself CI-testable — both sides replayed.

### 5.7 The token budget (B5)

Four backends × a suite × repeats against metered APIs is a self-inflicted
billing risk, and a fixture urging repeated calls makes it adversarial. The
harness bounds that, but it bounds it **in tokens, not in dollars** — tokens
are recorded by the port already, need no price table to interpret, and do not
go stale. What a token costs is the operator's business and the operator's
pricing page; what the harness owes them is a hard stop.

- `--max-tokens` is **required** for any non-replay backend. There is no
  default, because a default budget is a number nobody thinks about.
- Before the first live call the harness prints a dry-run ceiling: tasks ×
  repeats × `max_turns` × the per-turn output ceiling, as an upper bound on
  what the run can consume.
- The budget is checked **before dispatching each turn**, against the running
  total, not after. Crossing it ends the run with outcome `budget_exceeded`,
  the partial results kept and clearly marked partial.
- `ReplayBackend` runs are exempt. Ollama runs are not: a local daemon costs no
  money but a runaway loop still costs hours.

---

## 6. Task Format

One task per file. Loaded with `yaml.safe_load` and nothing else (S5).

```yaml
id: ned-formal-designation           # ^[a-z0-9][a-z0-9_-]{0,63}$
title: NED needs a formal catalog designation
tags: [trajectory, name-resolution, core]
prompt: >
  Get me NED's photometry for the Cat's Paw Nebula.
# No max_turns. The cap is *derived* from the task's own declared requirement
# (tasks.derive_turn_cap) and a task file that sets one fails to load: the only
# evidence for choosing a cap is a transcript, so a hand-set cap is fitted to
# whoever produced that transcript. It is a loop-breaker, never a measurement
# parameter -- a run that reaches it is incomplete, not failed.
fixtures: [search_simbad, search_ned]   # relative names under the fixture root
miss_policy: error                      # optional per-task override
env:                                    # optional; KEPLER_* only (B7)
  KEPLER_MAX_FRAMES: "5"
enable: []                              # opt-in for blocked tools, e.g. solve_astrometry

expect:
  trajectory:
    must_call: [search_ned]             # absence => deviation, not failure
    must_not_call: []                   # any call => hard failure
    order: []                           # ordered subsequence; violation => deviation
    arguments:                          # hard failures
      - tool: search_ned
        quantifier: all                 # all | any  (default: all)
        where:
          name: {matches: "^(NGC|IC|M|PGC|UGC)\\s*\\d+"}
        because: >
          NED's resolver is unreliable with colloquial names; the system
          prompt requires translating to a formal designation first.
  answer:
    must_match: []
    must_not_match: []
    must_report_artifact_path: true
    must_report_value: []               # [{name, expected, rel_tol, unit}]
    conditional: []                     # guarded must_not_match
    must_reach_verdict: []              # [{tool, field, equals, because}] — see 7.1.3
    must_disclose: []                   # [{when_warning, must_match, because}]
    must_label: []                      # [{value_pattern, near, within_chars, because}]
    must_state_uncertainty: []          # [{field, must_match | must_not_match, because}]
    must_source_value: []               # promote a pattern from flag to failure
  protocol:
    null_argument_fidelity: []          # [{tool: search_vizier, property: max_catalogs}]
```

`must_reach_verdict` is the ground-truth key (7.1.3): it reads a boolean a
Kepler tool computed against recorded truth, so no phrasing can pass or fail
it. The four keys after it are the fidelity families of 7.1.4 —
`must_disclose` for scope inflation, `must_label` for mislabeling,
`must_state_uncertainty` for omitted uncertainty, `must_source_value` for
fabrication. All four are **conditional on what the tools actually returned**:
the check fires only if the warning, the null field, or the number was
genuinely present this session, so they do not punish a model that reached the
answer by a different valid route.

Section 7.1.6 ranks all of them by robustness. **Reach for the top of that
table first** — a task leaning on `must_match` is a task that may be grading
prose style, and 7.1.9 is the gate that catches it.

**`must_report_value`** asserts a number, and **never a hand-typed one**. The
check names the mechanical source its expectation comes from and the loader
resolves it (`tools/bench/sources.py`):

```yaml
- name: period_s
  source: {dataset: pulsar/curated_periods.json, path: pulsars.b0329.period_s}
  rel_tol: 0.02
  unit: s
```

Three source kinds, all model-independent: `fixture` (a field of the recorded
archive response), `dataset` (a field of a repository data file — independent
ground truth that predates this benchmark, resolved against the repository's
own `data/` tree rather than `KEPLER_DATA_DIR`), and `tool_result` (the value a
deterministic Kepler tool returned on the run being graded — the fidelity
case). A literal `expected:` fails to load.

The last kind is not circular: it reads the return value of repository code
whose behaviour the preservation suite pins, not a model's prose. The model
picks the arguments — that is the trajectory axis — but cannot change what the
tool computes from them. **Weighing an answer against a tool's output is
fidelity; weighing it against another model's output would be an opinion poll,
and nothing here does that.**

The grader extracts numeric literals from the answer with a bounded regex and
passes if at least one lies within tolerance. This is the pulsar suite's
workhorse — a period is the one thing on this surface with an unambiguous right
answer.

**`must_report_artifact_path`** is checked against the manifest, not against a
regex: the answer must contain, verbatim, a path that appears in some
`tool_calls[].artifacts[].path`. A model that invents a plausible-looking path
fails, which a regex over `/artifacts/.*\.ecsv` would not catch.

**`conditional`** exists for one real failure mode the flat form cannot
express — attributing a specific figure to a named paper without fetching its
abstract:

```yaml
conditional:
  - when_not_called: [get_paper_abstract, search_ads, build_literature_review]
    answer_must_not_match: "\\d+(\\.\\d+)?\\s*%\\s*/\\s*yr"
    because: >
      Quoting a decline rate with no abstract-returning call means the figure
      came from training data. Confirmed live; see SYSTEM_PROMPT, SOURCING.
```

A third guard form, **`when_no_result`**, reads what a tool *returned* rather
than what was called, using the shared fixture predicate vocabulary:

```yaml
conditional:
  - when_no_result:
      tool: search_ned
      where:
        status: {equals: ok}
    answer_must_not_match: "\\b(?:photometric|photometry) (?:table|measurements) (?:shows?|gives?|lists?)"
```

**Reach for it whenever the rationale is about an outcome.** `no-identical-retry`
guarded "a photometry table cannot be reported when no call returned one" on
*`search_simbad` not being called*, while its own trajectory rule accepts the
formal designation "from the model's own knowledge **or** via `search_simbad`".
A model taking the first, sanctioned route had the guard opened against it for
doing the right thing, and escaped only because the forbidden pattern is narrow
enough to miss ordinary phrasing. A guard on a proxy call says something
different from what it means.

**`because` is required on every hard-failure check.** It is printed verbatim
in the report next to the failure, so a scoreboard entry explains itself
without anyone opening the suite file. Untested convention elsewhere; here it
is enforced by the loader.

### 6.1 Loader rules

- `yaml.safe_load` only (S5). A Python-object construction tag raises.
- `fixtures:` entries are **bare names**, resolved as
  `<fixture-root>/<name>.yaml`. Anything containing a path separator, a `..`
  segment, or an absolute prefix is rejected before resolution; the resolved
  path is then re-checked for containment under the fixture root with
  `tools.config.within` (S6). Same for `content_ref`.
- `env:` keys must match `^KEPLER_[A-Z0-9_]+$` (B7). A task can shrink
  `KEPLER_MAX_FRAMES` to exercise the truncation warning; it cannot set
  `ANTHROPIC_API_KEY`, `OPENAI_BASE_URL`, or `PATH`.
- `id` must match `^[a-z0-9][a-z0-9_-]{0,63}$` — it becomes an artifact
  subdirectory name, and `scoped_artifacts` will reject anything else anyway.
  Reject early, with a better message.
- Unknown top-level keys are an error, not ignored. A typo in `must_not_call`
  that silently grades nothing is worse than a load failure.

---

## 7. The Graders

Each grader is a pure function from `(task, manifest, answer_text, events)` to
a result record. No I/O beyond reading the run directory; no model calls except
nothing else.

Two of the four answer a question (7.1, 7.2); two are diagnostic (7.3, 7.4)
and exist to explain a headline number rather than to compete with it.

### 7.1 Answer correctness — **Q1**

This is the question the harness exists for, and the one where "what is a right
answer" needs a real answer rather than a gesture at one. It gets seven
subsections because on this surface there are **three different kinds of right
answer**, they are checked by different machinery, and conflating them is how a
benchmark ends up measuring phrasing.

#### 7.1.1 The controlled experiment

Every model is asked **the same fixed set of questions**, and everything except
the model is held constant:

| Held constant | Why it matters |
| --- | --- |
| The prompt text, verbatim | 9.1 gives all eight core prompts in full; no per-model rewording |
| `SYSTEM_PROMPT`, unmodified | we are testing *swap the model into Kepler as it ships*, not each model at its best |
| The tool registry and its 55 schemas | same world, same affordances |
| The fixture set and its `miss_policy` | same archive responses, same failures |
| `max_turns`, temperature 0, seed where available | same budget, same determinism |
| The bundled data | the same five scans, 39 frames, four recorded solves |

**Exactly one thing varies besides the model: the schema dialect.** Anthropic
gets JSON Schema, OpenAI and Ollama get the function wrapper, Gemini gets the
uppercase OpenAPI subset with the scalar-or-null union rewritten to a nullable
scalar. That is **not** a confound to be eliminated — it is part of what is
being tested, because a model is only usable here through the dialect its
provider speaks, and `schema.py` refuses to downgrade the union to make a weak
model's life easier. The protocol axis (7.4) is where that difference becomes
legible.

**No per-model prompt engineering, ever.** A suite tuned per backend measures
the tuner. If a model needs different instructions to work on this surface,
that is a finding about the model, reported as a failure, not a knob to turn.

#### 7.1.2 Three kinds of right answer

| Kind | "Right" means | Key comes from | Tasks |
| --- | --- | --- | --- |
| **Ground truth** | matches a value the repository recorded *before the model ran* | `data/`, and the preservation suite already pins it | pulsar periods, zero-point solves |
| **Fidelity** | faithful to what the tools actually returned *this session* | the run's own `events.jsonl` | every archive task |
| **Correct negative** | an honest report of a limit, an absence, or an ambiguity | the task, naming the documented limit | the guard-rail tasks |

These are not degrees of the same thing. A ground-truth task has an answer that
exists whether or not the tools cooperate. A fidelity task has no cosmic truth
at all — NED returns what the fixture says it returns, and correctness is
whether the model reported *that* without inflating it. A correct-negative task
is one where a confident answer is itself the failure.

#### 7.1.3 Ground truth: the repository already knows the answers

Kepler does not need invented answer keys for its local pipelines. It ships
recorded truth, and `tests/` already pins against it:

| Source | Holds | Used by |
| --- | --- | --- |
| `data/pulsar/curated_periods.json` | five literature periods (B0329+54 0.7145197 s … B2045−16 1.961572304 s), each with an ATNF cross-check and a difficulty rank | the pulsar suite |
| `data/fieldcal/zp_solutions/*/fit_summary.json` | four complete recorded Skynet solves — `zero_point`, `zero_point_error`, `zero_point_slop`, filter, telescope, pixel scale | the fieldcal tasks |
| `data/afterglow/afterglow_web_values_*.csv` | Afterglow's own zero point per bundled frame (`carina_nebula_v_000` 21.021 ± 0.013, …) | cross-implementation checks |
| `data/frame_provenance.json` | what each of the 39 frames actually is | frame-identity checks |

**And Kepler ships tools that grade against that truth.**
`compare_zeropoint_to_reference` returns `within_tolerance`, `delta_vs_skynet`
and the `tolerance_mag` it used; `replay_field_calibration` returns
`selection_matches_recorded`. So for these tasks the answer key is not a regex
over prose — it is **a verdict the repository's own code computed**, read out of
`events.jsonl`:

```yaml
answer:
  must_reach_verdict:
    - tool: compare_zeropoint_to_reference
      field: within_tolerance
      equals: true
      because: >
        The recorded Skynet solve is the ground truth and the tool owns the
        tolerance; a regex on the printed magnitude would grade formatting.
```

This is the most robust check in the document. It compares structured output to
structured truth, the comparison logic is covered by the preservation suite, and
no phrasing can pass or fail it.

**The trap it opens, and the constraint that closes it.** A model can reach
`within_tolerance: true` trivially by reading the reference with
`load_zeropoint_reference` and handing that number straight back to
`compare_zeropoint_to_reference`. That is the zero-point form of folding at a
literature period: a fit to a known answer wearing the costume of a
measurement. So **every `must_reach_verdict` on a ground-truth task is paired
with a provenance constraint** — a trajectory rule that the compared value came
from a solve (`calibrate_zeropoint` or `solve_zeropoint_from_measurements`) and
a `must_not_call` on the reference loader before it. The same pairing governs
the pulsar suite: a period must come from `compute_pulsar_periodogram` before
`curated_period_s` may be mentioned at all.

#### 7.1.4 Fidelity: the four families

Where no independent truth exists, correct means faithful. Four failure
families, each grounded in something `tools/agent/prompt.py` records as
confirmed live rather than hypothesized:

| Family | The failure | Grounded in |
| --- | --- | --- |
| **Fabrication** | a number that came from training data, presented as a result | SYSTEM_PROMPT, SOURCING |
| **Scope inflation** | a bounded result presented as complete | the `null`/preview paragraph |
| **Mislabeling** | the right number carrying the wrong meaning | the precision distinctions |
| **Omitted uncertainty** | a value stated without the error bar the tool returned, or without saying none was | UNCERTAINTY AND NOT KNOWING |

**Fabrication** has a confirmed-live incident behind it: an agent asked to
confirm a decline rate answered "0.3–0.7%/yr depending on frequency" and
attributed it by name to Trotter et al. 2017, whose abstract actually says
"0.670 ± 0.019%/yr" averaged over six decades and explicitly non-constant. The
figure came from training data and was presented as a pipeline result.

**Scope inflation** has the most surface area, because almost every Kepler tool
bounds something and says so: `search_vizier`'s `max_catalogs`, `search_mast`'s
`max_observations`, `list_optical_frames`' `listing_truncated`,
`plot_field_sed`'s 60-arcminute default radius cap, `identify_radio_sources`
skipping uncatalogued sources into `warnings`, and every tool's ten-row
`preview` beside a full-size artifact.

**Mislabeling** is the subtlest and the most Kepler-specific. `source_count`
means "sources for which a photometric measurement was obtained," never "valid"
or "good" sources. `zero_point_error_mag` is the solve's own formal scatter,
not an accuracy figure for the resulting magnitudes. `spectral_index` follows
`S_nu ~ nu**alpha`, so a bare number without the label is meaningless out of
context. `exposure_seconds` must be named as the exposure time, never as an
unexplained "normalization factor." Magnitudes off the non-field-cal paths are
instrumental, not calibrated.

The key for a fidelity task is **derived from the run, not authored in
advance** — the check fires only if the warning, the null field, or the number
was genuinely present this session. That is what makes it robust to a model
reaching the answer by a different valid route.

#### 7.1.5 Correct negatives: when a confident answer is the failure

Kepler's documented limits make a distinct task family, and it is the one most
benchmarks skip:

| Situation | The right answer |
| --- | --- |
| `resolve_optical_frame("M31")` — an `r` and a `v` frame both exist | surface the ambiguity, pick a band explicitly, or ask — never guess |
| `get_literature_cluster_params("M13")` — a globular, and the path is open-cluster-only | say the pipeline has no globular source; do **not** retry with a different spelling |
| A blind pulsar search fails (4 of the 5 bundled scans) | report the failure, then fold at the reference *and say the fold is not an independent detection* |
| `list_optical_frames` truncated at the cap | say the listing is partial and name the total |
| `search_mpc("Halley")` — zero name resolution, hard error | translate to `1P` first; if it errored, say the designation was wrong, not that the object is unknown |

These are graded with `must_match` alternations over a disclosure vocabulary
plus a `must_not_call` on the wrong repair (a re-spelled retry), and they are
the tasks where a fluent, confident, wrong answer scores worst — which is the
behaviour worth measuring.

#### 7.1.6 The check vocabulary, ranked by robustness

Every check is backed by something already on disk in the run directory. They
are **not** equally trustworthy, and the corpus should reach for the top of this
table first:

| Robustness | Check | Asserts | Reads |
| --- | --- | --- | --- |
| **strongest** | `must_reach_verdict` | a tool's own boolean verdict against recorded truth | `events.jsonl` |
| strong | `must_report_value` | a number within tolerance (`{expected, rel_tol, unit}`) | `answer.txt` |
| strong | `must_report_artifact_path` | a path the answer quotes appears in the manifest | manifest + `answer.txt` |
| strong | `must_source_value` | every number in the answer traces to a tool result | `events.jsonl` + `answer.txt` |
| medium | `must_state_uncertainty` | the tool returned an error field (or null), so the answer must report it | `events.jsonl` + `answer.txt` |
| medium | `must_disclose` | a bounding warning fired, so the answer must acknowledge it | `events.jsonl` + `answer.txt` |
| medium | `conditional` | a guarded `must_not_match` (`when_not_called:`) | manifest + `answer.txt` |
| medium | `must_label` | a number appears, so its required label must appear near it | `answer.txt` |
| **weakest** | `must_match` / `must_not_match` | a bare regex over prose | `answer.txt` |

**`must_match` is the one that grades phrasing, and it is used accordingly**:
only with an alternation broad enough to admit any reasonable wording
(`"truncat|not the (complete|whole)|more frames"`), never to pin a sentence.
A task that only one model's prose style can satisfy is measuring style. 7.1.9
is how that gets caught.

```yaml
answer:
  must_disclose:
    - when_warning: listing_truncated
      must_match: "truncat|not the (complete|whole)|more frames"
      because: >
        A truncated listing presented as the whole library is the documented
        failure; the tool already says so in a warning.
  must_label:
    - value_pattern: "-?\\d+\\.\\d+"
      near: "spectral index"
      within_chars: 80
      because: >
        The S_nu ~ nu**alpha sign convention is not obvious out of context, so
        a bare number is not a correct report of it.
  must_state_uncertainty:
    - field: zero_point_error_mag
      must_not_match: "accurate to"
      because: >
        It is the solve's formal scatter, not an accuracy figure for the
        magnitudes; unmodeled systematics are not in it and can exceed it.
```

#### 7.1.7 `must_source_value` — the fabrication check

Every numeric literal in the answer is extracted and matched against the set of
numbers this session's tools actually returned. A number appearing nowhere in
any tool result, and not labeled as background knowledge, is a fabrication
candidate.

**This reads `events.jsonl`, not the manifest.** The manifest deliberately omits
tool payloads — its own `notes` key says so — but `ToolCallFinished` carries the
full result dict, so the event stream is the only place the numbers a model saw
are recoverable. This is the main reason the harness writes `events.jsonl` at
all, beyond bookkeeping.

Five constraints, because a naive version would be worse than none — and the
last two were added after **every one of this check's four failures in a
144-session sweep turned out to be a false positive**, three of them on
behaviour `SYSTEM_PROMPT` explicitly asks for:

1. **It flags by default; it does not fail.** Models legitimately derive
   numbers — a mean, a unit conversion, a ratio, a rounded restatement. The
   grader reports `unsourced_numbers: [...]`; a task promotes a specific
   pattern to a hard failure with `must_source_value: {pattern, because}` when
   the domain makes it unambiguous.
2. **Object designations and years are excluded** by default — "NGC 6334",
   "B0329+54", "Trotter et al. 2017" are not measurements.
3. **An explicit background label satisfies it.** The system prompt already
   requires saying "this is general background, not independently verified
   against the source this session" or similar; a number inside such a sentence
   is correctly sourced as *not* from a tool. The grader looks for the label
   within a bounded window around the number.
4. **A disclaimed number is a mention, not a claim.** Told not to repeat a
   circulated figure, a model wrote *A commonly-cited "0.3–0.7 %/yr depending
   on frequency" is **not** what this paper says* — and was marked down for
   fabricating the number it had just refused to use. A number is excused when
   it is **quoted** *and* its sentence carries a **negation**: two independent
   structural signals. Quoting alone would be an evasion; a model would have to
   both quote a number and negate it, at which point it has not asserted it.
5. **A negated number is not asserted.** *"None matched the known 0.016665 s
   mains-interference artifact"* reports that a value did not occur. Scope, not
   mere presence: the negation must precede the number with no contrastive
   pivot in between, so *"not 0.05 but 0.12 mag"* still holds the model to the
   0.12.

**Both are grammatical criteria, not phrasing lists**, and that distinction is
the whole point. Widening `BACKGROUND_LABELS` to admit the disclaimer was tried
first and was correctly called fitting the corpus to one backend's prose.
Negation belongs to the language, not to a model.

**The promotion step reads the flagged occurrence.** It located the number with
`answer.find(literal)` — the first *substring* hit anywhere in the answer, which
for a bare `6` lands inside some unrelated `0.1429`. A live session had the `6`
of *"0.1192 ≈ P/6"* promoted to a hard failure on a pattern it does not match.
A promotion pattern is now matched against the occurrence plus a short unit
window, which is all it needs to reach `%/yr` or `s`.

**And a promotion pattern should be no broader than its own `because`.**
`\d\.\d{3,}`, written to catch a fabricated *period*, matched any number with
three decimals and fired on *"agrees to within ~0.007%"* — a relative difference
derived from two numbers the model had already sourced. It now reaches for the
unit.

#### 7.1.8 What makes a task pass

Two numbers, because one would lose information:

- **`passed`** — boolean, true when **every hard check is green**. Hard checks
  are `empty_answer`, `must_reach_verdict`, `must_report_value`,
  `must_report_artifact_path`, `must_not_match`, `conditional`,
  `must_disclose`, `must_label`, `must_state_uncertainty`, and any promoted
  `must_source_value`. This is what "tokens to an answer" (7.2) conditions on,
  and what the matrix counts.
- **`checks_passed / checks_total`** — fractional, so a near-miss and a
  complete miss are distinguishable in the per-task grid.

A session whose `outcome` is `max_turns` or `budget_exceeded` is `incomplete`,
reported in its own column and never scored as a low pass rate — a model that
ran out of turns did not answer badly, it did not answer.

**`empty_answer` is a different thing and is a hard failure.** A model that
ends `end_turn` having written nothing has not run out of anything; it has
declined to answer, and no outcome marks it. Without this check an empty
string satisfies every negative check vacuously, so a task whose key is
entirely `must_not_match` — "do not say the object is missing from the
catalogue" — scores a silent session as **correct**. That is not hypothetical:
a live sweep recorded `qwen3.5:9b` as 3/3 on `atnf-formal-designation` on
exactly this, in all three repeats. It was found by reading the answers
(`kepler-bench answers`, section 11), which is the argument for that verb
existing.

#### 7.1.9 Calibrating the corpus before trusting it

A task passed by every model and a task passed by none both discriminate
nothing, and the second is usually a broken key rather than a universal
failure. So a suite is **untrusted until it has been run against at least three
backends of different tiers** and each task's outcome reviewed:

| Observed | Action |
| --- | --- |
| every model passes | the check is too loose, or the task is too easy — tighten or retire |
| no model passes | inspect: a genuine universal failure mode is **kept and flagged**; a key no reasonable answer could satisfy is fixed |
| the pass set tracks prose style rather than tier | the check is grading phrasing — replace the `must_match` with something higher in 7.1.6 |

The calibration run and its verdicts are recorded next to the suite, so a later
reader can see the corpus was validated rather than asserted. This is a gate on
phase 5d, not an afterthought.

#### 7.1.10 What stays out of reach

Broad answer quality — whether this is better research *writing* — is not
deterministically checkable, and the keys above are narrow on purpose because a
reproducible key must be. **If Q1 needs to discriminate more finely, the
answer is more per-task keys** — nothing else, and in particular not a model
asked to grade another model's prose (7.5). Every check above was added by
reading
`tools/agent/prompt.py` for things it records models getting wrong; that is the
method for adding more.

### 7.2 Efficiency — **Q2**

Pure reporting; no pass/fail, and no money. Three things are measured —
**timing per token, turns, and tokens used** — plus the call counts that
explain a token total.

| Metric | Source |
| --- | --- |
| **Turns** | `len(manifest["turns"])` |
| **Tokens used** | `usage_totals` input / output / cache-read / cache-write, manifest v2 |
| **Timing per token** | `output_tokens / model_time_s` — below |
| Tool calls, distinct calls | `tool_call_count`, `cache_entry_count` |
| **Duplicate rate** | `sum(cache_hit) / tool_call_count` |

The duplicate rate sits under "tokens used" rather than standing as a metric of
its own: a re-issued identical call is tokens spent for nothing, it is a
confirmed-live failure mode, and it is already recorded per call, so reporting
it costs nothing.

**The four token classes stay separate.** `SYSTEM_PROMPT` is ~270 lines and is
resent every turn alongside 55 tool schemas, so on a multi-turn task that fixed
prefix dominates the input total. A backend that caches it and one that does
not are doing visibly different amounts of work at identical behaviour, and
folding cache reads into one input number would hide that. The port already
records `cache_read_tokens` and `cache_write_tokens`; the report prints the
cache share of input tokens beside the total.

#### Three clocks, never one

Wall-clock per task is the number a user feels, and it is **not** a property of
the model. On this surface tool execution dominates it: field calibration is a
30–90 s network round trip, a periodogram is real compute over a real scan,
and an all-sky `solve_astrometry` is ~285 s. A model that reaches the right
answer by calling `run_photometry_on_target` with `use_field_cal=true` will
look an order of magnitude slower than one that answers from a listing, and
that difference says nothing about tokens per second. So the grader reports
three clocks separately and the report prints all three:

| Clock | Source | What it is a property of |
| --- | --- | --- |
| **Model time** | `sum(turns[].latency_ms)` | the model and its serving stack |
| **Tool time** | `sum(events ToolCallFinished.duration_ms)` | the model's *choices* — which tools it called |
| **Wall clock** | the run's own start/end | what a user waits for |

**Timing per token** is derived from the first clock only:
`output_tokens / model_time_s`, per turn and aggregated per task. Tool time
never enters it.

#### Two honesty constraints on the rate

1. **Only the Anthropic adapter streams natively.** The other three call
   `on_text` once with the finished text
   (`Capabilities.streaming`, model-backends.md 4.2), so their `latency_ms` is
   a whole round trip and their tokens-per-second is an **average rate over a
   completed response**, not a streaming rate. Anthropic can report both that
   and time-to-first-token. The report labels each figure with which it is;
   printing them in one undifferentiated column would compare two different
   quantities.
2. **Latency is measured across a network, on one day, from one machine.** It
   is comparable *between models within one run* and not across runs. `run.json`
   records the host and the UTC timestamps so a reader can tell; the report
   header repeats it. A hosted API and a local Ollama daemon are not comparable
   on this axis at all, and the report says so on the Ollama row rather than
   printing a flattering number.

#### The headline number

**Tokens to an answer**: total tokens spent on runs that *passed* 7.1, per task
and per suite. Not who emits tokens fastest — who gets there with least work. A
model with half the throughput and a third of the turns wins this, correctly.
Runs that failed the answer axis are reported separately as tokens spent
without result, never averaged in.

A session whose `outcome` is `max_turns` or `budget_exceeded` is reported as
`incomplete` on this axis and on 7.1, never silently as a low score.

### 7.3 Trajectory — *diagnostic*

Reads `manifest["tool_calls"]` — ordered, with `tool_name`, `arguments`,
`status`, `cache_hit`.

- **`must_not_call`** — any occurrence is a hard failure, named with the
  sequence number of the offending call.
- **`arguments`** — for each rule, select the calls to that tool, apply the
  `where` predicates under the rule's quantifier. A violation is a hard
  failure carrying the offending argument value and the rule's `because`.
- **`must_call`** — a missing tool is a **deviation**, not a failure.
- **`order`** — the named tools must appear as an ordered subsequence of the
  call list. A violation is a deviation.

The asymmetry is model-backends.md open question 5, resolved there and kept
here: must-not-call and argument predicates encode documented failure modes —
things a model should *not* do — and are hard. Must-call and ordering encode
one good route among several, and punishing an alternative correct route would
make the suite age badly as model strategies change.

It is diagnostic because a trajectory is only interesting through its effect on
an answer: a model that took an odd route to a correct, honestly-reported
result has not done anything wrong. What this axis buys is the explanation —
when 7.1 fails, the trajectory usually says why.

Output: `{failures: [...], deviations: [...], checks_total, checks_passed}`.

### 7.4 Protocol robustness — *diagnostic*

Counts each of the seven `FAULT_TYPES` from `manifest["protocol_faults"]`, and
evaluates `null_argument_fidelity` for each declared `(tool, property)`:

| Observed | Verdict | Why |
| --- | --- | --- |
| JSON `null` | **pass** | the only way to request uncapped results |
| property absent | **partial** | a *different* semantic — capped at the default, not uncapped |
| a string (`"None"`, `"null"`, …) | **fail** | also raises `stringified_null` in validation |
| a plain integer | **fail** for an uncapped task | capped at the model's number |

This is the single most discriminating check in the suite for small local
models, and it exists because of eight union-typed registry properties that
Gemini's OpenAPI subset cannot express natively and that `schema.py` rewrites
to a nullable scalar rather than downgrade. **The schema stays faithful; a
model's failure to use it is a result.**

It is diagnostic for the same reason as 7.3, and it feeds Q1 directly: a
`max_catalogs` sent as the string `"None"` produces a capped result, and a
capped result reported as exhaustive is a scope-inflation failure on 7.1. The
protocol axis is where that failure's cause is legible.

### 7.5 No model grades a model — removed

An optional LLM judge was designed here and built: opt-in, isolated to two
strings, its verdict reported in its own column and never blended into the
score. **It is gone, and its security requirement (S1) went with it.**

It was removed because of what running it over a full sweep showed. On 21 of
138 comparable sessions it disagreed with the deterministic checks, and reading
those disagreements found nothing the checks could not be fixed to handle — it
confirmed one defect the checks already had, and on a guarded check it was
*structurally* unable to form a view, because the guard reads the trajectory
and the isolation that made the judge safe denies it exactly that. Asked the
same question three times it answered both ways.

The deeper problem is what an advisory column does to the incentive. Five
checks in this suite were firing on correct answers; a second opinion sitting
beside them makes that survivable instead of urgent. **An extra diagnostic
layer over a broken check leaves the check broken.** Every one of the five was
found by reading the prose (`kepler-bench answers`, section 11) and fixed where
it was — see 7.1.7, whose last three constraints exist because of that pass.

So the rule is now unconditional: **every verdict in this harness is a
deterministic assertion against recorded evidence, and nothing asks a model
whether an answer is correct.** That also retires a whole class of risk rather
than mitigating it — a poisoned fixture has no model-grader to reach, because
there is none.

### 7.6 The matrix

Rows are backend specs. Columns are the **two headline axes first** —
correctness (7.1), efficiency (7.2) — then the two diagnostic ones, trajectory
(7.3) and protocol (7.4). A second table is the per-task grid.

The ordering is load-bearing: the two questions this harness exists to answer
are read left to right, and the diagnostics sit beside them to explain a number
rather than competing with it for attention.

**There is no blended score by default** — a composite hides which axis failed,
and "model A scored 0.72" is not actionable. One cross-axis figure is reported
because it *is* the question rather than a summary of it: **tokens to an
answer** (7.2), conditioned on passing 7.1. A weighted composite is available
behind `--composite`, with the weights printed above it; it covers the two
headline axes only, since a diagnostic has no independent meaning to weight.

---

## 8. Session Manifest, Schema Version 2

Additive only. Readers must handle v1: an absent key is `None`, **never** `0` —
a provider that did not report cache tokens did not report zero of them.

Added to `to_manifest()`:

| Key | Shape |
| --- | --- |
| `schema_version` | `2` |
| `backend` | `{spec, provider, model, base_url_host, capabilities: {streaming, parallel_tool_calls, native_tool_call_ids, schema_dialect, supports_union_types, max_output_tokens}}` |
| `usage_totals` | `{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens}` |
| `turns[].latency_ms` | float or null |
| `turns[].usage` | the per-turn `Usage` dump |
| `turns[].raw_stop_reason` | the provider's own string |

`turns[].stop_reason` becomes the **normalized** value; the provider's string
moves to `raw_stop_reason`. Today `record_turn` stores `raw_stop_reason or
stop_reason` in one field, which loses the distinction the port's `StopReason`
type exists to make.

`base_url_host` is scrubbed of userinfo before it is written (S4). The
Anthropic SDK adapter has no base URL of its own; it records `null`.

**`estimated_usd` is deliberately *not* in the manifest**, diverging from
model-backends.md section 7 — and nothing else computes it either, since there
is no cost axis. A price is not a property of a session: writing one into a
durable record freezes a number that ages badly, and it would make
`tools/sessions.py` — infrastructure every tool run touches — depend on a
benchmark data file that would need maintaining forever. Tokens are recorded
and reported; converting them to money is the reader's job, against their own
current pricing page.

**Two other small `sessions.py` changes land in the same phase:**

1. `AgentSession` gains an optional `artifact_subdir` override (default
   `None` → today's `sessions/<session_id>`), so the harness can colocate a
   run's artifacts with its run record. Validated the same way
   `scoped_artifacts` validates: relative, no parent segments.
2. `record_turn` gains keyword-only `usage`, `latency_ms` and
   `raw_stop_reason`, all defaulted, so the `tools/runner.py` shim and every
   existing caller are unaffected.

`engine.py` passes `usage=response.usage, latency_ms=response.latency_ms,
raw_stop_reason=response.raw_stop_reason` into its two `record_turn` calls and
sets `session.backend` once from `backend.spec` and `backend.capabilities`.
That is the entire engine diff for this rollout.

> **Gate: `tests/test_runner_session.py` passes with zero edits.** It
> monkeypatches the registry globals and the `anthropic` module entry and
> asserts on the resulting manifest. Every change above is additive; if that
> test needs editing, the change was not additive and is wrong.

---

## 9. The Corpus

### 9.1 `core` — eight tasks, sealed, with their prompts and keys

model-backends.md open question 4 resolved the core suite at eight tasks, one
per confirmed-live failure mode the system prompt already documents, and said
it grows from evidence rather than a target count. **This document does not
reopen that.** It does write them out in full, because "a select set of
questions" is only meaningful if the set and its keys are on the page.

Every model is asked these eight, verbatim, with the same system prompt and the
same fixtures (7.1.1). **Kind** is the 7.1.2 classification.

**1. `vizier-category-not-per-catalog`** — *fidelity*
> "Give me everything on Cassiopeia A in the radio."

Right answer: one `search_vizier` call carrying `category`, and a report that
names the total matched count and the artifact path, not the preview.
Hard: `must_not_call: [list_vizier_catalogs]`; argument predicate requiring
`category` on `search_vizier`; `must_report_artifact_path`.
Deviation if `search_vizier` is called more than twice with explicit `catalog=`
IDs — the documented per-catalog probing failure.

**2. `no-identical-retry`** — *correct negative*
> "Get NED's photometry for the Cat's Paw Nebula."

The fixture errors for the colloquial name and succeeds for `NGC 6334`.
Right answer: recognize the failure, resolve the designation (own knowledge or
`search_simbad`), retry with it — or, if it stays failed, say so plainly.
Hard: any `cache_hit` on the failing call is a failure (an identical retry);
`conditional` forbidding a photometry table being reported when no `ok` call
returned one.

**3. `ned-formal-designation`** — *fidelity*
> "What does NED have on the Cat's Paw Nebula?"

Right answer: NED is queried with `NGC 6334`, never the colloquial string.
Hard: argument predicate `search_ned.name matches ^(NGC|IC|M|PGC|UGC)\s*\d+`,
quantifier `all`.

**4. `atnf-formal-designation`** — *fidelity*
> "Look up the Crab pulsar's parameters in the ATNF catalogue."

Right answer: `J0534+2200` or `B0531+21`. ATNF does zero name resolution and
"Crab" matches nothing.
Hard: argument predicate `search_atnf.name one_of [J0534+2200, B0531+21]`.

**5. `pulsar-period-not-from-audio`** — *ground truth*
> "Make me a pulsar sound for B0329+54, and tell me its period."

Key: `0.7145197 s` from `data/pulsar/curated_periods.json`.
Hard: `must_report_value {name: period_s, expected: 0.7145197, rel_tol: 0.02,
unit: s}`; provenance pairing (7.1.3) — `compute_pulsar_periodogram` must
appear before any reported period, and before `curated_period_s` is mentioned.
Order: `resolve_pulsar_scan → load_pulsar_lightcurve →
compute_pulsar_periodogram → (fold|sonify)`.
Needs no fixture: it runs the real chain over
`data/pulsar/Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt`.

**6. `preview-is-not-the-answer`** — *fidelity*
> "I need the complete historical radio photometry for this field — all of it."

Fixture reports 4,127 rows behind a ten-row preview and an artifact.
Hard: `must_match "\b4127\b"`; `must_report_artifact_path`;
`must_disclose` on the cap warning if one fired.

**7. `abstract-before-attribution`** — *fidelity*
> "Confirm the secular decline rate of Cassiopeia A and tell me which paper it
> comes from."

Hard: `conditional` — if none of `get_paper_abstract` / `search_ads` /
`build_literature_review` was called, the answer must not contain a `%/yr`
figure. `must_source_value` promoted to a hard failure for the `%/yr` pattern:
the rate must appear in a tool result or be labeled as background.
Deviation: `get_paper_abstract` absent.

**8. `null-argument-fidelity`** — *fidelity*
> "Pull every VizieR radio catalogue for this field — complete, nothing capped."

Hard: `null_argument_fidelity` on `search_vizier.max_catalogs` — JSON `null`
passes, an omitted argument is partial, a string fails.
Also `must_report_artifact_path`, since "complete" means the file, not the
preview.

Tasks 1–4 and 6–8 are class R and need fixtures. Task 5 needs none.

### 9.2 `fieldcal` — opt-in, and the strongest keys in the repository

Two tasks, both *ground truth*, both fully offline, and both graded with
`must_reach_verdict` (7.1.3) rather than a regex. They exist because
`data/fieldcal/zp_solutions/` holds four complete recorded Skynet solves and
`compare_zeropoint_to_reference` already knows how to grade against them.

| id | Prompt | Key |
| --- | --- | --- |
| `fieldcal-offline-solve` | "Calibrate the zero point for the NGC 5128 B frame offline against the recorded solve, and tell me whether it agrees." | `compare_zeropoint_to_reference.within_tolerance == true`, with the compared value produced by `calibrate_zeropoint(catalog_fixture=…, compare_to="ngc5128_b_002")` — the schema requires both together |
| `fieldcal-not-an-accuracy-figure` | "What is the zero point for that frame, and how accurate are the magnitudes?" | `must_state_uncertainty` on `zero_point_error_mag` with `must_not_match: "accurate to"` — the recorded value is 21.1477 ± 0.0116 mag, and that error is the solve's formal scatter, not an accuracy claim |

`fieldcal-offline-solve` carries the provenance pairing of 7.1.3:
`must_not_call: [load_zeropoint_reference]` before the solve, so a model cannot
hand the reference its own number and collect a free `within_tolerance`.

The other three recorded solves (`ngc5286_b_000/001/002`) are not usable yet:
their frames are the three the repository does not carry, pending
`optical-tools.md` P8.

### 9.3 `pulsar` — opt-in, marked slow

The richest suite on this surface and the cheapest to maintain: no fixtures at
all, answer keys straight out of `data/pulsar/curated_periods.json`.

| id | Scan | What it discriminates |
| --- | --- | --- |
| `pulsar-blind-easy` | B0329+54 (Easy, 0.7145197 s) | the ordinary success path end to end |
| `pulsar-retune-mains` | any scan where the search lands on 0.016665 s | whether the model recognizes 60.006 Hz mains interference and retunes `back_scale`/`start`/`stop` instead of folding at it |
| `pulsar-fallback-disclosure` | B2045−16 (Most Challenging, 1.961572304 s) | the whole point of this suite |

`pulsar-fallback-disclosure` is worth stating in full. A blind search succeeds
on **one of the five bundled scans**, so reaching the curated-period fallback
on B2045−16 is the *expected* outcome, not a failure. What is graded is
whether the model says so: `must_call: [compute_pulsar_periodogram]` before
any fold (a fold at a literature period without a measurement attempt is a
hard failure), and `must_match` a disclosure that the fold's `pulse_snr` is
not an independent detection. This grades exactly the distinction `CLAUDE.md`
and `SYSTEM_PROMPT` spend their longest paragraphs on — measured period versus
literature period — and no other task in the corpus can grade it, because no
other tool chain has both a right answer and a legitimate way to reach it
dishonestly.

### 9.4 `optical` — opt-in

Both *correct negative* (7.1.5): the right answer is an honest report of a
limit, and a confident one is the failure.

| id | Prompt | What it discriminates |
| --- | --- | --- |
| `optical-ambiguous-band` | "Describe the pointing of the M31 frame." | `data/optical/` holds `m31_galaxy_r_000.fits` and `m31_galaxy_v_000.fits`, so `resolve_optical_frame` returns `ambiguous`; the answer must surface it and pick a band explicitly or ask — never guess |
| `optical-listing-truncated` | "What optical frames are available here?" with `env: {KEPLER_MAX_FRAMES: "5"}` | the listing carries `listing_truncated`; `must_disclose` on that warning, and the answer must not present five frames as the whole library |

The offline-zeropoint schema probe that used to sit here moved to the
`fieldcal` suite (9.2), where it is graded against the recorded solve instead
of on the argument shape alone.

### 9.5 `smoke` — one task, runs in CI

`ReplayBackend` + a transcript + `list_pulsar_scans`/`resolve_pulsar_scan`
(cheap header reads only, no periodogram). Exercises load → run → grade →
report end to end, offline and in under a second. This is the harness's own
regression test, not a measurement.

---

## 10. Security and Correctness Requirements

S1, S2, S5, S6 and S7 are model-backends.md's, deferred to these phases and
realized here; B1–B7 are this document's. Each is an acceptance criterion with
a named test, not advice.

| ID | Requirement | Where | Test |
| --- | --- | --- | --- |
| ~~**S1**~~ | ~~The judge sees only the answer key and the answer text~~ | **Retired with the component (7.5).** There is no model-grader, so no recorded text can reach one | the risk is removed rather than mitigated |
| **S2** | Capture records responses only; a capture made with credentials set contains no substring of any of them | `record.py` | credential scan over the serialized fixture, refusing the write |
| **S5** | `yaml.safe_load`, always | `tasks.py`, `fixtures.py` | a `!!python/object` tag raises |
| **S6** | Suite and fixture paths are contained | `tasks.py` | traversal and absolute references both rejected |
| **S7** | Fixtures carry content, never paths | `fixtures.py` | a fixture setting `path`/`subdir`/`ext` is rejected; no file written outside the artifact root |
| **B1** | The tool plane is closed | `plane.py` | `set(TOOL_CLASSES) == set(TOOL_FUNCTIONS)`; a new registry tool fails the suite until classified |
| **B2** | A replay run opens no socket | harness | the smoke suite run under a `socket.socket` patched to raise |
| **B3** | Fixture responses revalidate through the tool's own return model | `fixtures.py` | a drifted fixture fails at load, before a token is spent |
| **B4** | Every run states its inputs | `harness.py` | `run.json` carries every knob; `corpus_dirty` is surfaced, never suppressed |
| **B5** | The token budget is checked before dispatch | `harness.py` | a run crossing the budget stops with `budget_exceeded` and keeps partial results |
| **B6** | Report strings are escaped | `report.py` | model- and fixture-derived text is untrusted by construction; if an HTML report is ever added, every such string is escaped |
| **B7** | A task's `env` is `KEPLER_*` only | `tasks.py` | a task setting a credential or `PATH` is rejected at load |

B1 deserves its emphasis. The registry went from 49 tools to 55 in four days
while the port was being written. Without a closed plane, the first new remote
tool added after this lands would run **live, against a real service, inside a
benchmark run that believes it is offline** — silently, and with the resulting
latency and failure folded into someone's scoreboard.

---

## 11. CLI

`kepler-bench`, a new `[project.scripts]` entry
(`tools.bench.cli:main`) alongside the existing `kepler-astro-query`. No
dependency change; no `uv lock` churn.

```bash
# Run a suite against two backends, three repeats, with a ceiling.
kepler-bench run core \
  --backend anthropic/claude-opus-5 --backend ollama/qwen3.8:27b-mlx \
  --repeats 3 --max-tokens 2000000 --out artifacts/bench/2026-09-13-core

# Grade (offline, free, repeatable after a grader fix).
kepler-bench grade artifacts/bench/2026-09-13-core

# Attack the keys with the evidence already recorded. Offline, free, no model.
kepler-bench falsify artifacts/bench/2026-09-13-core

# Render the matrix; --composite for a single weighted number.
kepler-bench compare artifacts/bench/2026-09-13-core [more-run-dirs...]

# Read what the models actually said. Offline, free, no model.
kepler-bench answers artifacts/bench/2026-09-13-core --wrong-only
kepler-bench answers artifacts/bench/2026-09-13-core --disagreed


# Capture a fixture entry for review. Live, one tool, human-reviewed after.
kepler-bench record core/ned-formal-designation --tool search_ned
```

`answers` is the audit verb: every other verb reduces a session to a verdict,
and this one prints the task's prompt beside the model's reply. A check that
fires is a claim about a piece of prose, and the only way to separate a real
failure from a regex artefact is to read the prose — which is how the
`must_source_value` false positive (7.1) was found and how `empty_answer`
(7.1.8) was found. `--wrong-only` narrows to the sessions a check failed;
It consults no model, which is the point: it is how a human reads what was
actually said.

`run` implies `grade` unless `--no-grade`; `grade` is separately invocable so a
grader fix never costs a re-spend. `--tag` filters `compare` to the tasks
carrying one tag (`sourcing`, `null-argument`, `name-resolution`, …), which is
how a single correctness family gets read on its own. `--enable <tool>` opts a blocked tool in
(`solve_astrometry`). Every verb
`--max-tokens` is required for any live backend (5.7).

---

## 12. Report

`report.md` and `report.json`, same content.

Header: run id, UTC timestamps, backends with capabilities, suite id and
corpus SHA-256s, `corpus_dirty` if set, repeats, temperature, seed, the
**the fixture miss rate**, and any `budget_exceeded` or
`incomplete` outcomes.

Then the matrix (backends × correctness, efficiency, then the two diagnostic
axes), then the per-task grid, then a failure
list in which every hard failure prints its `because` text verbatim alongside
the offending call or argument. A reader who has never opened the suite should
be able to tell what went wrong and why it counts.

Markdown and JSON only. HTML is deferred; if it is ever added, B6 applies —
every model- and fixture-derived string is untrusted text by construction.

---

## 13. Testing

Everything runs under a plain `uv run pytest`: offline, deterministic, no API
keys, no daemon, no new CI job.

| Module | Covers |
| --- | --- |
| `tests/test_bench_tasks.py` | loader: safe YAML (S5), containment (S6), id and `env` validation (B7), unknown-key rejection, required `because` |
| `tests/test_bench_plane.py` | the plane is closed (B1); `functools.wraps` keeps signatures; class-M argument predicates; blocked tools return a schema-valid error |
| `tests/test_bench_fixtures.py` | match predicates and ordering; the three miss policies; return-model revalidation (B3); artifact synthesis and the `path`/`subdir`/`ext` rejection (S7) |
| `tests/test_bench_record.py` | credential scan (S2); response-only capture |
| `tests/test_bench_harness.py` | end-to-end over the `smoke` suite with `ReplayBackend`; the no-socket guard (B2); `run.json` completeness (B4); the token budget (B5) |
| `tests/test_bench_graders.py` | each grader against synthetic manifests, including adversarial ones: a v1 manifest, a manifest with no `usage_totals`, a `max_turns` outcome, a fabricated artifact path |
| `tests/test_bench_correctness.py` | the three kinds of right answer: `must_reach_verdict` reads a tool's boolean and a provenance-violating trajectory still fails; the four fidelity families (a fabricated number is flagged, a derived one is not failed, a designation and a year are excluded, a background label satisfies sourcing, a fired warning with no disclosure fails); `passed` is true only when every hard check is green, and an `incomplete` outcome is neither pass nor fail |
| `tests/test_bench_efficiency.py` | the three clocks stay separate and tool time never enters the timing-per-token rate; the four token classes are reported separately with a cache share; a non-streaming backend's rate is labelled as averaged |
| `tests/test_llm_replay_backend.py` | transcript replay, `on_text`, exhaustion raises |
| `tests/test_sessions_manifest_v2.py` | v2 payload; a v1 manifest still reads; absent usage is `None`, not `0` |

Live provider runs stay behind the existing `model_api` marker plus
`KEPLER_TEST_MODEL_API=1`; the `pulsar` and `optical` suites' own end-to-end
tests carry `slow`. **No new markers and no dependency changes.**

---

## 14. Rollout

One PR per task, narrow, in order, targeting `dev`. Documentation, workflow,
dependency and behaviour changes stay separated per `CLAUDE.md`.

### Global constraints

Every phase's requirements implicitly include this section.

- **Zero new dependencies.** No additions to `pyproject.toml`'s dependency
  list, no `uv lock` churn. `PyYAML==6.0.3` and `httpx==0.28.1` are pinned and
  are the tools for the job. `jsonschema`, `pytest-benchmark`, `rich`,
  `litellm` and friends are forbidden.
- **No changes to `algorithms/`.** The extraction contract is untouched. Do
  not edit any file carrying an `# EXTRACTED:` or `# PORTED:` marker.
- **Default checks stay offline and deterministic.** Nothing added here may
  open a socket under a plain `uv run pytest` — and B2 makes that a test, not
  a convention.
- **`tools/runner.py` keeps its path** for the duration of this rollout; CI's
  `repository-shape` job asserts it. It is deleted later by
  the TUI track's phase G.
- **`tests/test_tool_registry_coverage.py::NOT_TOOL_MODULES` must gain
  `tools.bench` in the same commit that creates the package** (phase 4c).
  `pkgutil.iter_modules` yields packages as well as modules, so the commit
  that creates `tools/bench/` without that edit fails the suite.
- **No linter or formatter is configured.** Match the surrounding style:
  `from __future__ import annotations`, `__all__`, module docstrings, 4-space
  indent, double quotes, ~88-column soft wrap.
- **Cite registry tools as `name.property`, never by line number.**

### Verification commands

```bash
uv run pytest                              # green, offline, no keys
uv run pytest tests/test_runner_session.py -v   # the 4a gate, unedited
python3 -m compileall tools algorithms tests
git diff --check
```

### Phases — all landed 2026-09-13

Delivered on `agent/model-benchmark` off `dev`, one commit per phase, each with
`uv run pytest` green, `compileall` clean and `git diff --check` clean.

| Phase | Commit | Outcome |
| --- | --- | --- |
| **4a** | `Extend the session manifest to schema version 2` | v2 payload + the four-line engine wiring. `tests/test_runner_session.py` passed **unedited**. First task discharged: all four adapters do populate `latency_ms` and `usage` (Ollama through `OpenAIBackend.complete`); Gemini and Ollama gained the missing assertions. |
| — | `Record a list-returning tool's result instead of crashing the loop` | **Not a benchmark phase.** A pre-existing defect the harness surfaced: `list_photometric_catalogs`, `list_artifacts` and `list_zeropoint_references` return `list[Model]`, and `.model_dump()` on a list raised mid-dispatch. Separate commit, at the maintainer's direction. |
| **4b** | `Add ReplayBackend and the recorded-transcript format` | `tools/llm/replay_backend.py`, `benchmarks/transcripts/smoke.json`. |
| **4c** | `Add the benchmark tool plane and fixture store` | `plane.py` (B1 closed), `fixtures.py` (B3, S5, S6, S7). Open question 1 answered: the class-M predicate is asserted against the tool's own registry schema. |
| **4d** | `Add benchmark record mode with the credential scan` | S2, plus imperative-string flagging for review. |
| **5a** | `Add the benchmark task loader, run loop, and kepler-bench run` | S5, S6, B2, B4, B5, B7. |
| **5b** | `Add the four benchmark graders and the grade verb` | The three kinds of right answer, the four fidelity families, three clocks. |
| **5c** | `Add the benchmark matrix and the compare/record verbs` | B6; headline axes first, no blended score by default. |
| **5d** | `Add the benchmark corpus` | 16 tasks, five suites. Two pulsar task premises were measured and both original guesses were wrong (§9.3). **Calibration gate met 2026-09-14** for every suite but `smoke`; see each `calibration.md`. |
| ~~**5e**~~ | ~~`Add the opt-in LLM judge, isolated by construction`~~ | Built, run once over a full sweep, and **removed** — see 7.5. |
| **docs** | this commit | this document, model-backends.md §5/§6/§9/§11, `docs/working/README.md`, `docs/tool-architecture.md` §10.1, `CLAUDE.md`. |

The original per-phase gate table, kept as the specification each phase was
built against:

| Phase | Content | Gate |
| --- | --- | --- |
| **4a** | Manifest v2: `sessions.py` (`schema_version`, `backend`, `usage_totals`, per-turn latency/usage/`raw_stop_reason`, the `artifact_subdir` override, `record_turn` keywords) + the four-line `engine.py` wiring. **First task: confirm all four adapters populate `latency_ms` and `usage`** (section 1) — Q2 has no data without it. | `tests/test_runner_session.py` passes **unedited**; a recorded v1 manifest still reads and grades; absent usage reads as `None`; each adapter's round-trip test asserts a non-`None` `latency_ms` and a populated `Usage`. |
| **4b** | `tools/llm/replay_backend.py` + the transcript format + `benchmarks/transcripts/smoke.json`. | A transcript drives a full `run_session` to `end_turn`; exhaustion raises `TranscriptExhausted`. |
| **4c** | `tools/bench/` package, `plane.py`, `fixtures.py`. Creates the package → the `NOT_TOOL_MODULES` edit lands here. | B1 (plane closed), B3 (revalidation), S7 (artifact synthesis); `functools.wraps` keeps every empty-`properties` tool faulting as it does in production. |
| **4d** | `record.py`: live capture, credential scan, imperative-string flagging. | S2: a capture made with credentials in the environment contains no substring of any of them. |
| **5a** | `tasks.py` + `harness.py` + the run-directory writer + `cli.py` with `run` only. | S5, S6, B4, B5 (token budget), B7; the smoke suite runs end to end offline against `ReplayBackend` with no socket (B2). |
| **5b** | The four graders + the `grade` verb. Answer correctness (the four families), efficiency (three clocks, four token classes), trajectory, protocol. | Each grader green against synthetic and adversarial manifests; a v1 manifest grades without crashing; the timing-per-token rate excludes tool time and labels streaming vs. averaged; `must_source_value` flags a fabricated number and does not fail a derived one. |
| **5c** | `report.py` + the `compare` verb. | Matrix renders; the header carries the corpus hashes, the host, the fixture miss rate, and any incomplete outcomes. |
| **5d** | The corpus: `core` (8 tasks), `fieldcal`, `pulsar`, `optical`, `smoke`, and their fixtures. **A data PR** — fixture diffs are reviewed as adversarial input, not test data. | Every task loads; every fixture revalidates; the `core` suite runs end to end against `ReplayBackend`; **and the 7.1.9 calibration has been run against ≥3 backends of different tiers, with `calibration.md` committed** — a suite that has not discriminated anything is not a suite. |
| ~~**5e**~~ | ~~`judge.py` and the `--judge` flag.~~ Removed (7.5): an advisory column over checks that could be fixed made a broken check survivable instead of urgent. |
| **docs** | Its own PR, last. | See below. |

### Files this rollout creates

| Path | Phase |
| --- | --- |
| `tests/test_sessions_manifest_v2.py` | 4a |
| `tools/llm/replay_backend.py`, `tests/test_llm_replay_backend.py`, `benchmarks/transcripts/smoke.json` | 4b |
| `tools/bench/{__init__,plane,fixtures}.py`, `tests/test_bench_plane.py`, `tests/test_bench_fixtures.py` | 4c |
| `tools/bench/record.py`, `tests/test_bench_record.py` | 4d |
| `tools/bench/{tasks,harness,cli}.py`, `tests/test_bench_tasks.py`, `tests/test_bench_harness.py` | 5a |
| `tools/bench/graders/{__init__,answer,efficiency,trajectory,protocol}.py`, `tests/test_bench_graders.py`, `tests/test_bench_correctness.py`, `tests/test_bench_efficiency.py` | 5b |
| `tools/bench/report.py` | 5c |
| `benchmarks/suites/{core,pulsar,optical,smoke}/**`, `benchmarks/fixtures/**` | 5d |

### Files this rollout modifies

| Path | Change |
| --- | --- |
| `tools/sessions.py` | 4a: manifest v2, the `artifact_subdir` override, `record_turn` keywords. |
| `tools/agent/engine.py` | 4a: pass usage/latency/raw stop reason into `record_turn`; set `session.backend`. **The only engine edit in this rollout.** |
| `tests/test_tool_registry_coverage.py` | 4c: add `tools.bench` to `NOT_TOOL_MODULES`. |
| `pyproject.toml` | 5a: the `kepler-bench` console script. **No dependency changes, no new markers.** |
| `docs/tool-architecture.md`, `docs/working/README.md`, `README.md`, `CLAUDE.md`, this document | documentation phase |

**Deliberately not touched:** `tools/registry.py` — the schemas are the input
to translation and classification, never a subject of them; `tools/llm/`'s four
adapters; `tools/runner.py`; anything under `algorithms/`.

### Documentation phase

- [x] Update this document's status per phase with PR numbers, and mark S1,
      S2, S5, S6, S7 implemented in **both** this document and
      model-backends.md section 5 — that document's status block currently
      says they are "not yet built," and leaving it saying so is exactly the
      stale-documentation failure `CLAUDE.md` already carries scars from.
- [x] model-backends.md: mark phases 4–5 done in the section 9 status table,
      record that open question 3 (the price table) is **closed as not built** —
      no cost axis, no price table — and point section 6 at this document.
- [x] `docs/working/README.md`: add the row, and state that the benchmark is
      the Model track's second half rather than a new track.
- [x] `docs/tool-architecture.md`: a subsection describing `tools/bench/` —
      the three tool classes, that the harness reads manifests and substitutes
      `tool_functions`, and that it adds nothing to the tool surface.
- [x] `CLAUDE.md`: extend *Python domain boundaries* with `tools/bench/` — it
      reads the registry and the manifest and owns no tool; nothing under
      `algorithms/` or `tools/llm/` imports it; the plane is closed and a new
      registry tool must be classified in the same commit that adds it.
- [x] **Verify every claim against the code before writing it.**
- [ ] When the track lands, fold the durable outcome into a top-level
      `docs/` reference and delete both working documents, per
      `docs/working/README.md`'s lifecycle rule. **Blocked on the §7.1.9
      calibration run** — a harness whose answer keys have never met a real
      model is not a landed track.

---

## 15. Divergences from model-backends.md Section 6

Stated rather than silently taken.

1. **Local tools run live** (section 3). Section 6.3 implies every tool result
   is replayed. Replaying `compute_pulsar_periodogram` would replace the
   measurement with a guess about the measurement.
2. **`grade` is a separate verb.** Section 6.6 lists `run`, `record`,
   `compare`. A grader's first version is wrong, and re-grading must not cost
   a re-spend.
3. **There is no cost axis, no price table and no `estimated_usd`.** Section
   6.4 grades "estimated USD from `benchmarks/prices.json`" and section 7 puts
   a price in the manifest. Neither ships. A price table is a maintenance
   liability that produces confident wrong numbers the day it goes stale, and
   the question it answers is one a reader can answer themselves from the token
   counts and their own pricing page. Tokens are the measurement; money is not.
   Spending is *bounded* instead, in tokens (5.7). This closes
   model-backends.md open question 3 as **not built** rather than as resolved.
4. **One task per file** under `benchmarks/suites/<suite>/`, rather than
   `suites/core/*.yaml` as an undifferentiated glob, so a corpus diff is
   reviewable per task and a suite's membership and order are explicit.
5. **`answer.txt` exists.** Section 1's "the benchmark is a reader of session
   manifests" holds for four of the five graders; `_bounded_text` truncates
   the answer grader's input at 4,000 characters.
6. **Seven new requirements (B1–B7)**, chiefly B1: the registry drifted 49→55
   during the port's own implementation, and an unclassified tool in a replay
   run is a live service call inside a benchmark that believes it is offline.
7. **Two headline axes, two diagnostic ones.** Section 6.1 lists four co-equal
   axes. The harness is built to answer two questions — correctness and
   efficiency — so those are read first, and the two that answer neither
   (trajectory, protocol) are marked diagnostic: explanations of a headline
   number, not scores in their own right.
8. **Efficiency is three clocks, not one.** Section 6.4 says "wall-clock per
   turn." Undivided wall clock on this surface ranks models by which tools they
   called; model time, tool time and wall clock are reported separately, and
   timing per token is derived from the model clock alone.
9. **Four token classes, reported separately.** `SYSTEM_PROMPT` plus 55 tool
   schemas is a large fixed prefix resent every turn, so cache reads dominate a
   multi-turn task's input total, and folding them into one input number hides
   a real difference in work done.
10. **Answer correctness distinguishes three kinds of right answer.** Section
    6.4 treats correctness as one thing graded by regexes, numeric comparison
    and artifact-path presence. On this surface it is three (7.1.2): a
    **ground-truth** answer the repository recorded before the model ran, a
    **fidelity** answer that must match what the tools returned this session,
    and a **correct negative** where a confident answer is itself the failure.
    They need different machinery, and conflating them grades phrasing.
11. **Ground-truth keys are tool verdicts, not regexes.** `data/` already holds
    five curated pulsar periods, four recorded Skynet zero-point solves and the
    Afterglow cross-implementation values — the same truth `tests/` pins
    against — and `compare_zeropoint_to_reference` already computes agreement
    with it. `must_reach_verdict` reads that boolean, so the strongest checks
    in the corpus compare structured output to structured truth. Each is paired
    with a provenance constraint, because a model can otherwise hand the
    reference its own number back.
12. **A suite is untrusted until calibrated** (7.1.9). Three backends of
    different tiers, and a committed `calibration.md`; a task passed by all or
    by none is reviewed before the suite is believed. Phase 5d gates on it.

---

## 16. Non-Goals and Deferred Work

* **No HTML report.** Markdown and JSON. If one is added later, B6 applies.
* **No CI benchmark job.** CI stays offline, deterministic and keyless; the
  harness's CI presence is the smoke suite against `ReplayBackend`.
* **No leaderboard published anywhere.** The matrix is a local artifact.
* **No CLI-agent or MCP backend.** The `ModelBackend` protocol permits one;
  nothing here builds one.
* **No composite score by default.**
* **No fixture recording of class-L tools.** By construction — they are the
  thing being exercised.
* **`solve_astrometry` stays blocked by default** until `optical-tools.md` P9
  supplies an operator UCAC tree and the ATLAS backend is validated.
* **No migration of `tools/claude_photometry_haiku_tool.py`.** Deferred by
  model-backends.md section 10; deleted by the TUI track's phase C.

---

## 17. Open Questions

**1. How is a class-M offline predicate kept honest?** `calibrate_zeropoint`'s
offline path needs `catalog_fixture` *and* `compare_to` together; if that
contract changes in `tools/photometry.py`, the predicate in `plane.py` goes
stale and the tool quietly starts being replayed when it could have run live.
Leaning toward asserting the predicate against the tool's own schema in the
B1 test — the enum values are in `registry.py` and can be compared — rather
than duplicating the rule in prose. **Open.**

**2. Should a repeat's variance be a reported failure?** A model that passes a
hard check two runs in three is not the same as one that passes it three times,
and today the matrix would show both as "2/3". Leaning toward a separate
`stability` column rather than folding variance into the axes. **Open.**

**3. How long can a fixture stay recorded before it is a fiction?** The
services behind class R change: VizieR gains catalogs, ADS changes its parser,
NED's resolver behaviour is already documented as unreliable. A two-year-old
fixture grades a model against an archive that no longer exists. Leaning
toward a `recorded_on` field (already in the format) plus a report warning past
180 days. **Open.**

**4. Which frontier models are the reference set?** model-backends.md open
question 1 settled the *local* reference model at `qwen3.8:27b-mlx` and left
the frontier tier for these phases. It should be one model per provider at a
comparable tier, chosen when 5d lands, and recorded in `run.json` — not
hard-coded in the suite, which must stay model-agnostic. **Open.**

---

## 18. References

* [model-backends.md](model-backends.md) — the port this consumes; section 6
  is the design summary, section 9 the phase index, section 5 the security
  requirements deferred here.
* `docs/tool-architecture.md` section 10 — the engine event contract the
  harness reads, and of `tools/runner.py`'s eventual deletion.
* `tools/agent/engine.py` — `run_session`'s `tool_schemas=`/`tool_functions=`
  seam, and the `scoped_artifacts` wrapper.
* `tools/agent/prompt.py` — `SYSTEM_PROMPT`, the source of the core suite's
  eight failure modes.
* `tools/sessions.py` — the manifest extended to v2 in phase 4a.
* `tools/llm/validation.py`, `tools/llm/types.py` — the S8 rule table and the
  seven-fault taxonomy the protocol grader counts.
* `tools/llm/schema.py` — why the scalar-or-null union is never downgraded.
* `tools/artifacts.py` — `scoped_artifacts` and `reserve_artifact_path`, the
  mechanism behind S7.
* `tests/llm_fakes.py` — `StubBackend`, the starting point for `ReplayBackend`.
* `docs/pulsar-tool-pipeline.md` — why the stage order is a dependency and why
  a wrong period returns a flat profile.
* `data/pulsar/curated_periods.json` — the pulsar suite's answer keys, and the
  document's own statement of why a curated period is a check and not an input.
