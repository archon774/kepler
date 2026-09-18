# Benchmarking

Everything about measuring models on Kepler's tool surface: the harness's
architecture, the sweep it produced, and the figures drawn from it. The code is
`tools/bench/` and the CLI is `kepler-bench`;
[`../tool-architecture.md`](../tool-architecture.md) section 10.1 is the
one-screen summary that tracks the code.

The track is complete. Every phase landed on 2026-09-13, the calibration gate
was met on 2026-09-14, and a completion audit on 2026-09-18 re-verified the
harness against `dev`. [harness.md](harness.md) is therefore a record rather
than a plan, and carries an `Archived` block saying what was re-checked.

## What is here

| File | What it is |
| --- | --- |
| [harness.md](harness.md) | The architecture, the corpus, the graders, the security and correctness requirements, and the rollout record. The design document; was `docs/working/benchmark.md`. |
| [results.md](results.md) | The sweep, read and interpreted: all sixteen prompts, what separates the models, what every model gets wrong, what no check catches, and the limits. **Start here** if you want the findings rather than the machinery. |
| [report.md](report.md) | The full generated report `kepler-bench compare` produced. `results.md` selects from it. |
| `report.json` | The same report as data. Committed because the run directories under `artifacts/` are not, and the figures are built from it. |
| [`figures/`](figures) | The five PNGs `results.md` embeds, and `make.py`, which regenerates them. |

## The sweep

16 tasks × 3 repeats × 3 backends = **144 sessions**, one host, sequential,
temperature 0 where the provider allows it — `anthropic/claude-sonnet-5`,
`ollama/qwen3.8:27b-mlx` and `ollama/qwen3.5:9b`. Suite SHA-256
`b681227692d1`, repository `4101b9f`.

**Every verdict is a deterministic assertion against recorded evidence.**
Nothing here asks a model whether an answer is correct. An LLM judge was built,
run once over a full sweep, and removed; a test now forbids the grading path
from importing anything that can reach a model.

## Two limits the archive does not retire

Stated in `results.md` and worth repeating at the front door, because they
bound what the scoreboard means rather than qualifying a detail:

1. **Three of the four backends share one schema dialect**
   (`openai_function`), so dialect effects are not isolated. A second dialect
   is the single thing most worth another run.
2. **The corpus was authored while watching the backend that now ranks
   first**, which no test can fully rule out.

`results.md`'s own *Limits* section carries four more, including the largest
known hole: nothing checks non-numeric provenance, so a fabricated author or
catalogue name passes every check in the suite.

## Reproducing

```bash
kepler-bench run <suite> --backend <provider/model> --repeats 3 \
    --max-tokens <budget> --out artifacts/bench/<date>-<model>-<suite>
kepler-bench grade   artifacts/bench/<date>-<model>-<suite>
kepler-bench falsify artifacts/bench/*        # attack the keys
kepler-bench answers artifacts/bench/* --wrong-only
kepler-bench compare artifacts/bench/*        # the report
```

Every verb but `run` is offline and free, and `--max-tokens` has no default —
a run against a live backend that omits it is refused. The figures regenerate
from the committed JSON:

```bash
uv run python docs/benchmarking/figures/make.py
```

Nothing under `benchmarks/` or `tools/bench/` opens a socket under a plain
`uv run pytest`, and that is a test (B2), not a convention.
