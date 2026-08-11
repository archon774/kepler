// EXTRACTED from astromancer:
//   src/app/tools/pulsar/periodogram/pulsar-periodogram-highcharts/
//     pulsar-periodogram-highcharts.component.ts
//   - findLocalMax        (lines 152-162, verbatim)
//   - confidence-line math (lines 234-247, math lifted out of addConfidenceLines)
//
// These two pieces are the only algorithmic content in that 319-line file;
// everything else is Highcharts series/axis plumbing and was left behind.
//
// EXTRACTED: was a private method of PulsarPeriodogramHighchartsComponent
// (Angular @Component). The `this.chartObject.addSeries(...)` / `setData(...)`
// calls that consumed these numbers are NOT reproduced here.
//
// Note: the variable tool has no equivalent — it plots the raw Lomb-Scargle
// trace with no peak marker and no confidence lines.

/**
 * Peak detection.
 *
 * Despite the name this returns the GLOBAL maximum (as a single-element
 * array), not every local maximum. The name is original; the astromancer
 * chart series it feeds is likewise labelled "Global Maxima". The returned
 * point's x value is the peak period (or peak frequency in frequency mode)
 * that the period-folding tab consumes.
 *
 * Copied verbatim, including the original indentation.
 */
export function findLocalMax(points: [number, number][]): [number, number][] {
    let globalMax = points[0];

    for (let i = 1; i < points.length; i++) {
        if (points[i][1] > globalMax[1]) {
            globalMax = points[i];
        }
    }

    return [globalMax];
}


/**
 * False-alarm-probability confidence levels drawn as horizontal lines across
 * the periodogram. Copied verbatim from addConfidenceLines(); `color` is
 * retained because it is part of the original literal, though it is a
 * rendering concern.
 */
export const CONFIDENCE_LEVELS = [
    {id: "conf-1-sigma", name: "67.3% Confidence", alpha: 1 - 0.673, color: "red"},
    {id: "conf-2-sigma", name: "95.4% Confidence", alpha: 1 - 0.954, color: "orange"},
    {id: "conf-3-sigma", name: "99.73% Confidence", alpha: 1 - 0.9973, color: "green"},
];

/**
 * Spectral-power threshold above which a peak beats the given false-alarm
 * probability, for a periodogram sampled at `points` independent frequencies.
 *
 * Verbatim from the original body of addConfidenceLines():
 *     const z = -Math.log(1 - (1 - alpha) ** (1 / points));
 *
 * `points` is the periodogram's step count (PulsarPeriodogram.points).
 */
export function confidenceThreshold(alpha: number, points: number): number {
    return -Math.log(1 - (1 - alpha) ** (1 / points));
}
