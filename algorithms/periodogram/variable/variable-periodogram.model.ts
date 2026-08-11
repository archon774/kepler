// EXTRACTED from astromancer:
//   src/app/tools/variable/variable.service.util.ts  (697 lines total)
//   - VariableDataDict                  (lines 5-12,    verbatim)
//   - errorMSE                          (lines 14-20,   verbatim)
//   - VariablePeriodogramStorageObject  (lines 298-305, verbatim)
//   - VariablePeriodogramInterface      (lines 308-336, verbatim)
//   - VariablePeriodogram               (lines 339-437, verbatim)
//
// Input/output models for the variable-star periodogram. The key difference
// from the pulsar variant: VariableDataDict carries per-point errors, and
// errorMSE combines the two source errors into the single weight the
// error-weighted Lomb-Scargle consumes.
//
// The variable parameter block is deliberately smaller than the pulsar one —
// no `points` and no `method`. The variable tool hardcodes 2000 steps and is
// period-mode only. See docs/extraction.md, Periodogram for the full pulsar-vs-variable split.
//
// Framework seams: none — these are plain TS types and classes.
//
// LEFT BEHIND from the same file: VariableData (light-curve container),
// VariableInterfaceImpl, VariableChartInfo, VariablePeriodFolding,
// VariableStorage (localStorage).
//
// OVERLAP: VariableDataDict and errorMSE are duplicated into the lightcurve
// extraction by design — the light curve needs the same row type.

export interface VariableDataDict {
  jd: number | null;
  source1: number | null;
  source2: number | null;
  error1: number | null;
  error2: number | null;
  errorMSE: number | null;
}

/**
 * Combined per-point uncertainty: quadrature sum of the two source errors,
 * halved. This is the value fed to lombScargleWithError() as its `error`
 * array, where it becomes the 1/sigma^2 weight.
 */
export function errorMSE(error1: number | null, error2: number | null): number | null {
  if (error1 == null || error2 == null) {
    return null;
  } else {
    return Math.sqrt(error1 ** 2 + error2 ** 2) / 2;
  }
}


export interface VariablePeriodogramStorageObject {
  title: string;
  xAxisLabel: string;
  yAxisLabel: string;
  dataLabel: string;
  startPeriod: number;
  endPeriod: number;
}


export interface VariablePeriodogramInterface {
  getPeriodogramTitle(): string;

  getPeriodogramXAxisLabel(): string;

  getPeriodogramYAxisLabel(): string;

  getPeriodogramDataLabel(): string;

  getPeriodogramStartPeriod(): number;

  getPeriodogramEndPeriod(): number;

  getPeriodogramStorageObject(): VariablePeriodogramStorageObject;

  setPeriodogramTitle(title: string): void;

  setPeriodogramXAxisLabel(xAxis: string): void;

  setPeriodogramYAxisLabel(yAxis: string): void;

  setPeriodogramDataLabel(data: string): void;

  setPeriodogramStartPeriod(startPeriod: number): void;

  setPeriodogramEndPeriod(endPeriod: number): void;

  setPeriodogramStorageObject(storageObject: VariablePeriodogramStorageObject): void;
}


export class VariablePeriodogram implements VariablePeriodogramInterface {
  public static readonly defaultHash: string = "XQGeSlw7M6";
  private title: string;
  private xAxisLabel: string;
  private yAxisLabel: string;
  private dataLabel: string;
  private startPeriod: number;
  private endPeriod: number;


  constructor() {
    this.title = VariablePeriodogram.getDefaultPeriodogram().title;
    this.xAxisLabel = VariablePeriodogram.getDefaultPeriodogram().xAxisLabel;
    this.yAxisLabel = VariablePeriodogram.getDefaultPeriodogram().yAxisLabel;
    this.dataLabel = VariablePeriodogram.getDefaultPeriodogram().dataLabel;
    this.startPeriod = VariablePeriodogram.getDefaultPeriodogram().startPeriod;
    this.endPeriod = VariablePeriodogram.getDefaultPeriodogram().endPeriod;
  }

  public static getDefaultPeriodogram(): VariablePeriodogramStorageObject {
    return {
      title: "Title",
      xAxisLabel: "x",
      yAxisLabel: "y",
      dataLabel: VariablePeriodogram.defaultHash,
      startPeriod: 0.1,
      endPeriod: 1,
    }
  }

  getPeriodogramDataLabel(): string {
    return this.dataLabel;
  }

  getPeriodogramEndPeriod(): number {
    return this.endPeriod;
  }

  getPeriodogramStartPeriod(): number {
    return this.startPeriod;
  }

  getPeriodogramStorageObject(): VariablePeriodogramStorageObject {
    return {
      title: this.title,
      xAxisLabel: this.xAxisLabel,
      yAxisLabel: this.yAxisLabel,
      dataLabel: this.dataLabel,
      startPeriod: this.startPeriod,
      endPeriod: this.endPeriod,
    }
  }

  getPeriodogramTitle(): string {
    return this.title;
  }

  getPeriodogramXAxisLabel(): string {
    return this.xAxisLabel;
  }

  getPeriodogramYAxisLabel(): string {
    return this.yAxisLabel;
  }

  setPeriodogramDataLabel(data: string): void {
    this.dataLabel = data;
  }

  setPeriodogramEndPeriod(endPeriod: number): void {
    this.endPeriod = endPeriod;
  }

  setPeriodogramStartPeriod(startPeriod: number): void {
    this.startPeriod = startPeriod;
  }

  setPeriodogramStorageObject(storageObject: VariablePeriodogramStorageObject): void {
    this.title = storageObject.title;
    this.xAxisLabel = storageObject.xAxisLabel;
    this.yAxisLabel = storageObject.yAxisLabel;
    this.dataLabel = storageObject.dataLabel;
    this.startPeriod = storageObject.startPeriod;
    this.endPeriod = storageObject.endPeriod;
  }

  setPeriodogramTitle(title: string): void {
    this.title = title;
  }

  setPeriodogramXAxisLabel(xAxis: string): void {
    this.xAxisLabel = xAxis;
  }

  setPeriodogramYAxisLabel(yAxis: string): void {
    this.yAxisLabel = yAxis;
  }

}
