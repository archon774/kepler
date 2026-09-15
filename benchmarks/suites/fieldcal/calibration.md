# `fieldcal` — calibration record

**Status: CALIBRATED — and one of its two tasks is failed by every backend,
kept and flagged.**

Three backends across three tiers, three repeats each — 18 sessions, in the
2026-09-14 full sweep. §7.1.9's gate is met.

| task | `claude-sonnet-5` | `qwen3.8:27b-mlx` | `qwen3.5:9b` | verdict |
| --- | :-: | :-: | :-: | --- |
| `fieldcal-offline-solve` | 0/3 | 0/3 | 0/3 | **universal failure — kept and flagged** |
| `fieldcal-not-an-accuracy-figure` | 2/3 | 1/3 | 0/3 | discriminates cleanly by tier |

### `fieldcal-offline-solve`: 0/3 for everyone, and §7.1.9 says keep it

The gate's rule for *no model passes* is to inspect, then keep a genuine
universal failure mode and fix a key no reasonable answer could satisfy. This
is the first kind, and the distinction is not a judgement call here:
`compare_zeropoint_to_reference` is registered, classified class-L, named in
the task's own `must_call`, and available every turn. **Nothing blocked it.**

Every backend resolves the frame, lists the references, calibrates — and then
judges agreement itself, in prose, instead of calling the tool that decides it.
All three failed on `must_reach_verdict`, which reads a boolean the repository's
own code computed against the recorded solve, so no phrasing can pass it. Each
backend also skipped or reordered 6 declared calls across its 3 repeats: the
same missing call, counted on the trajectory axis.

Asked to *"calibrate the zero point and tell me whether it agrees"*, every model
does the arithmetic rather than invoking the comparison. That is the most
informative single result in the sweep and it separates no models at all.

### The reachability question this file posed is answered

It asked two things of calibration. Both now have answers, and **neither is the
answer expected**:

- *Does a model asked this question find `catalog_fixture` + `compare_to`
  without being told?* Yes — the offline calibration path is reached by all
  three. What is not reached is the comparison afterwards.
- *Does the provenance `must_not_call` catch a model that reads the reference
  and hands its number back?* **It never fired, for any backend, on any
  repeat.** That hypothesised cheat is not what these models do; the real
  failure is more banal than the one the key was built to catch. The check
  stays — it costs nothing and an untested guard is not a disproved one — but
  it has now been run against three models and caught nobody.

`fieldcal-offline-solve` is also the suite's slow end: 13–15 s per session on
the hosted backend against 369–394 s on `qwen3.8:27b-mlx`.

### The premises, established before the run

These two tasks carry the strongest keys in the repository, and their strength
is independent of calibration: `fieldcal-offline-solve` is graded by
`compare_zeropoint_to_reference.within_tolerance`, a boolean the repository's
own code computes against a recorded Skynet solve whose preservation the test
suite already pins. No phrasing can pass or fail it.

What calibration would still establish is whether the tasks are *reachable* by
a real model — whether a model asked this question finds
`catalog_fixture` + `compare_to` without being told, and whether the
provenance `must_not_call` catches a model that instead reads the reference
and hands its number back. Both questions are answered above.

~~**Neither task has been run end to end even against replay.**~~ Both were
run live against three backends on 2026-09-14; see the table at the top. They
still have no authored transcript, so `tests/test_bench_corpus.py` continues
to assert only that they load and that their fixtures and checks validate —
running them needs `calibrate_zeropoint` to execute its offline path over
`data/optical/ngc5128_galaxy_b_001.fits`, which is real compute and stays out
of a plain `uv run pytest`.

The recorded truth these grade against:

- `data/fieldcal/zp_solutions/ngc5128_b_002/fit_summary.json` — zero point
  21.147659857998637 mag, formal error 0.011615705331140265 mag, 35 matched
  APASS sources, 26 accepted by the fit.
- The other three recorded solves (`ngc5286_b_000/001/002`) are **not usable**:
  their frames are the three this repository does not carry, pending
  `optical-tools.md` P8.
