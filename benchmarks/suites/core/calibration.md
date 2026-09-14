# `core` — calibration record

**Status: PARTIALLY CALIBRATED.** Two backends of two tiers have run this
suite on the de-biased corpus; §7.1.9 asks for three of different tiers. The
recorded scoreboard is [../../../docs/working/benchmark-results.md](../../../docs/working/benchmark-results.md).

| Backend | Tier | Result |
| --- | --- | --- |
| `ollama/qwen3.8:27b-mlx` | local 27B | 8 / 8 |
| `anthropic/claude-sonnet-5` | frontier | 6 / 7, 1 incomplete |

**Two tasks discriminated; six did not.** Six passed by both is what §7.1.9
calls "too loose or too easy" — pending a third backend, because tightening on
two data points is how a suite gets fitted to the models it has seen.

### The calibration found bias in this suite, twice

Both times the corpus, not a model, was at fault:

1. **Keys tuned to one model.** Three rounds of fixes were made against the
   local model before any other backend ran. Two were model-specific and were
   removed: a sourcing vocabulary grown from that model's prose (21 entries, 14
   of them absent from `SYSTEM_PROMPT`), and an evidence-free `max_turns: 8`
   that failed a more exploratory model for exploring. Tests now enforce both —
   every sourcing label must be a phrase the system prompt uses, no turn cap
   may be tight enough to decide an outcome, and no task file may name a model
   or provider.
2. **A fixture world too sparse for an open-ended prompt.**
   `vizier-category-not-per-catalog` is still unresolved. One model answered it
   in 13 calls; the other made 38, hit the turn cap, and never answered — 31 of
   its 38 calls returned an empty synthesized result and it kept trying further
   archives. Neither `miss_policy: error` nor `synthesize` fixes a world that
   is simply empty; it needs recorded responses for the tools a model actually
   reaches.

### Superseded runs

Kept because they are what found the defects, and excluded from the scoreboard
because they were graded against a corpus adjusted to one of the models:

| Run | Result | Found |
| --- | --- | --- |
| local r1 | 6/8 | Two prompts with no antecedent; two tasks passing on `0/0` checks; a `must_not_call` punishing correct behaviour; `"4,127"` parsed as `4` and `127` |
| local r2 | 6/8 | Two false positives in the keys added after r1 |
| frontier (biased corpus) | 5/7 + 1 ⏳ | The fixture-coverage defect; a fabrication attributed to `top_peaks` |

## The calibration run, when someone does it

```bash
kepler-bench run core \
  --backend anthropic/claude-opus-5 \
  --backend openai/gpt-4.1 \
  --backend ollama/qwen3.8:27b-mlx \
  --repeats 3 --max-tokens 2000000
kepler-bench compare artifacts/bench/<run-id>
```

Then fill in the table below and review each row against §7.1.9:

| Observed | Action |
| --- | --- |
| every model passes | the check is too loose, or the task is too easy — tighten or retire |
| no model passes | inspect: a genuine universal failure mode is **kept and flagged**; a key no reasonable answer could satisfy is fixed |
| the pass set tracks prose style rather than tier | the check is grading phrasing — replace the `must_match` with something higher in §7.1.6 |

| task | frontier | mid | local | verdict |
| --- | --- | --- | --- | --- |
| `vizier-category-not-per-catalog` | — | — | — | not run |
| `no-identical-retry` | — | — | — | not run |
| `ned-formal-designation` | — | — | — | not run |
| `atnf-formal-designation` | — | — | — | not run |
| `pulsar-period-not-from-audio` | — | — | — | not run |
| `preview-is-not-the-answer` | — | — | — | not run |
| `abstract-before-attribution` | — | — | — | not run |
| `null-argument-fidelity` | — | — | — | not run |
