// EXTRACTED from astromancer:
//   src/app/tools/pulsar/light-curve/pulsar-light-curve/
//     pulsar-light-curve.component.ts  (364 lines total)
//   - cal-file branch, lines 270-300     -> nyquistPeriodogramRange()
//   - standard-file branch, lines 139-150 -> nyquistFoldingFloor()
//
// JUDGMENT CALL: this code physically lives in a light-curve component (the
// file-upload handler), but what it computes is the periodogram's default
// frequency/period GRID BOUNDS from the data's sampling cadence. Grid
// construction is periodogram algorithm, so it is extracted here. The
// surrounding file parsing (P_topo / SRC_NAME / UTC / DATE_OBS header
// scraping, column mapping, background subtraction) is light-curve territory
// and was left behind — see docs/extraction.md, Periodogram.
//
// EXTRACTED: was inline inside an Angular FileReader onload handler; all
// `this.service.setPeriodogram*` / `setPeriodFolding*` writes are returned as
// a plain object instead of pushed through the service.
//
// OVERLAP: the lightcurve extraction owns the same upload handler. Expect the
// parsing half to appear there; only the Nyquist/bounds math is duplicated.

/**
 * Default periodogram bounds derived from the observation's sample cadence.
 *
 * `avgDiff` is 2x the mean sample interval — the Nyquist period, i.e. the
 * shortest period the data can resolve. Rounding to 5 decimals is original.
 *
 * Guard preserved verbatim from the source comment: a cal file with 0 or 1
 * valid rows would produce NaN / -0 / Infinity and persist that as the
 * periodogram bounds, so callers must skip when ts.length < 2 (this function
 * returns null in that case rather than emitting garbage).
 *
 * @param ts      time values in seconds (UTC_Time(s) minus the UTC header)
 * @param method  was this.service.getPeriodogramMethod()
 *                false = period mode, true = frequency mode
 */
export function nyquistPeriodogramRange(ts: number[], method: boolean): {
    startPeriod: number,
    endPeriod: number,
    periodFoldingPeriodMin: number,
    periodFoldingPeriodMax: number,
} | null {
    if (ts.length < 2) {
        return null;
    }

    let totalDiff = 0;
    for (let i = 1; i < ts.length; i++) {
        totalDiff += ts[i] - ts[i - 1];
    }

    // Nyquist = 2× average sample interval; the shortest meaningful
    // period the data can resolve.
    const avgDiff = Math.round(totalDiff / (ts.length - 1) * 2 * 100000) / 100000;

    let startPeriod: number;
    let endPeriod: number;

    if (method) {
        // Frequency mode: start = 1/default-max-period (0.1 Hz),
        // end = Nyquist frequency (1/avgDiff).
        startPeriod = 0.1;
        endPeriod = Math.round((1 / avgDiff) * 100000) / 100000;
    } else {
        // Period mode: start = Nyquist period, end = default max (3s).
        // The end no longer tracks the observation length.
        startPeriod = avgDiff;
        endPeriod = 3;
    }

    // Period folding slider always in seconds; same bracket as the
    // periodogram defaults so the two views agree on what's meaningful.
    return {
        startPeriod,
        endPeriod,
        periodFoldingPeriodMin: avgDiff,
        periodFoldingPeriodMax: 3,
    };
}


/**
 * Standard / prefolded-file variant. Same Nyquist rule, but these files never
 * reach the periodogram tab, so only the folding slider floor is set and the
 * ceiling is a flat 10 s.
 *
 * Verbatim from the standard-file branch:
 *   "Compute Nyquist from the time values so the period-folding slider floor
 *    matches the data's effective sample resolution, matching the same rule
 *    as the cal-file branch (Nyquist … 10 s default)."
 */
export function nyquistFoldingFloor(xvalues: number[]): {
    periodFoldingPeriodMin: number,
    periodFoldingPeriodMax: number,
} | null {
    if (xvalues.length < 2) {
        return null;
    }

    let totalDiff = 0;
    for (let i = 1; i < xvalues.length; i++) {
        totalDiff += xvalues[i] - xvalues[i - 1];
    }
    const avgDiff = Math.round(totalDiff / (xvalues.length - 1) * 2 * 100000) / 100000;

    return {
        periodFoldingPeriodMin: avgDiff,
        periodFoldingPeriodMax: 10,
    };
}
