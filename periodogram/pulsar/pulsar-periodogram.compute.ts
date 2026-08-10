// EXTRACTED from astromancer:
//   src/app/tools/pulsar/pulsar.service.ts  (1263 lines total)
//   - getChartPeriodogramDataArray (lines 663-700)
//   - getChartPulsarDataArray      (lines 609-613)
//   - getJdRange                   (lines 455-468)
//   - getLabels                    (lines 470-493)
//   - compute                      (lines 442-445, documented only — see below)
//
// This is the pulsar tool's periodogram driver: it selects and cleans the
// input columns, then calls the shared Lomb-Scargle core once per source
// channel. The pulsar tool uses the UNWEIGHTED lombScargle() — pulsar rows
// carry no per-point error.
//
// EXTRACTED: was `@Injectable({providedIn: 'root'}) export class PulsarService`
// (Angular DI). All `this.<service getter>` reads have been turned into
// explicit parameters; the method bodies below are otherwise unchanged.
//
// EXTRACTED: was `this.setChartComputedPeriodogramDataArray(...)`, which wrote
// the result through PulsarData into localStorage and pushed an RxJS
// BehaviorSubject. Replaced by the optional `onComputed` callback so the
// caching side effect stays visible without dragging in storage or RxJS.
//
// EXTRACTED: `compute()` in the service was only
//     this.isComputingSubject.next(!this.isComputingSubject.getValue());
// i.e. an RxJS toggle that tells the chart to re-run getChartPeriodogramDataArray.
// It carries no math, so it is documented here rather than reproduced.

import {lombScargle} from "../core/lomb-scargle";
import {PulsarDataDict} from "./pulsar-periodogram.model";


/**
 * Verbatim from PulsarService.getChartPulsarDataArray().
 * Row selection for periodogram input: keep rows that have a time and a
 * primary source; source2 is passed through even when null.
 */
export function getChartPulsarDataArray(data: PulsarDataDict[]): (number | null)[][] {
    return data.filter((row: PulsarDataDict) =>
        row.jd !== null && row.source1 !== null)
        .map((row: PulsarDataDict) => [row.jd, row.source1!, row.source2!] as [number, number, number])
}


/**
 * Verbatim body of PulsarService.getChartPeriodogramDataArray(start, end).
 *
 * @param data    was this.getData()               (PulsarData row list)
 * @param start   start period (or start frequency when method === true)
 * @param end     end period   (or end frequency   when method === true)
 * @param points  was this.getPeriodogramPoints()  (grid step count)
 * @param method  was this.getPeriodogramMethod()  (false = period, true = frequency)
 * @param onComputed  EXTRACTED seam: was setChartComputedPeriodogramDataArray()
 */
export function getChartPeriodogramDataArray(
    data: PulsarDataDict[],
    start: number,
    end: number,
    points: number,
    method: boolean,
    onComputed?: (computed: [Number[], Number[]]) => void,
): { data1: number[][], data2?: number[][] } {
    // EXTRACTED: was `const pulsarData = this.getChartPulsarDataArray();` —
    // assigned but never read in the original. Retained as a comment rather
    // than silently dropped, since this is an extraction, not a cleanup.
    // const pulsarData = getChartPulsarDataArray(data);

    // Filter valid data for the first two columns
    const validData = data.filter((row: PulsarDataDict) =>
        row.jd !== null && row.source1 !== null
    );

    // Extract data for each column
    const jd: number[] = validData.map((entry) => entry.jd!) as number[];
    const mag1: number[] = validData.map((entry) => entry.source1!) as number[];

    // Check for the third column (if present and not null)
    const mag2: number[] = validData.map((entry) => entry.source2).filter(value => value !== null) as number[];

    // Generate periodograms for each series
    const periodogram1 = lombScargle(jd, mag1, start, end, points, method);

    let periodogram2: number[][] | undefined = undefined;
    if (mag2.length > 0) {
        periodogram2 = lombScargle(jd, mag2, start, end, points, method);
    }

    if (periodogram2 === undefined) {
        onComputed?.([periodogram1, [0]]);
    } else {
        let periodogram3 = periodogram2 as any[];
        onComputed?.([periodogram1, periodogram3]);
    }

    return {
        data1: periodogram1,
        data2: periodogram2
    };
}


/**
 * Verbatim body of PulsarService.getJdRange(). Total time span of the
 * observation; the period-folding step size is derived from it.
 *
 * @param data was this.getData()
 */
export function getJdRange(data: PulsarDataDict[]): number {
    const jdArray = data.map((row: PulsarDataDict) => row.jd)
        .filter((jd: number | null) => jd !== null) as number[];
    if (jdArray.length === 0) return 0;
    // Reduce instead of Math.max/min(...arr): the spread form overflows
    // the call stack on large data files (~125k+ samples on V8).
    let max = jdArray[0], min = jdArray[0];
    for (let i = 1; i < jdArray.length; i++) {
        const v = jdArray[i];
        if (v > max) max = v;
        if (v < min) min = v;
    }
    return parseFloat((max - min).toFixed(4));
}


/**
 * Period <-> frequency axis inversion, from PulsarService.getLabels(isHz).
 *
 * EXTRACTED: the original mutated service state via
 * setPeriodogramStartPeriod / setPeriodogramEndPeriod / setPeriodogramXAxisLabel.
 * The reciprocal-swap math is preserved exactly; the results are returned
 * instead of written back through the service.
 *
 * Preserved quirk: both branches apply the SAME inversion
 * (newEnd = 1/currentStart, newStart = 1/currentEnd). Toggling the mode is
 * therefore self-inverse — that is the shipped behaviour, not a transcription
 * slip. Only the labels differ between branches.
 */
export function getLabels(isHz: boolean, currentStart: number, currentEnd: number): {
    startPeriodLabel: string,
    endPeriodLabel: string,
    xAxisLabel: string,
    startPeriod: number,
    endPeriod: number,
} {
    let startPeriodLabel: string;
    let endPeriodLabel: string;
    let xAxisLabel: string;

    if (isHz) {
        startPeriodLabel = 'Start Frequency (Hz)';
        endPeriodLabel = 'End Frequency (Hz)';
        xAxisLabel = 'Frequency (Hz)';
    } else {
        startPeriodLabel = 'Start Period (s)';
        endPeriodLabel = 'End Period (s)';
        xAxisLabel = 'Period (s)';
    }

    // Return both labels
    return {
        startPeriodLabel,
        endPeriodLabel,
        xAxisLabel,
        endPeriod: 1 / currentStart,
        startPeriod: 1 / currentEnd,
    };
}
