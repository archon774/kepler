# Benchmark Results — Kepler's `core` Suite

**What this is:** the recorded scoreboard for [benchmark.md](benchmark.md)'s
`core` suite. One column per backend; a new provider appends rather than
replaces.

**Status:** **calibrated.** Four backends across four tiers, three repeats
each — 96 sessions, 421 tool calls. §7.1.9's gate (three backends of different
tiers) is met. What that licenses and what it does not is in
[Limits](#limits-of-this-ranking).

**Corpus:** suite SHA-256 `b681227692d1`, clean, repository `42f345a`. All 22
class-R tools have recorded fixtures. Run 2026-09-14, one host, **sequential**,
`--repeats 3`.

---

## Ranking

Ordered by the composite (§7.6), which weights the two headline axes
**0.7 correctness / 0.3 efficiency** and is off by default — a single number
hides which axis failed, so read the columns beside it.

| # | Backend | Tier | Composite | Correctness | Stability | Tokens / answer |
| --: | --- | --- | --: | --- | --- | --- |
| 1 | `ollama/qwen3.8:27b-mlx` | local 27B | **0.918** | ✅ **23/24** `████████████████` 96% | 88% | `██████████░░░░░░` 85,179 |
| 2 | `ollama/qwen3.5:9b` | local 9B | 0.787 | ⚠️ 17/24 `████████████░░░░` 71% | 75% | `████████░░░░░░░░` 72,128 |
| 3 | `ollama/gemma4:12b` | local 12B | 0.767 | ⚠️ 16/24 `███████████░░░░░` 67% | **88%** | `████████░░░░░░░░` **70,075** |
| 4 | `anthropic/claude-sonnet-5` | frontier | 0.745 | ✅ 21/24 `██████████████░░` 88% | 75% | `████████████████` 158,922 |

**Read this ranking carefully.** The composite puts the frontier model last
because it costs **2.3× the cheapest** per answer while the 27B local model
beats it on correctness. On correctness alone the order is
qwen3.8 (96%) → Sonnet (88%) → qwen3.5 (71%) → gemma4 (67%), which tracks tier
except that the 27B leads. See [Limits](#limits-of-this-ranking) before
treating either ordering as a general statement about these models.

**Zero protocol faults from any backend**, across 421 tool calls and two schema
dialects.

---

## Per-task grid

Passes out of 3 repeats. **Bold** = the task discriminated.

| # | Task | Kind | `qwen3.8:27b` | `sonnet-5` | `qwen3.5:9b` | `gemma4:12b` |
| --: | --- | --- | :-: | :-: | :-: | :-: |
| 1 | **`vizier-category-not-per-catalog`** | fidelity | 3/3 | 3/3 | 1/3 | 0/3 |
| 2 | `no-identical-retry` | correct negative | 3/3 | 3/3 | 3/3 | 3/3 |
| 3 | **`ned-formal-designation`** | fidelity | 3/3 | 2/3 | 3/3 | 0/3 |
| 4 | `atnf-formal-designation` | fidelity | 3/3 | 3/3 | 3/3 | 3/3 |
| 5 | **`pulsar-period-not-from-audio`** | ground truth | 3/3 | 3/3 | 1/3 | 3/3 |
| 6 | `preview-is-not-the-answer` | fidelity | 3/3 | 3/3 | 3/3 | 3/3 |
| 7 | **`abstract-before-attribution`** | fidelity | 2/3 | 1/3 | 3/3 | 3/3 |
| 8 | **`null-argument-fidelity`** | fidelity | 3/3 | 3/3 | 0/3 | 1/3 |

**Five of eight tasks discriminated**, up from two on the previous
two-backend run. Three are passed by everything and are candidates to tighten
or retire (§7.1.9).

---

## The two findings worth the whole exercise

### Small models fail on mechanics; large models fail on over-claiming

The failure modes invert by tier, and cleanly:

| Backend | Failing checks |
| --- | --- |
| `qwen3.8:27b-mlx` | `must_source_value` ×1 |
| `claude-sonnet-5` | `must_source_value` ×2, `must_report_artifact_path` ×1 |
| `qwen3.5:9b` | `must_report_artifact_path` ×4, `must_report_value` ×3, `must_disclose` ×1 |
| `gemma4:12b` | `must_report_artifact_path` ×6, `must_disclose` ×2, `must_report_value` ×1 |

The two smaller models fail almost entirely on **citation mechanics** — not
quoting the artifact they wrote, not reporting the number the tool returned,
not acknowledging a warning that fired. The two larger ones pass all of that
and fail instead on **saying more than the tools support**.

### Both large models reproduced the exact documented fabrication

Task 7's failures are not generic over-claiming. `SYSTEM_PROMPT` warns about
one specific incident by name:

> *An agent asked to confirm a decline rate once answered "0.3-0.7%/yr
> depending on frequency" and attributed it by name to a real paper (Trotter
> et al. 2017) — the actual abstract says "0.670 +/- 0.019%/yr".*

`claude-sonnet-5` emitted **0.7** and `qwen3.8:27b-mlx` emitted **0.3 and
0.7** — the warned-about figure, in a session where no tool returned it, with
the warning in their context. Neither smaller model did, because neither has
the association to recall.

`must_source_value` caught it by reading `events.jsonl`, which is the only
record of what the tools actually returned. This is the single strongest
argument in the results for keeping that check, and for the event stream
existing at all.

### A plan prediction that did not survive contact

§7.4 calls `null_argument_fidelity` "**the single most discriminating check in
the suite for small local models**." It is not. **All four backends passed
JSON `null` on every repeat** — including the 9B. Task 8 still discriminated,
but on `must_report_artifact_path`, not on the union.

The integer-or-null union that `schema.py` refuses to downgrade is handled
correctly by every model tested here. That is a real result about the port's
schema translation, and it means the prediction should be revised rather than
repeated.

---

## Stability

Share of tasks giving the same verdict across all three repeats (§17 q2).

| Backend | Stability | Flaky tasks |
| --- | --- | --- |
| `qwen3.8:27b-mlx` | `██████████████░░` 88% | `abstract-before-attribution` |
| `gemma4:12b` | `██████████████░░` 88% | `null-argument-fidelity` |
| `claude-sonnet-5` | `████████████░░░░` 75% | `ned-formal-designation`, `abstract-before-attribution` |
| `qwen3.5:9b` | `████████████░░░░` 75% | `vizier-category-not-per-catalog`, `pulsar-period-not-from-audio` |

**No backend was stable on everything.** At `--repeats 1` every one of these
would have looked deterministic, and six task-level results would have been
coin flips reported as facts. `claude-sonnet-5` **cannot be given a
temperature** — its API rejects the parameter — so nothing bounds its drift
but repetition.

---

## Efficiency

Three clocks, never combined. **Tool time is ~0.1% of wall clock** because
remote tools are replayed; in production it dominates. These measure the
model, not the surface.

| Backend | Tokens / answer | Turns / run | Duplicate calls | Model tok/s |
| --- | --- | --: | --: | --: |
| `gemma4:12b` | `████████░░░░░░░░` **70,075** | 3.0 | 0% | 14.0 |
| `qwen3.5:9b` | `████████░░░░░░░░` 72,128 | 4.2 | 6% | 25.5 |
| `qwen3.8:27b-mlx` | `██████████░░░░░░` 85,179 | 3.8 | 3% | 12.2 |
| `claude-sonnet-5` | `████████████████` 158,922 | 4.8 | 3% | 84.0 |

Tokens spent **without** reaching a passing answer — the number a cheap model
hides behind a low per-answer figure:

| Backend | Wasted tokens |
| --- | --- |
| `qwen3.8:27b-mlx` | `█░░░░░░░░░░░░░░░` 63,933 |
| `claude-sonnet-5` | `██████░░░░░░░░░░` 375,683 |
| `gemma4:12b` | `██████░░░░░░░░░░` 391,602 |
| `qwen3.5:9b` | `████████████████` 1,029,527 |

**`qwen3.5:9b` is the cautionary row**: second-cheapest per answer, and it
burned **16× more tokens than the 27B on runs that produced nothing**. A
per-answer figure alone would have flattered it.

`tok/s` is not a model comparison: three backends are a local daemon on this
host, one is a network round trip.

---

## Limits of this ranking

§7.1.9's gate is met, and these remain true:

1. **Three of four backends share a schema dialect.** Only Sonnet exercises
   `json_schema`; the rest use `openai_function` through Ollama. Dialect
   effects are **not** isolated — that needs OpenAI or Gemini credentials.
2. **One frontier model, three local.** "Frontier models rank below a local
   27B" is not supported by n=1 at that tier. What *is* supported: on this
   surface, this 27B model was more reliable and 1.9× cheaper per answer than
   this frontier model.
3. **The corpus was authored while watching `qwen3.8:27b-mlx`.** Two
   model-specific tunings were found and removed, and tests now prevent
   recurrence — but no test proves the absence of bias in *which failure modes
   were chosen*. The top-ranked model is the one the suite grew up with, and
   that should be held against the result.
4. **The fixtures are hand-authored, not captured.** The archive all four
   faced is invented; counts like "4,127 rows" are placeholders. A model with
   real knowledge of these archives could be penalised for contradicting one.
5. **Three tasks discriminate nothing** and should be tightened or retired.
6. **The suite measures documented failure modes, not answer quality.** One
   model called B0329+54 *"a fast, bright millisecond-adjacent pulsar"* — its
   period is 715 ms — in a passing answer. No check looks at whether an
   object's characterisation is sane.

### What would strengthen it most, in order

1. A second frontier model, and one on a third dialect (OpenAI or Gemini).
2. Captured fixtures replacing the hand-authored ones.
3. Retire or tighten tasks 2, 4 and 6; add a characterisation-sanity check.

---

## Runs recorded

| Backend | Tier | Dialect | Passed | Tokens | Temp. settable |
| --- | --- | --- | --- | --: | :-: |
| `ollama/qwen3.8:27b-mlx` | local 27B | `openai_function` | 23/24 | 2,023,055 | — |
| `anthropic/claude-sonnet-5` | frontier | `json_schema` | 21/24 | 3,713,050 | **no** |
| `ollama/qwen3.5:9b` | local 9B | `openai_function` | 17/24 | 2,255,708 | — |
| `ollama/gemma4:12b` | local 12B | `openai_function` | 16/24 | 1,512,801 | — |

All four were graded by the **same grader commit**, re-graded together after a
fix to `must_report_artifact_path` (it had required a path verbatim and failed
models that elided the middle while quoting the real filename). Re-grading was
offline and free — that is why `run` and `grade` are separate verbs.

Superseded runs, kept only as the record of what they found:

| Run | Found |
| --- | --- |
| local r1, r2 | Two prompts with no antecedent; two tasks passing on `0/0` checks; `"4,127"` parsed as `4` and `127`; two false positives in the keys added after r1 |
| frontier (biased corpus) | The fixture-coverage defect; a fabrication attributed to `top_peaks` |
| two-backend (pre-repeats) | The turn cap and sourcing vocabulary tuned to one model |

## How to add a provider

```bash
kepler-bench run core --backend openai/gpt-5 \
  --repeats 3 --max-tokens 12000000 \
  --out artifacts/bench/<date>-core-<model>
kepler-bench compare artifacts/bench/* --composite
```

Add a **Ranking** row and one **Per-task grid** column. If a key must change to
accommodate the new provider, **re-grade every backend** — never compare runs
graded by different rules.

## Reading these numbers honestly

- **Latency is one host, one day**, and not comparable between a hosted API
  and a local daemon.
- **Every rate is averaged, not streaming.** Only the Anthropic adapter
  streams natively.
- **A dash is not a zero.** No backend reported cached tokens.
- **There is no cost column.** Tokens are the measurement; money is the
  reader's arithmetic against their own pricing page (§15.3).
- **`incomplete` is not a failure** — there were none in this sweep.
- **Only the schema dialect varies besides the model**, deliberately (§7.1.1).
