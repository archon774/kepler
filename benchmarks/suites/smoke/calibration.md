# `smoke` — calibration record

**Status: NOT CALIBRATED, and deliberately never will be.**

This suite is the harness's own regression test, not a measurement. Its single
task, `pulsar-scan-inventory`, runs both sides replayed — a recorded transcript
against header-read-only class-L tools — so that load → run → grade → report is
exercised end to end, offline, in under a second, inside a plain
`uv run pytest`. That is why the benchmark needs no CI job of its own.

§7.1.9's calibration gate asks whether a suite discriminates between models.
This one is not trying to: it is driven by a fixed transcript, so every backend
produces identical output by construction. Running it against three tiers would
measure nothing.

| task | purpose | verdict |
| --- | --- | --- |
| `pulsar-scan-inventory` | the harness's end-to-end regression test | not a measurement |

What it does assert, via `tests/test_bench_harness.py` and
`tests/test_llm_replay_backend.py`: the loop reaches `end_turn`, the run
directory holds the four files a grader reads, the session's artifacts land
inside it, no socket is opened (B2), `run.json` states every knob (B4), and the
token budget stops a run before dispatch (B5).
