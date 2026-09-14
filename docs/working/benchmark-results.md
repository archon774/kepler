# Benchmark Results — Kepler's `core` Suite

**What this is:** the recorded scoreboard for [benchmark.md](benchmark.md)'s
`core` suite. One column per backend; a new provider appends rather than
replaces.

**Status:** **calibrated, and not yet able to rank.** Four backends across four
tiers, three repeats each — 96 sessions, 421 tool calls, zero protocol faults,
zero incompletes. §7.1.9's gate (three backends of different tiers) is met.

**The headline finding is about the suite, not the models.** At 24 trials per
backend, **no pair of these four is separated at 95% confidence** — not even
96% against 67%. What that costs and what it would take to fix is in
[Resolution](#resolution-what-24-trials-will-not-buy), and it is the reason
this document no longer opens with an ordered table.

**Corpus:** suite SHA-256 `b681227692d1`, clean, repository `67070c1`. All 22
class-R tools have recorded fixtures. Every answer key resolves to a
mechanical source and is frozen in `benchmarks/keys.lock`. Run 2026-09-14, one
host, **sequential**, `--repeats 3`.

---

## Results

Ordered by correctness. **The order is not a ranking** — see the interval
column, then [Resolution](#resolution-what-24-trials-will-not-buy).

| Backend | Tier | Correctness | 95% interval | Stability | Tokens / answer |
| --- | --- | --- | --- | --- | --: |
| `ollama/qwen3.8:27b-mlx` | local 27B | 23/24 · 96% | `80%–99%` | 88% | 85,179 |
| `anthropic/claude-sonnet-5` | frontier | 21/24 · 88% | `69%–96%` | 75% | 158,922 |
| `ollama/qwen3.5:9b` | local 9B | 17/24 · 71% | `51%–85%` | 75% | 72,128 |
| `ollama/gemma4:12b` | local 12B | 16/24 · 67% | `47%–82%` | 88% | 70,075 |

Every interval overlaps every other. The suite has measured that all four are
somewhere between roughly half and nearly all, and has not separated them.

A previous version of this document ranked these four by a weighted composite
and put the frontier model last. That ordering was an artifact of the weights
(0.7 correctness / 0.3 efficiency) applied to differences the trial count does
not support. The composite is still available behind `--composite`; it is not
used here, and a single number over two unseparated axes is worth less than
the columns beside it.

---

## Resolution: what 24 trials will not buy

Eight tasks × three repeats is 24 trials. A Wilson interval on 23/24 runs from
80% to 99%. Subtracting two such rates is not a measurement.

Computed rather than guessed — the trials needed to separate each pair at 95%:

| Pair | Gap | Trials needed | = repeats of 8 tasks |
| --- | --: | --: | --: |
| 27B vs 12B | 96% → 67% | 32 | 4 |
| frontier vs 12B | 88% → 67% | 72 | 9 |
| **27B vs frontier** | 96% → 88% | **176** | **22** |

The bottom row is the important one. **The top of this suite is saturated**:
three of eight tasks are passed by every backend, so the two strongest models
differ on two items and it would take 176 trials to call that difference real.

That is a statement about the suite, not about those two models — and it is
worth weighing against outside evidence, where a frontier hosted model is
expected to lead an open-weight 27B comfortably on general agentic benchmarks.
This suite does not contradict that. It fails to resolve it, and then a
composite weighting turned the failure into an ordering.

**More tasks beat more repeats.** 22 tasks × 8 repeats is the same 176 trials
and buys independent failure modes with them; 8 tasks × 22 repeats buys
twenty-two more looks at the same eight.

---

## Per-task grid

Passes out of 3 repeats. **Bold** = the task discriminated between backends.

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

Tasks 2, 4 and 6 separate nothing. Retiring them is **not** the obvious fix:
"discriminates nothing" is judged against these four models, so dropping them
fits the corpus to the models a second time and leaves no trace that it
happened. A task is retired for a stated property of the task, not for its
scoreboard behaviour.

---

## The findings worth more than the table

### Failure modes invert by tier

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

Unlike the ordering, this does not depend on separating 23/24 from 21/24. It
is a difference in *which* checks fail, and it is clean.

### Both large models reproduced the exact documented fabrication

`SYSTEM_PROMPT` warns about one specific incident by name:

> *An agent asked to confirm a decline rate once answered "0.3-0.7%/yr
> depending on frequency" and attributed it by name to a real paper (Trotter
> et al. 2017) — the actual abstract says "0.670 +/- 0.019%/yr".*

`claude-sonnet-5` emitted **0.7** and `qwen3.8:27b-mlx` emitted **0.3 and
0.7** — the warned-about figure, in a session where no tool returned it, with
the warning in their context. Neither smaller model did, because neither has
the association to recall.

`must_source_value` caught it by reading `events.jsonl`, the only record of
what the tools actually returned. This is the strongest argument in the
results for keeping that check and for the event stream existing at all.

### A plan prediction that did not survive contact

§7.4 calls `null_argument_fidelity` "**the single most discriminating check in
the suite for small local models**." It is not. **All four backends passed
JSON `null` on every repeat** — including the 9B. Task 8 still discriminated,
but on `must_report_artifact_path`, not on the union.

The integer-or-null union that `schema.py` refuses to downgrade is handled
correctly by every model tested here. That is a real result about the port's
schema translation, and the prediction is revised rather than repeated.

---

## How the keys were de-biased

An earlier version of this corpus was authored while watching
`qwen3.8:27b-mlx`, which then ranked first. Measuring that effect is possible
because answer-key revisions are visible in git: three tasks had keys revised
after a model run, five never did.

| Backend | Keys never revised (5 tasks) | Keys revised (3 tasks) |
| --- | --- | --- |
| `qwen3.8:27b-mlx` | 14/15 · 93% | **9/9 · 100%** |
| `claude-sonnet-5` | 13/15 · 87% | 8/9 · 89% |
| `qwen3.5:9b` | 10/15 · 67% | 7/9 · 78% |
| `gemma4:12b` | 10/15 · 67% | 6/9 · 67% |

The authoring model is perfect exactly where its own runs shaped the key and
93% where they did not — the direction key-fitting predicts. Four structural
changes followed, none of which rely on choosing a better model to author
against:

1. **Keys are derived, not typed** (`tools/bench/sources.py`). A value check
   names its source — a field of the recorded archive, a field of a repository
   data file, or the value a deterministic Kepler tool returned on the run
   being graded — and the loader resolves it. A hand-typed `expected:` fails to
   load. Weighing an answer against a tool's output is fidelity; weighing it
   against another model's output would be an opinion poll.
2. **Turn caps are derived** (`tasks.derive_turn_cap`). The only evidence for
   choosing a cap is a transcript, so any cap read off one is fitted to whoever
   produced it. The cap is now a function of the task's own declared
   requirement, and a task file that sets one fails to load. It is a
   loop-breaker, not a measurement parameter: a run that reaches it is
   incomplete, never failed.
3. **Keys are frozen** (`benchmarks/keys.lock`). A key changes only when a
   transcript demonstrates it is invalid, never to calibrate a score, and the
   change appears in review as a diff alongside a re-grade of every backend.
4. **Keys are attacked** (`kepler-bench falsify`). Four probes compare recorded
   failures against the mechanical source the key cites, consulting no model.
   The asymmetry is the design: evidence can show a key is wrong; nothing can
   show one is right.

`falsify` finds **no candidates across all four backends**. Every probe is
tested against a constructed false positive, so that result means something —
but it is the absence of a demonstration, not a clean bill of health.

---

## Stability

Share of tasks giving the same verdict across all three repeats (§17 q2).

| Backend | Stability | Flaky tasks |
| --- | --- | --- |
| `qwen3.8:27b-mlx` | 88% | `abstract-before-attribution` |
| `gemma4:12b` | 88% | `null-argument-fidelity` |
| `claude-sonnet-5` | 75% | `ned-formal-designation`, `abstract-before-attribution` |
| `qwen3.5:9b` | 75% | `vizier-category-not-per-catalog`, `pulsar-period-not-from-audio` |

**No backend was stable on everything.** At `--repeats 1` every one would have
looked deterministic and six task-level results would have been coin flips
reported as facts. `claude-sonnet-5` **cannot be given a temperature** — its
API rejects the parameter — so nothing bounds its drift but repetition.

---

## Efficiency

Three clocks, never combined. **Tool time is ~0.1% of wall clock** because
remote tools are replayed; in production it dominates.

| Backend | Tokens / answer | Turns / run | Duplicate calls | Model tok/s |
| --- | --: | --: | --: | --: |
| `gemma4:12b` | **70,075** | 3.0 | 0% | 14.0 |
| `qwen3.5:9b` | 72,128 | 4.2 | 6% | 25.5 |
| `qwen3.8:27b-mlx` | 85,179 | 3.8 | 3% | 12.2 |
| `claude-sonnet-5` | 158,922 | 4.8 | 3% | 84.0 |

Tokens spent **without** reaching a passing answer — the number a cheap model
hides behind a low per-answer figure:

| Backend | Wasted tokens |
| --- | --: |
| `qwen3.8:27b-mlx` | 63,933 |
| `claude-sonnet-5` | 375,683 |
| `gemma4:12b` | 391,602 |
| `qwen3.5:9b` | **1,029,527** |

**`qwen3.5:9b` is the cautionary row**: second-cheapest per answer, and it
burned **16× more tokens than the 27B on runs that produced nothing**.

Efficiency is the one axis where these four *are* cleanly separated — 70k
against 159k is not a two-item difference. It is also the axis that says least
about whether a model is right.

`tok/s` is not a model comparison: three backends are a local daemon on this
host, one is a network round trip.

---

## Limits

1. **The suite cannot separate these backends on correctness.** Everything
   above about ordering is bounded by that.
2. **Three of four backends share a schema dialect.** Only Sonnet exercises
   `json_schema`; the rest use `openai_function` through Ollama. Dialect
   effects are not isolated — that needs OpenAI or Gemini credentials.
3. **One frontier model, three local.** n=1 at that tier.
4. **Residual authorship bias cannot be removed, only bounded.** The four
   structural changes above close the routes that leave a fingerprint —
   tuned parameters, typed values, revised keys, unexamined checks. They do
   not touch the one that leaves none: *which failure modes were written at
   all*. You cannot grep for the task nobody wrote. The only complete removal
   is exclusion — never ranking the model a corpus was developed against.
5. **The fixtures are hand-authored, not captured.** Counts like "4,127 rows"
   are placeholders; a model with real knowledge of these archives could be
   penalised for contradicting one.
6. **The suite measures documented failure modes, not answer quality.** One
   model called B0329+54 *"a fast, bright millisecond-adjacent pulsar"* — its
   period is 715 ms — in a *passing* answer.

### What would strengthen it most, in order

1. **More tasks.** 22 tasks at 3 repeats would resolve the top pair and add
   fourteen independent failure modes. This is the single highest-value change
   and nothing else competes.
2. A second frontier model, and one on a third dialect (OpenAI or Gemini).
3. Captured fixtures replacing the hand-authored ones.
4. A characterisation-sanity check, for the millisecond-pulsar class of error.

---

## Runs recorded

| Backend | Tier | Dialect | Passed | Tokens | Temp. settable |
| --- | --- | --- | --- | --: | :-: |
| `ollama/qwen3.8:27b-mlx` | local 27B | `openai_function` | 23/24 | 2,023,055 | — |
| `anthropic/claude-sonnet-5` | frontier | `json_schema` | 21/24 | 3,713,050 | **no** |
| `ollama/qwen3.5:9b` | local 9B | `openai_function` | 17/24 | 2,255,708 | — |
| `ollama/gemma4:12b` | local 12B | `openai_function` | 16/24 | 1,512,801 | — |

All four were graded by the **same grader commit**. Re-grading is offline and
free — that is why `run` and `grade` are separate verbs, and it is what makes
a grader fix safe to apply to already-paid-for evidence.

Superseded runs, kept only as the record of what they found:

| Run | Found |
| --- | --- |
| local r1, r2 | Two prompts with no antecedent; two tasks passing on `0/0` checks; `"4,127"` parsed as `4` and `127`; two false positives in the keys added after r1 |
| frontier (biased corpus) | The fixture-coverage defect; a fabrication attributed to `top_peaks` |
| two-backend (pre-repeats) | The turn cap and sourcing vocabulary tuned to one model |
| four-backend (pre-intervals) | That the ordering it published was not supported by its own trial count |

## How to add a provider

```bash
kepler-bench run core --backend openai/gpt-5 \
  --repeats 3 --max-tokens 12000000 \
  --out artifacts/bench/<date>-core-<model>
kepler-bench grade artifacts/bench/<date>-core-<model>
kepler-bench falsify artifacts/bench/*
kepler-bench compare artifacts/bench/*
```

Add a row and a **Per-task grid** column, and read the interval column before
writing a sentence that orders anything. If a key must change to accommodate
the new provider, it changes only on demonstrated invalidity — regenerate
`benchmarks/keys.lock` and **re-grade every backend** in the same commit.

## Reading these numbers honestly

- **An ordered table is not a ranking.** Check the interval column.
- **Latency is one host, one day**, and not comparable between a hosted API
  and a local daemon.
- **Every rate is averaged, not streaming.** Only the Anthropic adapter
  streams natively.
- **A dash is not a zero.** No backend reported cached tokens.
- **There is no cost column.** Tokens are the measurement; money is the
  reader's arithmetic against their own pricing page (§15.3).
- **`incomplete` is not a failure** — there were none in this sweep.
- **Only the schema dialect varies besides the model**, deliberately (§7.1.1).
