# `docs/examples/` — committed sample output

One file, kept as a reference for what the pulsar pipeline actually produces.
**Generated output is normally not committed** (`.gitignore` covers
`artifacts/`); this is a deliberate one-off so the result can be listened to
without running the pipeline.

## `psr_b0329_54_sonification.wav`

PSR B0329+54 rendered as audio: 60 s, stereo, 16-bit PCM, 44.1 kHz, 10.1 MB.
Each polarization is one channel, and the pulse arrives as a burst of static
roughly every 0.71 s.

Produced by the **agent loop**, not by a script — `tools/runner.py` driving
`tools.registry.TOOL_SCHEMAS`, given only this instruction:

> Sonify pulsar B0329+54, but measure the period from the observation itself
> with a periodogram rather than taking a catalogue value. Fold at what you
> measure, then render the audio.

The tool calls it chose, in order:

| Turn | Call | Result |
| --- | --- | --- |
| 1 | `resolve_pulsar_scan("B0329+54")` | the local scan path |
| 2 | `load_pulsar_lightcurve(path)` | light-curve `.ecsv` |
| 3 | `compute_pulsar_periodogram(lightcurve)` | coarse peak |
| 4 | `compute_pulsar_periodogram(…, start=0.7, stop=0.73, steps=2000)` | refined peak |
| 5 | `fold_pulsar_lightcurve(lightcurve, period_s=…)` | profile, 316σ |
| 5 | `sonify_pulsar(lightcurve, period_s=…)` | this file |

Narrowing the search in turn 4 was the agent's own decision, not a scripted
step.

**The period came from the data alone.** The measured value was
`0.7144527749932426 s`, which is 9.4e-5 relative from both the curated
literature period (`test_data/pulsar/Curated pulsars.docx`, 0.7145197 s) and
ATNF's live `P0` — with no catalogue consulted during the run.

### Regenerating it

```bash
export ANTHROPIC_API_KEY=...          # the loop needs a key; the tools do not
uv run kepler-astro-query "Sonify pulsar B0329+54, but measure the period from the observation itself with a periodogram rather than taking a catalogue value. Fold at what you measure, then render the audio."
```

Or without an agent, three deterministic calls:

```python
from tools.pulsar import (
    load_pulsar_lightcurve, compute_pulsar_periodogram, sonify_pulsar,
)

lc = load_pulsar_lightcurve("test_data/pulsar/Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt")
pg = compute_pulsar_periodogram(lc.artifact.path, start=0.7, stop=0.73, steps=2000)
wav = sonify_pulsar(lc.artifact.path, period_s=pg.peak_period_s)
```

The render is deterministic: the noise carrier is seeded (`seed=0` by default),
so a repeat run is byte-identical.

## Please don't add more

A 10 MB binary is permanent in git history even if deleted later, and audio is
incompressible. `artifacts/` stays ignored for a reason — see
`test_data/README.md`, "Repository size". If a second example ever becomes
necessary, prefer a few seconds of audio over a full 60 s render
(`audio_seconds=5`).
