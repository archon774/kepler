# Pulsar Pipeline — Open Bugs and Plotting-Tools Review

Status: open findings, not yet scheduled
Scope: defects in `tools/pulsar.py` and its tests — not the pipeline's shape.

Split out of [`../pulsar-tool-pipeline.md`](../pulsar-tool-pipeline.md) so the
architecture document stays a description of the pipeline as designed. §1 comes
from the 2026-08-11 pipeline write-up; §2 reviews the `agent/pulsar-plots` work
merged to `dev` in `808f2ad`.

The working `broken-links-remediation-plan.md` is scoped away from all of this —
its §10.4 names these as "a doc-only PR", which the split into this file is.

---

## 1. Open tool-correctness bugs

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

## 2. Review of Plotting Tools and Charts

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
