# Working Documents

Plans under active development, one plan per file. These documents change as the
work proceeds and are not a description of the current codebase.

| Document | Description |
| --- | --- |
| [broken-links-remediation-plan.md](broken-links-remediation-plan.md) | Plan to close the seam between the public `tools/` surface and the local data in `test_data/`: twelve findings where a tool that should run against bundled data cannot reach it, plus a phased fix. |
| [model-backends-and-benchmarking.md](model-backends-and-benchmarking.md) | Design for a provider-neutral model port (Ollama, Anthropic, OpenAI-compatible, Gemini) behind one interface, and a benchmark harness that grades backends on the existing tool surface. |
| [model-port-plan.md](model-port-plan.md) | Task-by-task implementation plan for phases -1 to 3 of the model port (the backend interface and adapters); the benchmark-harness phases get their own plan later. |
| [tui-harness-design.md](tui-harness-design.md) | Design for the Kepler TUI: a Textual console over a headless event-emitting engine, replacing `kepler-astro-query` and the standalone photometry script with one interactive surface. Depends on the model port. |

When a plan's work lands, fold the durable outcome into a reference document at
the top level of `docs/`, then delete the plan — git history preserves it.
Completed plans are not meant to accumulate here. See [`../README.md`](../README.md)
for how `docs/` is organized.
