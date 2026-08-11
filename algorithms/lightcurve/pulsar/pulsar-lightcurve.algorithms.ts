// EXTRACTED from astromancer: src/app/tools/pulsar/pulsar.service.ts
//
// The astromancer original is `@Injectable() export class PulsarService`
// (1263 lines) which mixes four unrelated concerns: light-curve math,
// periodogram math, RxJS/localStorage state plumbing, and Highcharts handles.
// This file keeps ONLY the light-curve / period-folding math, with every
// method body verbatim.
//
// Methods carried over, with their line ranges in pulsar.service.ts:
//   getPeriodFoldingChartData   273-314   phase folding of the light curve
//   getJdRange                  455-468   time baseline of the observation
//   getChartPulsarDataArray     609-613   [jd, source1, source2] tuples
//   getChartSourcesDataArray    649-660   per-source [jd, value] tuples
//   median                      715-720   used by backgroundSubtraction
//   backgroundSubtraction       722-739   sliding-window median subtraction
//   binData                     850-886   fixed-width binning + bin averaging
//   interpolateLinear          1227-1240  linear upsampling by integer factor
//   resampleLinear             1250-1262  linear resample to a new length
//
// FRAMEWORK SEAMS CUT (see docs/extraction.md, Light Curve for the full list):
//   - `@Injectable()` decorator and the `@angular/core` import
//   - every `this.pulsarStorage.save*()` / `get*()` call (localStorage)
//   - every `this.<name>Subject.next(...)` emission (RxJS BehaviorSubject)
//   - the `Highcharts.Chart` handles and their get/set pairs
// The class still composes PulsarData / PulsarInterfaceImpl / PulsarPeriodFolding
// exactly as the original service did, so method bodies did not have to change.

// EXTRACTED: was `import {floatMod, lombScargle, UpdateSource} from "../shared/data/utils"`
//            lombScargle + UpdateSource dropped (periodogram math / RxJS plumbing).
import {floatMod} from "../shared/numeric-utils";
import {PulsarData, PulsarDataDict, PulsarInterfaceImpl, PulsarStarOptions} from "./pulsar-lightcurve.types";
import {PulsarDisplayPeriod, PulsarPeriodFolding} from "./pulsar-period-folding.types";

// EXTRACTED: was `@Injectable() export class PulsarService implements MyData,
//   PulsarInterface, ChartInfo, PulsarPeriodogramInterface, PulsarPeriodFoldingInterface`
export class PulsarLightCurveAlgorithms {
    private pulsarData: PulsarData = new PulsarData();
    private pulsarInterface: PulsarInterfaceImpl = new PulsarInterfaceImpl();
    private pulsarPeriodFolding: PulsarPeriodFolding = new PulsarPeriodFolding();

    /** Data access
     *  EXTRACTED: the originals additionally wrote through to PulsarStorage
     *  (localStorage) and pushed the new value onto dataSubject /
     *  periodogramDataSubject / periodFoldingDataSubject. Those lines are gone;
     *  the in-memory mutation below is what the algorithms depend on.
     */

    getData(): PulsarDataDict[] {
        return this.pulsarData.getData();
    }

    getCombinedData(): PulsarDataDict[] {
        return this.pulsarData.getCombinedData();
    }

    getRawData(): PulsarDataDict[] {
        return this.pulsarData.getRawData();
    }

    getDataArray(): (number | null)[][] {
        return this.pulsarData.getDataArray();
    }

    getTableType(): string {
        return this.pulsarData.getTableType();
    }

    setData(data: any[]): void {
        this.pulsarData.setData(data);
    }

    setCombinedData(data: any[]): void {
        this.pulsarData.setCombinedData(data);
    }

    setRawData(data: any[]): void {
        this.pulsarData.setRawData(data);
    }

    setTableType(type: string): void {
        this.pulsarData.setTableType(type);
    }

    addRow(index: number, amount: number): void {
        this.pulsarData.addRow(index, amount);
    }

    removeRow(index: number, amount: number): void {
        this.pulsarData.removeRow(index, amount);
    }

    resetData(): void {
        this.pulsarData.setData(PulsarData.getDefaultDataDict());
        this.pulsarData.setRawData(this.pulsarData.getData());
        this.pulsarData.setCombinedData(this.pulsarData.getData());

        // Reset the table type to 'subtracted'. Without this, if the user
        // had switched the table to 'raw' on a prior file, that setting
        // would persist across Reset Tool and into the next uploaded file.
        this.setTableType('subtracted');
    }

    /** Algorithm parameters */

    getbackScale(): number {
        return this.pulsarInterface.getbackScale();
    }

    setbackScale(backScale: number): void {
        this.pulsarInterface.setbackScale(backScale);
    }

    getPulsarStar(): PulsarStarOptions {
        return this.pulsarInterface.getPulsarStar();
    }

    setPulsarStar(pulsarStar: PulsarStarOptions): void {
        this.pulsarInterface.setPulsarStar(pulsarStar);
    }

    getPeriodFoldingDisplayPeriod(): PulsarDisplayPeriod {
        return this.pulsarPeriodFolding.getPeriodFoldingDisplayPeriod();
    }

    getPeriodFoldingPeriod(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingPeriod();
    }

    getPeriodFoldingPeriodMin(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingPeriodMin();
    }

    getPeriodFoldingPeriodMax(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingPeriodMax();
    }

    getPeriodFoldingPhase(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingPhase();
    }

    getPeriodFoldingCal(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingCal();
    }

    getPeriodFoldingSpeed(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingSpeed();
    }

    getPeriodFoldingBins(): number {
        return this.pulsarPeriodFolding.getPeriodFoldingBins();
    }

    setPeriodFoldingDisplayPeriod(displayPeriod: PulsarDisplayPeriod): void {
        this.pulsarPeriodFolding.setPeriodFoldingDisplayPeriod(displayPeriod);
    }

    setPeriodFoldingPeriod(period: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingPeriod(period);
    }

    setPeriodFoldingPeriodMin(period: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingPeriodMin(period);
    }

    setPeriodFoldingPeriodMax(period: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingPeriodMax(period);
    }

    setPeriodFoldingPhase(phase: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingPhase(phase);
    }

    setPeriodFoldingCal(cal: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingCal(cal);
    }

    setPeriodFoldingSpeed(speed: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingSpeed(speed);
    }

    setPeriodFoldingBins(bins: number): void {
        this.pulsarPeriodFolding.setPeriodFoldingBins(bins);
    }


    /** Period folding — pulsar.service.ts:273-314, verbatim.
     *
     *  NOTE: unlike the variable-star sibling
     *  (VariableService.getPeriodFoldingChartDataWithError), this version does
     *  NOT apply `phase` here and does not duplicate points for
     *  displayPeriod === TWO. The pulsar tool applies phase and duplication
     *  later, after binning — see foldAndBin/duplicateIfNeeded in
     *  ./pulsar-period-folding.algorithms.ts.
     */
    getPeriodFoldingChartData(): { [key: string]: number[][] } {
        const data = this.getChartPulsarDataArray()
            .filter((entry) => entry[0] !== null)
            .sort((a, b) => a[0]! - b[0]!);

        // Empty table (user deleted all rows, or a file upload produced no
        // valid rows). Bail out with an empty series instead of dereferencing
        // data[0] and throwing.
        if (data.length === 0) {
            return { data: [] };
        }

        const minJD = data[0][0]!;
        const period = Number(this.getPeriodFoldingPeriod());

        // Initialize arrays for two series
        let pfData1: number[][] = []; // For source1
        let pfData2: number[][] = []; // For source2 (optional)

        if (period !== 0 && period !== null) {
            for (let i = 0; i < data.length; i++) {
                // Calculate x-axis (phase folded JD)
                let temp_x = period + floatMod((data[i][0]! - minJD), period);
                if (temp_x > period) {
                    temp_x -= period;
                }

                pfData1.push([temp_x, data[i][1]!]);

                if (data[i][2] !== null) {
                    pfData2.push([temp_x, data[i][2]!]);
                }
            }
        }

        pfData1.sort((a, b) => b[0] - a[0]);
        pfData2.sort((a, b) => b[0] - a[0]);

        return pfData2.length > 0
            ? { data: pfData1, data2: pfData2 }
            : { data: pfData1 };
    }


    /** Time-axis handling — pulsar.service.ts:455-468, verbatim. */
    getJdRange(): number {
        const jdArray = this.getData().map((row: PulsarDataDict) => row.jd)
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


    /** Data shaping — pulsar.service.ts:609-613 and 649-660, verbatim. */

    getChartPulsarDataArray(): (number | null)[][] {
        return this.getData().filter((row: PulsarDataDict) =>
            row.jd !== null && row.source1 !== null)
            .map((row: PulsarDataDict) => [row.jd, row.source1!, row.source2!] as [number,number,number])
    }

    getChartSourcesDataArray(): (number | null)[][][] {
        return [
          this.pulsarData.getData().filter(
            (entry: PulsarDataDict) => entry.jd !== null && entry.source1 !== null)
            .map(
              (entry: PulsarDataDict) => [entry.jd, entry.source1]),
          this.pulsarData.getData().filter(
            (entry: PulsarDataDict) => entry.jd !== null && entry.source2 !== null)
            .map(
              (entry: PulsarDataDict) => [entry.jd, entry.source2])
        ]
      }


    /** Background subtraction — pulsar.service.ts:715-739, verbatim.
     *
     *  `median` is only ever called by `backgroundSubtraction`.
     *  `dt` is the backScale window width (seconds); the window is centred on
     *  each sample, so it spans [t_i - dt/2, t_i + dt/2].
     */

    median(arr: number[]) {
        arr = arr.filter(num => !isNaN(num));
        const mid = Math.floor(arr.length / 2);
        const nums = arr.sort((a, b) => a - b);
        return arr.length % 2 !== 0 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
    }

    backgroundSubtraction(frequency: number[], flux: number[], dt: number): number[] {
        let n = Math.min(frequency.length, flux.length);
        const subtracted = [];

        let jmin = 0;
        let jmax = 0;
        for (let i = 0; i < n; i++) {
            while (jmin < n && frequency[jmin] < frequency[i] - (dt / 2)) {
                jmin++;
            }
            while (jmax < n && frequency[jmax] <= frequency[i] + (dt / 2)) {
                jmax++;
            }
            let fluxmed = this.median(flux.slice(jmin, jmax));
            subtracted.push(flux[i] - fluxmed);
        }
        return subtracted;
    }


    /** Binning — pulsar.service.ts:850-886, verbatim. */
    binData(data: number[][], bins: number): number[][] {
        if (data.length === 0) return [];

        // Calculate bin size — loop instead of Math.min/max(...) to avoid the
        // spread-arg stack overflow on large datasets.
        let xMin = data[0][0], xMax = data[0][0];
        for (let i = 1; i < data.length; i++) {
            const x = data[i][0];
            if (x < xMin) xMin = x;
            if (x > xMax) xMax = x;
        }
        const binSize = (xMax - xMin) / bins;

        // Initialize bins. Phase shifting is applied by the callers
        // (foldAndBin in the period-folding chart), not here.
        const binnedData: { x: number; ySum: number; count: number }[] = Array(bins)
          .fill(0)
          .map((_, index) => ({
            x: xMin + index * binSize + binSize / 2,
            ySum: 0,
            count: 0,
          }));

        // Populate bins
        data.forEach(([x, y]) => {
          const binIndex = Math.floor((x - xMin) / binSize);
          if (binIndex >= 0 && binIndex < bins) {
            binnedData[binIndex].ySum += y;
            binnedData[binIndex].count += 1;
          }
        });

        // Compute averages
        return binnedData
          .filter(bin => bin.count > 0) // Ignore empty bins
          .map(bin => [bin.x, bin.ySum / bin.count]);
    }


    /** Resampling helpers — pulsar.service.ts:1227-1240 and 1250-1262, verbatim.
     *
     *  JUDGMENT CALL: in astromancer the ONLY callers of these two are the
     *  sonifier (`sonification` / `sonificationBrowser`), which is audio
     *  rendering and is deliberately out of scope. They are kept here anyway
     *  because they are pure, self-contained numeric resampling with no audio
     *  or framework dependency, and are generally useful on a binned light
     *  curve. The WAV encoding, AudioContext playback and burst/waveform
     *  synthesis around them were NOT extracted.
     */

    interpolateLinear(data: number[], factor: number): number[] {
        const result: number[] = [];
        for (let i = 0; i < data.length - 1; i++) {
            const start = data[i];
            const end = data[i + 1];
            result.push(start);
            for (let j = 1; j <= factor; j++) {
                const t = j / (factor + 1);
                result.push(start * (1 - t) + end * t);
            }
        }
        result.push(data[data.length - 1]);
        return result;
    }

    // Helper: Linearly resample data to new length
    resampleLinear(data: number[], newLength: number): number[] {
        const result = new Array(newLength);
        const oldLength = data.length;
        for (let i = 0; i < newLength; i++) {
            const t = i * (oldLength - 1) / (newLength - 1);
            const index = Math.floor(t);
            const frac = t - index;
            const v1 = data[index];
            const v2 = index + 1 < oldLength ? data[index + 1] : data[index];
            result[i] = v1 * (1 - frac) + v2 * frac;
        }
        return result;
    }
}
