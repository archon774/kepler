// EXTRACTED from astromancer: src/app/tools/shared/data/utils.ts
//
// Only the helpers the LIGHT CURVE / PERIOD FOLDING path actually uses are
// carried over here. `floatMod` is the sole shared numeric helper reached from
// the light-curve side (both PulsarService.getPeriodFoldingChartData and
// VariableService.getPeriodFoldingChartDataWithError import it).
//
// NOTE (periodogram overlap): the same source file also holds `lombScargle`,
// `lombScargleWithError` and the private `ArrMath` object. Those are
// periodogram math and are NOT reproduced here — see ../EXTRACTION.md.
//
// Also left behind from that file: `rad`, `deg`, `d2HMS`, `d2DMS` (celestial
// coordinate conversion, unused anywhere in pulsar/ or variable/), and
// `UpdateSource` (an RxJS form-refresh discriminator, framework plumbing).

/**
 * This function computes the floating point modulo.
 * @param {number} a The dividend
 * @param {number} b The divisor
 */
export function floatMod(a: number, b: number) {
    while (a > b) {
        a -= b;
    }
    return a;
}
