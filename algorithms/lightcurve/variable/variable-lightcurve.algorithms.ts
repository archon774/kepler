// EXTRACTED from astromancer: src/app/tools/variable/variable.service.ts
//
// The astromancer original is `@Injectable() export class VariableService`
// (536 lines). This file keeps only the light-curve / period-folding math,
// with every method body verbatim.
//
// Methods carried over, with their line ranges in variable.service.ts:
//   getPeriodFoldingPeriod                 77-82    sentinel -> full JD range
//   getPeriodFoldingChartDataWithError    162-194   phase folding with errors
//   getJdRange                            285-289   time baseline
//   getChartVariableDataArray             403-415   differential photometry
//   getChartVariableErrorArray            446-463   differential error bars
//
// FRAMEWORK SEAMS CUT:
//   - `@Injectable()` decorator and the `@angular/core` import
//   - every `this.variableStorage.save*()` call (localStorage)
//   - every `this.<name>Subject.next(...)` emission (RxJS BehaviorSubject)
//   - the `Highcharts.Chart` handles and their get/set pairs
//   - `getChartPeriodogramDataArray` (:465-473) — Lomb-Scargle, periodogram
//   - `getDefaultDataLabel` (:532-534) — a chart legend string
//
// PULSAR vs VARIABLE, the core difference: the variable light curve is
// DIFFERENTIAL PHOTOMETRY — the science signal is (target - reference +
// zero-point), computed in getChartVariableDataArray. The pulsar light curve
// is instead a raw intensity time series with a running-median background
// removed (PulsarLightCurveAlgorithms.backgroundSubtraction). The variable
// tool has no background subtraction and no binning; the pulsar tool has no
// error propagation.

// EXTRACTED: was `import {floatMod, lombScargleWithError, UpdateSource} from
//            "../shared/data/utils"` — lombScargleWithError + UpdateSource
//            dropped (periodogram math / RxJS plumbing).
import {floatMod} from "../shared/numeric-utils";
import {
    VariableData,
    VariableDataDict,
    VariableInterfaceImpl,
    VariableStarOptions
} from "./variable-lightcurve.types";
import {VariableDisplayPeriod, VariablePeriodFolding} from "./variable-period-folding.types";

// EXTRACTED: was `@Injectable() export class VariableService implements MyData,
//   VariableInterface, ChartInfo, VariablePeriodogramInterface,
//   VariablePeriodFoldingInterface`
export class VariableLightCurveAlgorithms {
    private variableData: VariableData = new VariableData();
    private variableInterface: VariableInterfaceImpl = new VariableInterfaceImpl();
    private variablePeriodFolding: VariablePeriodFolding = new VariablePeriodFolding();

    /** Data access
     *  EXTRACTED: the originals additionally wrote through to VariableStorage
     *  (localStorage) and pushed onto dataSubject / periodogramDataSubject /
     *  periodFoldingDataSubject.
     */

    getData(): VariableDataDict[] {
        return this.variableData.getData();
    }

    getDataArray(): (number | null)[][] {
        return this.variableData.getDataArray();
    }

    getChartSourcesDataArray(): (number | null)[][][] {
        return this.variableData.getChartSourcesDataArray();
    }

    getChartSourcesErrorArray(): (number | null)[][][] {
        return this.variableData.getChartSourcesErrorArray();
    }

    setData(data: any[]): void {
        this.variableData.setData(data);
    }

    addRow(index: number, amount: number): void {
        this.variableData.addRow(index, amount);
    }

    removeRow(index: number, amount: number): void {
        this.variableData.removeRow(index, amount);
    }

    resetData(): void {
        this.variableData.setData(VariableData.getDefaultDataDict());
    }

    /** Algorithm parameters */

    getVariableStar(): VariableStarOptions {
        return this.variableInterface.getVariableStar();
    }

    setVariableStar(variableStar: VariableStarOptions): void {
        this.variableInterface.setVariableStar(variableStar);
    }

    getReferenceStarMagnitude(): number {
        return this.variableInterface.getReferenceStarMagnitude();
    }

    setReferenceStarMagnitude(magnitude: number): void {
        this.variableInterface.setReferenceStarMagnitude(magnitude);
    }

    getIsLightCurveOptionValid(): boolean {
        return this.variableInterface.getIsLightCurveOptionValid();
    }

    getPeriodFoldingDisplayPeriod(): VariableDisplayPeriod {
        return this.variablePeriodFolding.getPeriodFoldingDisplayPeriod();
    }

    setPeriodFoldingDisplayPeriod(displayPeriod: VariableDisplayPeriod): void {
        this.variablePeriodFolding.setPeriodFoldingDisplayPeriod(displayPeriod);
    }

    getPeriodFoldingPhase(): number {
        return this.variablePeriodFolding.getPeriodFoldingPhase();
    }

    setPeriodFoldingPhase(phase: number): void {
        this.variablePeriodFolding.setPeriodFoldingPhase(phase);
    }

    setPeriodFoldingPeriod(period: number): void {
        this.variablePeriodFolding.setPeriodFoldingPeriod(period);
    }

    /** variable.service.ts:77-82, verbatim.
     *  The stored default is -1; a negative value means "not chosen yet", and
     *  the fold then spans the entire observation baseline.
     */
    getPeriodFoldingPeriod(): number {
        if (this.variablePeriodFolding.getPeriodFoldingPeriod() < 0)
            return this.getJdRange();
        else
            return this.variablePeriodFolding.getPeriodFoldingPeriod();
    }


    /** Period folding with error propagation — variable.service.ts:162-194, verbatim.
     *
     *  Contrast with the pulsar sibling
     *  (PulsarLightCurveAlgorithms.getPeriodFoldingChartData): this version
     *  applies `phase` inside the fold (`phase * period + floatMod(...)`)
     *  and duplicates each point one period later when displayPeriod === TWO,
     *  all before any plotting. The pulsar version defers both steps until
     *  after binning.
     *
     *  PRESERVED QUIRK (not fixed — see docs/extraction.md, Light Curve §9.1): `data` and `error`
     *  are built by two passes with DIFFERENT filter predicates —
     *  getChartVariableErrorArray additionally requires `row.errorMSE !== null`
     *  — and are then indexed in lockstep as data[i] / error[i]. A single row
     *  with a null errorMSE shortens `error` only, after which every subsequent
     *  pair is misaligned and the tail throws on `error[i][1]!`.
     *
     *  PRESERVED QUIRK (§9.2): `data[0][0]!` is dereferenced with no length
     *  check, so an empty table throws here. The pulsar sibling had exactly
     *  this guard added; the fix was never mirrored across.
     */
    getPeriodFoldingChartDataWithError(): { [key: string]: number[][] } {
        if (this.getVariableStar() === VariableStarOptions.NONE)
            return {data: [], error: []};
        const data = this.getChartVariableDataArray()
            .filter((entry) => entry[0] !== null)
            .sort((a, b) => a[0]! - b[0]!);
        const error = this.getChartVariableErrorArray()
            .filter((entry) => entry[0] !== null)
            .sort((a, b) => a[0]! - b[0]!);
        const minJD = data[0][0]!;
        const period = this.getPeriodFoldingPeriod();
        const phase = this.getPeriodFoldingPhase();
        let pfData: number[][] = [];
        let pfError: number[][] = [];
        if (period !== 0 && period !== null) {
            for (let i = 0; i < data.length; i++) {
                let temp_x = phase * period + floatMod((data[i][0]! - minJD), period);
                if (temp_x > period) {
                    temp_x -= period;
                }
                pfData.push([temp_x, data[i][1]!]);
                pfError.push([temp_x, error[i][1]!, error[i][2]!]);
                if (this.getPeriodFoldingDisplayPeriod() === VariableDisplayPeriod.TWO) {
                    let new_x = temp_x + parseFloat(period as any);
                    pfData.push([new_x, data[i][1]!]);
                    pfError.push([new_x, error[i][1]!, error[i][2]!]);
                }
            }
        }
        pfData.sort((a, b) => b[0] - a[0]);
        pfError.sort((a, b) => b[0] - a[0]);
        return {data: pfData, error: pfError};
    }


    /** Time-axis handling — variable.service.ts:285-289, verbatim.
     *
     *  NOTE: unlike the pulsar sibling, this one still uses the spread form of
     *  Math.max/Math.min. The pulsar copy was rewritten to a loop because it
     *  overflowed the call stack on ~125k+ sample files; the variable tool's
     *  datasets are small enough that the issue never surfaced. Preserved as-is.
     */
    getJdRange(): number {
        const jdArray = this.getData().map((row: VariableDataDict) => row.jd)
            .filter((jd: number | null) => jd !== null) as number[];
        return parseFloat((Math.max(...jdArray) - Math.min(...jdArray)).toFixed(4));
    }


    /** Differential photometry — variable.service.ts:403-415, verbatim.
     *
     *  This is the variable-star light curve proper: whichever source is
     *  designated the variable has the OTHER source (the comparison star)
     *  subtracted from it, then the reference star's catalogue magnitude is
     *  added back as a zero-point.
     */
    getChartVariableDataArray(): (number | null)[][] {
        if (this.getVariableStar() === VariableStarOptions.NONE) {
            return [];
        } else if (this.getVariableStar() === VariableStarOptions.SOURCE1) {
            return this.getData().filter((row: VariableDataDict) =>
                row.jd !== null && row.source1 !== null && row.source2 !== null)
                .map((row: VariableDataDict) => [row.jd, row.source1! - row.source2! + this.getReferenceStarMagnitude()])
        } else {
            return this.getData().filter((row: VariableDataDict) =>
                row.jd !== null && row.source1 !== null && row.source2 !== null)
                .map((row: VariableDataDict) => [row.jd, row.source2! - row.source1! + this.getReferenceStarMagnitude()])
        }
    }


    /** Differential error bars — variable.service.ts:446-463, verbatim.
     *
     *  Emits [jd, low, high] triples. `errorMSE` (the quadrature-combined,
     *  halved per-source error from variable-lightcurve.types.ts) is applied
     *  symmetrically about the differential magnitude.
     */
    getChartVariableErrorArray(): (number | null)[][] {
        if (this.getVariableStar() === VariableStarOptions.NONE) {
            return [];
        } else {
            return this.getData().filter(
                (row: VariableDataDict) => row.jd !== null && row.source1 !== null && row.source2 !== null && row.errorMSE !== null).map(
                (row: VariableDataDict) => {
                    let src: number;
                    if (this.getVariableStar() === VariableStarOptions.SOURCE1) {
                        src = row.source1! - row.source2! + this.getReferenceStarMagnitude();
                    } else {
                        src = row.source2! - row.source1! + this.getReferenceStarMagnitude();
                    }
                    return [row.jd, src - row.errorMSE!, src + row.errorMSE!]
                }
            )
        }
    }
}
