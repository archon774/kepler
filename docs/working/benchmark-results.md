# Benchmark Results — Kepler's `core` Suite

**What this is:** the recorded scoreboard for [benchmark.md](benchmark.md)'s
`core` suite. One column per backend; a new provider appends rather than
replaces, so the grid stays diff-reviewable.

**Status:** **partially calibrated.** Two backends of two tiers have run it.
§7.1.9 wants **three of different tiers** before a suite is trusted, so this is
evidence, not a verdict. The other providers the port supports (OpenAI, Gemini)
have no credentials on this host.

**Corpus:** de-biased — see [Why the earlier numbers are
gone](#why-the-earlier-numbers-are-gone). Suite SHA-256 `b681227692d1`,
clean, repository `4a0c892`.

**Runs:** 2026-09-14, one host, sequential (not concurrent, so the timing
columns are comparable), 1 repeat each.

---

## Headline

| Backend | Tier | Dialect | Correctness | Tokens per answer | Turns | Calls | Faults |
| --- | --- | --- | --- | --- | --: | --: | --: |
| `ollama/qwen3.8:27b-mlx` | local 27B | `openai_function` | ✅ **8 / 8** `████████████████` | `████████░░░░░░░░` **93,246** | 34 | 47 | 0 |
| `anthropic/claude-sonnet-5` | frontier | `json_schema` | ⚠️ **6 / 7** `██████████████░░` + 1 ⏳ | `████████████████` **176,578** | 56 | 83 | 0 |

*Tokens per answer* = tokens across runs that **passed**, ÷ the number that
passed. **Lower is better.** ⏳ = incomplete: did not answer, and by §7.1.8
never scored as a low pass rate.

**Zero protocol faults from either backend**, across 130 tool calls and both
schema dialects. `search_vizier.max_catalogs` — the integer-or-null union
`schema.py` refuses to downgrade — was passed as JSON `null` by both, which is
the only correct way to request an uncapped result.

---

## Per-task grid

| # | Task | Kind | `qwen3.8:27b-mlx` | `claude-sonnet-5` |
| --: | --- | --- | :-: | :-: |
| 1 | `vizier-category-not-per-catalog` | fidelity | ✅ `3/3` | ⏳ `max_turns` |
| 2 | `no-identical-retry` | correct negative | ✅ `2/2` | ✅ `2/2` |
| 3 | `ned-formal-designation` | fidelity | ✅ `3/3` | ❌ `2/3` |
| 4 | `atnf-formal-designation` | fidelity | ✅ `3/3` | ✅ `3/3` |
| 5 | `pulsar-period-not-from-audio` | ground truth | ✅ `2/2` | ✅ `2/2` |
| 6 | `preview-is-not-the-answer` | fidelity | ✅ `4/4` | ✅ `4/4` |
| 7 | `abstract-before-attribution` | fidelity | ✅ `2/2` | ✅ `2/2` |
| 8 | `null-argument-fidelity` | fidelity | ✅ `2/2` | ✅ `2/2` |

**Two tasks discriminated; six did not.** Six tasks passed by both is what
§7.1.9 calls "too loose or too easy" pending a third backend — do not tighten
on two data points.

---

## The one failure, and the one incomplete

### 3 · `ned-formal-designation` — an unciteable artifact

Sonnet wrote *"full contents in the saved file"* and quoted **no path** — its
answer contains zero path strings, so a reader cannot find the file. qwen
quoted the full path. `must_report_artifact_path` checks the answer against
paths in the manifest, not against a path-shaped regex, so an invented path
would fail too.

A real behavioural difference, and the check that caught it is structural —
it reads the manifest, not prose.

### 1 · `vizier-category-not-per-catalog` — **the suite's limit, not the model's**

| | qwen | Sonnet |
| --- | --: | --: |
| Turns | 7 | 20 (cap) |
| Tool calls | 13 | 38 |
| Fixture misses | 2 | 23 |
| `not_found` results | — | 31 of 38 |
| Distinct tools reached | — | 12 |

Sonnet made 13 calls to `build_literature_review` alone. **No call errored** —
every undeclared tool returned a synthesized `not_found`, the model read that
as "try another archive," and it never ran out of archives before it ran out
of turns.

This is the second form of the same defect. With `miss_policy: error` the
model was derailed by errors; with `synthesize` it is invited to retry
forever. The root cause is unchanged: **an open-ended prompt against a sparse
fixture world.** A real NED/ADS/SIMBAD query for Cassiopeia A returns plenty;
an empty one punishes a model that verifies across sources.

Raising the cap did not fix it and raising it further will not — see
[Open actions](#open-actions).

> **A finding is hidden here.** qwen answered this in 13 calls; Sonnet made 38
> and never answered. That difference is real and worth measuring, but
> `incomplete` is excluded from the pass rate by design, so it does not appear
> in the headline. The efficiency columns are where it shows.

---

## Efficiency

Three clocks, reported separately, never combined into one. **Tool time is
~0.15% of wall clock here** because every remote tool is replayed; in
production it dominates (field calibration is a 30–90 s round trip). These
numbers measure the model, not the surface.

| Backend | Model time | Tool time | Wall clock | Input | Output |
| --- | --- | --- | --- | --- | --- |
| `qwen3.8:27b-mlx` | `████████████████` 922 s | 1.4 s | 924 s | 733,006 | 12,966 |
| `claude-sonnet-5` | `████░░░░░░░░░░░░` 236 s | 1.5 s | 239 s | 1,840,051 | 19,925 |

Model time per task:

| Task | `qwen3.8:27b-mlx` | `claude-sonnet-5` |
| --- | --- | --- |
| `vizier-category-not-per-catalog` | `████████████████` 246 s | `█████░░░░░░░░░░░` 70 s ⏳ |
| `no-identical-retry` | `██░░░░░░░░░░░░░░` 37 s | `░░░░░░░░░░░░░░░░` 8 s |
| `ned-formal-designation` | `██████░░░░░░░░░░` 100 s | `█░░░░░░░░░░░░░░░` 19 s |
| `atnf-formal-designation` | `██░░░░░░░░░░░░░░` 37 s | `░░░░░░░░░░░░░░░░` 5 s |
| `pulsar-period-not-from-audio` | `█████████░░░░░░░` 138 s | `█░░░░░░░░░░░░░░░` 16 s |
| `preview-is-not-the-answer` | `███████████████░` 227 s | `██████░░░░░░░░░░` 85 s |
| `abstract-before-attribution` | `██████░░░░░░░░░░` 95 s | `█░░░░░░░░░░░░░░░` 21 s |
| `null-argument-fidelity` | `███░░░░░░░░░░░░░` 42 s | `█░░░░░░░░░░░░░░░` 12 s |

**Sonnet is ~3.9× faster in model time and uses ~2.5× the input tokens.** Both
follow from the same behaviour: it takes more turns and makes more calls (56
turns / 83 calls vs 34 / 47), and every turn re-sends the 55 tool schemas —
about 15k tokens of fixed prefix. Neither number is a quality judgement, and a
hosted API and a local daemon are **not comparable on latency at all**: one is
network round-trip, the other is this host's own hardware.

Neither backend reported cached tokens. Ollama's compatibility endpoint omits
the field; this Anthropic run set no cache breakpoints. A dash is not a zero.

---

## Determinism

**`claude-sonnet-5` rejects `temperature`** — the API answers a request
carrying it with a 400, so the adapter retries without it and records
`temperature_supported: false`. The determinism §5.6 claims from temperature 0
**does not hold for that backend**, and with 1 repeat a single run cannot
distinguish a characteristic behaviour from a coin flip.

This is not hypothetical. An earlier run of task 5 had Sonnet write that
*"mains interference at 0.01667 s and baseline red noise near 2.1–2.2 s were
the other candidate peaks in `top_peaks`"* — `top_peaks` actually held
`0.71479, 0.14288, 0.17847, 0.23777, 0.11916`, and neither quoted value is in
it. Those are real artefacts on *other* bundled scans, so it was correct
domain knowledge attributed to this session's tool output: §7.1.4's
fabrication family exactly, caught by `must_source_value` reading
`events.jsonl`.

**In this run the same task passed, because Sonnet simply did not make the
claim** — zero mentions of `top_peaks`, mains or red noise. So the *check*
works; whether the *behaviour* is characteristic is unresolved, and one run
each cannot settle it. `--repeats 3` is the instrument, not more key tuning.

---

## Why the earlier numbers are gone

Three earlier runs are not in the tables above, because they were graded
against a corpus that had been adjusted against one of the two models. Keeping
them beside these would imply a comparability they do not have.

| Run | Result | What it found |
| --- | --- | --- |
| qwen r1 | 6/8 | Two prompts with no antecedent ("this field"); two tasks passing on `0/0` checks; a `must_not_call` punishing correct behaviour; `"4,127"` parsed as `4` and `127` |
| qwen r2 | 6/8 | Two false positives in the keys added after r1 |
| Sonnet (biased corpus) | 5/7 + 1 ⏳ | The fixture-coverage defect, and the fabrication above |

Three things were then removed as model-specific:

1. **The sourcing vocabulary had been grown from one model's prose.**
   `BACKGROUND_LABELS` reached 21 entries of which **14 were not in
   `SYSTEM_PROMPT`** — `"paraphrase"`, `"if you've seen"`, `"commonly quoted"`
   and others were added after watching one model hedge. Every later provider
   was being measured against words it was never given. It is now 9 entries,
   each a phrase the system prompt uses, **enforced by a test**.
2. **The turn cap encoded one model's habits.** `max_turns: 8`, chosen with no
   evidence, against one model that never exceeds 5 turns and another that
   needs 8–20. A test now asserts no cap is tight enough to decide an outcome.
3. **A test rejects any task file naming a model or provider.**

The `4,127` parsing bug and the over-broad NED pattern were *general* defects
that would have misjudged any provider; those fixes stand.

---

## Corpus review

§7.1.9's table, applied. **This matters more than the scoreboard.**

| Observed | Task(s) | Action |
| --- | --- | --- |
| Both pass | 2, 4, 5, 6, 7, 8 | **Pending.** Too loose, too easy, or well-handled — a third backend decides. |
| One fails | 3 | **Keep.** Structural check, verified against the manifest. |
| Neither completes | 1 | **Fix the suite.** See below. |

### Open actions

1. **Fixture coverage, and it is now the only blocker.** Task 1 needs recorded
   responses for the tools a model actually reaches — `build_literature_review`,
   `search_simbad_bibliography`, `search_simbad_measurements`, `search_casda`,
   `get_citing_papers`, `get_referenced_papers`. Neither `error` nor
   `synthesize` fixes a world that is simply empty. This is real capture work
   and would change results for every provider, so it needs its own pass.
2. **`--repeats 3`, at least for the backend that cannot set temperature.**
   One run each cannot tell a characteristic behaviour from variance, and
   §5.6's spread column exists for this.
3. **Six tasks discriminate nothing yet.** Do not tighten them on two
   backends; a third is the evidence that would justify it.
4. **A third tier is still required** for §7.1.9. OpenAI and Gemini adapters
   exist and are untested against a real endpoint; both need credentials.
5. **The fixtures remain hand-authored, not captured.** Counts like "47
   catalogs" and "4,127 rows" are plausible placeholders, so a key asserting
   one grades the right *behaviour* against a number this repository invented.
6. **The suite misses whole classes of error.** In a passing answer, one model
   called B0329+54 *"a fast, bright millisecond-adjacent pulsar"*; its period
   is 715 ms. No check looks at whether an object's characterisation is sane,
   so nothing caught it. This suite measures a narrow set of documented
   failure modes, not answer quality.

---

## How to add a provider's results

1. Run it. `--max-tokens` is required for any live backend — there is no
   default, because a default budget is a number nobody thinks about.

   ```bash
   kepler-bench run core \
     --backend openai/gpt-5 \
     --repeats 3 --max-tokens 3000000 \
     --out artifacts/bench/<date>-core-<model>
   ```

2. `run` grades automatically; `kepler-bench grade <run-dir>` re-grades offline
   after a grader fix, without re-spending.
3. `kepler-bench compare <run-dir>...` merges runs into one matrix.
4. Add a **Headline** row and one **Per-task grid** column. Keep the task order
   fixed so the grid diffs cleanly.
5. Re-run **Corpus review** — and if a key has to change to accommodate the new
   provider, **re-run every backend**, or the comparison is not one.

## Reading these numbers honestly

- **Latency is one host, one day.** Comparable between models *within* a run,
  not across runs, and not at all between a hosted API and a local daemon.
- **Every rate here is averaged, not streaming.** Only the Anthropic adapter
  streams natively; the others call `on_text` once with the finished text.
- **A dash is not a zero.** A provider that did not report a token class did
  not report zero of them.
- **There is no cost column.** Tokens are the measurement; money is the
  reader's arithmetic against their own current pricing page (§15.3).
- **`incomplete` is not a failure.** It did not answer badly — it did not
  answer.
- **Only the schema dialect varies besides the model**, deliberately (§7.1.1):
  a model is only usable here through the dialect its provider speaks.
