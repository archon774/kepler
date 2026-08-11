# The Pulsar Tool Pipeline

Date: 2026-08-11
Status: active architecture

Four tools, one per stage, in the order they must run. This document is the
map from each stage to the extracted Astromancer code that backs it.

```text
   raw scan (.cal.txt)
          │
          ▼
┌───────────────────────────────┐
│ 1. load_pulsar_lightcurve     │  drop cal block, rebase time,
│                               │  subtract running-median baseline
└───────────────────────────────┘
          │  light curve (.ecsv)  ◄── the handoff every later stage takes
          ├──────────────────────────────────────────┐
          ▼                                          │
┌───────────────────────────────┐                    │
│ 2. compute_pulsar_periodogram │  Lomb-Scargle      │
│                               │  → THE PERIOD      │
└───────────────────────────────┘                    │
          │  period_s                                │
          ├───────────────────┬──────────────────────┤
          ▼                   ▼                      ▼
┌────────────────────┐  ┌──────────────────────────────────┐
│ 3. fold_pulsar_    │  │ 4. sonify_pulsar(period_s=…)     │
│    lightcurve      │  │    folds internally, then renders│
│    → pulse profile │  │    → audio (.wav)                │
└────────────────────┘  └──────────────────────────────────┘
```

---

## 1. Why the order is a dependency, not a convention

Stage 3 needs a period. Stage 2 is the only thing that produces one from the
data. So the sequence is forced, and it is the same sequence the Astromancer
tool's tabs impose on a student: **light curve → periodogram → period folding**,
with sonification hanging off the folding form.

The failure this ordering prevents is specific and quiet. **Folding at the
wrong period does not raise an error — it returns a flat profile**, which looks
like a faint source rather than a mistake. An agent that guesses a period, or
reads one off the audio, gets a plausible-looking null result with nothing
marking it as wrong. That is why:

- `fold_pulsar_lightcurve` reports `pulse_snr` and warns below 8 sigma;
- `compute_pulsar_periodogram` folds at its own peak and reports
  `peak_fold_snr`, warning `peak_does_not_fold` below 8 sigma. It also reports
  `peak_confidence`, but that is **not** the validity check — see §4, where
  four of five bundled scans return a confident artifact;
- `sonify_pulsar` warns (`unfolded_rendering`) when called without a period;
- every stage's schema says to prefer `search_atnf` for a known source, whose
  catalogued period beats anything a 60-second scan can measure.

Stage 4 can run without stage 2, and stage 3 can take a period from
`search_atnf` instead. Those are the two legitimate shortcuts; both are
documented on the tools themselves.

---

## 2. Stage → algorithm → upstream

Every stage calls a Python module under `algorithms/pulsar/`, which is a port
of a TypeScript extraction under `algorithms/lightcurve/` or
`algorithms/periodogram/`, which was extracted from Astromancer. Full
provenance and the preserved-quirk list live in `docs/extraction.md`
(Pulsar Sonification; Light Curve; Periodogram).

| Stage | Tool | Python algorithm | Extracted TypeScript | Astromancer origin |
| --- | --- | --- | --- | --- |
| 1 | `load_pulsar_lightcurve` | `algorithms/pulsar/ingest.py` | `lightcurve/pulsar/pulsar-lightcurve.ingest.ts`, `…algorithms.ts` | `pulsar-light-curve.component.ts::uploadHandler`; `pulsar.service.ts::median`, `backgroundSubtraction` |
| 2 | `compute_pulsar_periodogram` | `algorithms/pulsar/periodogram.py` | `periodogram/core/lomb-scargle.ts`, `periodogram/core/peak-detection.ts`, `periodogram/pulsar/pulsar-periodogram-range.ts` | `shared/data/utils.ts::lombScargle`; `pulsar-periodogram-highcharts.component.ts::findLocalMax`, `addConfidenceLines` |
| 3 | `fold_pulsar_lightcurve` | `algorithms/pulsar/folding.py` | `lightcurve/pulsar/pulsar-period-folding.algorithms.ts`, `…lightcurve.algorithms.ts`, `lightcurve/shared/numeric-utils.ts` | `pulsar.service.ts::getPeriodFoldingChartData`, `binData`; `pulsar-period-folding-highchart.component.ts::foldAndBin` |
| 4 | `sonify_pulsar` | `algorithms/pulsar/sonification.py` | `lightcurve/pulsar/pulsar-sonification.algorithms.ts` | `pulsar.service.ts::sonification`; `pulsar-period-folding-form.component.ts`, `pulsar-light-curve-sonifier.component.ts` |

`algorithms/pulsar/` is the one **port** rather than extraction under
`algorithms/`, marked `# PORTED:`. The TypeScript is kept and typechecked
(`npm run typecheck`) as the provenance record the port is diffed against.

---

## 3. The two sonification renderings

Stage 4 has two modes because Astromancer has two call sites, and they are not
equivalent.

| | Folded (`period_s` given) | Light curve (no period) |
| --- | --- | --- |
| Upstream call site | `pulsar-period-folding-form.component.ts` (4 sites) | `pulsar-light-curve-sonifier.component.ts` (2 sites) |
| Status upstream | **primary** | secondary |
| Input | folded, phase-binned profile | raw background-subtracted scan |
| One pass is | one rotation, looped | the whole scan, once |
| Faint source | pulse builds up across rotations | stays buried in noise |
| Audio vs sky time | quantized only (~0.4%) | quantized **and** gap-compressed (~3%) |

Both report `playback_stretch`: audio seconds per second of sky. Neither is
exactly 1.0, because `samplesPerPoint` is floored to a whole number of output
samples rather than fitted to elapsed time. The folded path avoids only the
gap-compression term. **No period should ever be read off the audio.**

---

## 4. Chaining

Each stage takes `path`, which may be a raw scan or the stage-1 `.ecsv`
artifact. Passing the artifact is preferred: it skips the re-ingest and
guarantees every stage sees the same samples.

```python
from tools.pulsar import (
    load_pulsar_lightcurve, compute_pulsar_periodogram,
    fold_pulsar_lightcurve, sonify_pulsar,
)

lc   = load_pulsar_lightcurve("test_data/pulsar/Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt")
pg   = compute_pulsar_periodogram(lc.artifact.path)
fold = fold_pulsar_lightcurve(lc.artifact.path, pg.peak_period_s)
wav  = sonify_pulsar(lc.artifact.path, period_s=pg.peak_period_s)
```

On the B0329+54 fixture that yields a peak at **0.714790 s** against ATNF's
0.714519699725801 s (0.04%), at power 399 versus a 12.8 three-sigma threshold,
folding to a **204 sigma** profile.

Note `pg.top_peaks` on that run: `0.7148, 0.1429, 0.1785, 0.2378, 0.1192` —
after the fundamental, every entry is a harmonic (P/5, P/4, P/3, P/6). That is
normal for a pulsar and is why the field exists.

### What a blind search actually achieves

B0329+54 is the **only** one of the five bundled scans where this works with
default settings. Verified against the curated periods in
`test_data/pulsar/Curated pulsars.docx`, cross-checked against live ATNF:

| Scan | Curated difficulty | `S1400` | Blind search result | Fold at curated `P0` |
| --- | --- | --- | --- |
| B0329+54 | Easy | 203 mJy | **the pulsar**, 0.04% | 316σ |
| B1133+16 | Lightly Challenging | 20 mJy | 0.016665 s — **60.006 Hz mains** | 17.7σ |
| B1933+16 | More Challenging | 58 mJy | ~2.18 s — baseline red noise | 7.5σ |
| B2021+51 | Lightly Challenging | 27 mJy | ~2.14 s — baseline red noise | 4.9σ |
| B2045−16 | Most Challenging | 22 mJy | 0.016665 s — **60.006 Hz mains** | 5.4σ |

That is the expected outcome for 60 seconds on a 20 m dish, not a defect: only
the bright source has the signal-to-noise for a blind period search, and the
curator's difficulty ratings — assigned before any of this code ran — say the
same thing. The
consequences for tool design are the load-bearing part:

1. **`peak_confidence` does not detect this.** All four failures clear the
   three-sigma false-alarm line, because that threshold assumes white noise and
   radio data has mains interference and red noise. A caller trusting it would
   confidently fold on 60 Hz.
2. **`peak_fold_snr` does.** Folding at the candidate and measuring the pulse
   separates all five correctly, which is why `compute_pulsar_periodogram`
   computes it and warns `peak_does_not_fold` below 8σ.
3. **Red-noise peaks move with `back_scale`; real periodicities do not.** On
   B1133+16 the spurious ~2.18 s peak appears at `back_scale` 3, 12 and 30 but
   the true 1.19 s period wins at 1 and 6. Varying it is the cheapest
   diagnostic available.
4. **For any known source, `search_atnf` beats measuring.** A catalogued period
   turns four of these five scans from failures into usable folds.

B1933+16 resists even a tuned search, for a physical reason worth recording:
`DM = 158.6` smears its pulse across ~11% of its 359 ms period over the 80 MHz
effective band. It is the brightest of the four faint scans and still the
hardest, and no amount of tuning fixes it — **dedispersion would**, and this
pipeline has none.

---

## 5. Where the output goes

Every stage writes into `<artifact dir>/pulsar/`, where the artifact directory
is `$KEPLER_ARTIFACT_DIR` if set and `./artifacts` otherwise, **resolved to an
absolute path at import**. Returned `artifact.path` values are therefore always
absolute — a caller can change directory or hand the path to another process.

Names are stage-consistent and derived from the scan's `SRC_NAME`:

```text
artifacts/pulsar/
  psr_b0329_54_lightcurve.ecsv            # stage 1
  psr_b0329_54_periodogram.ecsv           # stage 2
  psr_b0329_54_folded.ecsv                # stage 3
  psr_b0329_54_sonification_folded.wav    # stage 4, with a period
  psr_b0329_54_sonification_lightcurve.wav# stage 4, without one
```

A rendered sample is committed at
`docs/examples/psr_b0329_54_sonification.wav` — produced by the agent loop, not
a script; see that folder's README for the tool calls it chose. It is the only
generated file in the repository.

Pass `output_name` to override the stem, or `subdir` to change the folder.
Existing files are never overwritten: a second run appends `_1`, `_2`, ….
`artifacts/` is in `.gitignore`.

**These are deliberately not upstream's filenames.** Astromancer downloads
under its *chart* titles — `getChartTitle()` gives
`psr_b0329_54_2025-08-11T13:44:32.050_prefolded_light_curve` and
`getPeriodFoldingTitle()` gives `..._folded_light_curve`. Two problems for a
tool: the browser download filename was a UI concern (split off into
`downloadWav()` at extraction, not algorithm), and using the chart title for a
folded render names it "prefolded", which states the opposite of the truth. All
three upstream titles are still parsed and kept on `PulsarObservation`
(`title`, `periodogram_title`, `folding_title`) for anyone reproducing them.

---

## 6. Result contracts

Small typed models in `tools/models.py`, each carrying an `ArtifactRef` rather
than inline arrays, per `docs/tool-architecture.md`:

| Stage | Model | Artifact |
| --- | --- | --- |
| 1 | `PulsarLightCurve` | `.ecsv` — `time_s`, `source1`, `source2?` + header metadata |
| 2 | `PulsarPeriodogram` | `.ecsv` — `period_s`/`frequency_hz`, `power` |
| 3 | `PulsarFoldedProfile` | `.ecsv` — `phase_s`, `source1`, `source2?`, `difference?`, `sum?` |
| 4 | `PulsarSonification` | `.wav` — 16-bit PCM, stereo when both polarizations are present |

All four share `PulsarObservationInfo`, so the source name, sample counts and
background-subtraction settings read the same at every stage.

Failures are returned as `errors` on the model, never raised, so an agent loop
can report them and continue.

---

## 7. Not covered

- **No name-to-scan resolution.** Every stage takes a *file path*. An agent
  asked to "sonify B0329+54" has a source name and no way to reach a scan:
  `search_atnf` returns the catalogued period but no observational data, and
  nothing in the registry advertises that `test_data/pulsar/` exists. Today the
  caller must already know the path. `tools/claude_photometry_haiku_tool.py`
  solves the same problem for FITS frames with `list_bundled_targets()` /
  `resolve_fits_path()`, so there is a precedent to follow if this is wanted.

- **No dedispersion.** These are single-band continuum scans; the pipeline
  never sees a frequency axis, so dispersion measure plays no part.
- **No barycentric correction.** Periods are topocentric, which is why they
  differ from an ATNF `P0` in the fourth decimal.
- **No period uncertainty.** The periodogram reports a grid peak, not a fitted
  period with an error bar. Refine by re-running with a narrow `start`/`stop`
  and more `steps`.
- **`sonificationBrowser` is not ported** — it drives an `AudioContext`, which
  a file-writing tool has no use for. It remains extracted in TypeScript.

---

## 8. Pressing Issues and Tooling Bugs

- **The document is stale about scan discovery.** `tools.pulsar` and
  `tools.registry` now expose `list_pulsar_scans` and `resolve_pulsar_scan`,
  so §7's "No name-to-scan resolution" note is no longer true. The main
  diagram, stage count, result-contract table and "Not covered" section need
  to be updated so agents see the optional Stage 0 discovery step before the
  four processing stages.

- **The periodogram schema hides the recommended diagnostic knobs.**
  `compute_pulsar_periodogram()` accepts `back_scale` and
  `subtract_background`, and both this document and the tool description tell
  callers to vary `back_scale` when red-noise peaks move. The registry schema
  does not advertise either parameter, so an agent using `TOOL_SCHEMAS` cannot
  follow that guidance. Add them to the schema and pin the parity with a
  registry test.

- **Degenerate periodogram inputs can escape the "errors, never raised"
  contract.** A constant light-curve artifact raises `ZeroDivisionError` from
  `algorithms.pulsar.periodogram.lomb_scargle()` because the variance is zero,
  and an all-NaN artifact returns `errors=[]` with `peak_period_s` set to the
  lower search bound and `peak_power=nan`. Stage 2 should filter/validate
  finite values, reject zero-variance data with a `ToolError`, and catch this
  class of arithmetic failure at the tool boundary.

- **`top_peaks` is ambiguous in frequency mode.** In period mode each entry's
  `x` is seconds; in `freq_mode=True` it is Hz, while the model/docs still
  talk about period harmonics. Return explicit `period_s` and `frequency_hz`
  fields per peak, or make the schema/documentation mode-specific enough that
  callers cannot fold using a frequency value as if it were a period.

- **Folded rendering lacks hard resource guards for bad periods.**
  `fold_lightcurve()` preserves upstream's repeated-subtraction `floatMod`,
  so a tiny positive `period_s` can run for an impractically large number of
  loop iterations. The folded sonifier also sizes interpolation from
  `sample_rate * period_s`, while public `sample_rate` and very long periods
  are not bounded by the schema. Validate periods against the observation
  baseline/Nyquist range and cap rendered interpolation work before allocating
  arrays or entering the fold.

- **Stage 0 does not yet follow the same error-return discipline.**
  `list_pulsar_scans()` and `resolve_pulsar_scan()` return structured
  `ToolError`s for missing directories and ambiguous names, but header reads
  and `stat()` calls can still raise `OSError` for unreadable files. If Stage 0
  is part of the public pipeline, per-file read failures should be collected
  into `errors` or `warnings` rather than aborting the call.

---

## 9. Review of Plotting Tools and Charts

Review target: the `agent/pulsar-plots` work merged into `dev` by
`808f2ad`, primarily commits `e28a5e0` and `96072af`.

### Findings

1. **High: the periodogram chart can mislabel what it plotted.**
   `compute_pulsar_periodogram()` defaults to `channel="sum"`, searching
   source1 + source2, but `PERIODOGRAM_CHART` hard-codes the rendered series as
   "Polarization XX". The periodogram artifact also does not persist the
   selected channel, so `plot_pulsar()` cannot recover the truth later. This is
   scientifically misleading: the default plot is usually not XX at all, it is
   the summed trace. Store `channel` in the periodogram ECSV metadata and map
   it to "Sum", "Polarization XX", or "Polarization YY" when drawing.

2. **Medium: frequency-mode periodograms inherit period-mode chart semantics.**
   `plot_pulsar()` correctly detects a `frequency_hz` column, but still returns
   the Astromancer period-mode spec: x label "Period (s)" and logarithmic
   x-axis type. `freq_mode=True` uses a linear frequency grid, so the rendered
   plot should say "Frequency (Hz)" and should not silently force the period
   chart's axis semantics. Either make a frequency chart spec or override the
   period spec whenever `frequency_hz` is the x column.

3. **Medium: malformed `.ecsv` input can still raise instead of returning a
   `ToolError`.** `plot_pulsar()` catches `_LoadError` around file existence
   and raw-scan ingest, but `Table.read(file.path, format="ascii.ecsv")` is in
   the same block and its exceptions are not wrapped. A bad artifact can escape
   the result contract that "failures are returned as `errors` on the model,
   never raised." Mirror `_load_artifact()` and convert unreadable table files
   to `ToolError(code="parse_error", ...)`.

4. **Medium: the public schema hides useful plotting controls.**
   The Python function accepts `x_label`, `y_label`, `back_scale`,
   `subtract_background`, `dpi`, `figsize`, and `subdir`, but the registry
   schema advertises only `path`, `kind`, `title`, `show_hidden_series`, and
   `output_name`. For agent callers this means a raw-scan plot cannot vary the
   same baseline settings as stage 1, and generated figures cannot be sized or
   redirected even though the function supports it. Add the missing schema
   fields or intentionally remove the unsupported public parameters.

5. **Low: current tests prove the renderer writes PNGs, not that the charts are
   visually non-empty or correctly annotated.** `tests/test_pulsar_plots.py`
   checks spec constants, inferred kind, PNG dimensions, series names and
   metadata. That is good unit coverage, but it would not catch a blank axes
   area, invisible traces, a missing peak marker caused by metadata drift, or
   confidence lines hidden outside the plotted range. Add a small pixel-level
   smoke check for the committed B0329+54 examples or inspect matplotlib axes
   objects before saving.

### What Looks Sound

- The split between `algorithms/pulsar/charts.py` and `tools.pulsar` is the
  right boundary. Chart identity, labels, hidden series, confidence-line names
  and the folded x-axis ladder are treated as ported Astromancer semantics,
  while matplotlib remains only the file renderer.
- `compute_pulsar_periodogram()` now stores peak and confidence metadata in the
  periodogram artifact, so `plot_pulsar()` can draw the diagnostic marker and
  thresholds without recomputing the spectrum.
- `plot_pulsar()` accepts raw scans as a convenience but still prefers the
  artifact handoff: light-curve, periodogram and folded outputs can all be
  plotted by passing their `.ecsv` paths directly.
- The folded chart preserves Astromancer's hidden `Difference` and `Sum`
  series and exposes them through `show_hidden_series`, which is a practical
  translation of an interactive legend into a static PNG tool.
- The committed example PNGs are an appropriate exception to the generated-file
  rule: they are small, inspectable, and make the chart output reviewable
  without rerunning the pipeline.

### Suggested Follow-Up Order

Fix the periodogram label/metadata issue first, because it can change the
scientific meaning of the plot. Then fix frequency-mode chart semantics and
the malformed-ECSV error path. Schema parity and pixel-level plot checks can
follow as one focused hardening PR.
