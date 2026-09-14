# `core` — calibration record

**Status: NOT CALIBRATED.** This suite has not been run against any real model.

`docs/working/benchmark.md` §7.1.9 makes calibration a gate on phase 5d: a
suite is **untrusted until it has been run against at least three backends of
different tiers** and each task's outcome reviewed, because a task passed by
every model and a task passed by none both discriminate nothing — and the
second is usually a broken key rather than a universal failure.

That run has not happened. It needs credentials (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY` or `GEMINI_API_KEY`) or a local Ollama daemon with the
reference model pulled, and the machine this corpus was authored on had
neither. **No claim is made here about what any task discriminates.**

## What *has* been established

Weaker than calibration, and stated as such:

| Property | Where |
| --- | --- |
| Every task loads and every check is validated against the live registry | `tests/test_bench_corpus.py` |
| Every fixture revalidates through its tool's own return model (B3) | `tests/test_bench_corpus.py` |
| All eight tasks run end to end, offline, with no socket | `test_the_core_suite_runs_end_to_end_offline_against_replay` |
| Every check is *reachable* — a transcript written to pass does pass | `test_a_transcript_written_to_pass_does_pass_every_hard_check` |
| Each key *catches the failure it names* — a transcript doing the documented wrong thing fails, on the check that names it | the negative tests in `tests/test_bench_corpus.py` |

The last row is the closest thing here to evidence that a key works. It is not
calibration: it shows the key separates a deliberately wrong answer from a
deliberately right one, not that it separates real models from each other.

## The fixtures are hand-authored

None of `benchmarks/fixtures/*.yaml` is a capture. Each states so in its
`provenance`, and a test asserts it. They are faithful to the tools' **return
models** and to the documented behaviour of the services (NED's resolver
rejects colloquial names; ATNF performs no name resolution and returns an
empty result rather than an error). Their **counts are placeholders** —
`search_vizier`'s 47 catalogs and 4,127 rows, `search_ned`'s 214 photometry
rows — and the `get_paper_abstract` text is a paraphrase carrying the two
facts the task turns on, not the published abstract.

Two consequences follow, and both should be fixed by a `kepler-bench record`
capture before this suite is believed:

1. A key that asserts one of those counts (`preview-is-not-the-answer`'s 4127,
   `vizier-category-not-per-catalog`'s 47) is asserting a number this
   repository invented. It grades the right *behaviour* — reporting the total
   rather than the preview — against the wrong *number*.
2. A model with real knowledge of these archives could be penalised for
   contradicting a fixture that is wrong.

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
