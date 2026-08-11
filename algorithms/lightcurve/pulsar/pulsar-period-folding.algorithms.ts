// EXTRACTED from astromancer:
//   src/app/tools/pulsar/period-folding/pulsar-period-folding-highchart/
//     pulsar-period-folding-highchart.component.ts   (331 lines)
//   src/app/tools/pulsar/period-folding/pulsar-period-folding-form/
//     pulsar-period-folding-form.component.ts        (307 lines)
//
// Both originals are Angular components that are overwhelmingly Highcharts
// series plumbing (upsertSeries / removeSeriesById / addSeries / setExtremes)
// and RxJS subscriptions. The genuine math is a handful of closures buried
// inside `updateData()` plus `getPeriodStep()` in the form. Those are lifted
// out here as free functions with their bodies verbatim.
//
// FRAMEWORK SEAM: in the originals these were arrow-function closures that
// captured `period`, `phase` and `this.service.binData` from the enclosing
// component. Severing the closure means those captures become explicit
// parameters — that is the only change; no logic was altered.
//
// NOT EXTRACTED from the highchart component:
//   - upsertSeries / removeSeriesById and the stable SERIES_* ids — Highcharts
//     series lifecycle management
//   - setData() / updateData() themselves — they exist to push series into a
//     Highcharts chart object; their math is what appears below
//   - updateXAxisScale() — picks a rounded upper bound for the x-axis via a
//     magnitude ladder (delta 0.15 … 0.000001) and calls
//     chartObject.xAxis[0].setExtremes(). Numeric, but its only purpose is
//     choosing a chart viewport, so it is treated as rendering.
// NOT EXTRACTED from the form component:
//   - the FormGroup/FormControl wiring, debounceTime subscriptions, the
//     ChangeDetectorRef NG0100 workaround, resetForm/resetPulsar, and the
//     sonification()/sonificationBrowser() button handlers.

/**
 * Fold binned points into a single period, applying the phase shift.
 * Verbatim from pulsar-period-folding-highchart.component.ts:182-197.
 *
 * EXTRACTED: `period`, `phase` and `binData` were closure captures
 * (`this.service.binData`, and locals read off PulsarService).
 *
 * Note the ordering: this bins FIRST and phase-shifts afterwards, which is why
 * PulsarLightCurveAlgorithms.binData does no phase shifting of its own.
 */
export function foldAndBin(
  points: [number, number][],
  binsPerPeriod: number,
  period: number,
  phase: number,
  binData: (data: number[][], bins: number) => number[][],
): [number, number][] {
  // Step 1: bin first
  const binned = binData(points, binsPerPeriod) as [number, number][];

  // Step 2: apply phase shift + wrapping
  const shiftedWrapped = binned.map(([x, y]) => {
    const shifted = x + (phase * period);
    const wrappedX = ((shifted % period) + period) % period; // always in [0, period)
    return [wrappedX, y] as [number, number];
  });

  // Step 3: sort for plotting
  shiftedWrapped.sort((a, b) => a[0] - b[0]);

  return shiftedWrapped;
}


/**
 * Verbatim from pulsar-period-folding-highchart.component.ts:199-203.
 * EXTRACTED: `displayPeriod` and `period` were closure captures.
 */
// Helper: duplicate dataset if displayPeriod == 2
export function duplicateIfNeeded(
  arr: [number, number][],
  displayPeriod: number,
  period: number,
): [number, number][] {
  return displayPeriod === 2
    ? [...arr, ...arr.map(([x, y]) => [x + period, y] as [number, number])]
    : arr;
}


/**
 * Pairwise difference and sum of the two folded polarizations.
 * Verbatim from pulsar-period-folding-highchart.component.ts:224-232.
 *
 * EXTRACTED: was an inline block inside updateData(); the two output arrays
 * were fed straight into upsertSeries() for the (hidden by default)
 * 'Difference' and 'Sum' series.
 */
export function differenceAndSum(
  finalData1: [number, number][],
  finalData2: [number, number][],
): { diffData: [number, number][], sumData: [number, number][] } {
  const n = Math.min(finalData1.length, finalData2.length);
  const diffData: [number, number][] = [];
  const sumData: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    diffData.push([finalData1[i][0], finalData1[i][1] - finalData2[i][1]]);
    sumData.push([finalData1[i][0], finalData1[i][1] + finalData2[i][1]]);
  }
  diffData.sort((a, b) => a[0] - b[0]);
  sumData.sort((a, b) => a[0] - b[0]);
  return { diffData, sumData };
}


/**
 * Apply the relative calibration factor to the second polarization before it
 * is folded/binned alongside the first.
 * Verbatim from pulsar-period-folding-highchart.component.ts:218-220
 * (the same one-liner also appears at :137 in the setData() path).
 */
export function applyCalibration(
  data2: [number, number][],
  calibration: number,
): [number, number][] {
  return data2.map(([x, y]) => [x, y * calibration] as [number, number]);
}


/**
 * Single-source fallback mapping — verbatim from
 * pulsar-period-folding-highchart.component.ts:249-264.
 *
 * Used when the file carries only one polarization (`data2` absent or all
 * zeroes). Note this path ignores the true JD spacing and instead spreads the
 * samples evenly across one period by index — preserved as-is.
 *
 * EXTRACTED: `initialData` was built from `this.service.getData()`; it is now
 * a parameter. `period` / `phase` were closure captures.
 */
export function foldSingleSourceByIndex(
  initialData: { frequency: number, channel1: number, channel2: number }[],
  period: number,
  phase: number,
): [number, number][] {
  const chartData: [number, number][] = initialData.map(item => {
    const rawX = (item.frequency / initialData.length) * period + (period * phase);
    const wrappedX = ((rawX % period) + period) % period;
    return [wrappedX, item.channel1] as [number, number];
  });

  // Sort ascending by x before plotting. Without this, time-ordered
  // samples land at non-monotonic wrapped-phase positions and Highcharts
  // draws straight lines back across the period boundary each time the
  // wrapped x jumps from near-period to near-0 — visually identical to
  // "first and last points connecting" in a loop.
  chartData.sort((a, b) => a[0] - b[0]);

  return chartData;
}


/**
 * Slider granularity for the folding period.
 * Verbatim from pulsar-period-folding-form.component.ts:299-306.
 *
 * EXTRACTED: `this.service.getPeriodFoldingPeriod()` and
 * `this.service.getJdRange()` become parameters. Kept because the expression
 * P^2 * 0.01 / baseline is the resolution limit of the fold, not a UI constant.
 */
export function getPeriodStep(periodFoldingPeriod: number, jdRange: number): number {
  const someVal = Math.pow(periodFoldingPeriod, 2) * 0.01 / jdRange;
  if (someVal > 10e-6) {
    return parseFloat(someVal.toFixed(4));
  } else {
    return 10e-6;
  }
}
