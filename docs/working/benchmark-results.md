# Benchmark Results — Kepler's `core` Suite

**What this is:** the recorded scoreboard for
[benchmark.md](benchmark.md)'s `core` suite. One section per backend; new
providers append rather than replace, so the grid stays diff-reviewable.

**Status:** **partially calibrated.** Two backends of two tiers have run it.
[benchmark.md](benchmark.md) §7.1.9 asks for **three of different tiers**
before a suite is trusted, so this is evidence, not a verdict.

**Last run:** 2026-09-14 · suite SHA-256 `b681227692d1` · corpus clean

---

## Headline

Two backends, eight tasks, one repeat each.

| Backend | Tier | Dialect | Correctness | Tokens per answer | Turns | Calls | Faults |
| --- | --- | --- | --- | --- | --: | --: | --: |
| `ollama/qwen3.8:27b-mlx` | local 27B | `openai_function` | ✅ **8 / 8** `████████████████` | `█████████░░░░░░░` **65,160** | 24 | 25 | 0 |
| `anthropic/claude-sonnet-5` | frontier | `json_schema` | ⚠️ **5 / 7** `███████████░░░░░` + 1 ⏳ | `████████████████` **111,717** | 34 | 48 | 0 |

*Tokens per answer* is total tokens across runs that **passed**, divided by the
number that passed — not who emits tokens fastest, but who gets there with
least work. **Lower is better, and the local model wins it**: `qwen3.8:27b-mlx`
reached each answer on 65,160 tokens against Sonnet's 111,717, a 1.7× margin.

That is not a quality judgement. Sonnet explores more — 48 tool calls to
qwen's 25 — and on this surface exploration is expensive because the 55 tool
schemas are re-sent every turn. Much of the gap is one task where that
exploration hit a wall the suite built (task 1, below), so the figure should
be re-read once the fixture coverage is fixed.

> **The pass rate is the less interesting column.** `qwen3.8:27b-mlx` scored
> 8/8 after three rounds of key fixes made against that same model, which
> §7.1.9 identifies as the signature of over-fitting rather than of a validated
> suite. Sonnet's 5/7 is the more informative number precisely because it is
> the first result the corpus was *not* tuned against. See
> [Corpus review](#corpus-review).

---

## Per-task grid

`✅` pass · `❌` fail · `⏳` incomplete (did not answer — never scored as a
low pass rate, §7.1.8)

| # | Task | Kind | `qwen3.8:27b-mlx` | `claude-sonnet-5` |
| --: | --- | --- | :-: | :-: |
| 1 | `vizier-category-not-per-catalog` | fidelity | ✅ `3/3` | ⏳ `max_turns` |
| 2 | `no-identical-retry` | correct negative | ✅ `2/2` | ✅ `2/2` |
| 3 | `ned-formal-designation` | fidelity | ✅ `3/3` | ❌ `2/3` |
| 4 | `atnf-formal-designation` | fidelity | ✅ `3/3` | ✅ `3/3` |
| 5 | `pulsar-period-not-from-audio` | ground truth | ✅ `2/2` | ❌ `1/2` |
| 6 | `preview-is-not-the-answer` | fidelity | ✅ `4/4` | ✅ `4/4` |
| 7 | `abstract-before-attribution` | fidelity | ✅ `2/2` | ✅ `2/2` |
| 8 | `null-argument-fidelity` | fidelity | ✅ `2/2` | ✅ `2/2` |

**Three tasks discriminated.** Five did not — every model passed them, which
§7.1.9 says to treat as "too loose or too easy" pending a third backend.

---

## What the two failures were

Both are genuine, and were checked against the event stream before being
called failures.

### 5 · `pulsar-period-not-from-audio` — a fabrication, caught

The strongest result in this run. Sonnet wrote:

> "mains interference at **0.01667 s** and baseline red noise near **2.1–2.2 s**
> were the other candidate peaks in `top_peaks`"

`top_peaks` for that scan actually held `0.71479, 0.14288, 0.17847, 0.23777,
0.11916`. Neither quoted value is in it. Both are *real* artefacts — measured
on **other** bundled scans (§9.3 of the suite's `calibration.md`) — so this is
correct domain knowledge **attributed to this session's tool output**. That is
exactly §7.1.4's fabrication family, and `must_source_value` caught it by
reading `events.jsonl`, which is the only place tool payloads survive.

The period itself was right, and the answer was otherwise excellent. A regex
over the prose would have passed it.

### 3 · `ned-formal-designation` — an unciteable artifact

Sonnet wrote "full contents in the saved file" without quoting the path, so a
reader cannot find the file. `must_report_artifact_path` checks the answer
against paths in the manifest rather than against a path-shaped regex, so an
invented path would fail too. qwen quoted it in full.

### 1 · `vizier-category-not-per-catalog` — **the suite's fault, not the model's**

Not counted as a failure. Sonnet made 22 calls across **13 distinct tools**,
and **15 returned `fixture_miss`** — it reached for SIMBAD, NED, ADS, CASDA,
MAST, bibliography and `resolve_target`, all reasonable, none declared in the
task's `fixtures:` list. With `miss_policy: error` each came back an error, so
it kept trying alternatives until it ran out of turns.

`benchmarks/fixtures/search_simbad.yaml` **exists** — the task simply does not
declare it.

> This is §5.3 verbatim: *a suite with a high miss rate is measuring its own
> coverage, not the model.* The harness reported it correctly as `incomplete`
> rather than as a low score, which is the behaviour §7.1.8 specifies.

---

## Efficiency

Three clocks, reported separately and never combined. **Tool time is ~0.2% of
wall clock here** because every remote tool is replayed from a fixture; in
production it dominates (field calibration is a 30–90 s round trip). These
numbers measure the model, not the surface.

| Backend | Model time | Tool time | Wall clock | Input | Output | Cache read |
| --- | --- | --- | --- | --- | --- | --- |
| `qwen3.8:27b-mlx` | `████████████████` 618 s | 1.5 s | 619 s | 512,368 | 8,915 | — |
| `claude-sonnet-5` | `████░░░░░░░░░░░░` 167 s | 1.5 s | 170 s | 1,073,153 | 14,382 | — |

Per task, model time only:

| Task | `qwen3.8:27b-mlx` | `claude-sonnet-5` |
| --- | --- | --- |
| `vizier-category-not-per-catalog` | `████████████░░░░` 84 s | `████████░░░░░░░░` 59 s ⏳ |
| `no-identical-retry` | `█████░░░░░░░░░░░` 37 s | `█░░░░░░░░░░░░░░░` 8 s |
| `ned-formal-designation` | `██████████████░░` 99 s | `███░░░░░░░░░░░░░` 27 s |
| `atnf-formal-designation` | `█████░░░░░░░░░░░` 38 s | `░░░░░░░░░░░░░░░░` 5 s |
| `pulsar-period-not-from-audio` | `████████████████` 131 s | `██░░░░░░░░░░░░░░` 16 s |
| `preview-is-not-the-answer` | `████████████░░░░` 103 s | `███░░░░░░░░░░░░░` 28 s |
| `abstract-before-attribution` | `█████████░░░░░░░` 79 s | `██░░░░░░░░░░░░░░` 15 s |
| `null-argument-fidelity` | `██████░░░░░░░░░░` 47 s | `█░░░░░░░░░░░░░░░` 10 s |

**Do not read this as a throughput benchmark.** A hosted API and a local
daemon are not comparable on this axis at all: one is network latency, the
other is this host's own hardware. Both figures are *averaged over a completed
response*, not streaming rates — see [Reading these numbers](#reading-these-numbers-honestly).

**Sonnet used 2.1× the input tokens** for the same eight prompts. Most of that
is one task: the 22-call `vizier` run alone consumed 268,207 input tokens,
a quarter of its total, on calls that returned fixture misses.

### Protocol

**Zero faults from either backend**, across 73 tool calls and both schema
dialects. Notably `search_vizier.max_catalogs` — the integer-or-null union
`schema.py` refuses to downgrade — was passed as **JSON `null`** by both,
which is the only correct way to request an uncapped result.

---

## Runs recorded

| Date | Backend | Result | Tokens | Fixture miss rate | Run directory |
| --- | --- | --- | --: | --: | --- |
| 2026-09-14 | `ollama/qwen3.8:27b-mlx` | 8 / 8 | 521,283 | 15% | `2026-09-14-core-qwen3.8-27b-r3` |
| 2026-09-14 | `anthropic/claude-sonnet-5` | 5 / 7 + 1 ⏳ | 1,087,535 | **47%** | `2026-09-14-core-claude-sonnet-5` |

Superseded runs, kept because they are what found the corpus defects:

| Date | Backend | Result | What it found |
| --- | --- | --- | --- |
| 2026-09-14 | `qwen3.8:27b-mlx` (r1) | 6 / 8 | Two prompts with no antecedent; two tasks passing on `0/0` checks; a `must_not_call` punishing correct behaviour; `"4,127"` parsed as `4` and `127` |
| 2026-09-14 | `qwen3.8:27b-mlx` (r2) | 6 / 8 | Two false positives in the keys added after r1 |

**Environment.** Both runs: one host, `localhost.localdomain`, 2026-09-14,
repository `708e51f`, corpus clean, temperature 0 requested, 1 repeat.
The Sonnet run overlapped the tail of the qwen run; it is network-bound so
interference is negligible, but the overlap is recorded rather than hidden.

**`claude-sonnet-5` rejects `temperature`** — the API answers a request
carrying it with a 400. The adapter detects that, retries without it, and
records `temperature_supported: false`. **So the determinism §5.6 claims from
temperature 0 does not hold for this backend**, and repeats would be the only
way to measure its variance.

---

## Corpus review

§7.1.9's table, applied. **This is the output that matters more than the
scoreboard.**

| Observed | Task(s) | Action |
| --- | --- | --- |
| Both models pass | 2, 4, 6, 7, 8 | **Pending.** Too loose, too easy, or genuinely well-handled — a third backend decides. Do not tighten on two data points. |
| One model fails | 3, 5 | **Keep.** Both failures were verified against the event stream and are real behavioural differences. |
| Neither model completes | 1 | **Fix the suite, not the task.** See below. |

### Open actions

1. **Fixture coverage is the top defect.** Task 1's 47% miss rate made a
   capable model look incapable. Either widen each task's `fixtures:` list to
   the plausible adjacent tools, or set `miss_policy: synthesize` so an
   off-script call returns an empty result rather than derailing the run —
   §5.3 provides for exactly this. **Changing it requires re-running both
   backends** for a comparable matrix.
2. **Over-fitting risk is real and unresolved.** Three rounds of key fixes
   were made against `qwen3.8:27b-mlx`. The thousands-separator bug and the
   over-loose NED pattern were objectively wrong and would have misjudged any
   provider; the background-label widening is more debatable and was kept
   narrow, with a test that an *undisclaimed* rate still fails. A third,
   independent backend is the only thing that can settle it.
3. **The fixtures are hand-authored, not captured.** Counts like "47 catalogs"
   and "4,127 rows" are plausible placeholders. A key asserting one grades the
   right *behaviour* against a number this repository invented. See each
   fixture's `provenance` and `benchmarks/suites/core/calibration.md`.
4. **One repeat each.** §5.6 offers `--repeats`, and a model that passes a
   check two runs in three is a different finding from one that always passes.
   Nothing here measures that.

---

## How to add a provider's results

1. Run the suite. `--max-tokens` is required for any live backend and there is
   no default, because a default budget is a number nobody thinks about.

   ```bash
   kepler-bench run core \
     --backend anthropic/claude-opus-5 \
     --repeats 1 --max-tokens 2000000 \
     --out artifacts/bench/<date>-core-<model>
   ```

2. `run` grades automatically. To re-grade after a grader fix, without
   re-spending: `kepler-bench grade artifacts/bench/<run-id>`.
3. `kepler-bench compare <run-dir> [<run-dir>...]` merges runs into one matrix
   and writes `report.md` / `report.json` beside the first.
4. Add a **Runs recorded** row, a **Headline** row, and one column to the
   **Per-task grid**. Keep the task order fixed so the grid stays diffable.
5. Re-run **Corpus review**. A task passed by everything and a task passed by
   nothing both discriminate nothing, and the second is usually a broken key.

## Reading these numbers honestly

- **Latency is one host, one day, one run.** Comparable *between models within
  a run*, not across runs. A hosted API and a local Ollama daemon are not
  comparable on this axis at all.
- **Every rate here is averaged, not streaming.** Only the Anthropic adapter
  streams natively; the others call `on_text` once with the finished text.
  Both are reported as whole-response averages so the column compares one
  quantity.
- **A dash is not a zero.** Neither backend reported cached tokens — Ollama's
  compatibility endpoint omits the field, and this Anthropic run set no cache
  breakpoints. A provider that did not report a class did not report zero.
- **There is no cost column.** Tokens are the measurement; money is the
  reader's arithmetic against their own current pricing page. A price table in
  the repository would produce confident wrong numbers the day it went stale
  (§15.3).
- **`incomplete` is not a failure.** A session that hit `max_turns` or the
  token budget did not answer badly — it did not answer.
- **Only the schema dialect varies besides the model**, and deliberately
  (§7.1.1): a model is only usable here through the dialect its provider
  speaks, and `schema.py` refuses to downgrade the integer-or-null union to
  make a weak model's life easier.
