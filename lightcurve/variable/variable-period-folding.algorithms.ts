// EXTRACTED from astromancer:
//   src/app/tools/variable/period-folding/variable-period-folding-form/
//     variable-period-folding-form.component.ts   (129 lines; getPeriodStep only)
//
// The variable tool keeps almost all of its period-folding math inside the
// service — see VariableLightCurveAlgorithms.getPeriodFoldingChartDataWithError
// in ./variable-lightcurve.algorithms.ts, which folds, phase-shifts, duplicates
// for displayPeriod === TWO and carries the error bars through in one pass.
//
// That is the opposite of the pulsar tool, where the equivalent work is split
// across the service (getPeriodFoldingChartData) and the Highcharts component
// (foldAndBin / duplicateIfNeeded / differenceAndSum). So this file has only
// one function, while ../pulsar/pulsar-period-folding.algorithms.ts has six.
//
// NOT EXTRACTED from the form component: the FormGroup/FormControl wiring, the
// debounceTime subscriptions, resetForm(), saveGraph() (honor-code popup +
// Highcharts PNG export) and onChange() (slider event dispatch).
//
// Worth recording even though it was not extracted: the variable form derives
// its period-slider bounds inline as
//     periodMin = service.getPeriodogramStartPeriod()
//     periodMax = service.getJdRange()
// i.e. from the periodogram's lower bound up to the full observation baseline.
// The pulsar tool instead persists periodMin/periodMax on the period-folding
// model itself and seeds them from the data's Nyquist limit during ingest.

/**
 * Slider granularity for the folding period.
 * Verbatim from variable-period-folding-form.component.ts:121-128.
 *
 * EXTRACTED: `this.service.getPeriodFoldingPeriod()` and
 * `this.service.getJdRange()` become parameters.
 *
 * Identical arithmetic to the pulsar copy
 * (../pulsar/pulsar-period-folding.algorithms.ts::getPeriodStep); only this
 * one carries the explanatory comment. Both are preserved as found.
 */
export function getPeriodStep(periodFoldingPeriod: number, jdRange: number): number {
  const someVal = Math.pow(periodFoldingPeriod, 2) * 0.01 / jdRange;
  if (someVal > 10e-6) {
    // step = round((periodFoldingForm.period_num.value/range)*0.01, 4)
    return parseFloat(someVal.toFixed(4));
  } else {
    return 10e-6;
  }
}
