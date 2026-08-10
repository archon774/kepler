// EXTRACTED from astromancer:
//   src/app/tools/variable/variable.service.ts  (536 lines total)
//   - getChartPeriodogramDataArray (lines 465-473, verbatim body)
//   - getChartVariableDataArray    (lines 403-415, verbatim body)
//   - VariableStarOptions          (variable.service.util.ts lines 112-116, verbatim)
//
// The variable tool's periodogram driver. Unlike the pulsar variant it calls
// the ERROR-WEIGHTED lombScargleWithError(), because variable-star rows carry
// per-point uncertainties.
//
// EXTRACTED: was `@Injectable({providedIn: 'root'}) export class VariableService`
// (Angular DI, RxJS BehaviorSubjects, Highcharts chart handles). The
// `this.get*` service reads are now explicit parameters.

import {lombScargleWithError} from "../core/lomb-scargle";
import {VariableDataDict} from "./variable-periodogram.model";


// EXTRACTED: was in variable.service.util.ts alongside the light-curve
// interface state. Copied here because getChartVariableDataArray() branches
// on it. OVERLAP: the lightcurve extraction needs this enum too.
export enum VariableStarOptions {
  NONE = "None",
  SOURCE1 = "Source 1",
  SOURCE2 = "Source 2",
}


/**
 * Verbatim body of VariableService.getChartVariableDataArray().
 *
 * Differential photometry: the periodogram is run on the target minus the
 * reference star, offset by the reference star's known magnitude. Which
 * source is the target is a user choice, hence the branch.
 *
 * @param data                   was this.getData()
 * @param variableStar           was this.getVariableStar()
 * @param referenceStarMagnitude was this.getReferenceStarMagnitude()
 */
export function getChartVariableDataArray(
    data: VariableDataDict[],
    variableStar: VariableStarOptions,
    referenceStarMagnitude: number,
): (number | null)[][] {
    if (variableStar === VariableStarOptions.NONE) {
        return [];
    } else if (variableStar === VariableStarOptions.SOURCE1) {
        return data.filter((row: VariableDataDict) =>
            row.jd !== null && row.source1 !== null && row.source2 !== null)
            .map((row: VariableDataDict) => [row.jd, row.source1! - row.source2! + referenceStarMagnitude])
    } else {
        return data.filter((row: VariableDataDict) =>
            row.jd !== null && row.source1 !== null && row.source2 !== null)
            .map((row: VariableDataDict) => [row.jd, row.source2! - row.source1! + referenceStarMagnitude])
    }
}


/**
 * Verbatim body of VariableService.getChartPeriodogramDataArray(start, end).
 *
 * Note the hardcoded 2000 steps — the variable tool exposes no step-count
 * control, unlike the pulsar tool's `points` field. The original comment
 * explaining the number is preserved.
 *
 * Preserved fragility: `jd`/`mag` come from getChartVariableDataArray()
 * (which filters on jd/source1/source2) while `errorMSE` comes from a
 * separate filter that ALSO requires errorMSE !== null. If any row has
 * sources but a null errorMSE the two arrays fall out of alignment. That is
 * the shipped behaviour; not corrected here.
 *
 * @param data                   was this.getData()
 * @param variableStar           was this.getVariableStar()
 * @param referenceStarMagnitude was this.getReferenceStarMagnitude()
 * @param start                  start period
 * @param end                    end period
 */
export function getChartPeriodogramDataArray(
    data: VariableDataDict[],
    variableStar: VariableStarOptions,
    referenceStarMagnitude: number,
    start: number,
    end: number,
): (number | null)[][] {
    const variableData = getChartVariableDataArray(data, variableStar, referenceStarMagnitude);
    // EXTRACTED: this local was named `data` in the original (from
    // `this.getData().filter(...)`). Renamed to `filtered` only because
    // `data` is now the function parameter that replaced this.getData().
    const filtered = data.filter((row: VariableDataDict) =>
        row.jd !== null && row.source1 !== null && row.source2 !== null && row.errorMSE !== null)
    const jd = variableData.map((entry) => entry[0]) as number[];
    const mag: number[] = variableData.map((entry) => entry[1]) as number[];
    const errorMSE: number[] = filtered.map((row: VariableDataDict) => row.errorMSE!) as number[];
    // Maximum points for html2canvas to successfully render is 2000
    return lombScargleWithError(jd, mag, errorMSE, start, end, 2000);
}
