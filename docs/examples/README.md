# `docs/examples/` — committed sample output

What the pulsar pipeline produces, run end to end on PSR B0329+54. **Generated
output is normally not committed** (`.gitignore` covers `artifacts/`); these
are deliberate exceptions so the results can be seen and heard without running
anything.

| File | Stage | Size |
| --- | --- | --- |
| `psr_b0329_54_lightcurve.png` | 1 — light curve | 87 KB |
| `psr_b0329_54_periodogram.png` | 2 — periodogram | 78 KB |
| `psr_b0329_54_folded.png` | 3 — folded profile | 60 KB |
| `psr_b0329_54_sonification.wav` | 4 — audio | 10.1 MB |

## The three plots

Rendered by `tools.pulsar.plot_pulsar`, whose labels, series names and axis
semantics come from Astromancer's own chart configuration — see
`algorithms/pulsar/charts.py`.

**`psr_b0329_54_lightcurve.png`** — flux against time, both polarizations, after
running-median background subtraction. B0329+54 is bright enough that the
**individual pulses are visible in the raw scan**, roughly 78 of them across
56 s at 0.71 s spacing; no folding needed. Most pulsars do not look like this,
which is what makes this one "Easy" in `Curated pulsars.docx`.

**`psr_b0329_54_periodogram.png`** — spectral power against period on a
logarithmic axis, with the peak marked "Global Maxima" and the three dashed
false-alarm lines. Two things are legible here that a number cannot convey:
the **harmonic comb** at P/2, P/3, P/4… receding to the left, and how far
*below* every real feature the confidence lines sit — which is why
`peak_confidence` is not a validity check and `peak_fold_snr` is. See
`docs/pulsar-tool-pipeline.md` §4.

**`psr_b0329_54_folded.png`** — the pulse profile, 100 phase bins at the
measured period, 293σ. The x axis runs `[0, 0.7145]`, set by upstream's
`updateXAxisScale` ladder rather than by matplotlib. The narrow pulse occupying
a few percent of the rotation is the shape a pulsar is supposed to have.

Regenerate all three:

```python
from tools.pulsar import (
    load_pulsar_lightcurve, compute_pulsar_periodogram,
    fold_pulsar_lightcurve, plot_pulsar,
)

lc   = load_pulsar_lightcurve("data/pulsar/Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt")
pg   = compute_pulsar_periodogram(lc.artifact.path)
fold = fold_pulsar_lightcurve(lc.artifact.path, pg.peak_period_s)
for stage in (lc, pg, fold):
    plot_pulsar(stage.artifact.path, title="PSR B0329+54")
```

## The audio

### `psr_b0329_54_sonification.wav`

PSR B0329+54 rendered as audio: 60 s, stereo, 16-bit PCM, 44.1 kHz, 10.1 MB.
Each polarization is one channel, and the pulse arrives as a burst of static
roughly every 0.71 s.

Produced by the **agent loop**, not by a script — `tools/agent/` driving
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
literature period (`data/pulsar/Curated pulsars.docx`, 0.7145197 s) and
ATNF's live `P0` — with no catalogue consulted during the run.

### Regenerating it

```bash
export ANTHROPIC_API_KEY=...          # the loop needs a backend; the tools do not
uv run kepler                         # then ask, in the console:
```

> Sonify pulsar B0329+54, but measure the period from the observation itself
> with a periodogram rather than taking a catalogue value. Fold at what you
> measure, then render the audio.

The original run predates the console and was driven by the retired
`kepler-astro-query` shim over the same loop and the same registry; what it
did is unchanged by where it is typed.

Or without an agent, three deterministic calls:

```python
from tools.pulsar import (
    load_pulsar_lightcurve, compute_pulsar_periodogram, sonify_pulsar,
)

lc = load_pulsar_lightcurve("data/pulsar/Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt")
pg = compute_pulsar_periodogram(lc.artifact.path, start=0.7, stop=0.73, steps=2000)
wav = sonify_pulsar(lc.artifact.path, period_s=pg.peak_period_s)
```

The render is deterministic: the noise carrier is seeded (`seed=0` by default),
so a repeat run is byte-identical.

## Adding more

The PNGs are cheap (~75 KB each) and compress; adding a plot for another source
is reasonable. **The audio is not** — 10 MB, incompressible, and permanent in
git history even if deleted later. Keep it to the one file; if a second render
ever becomes necessary, prefer a few seconds over a full 60 s pass
(`audio_seconds=5`). See `data/README.md`, "Repository size".
