// EXTRACTED from astromancer:
//   src/app/tools/pulsar/period-folding/pulsar-period-folding-form/
//     pulsar-period-folding-form.component.ts  (307 lines total)
//   - isComputing$ subscriber body, lines 157-183 -> foldingRangeFromPeriodogram()
//
// SCOPE NOTE: period folding itself is NOT extracted here — see EXTRACTION.md.
// This file captures only the seam where periodogram OUTPUT becomes folding
// INPUT, because that mapping is periodogram-side semantics (it has to know
// about the period/frequency mode flag).
//
// EXTRACTED: was an RxJS `this.service.isComputing$.pipe(takeUntil, skip(1))`
// subscriber inside an Angular @Component, calling
// service.setPeriodFoldingPeriodMin/Max and poking a Subject + ChangeDetectorRef.
// Only the min/max derivation is reproduced.

/**
 * Map the periodogram's search window onto the period-folding slider bounds
 * when the user hits Compute.
 *
 * In frequency mode the bounds invert (a frequency range maps to a period
 * range back-to-front), which is why the branches are not symmetric.
 *
 * @param method  was this.service.getPeriodogramMethod()
 *                false = period mode, true = frequency mode
 * @param start   was this.service.getPeriodogramStartPeriod()
 * @param end     was this.service.getPeriodogramEndPeriod()
 */
export function foldingRangeFromPeriodogram(
    method: boolean,
    start: number,
    end: number,
): { min: number, max: number } {
    let newMin: number, newMax: number;
    if (method === false) {
        newMin = start;
        newMax = end;
    } else {
        newMax = 1 / start;
        newMin = 1 / end;
    }
    return {min: newMin, max: newMax};
}


/**
 * Period-folding slider step size, from the same component's getPeriodStep()
 * (lines 299-306, verbatim). Included because it is derived from the folding
 * period the periodogram peak feeds, and from getJdRange() which is extracted
 * in pulsar-periodogram.compute.ts.
 *
 * @param period   was this.service.getPeriodFoldingPeriod()
 * @param jdRange  was this.service.getJdRange()
 */
export function getPeriodStep(period: number, jdRange: number): number {
    const someVal = Math.pow(period, 2) * 0.01 / jdRange;
    if (someVal > 10e-6) {
        return parseFloat(someVal.toFixed(4));
    } else {
        return 10e-6;
    }
}
