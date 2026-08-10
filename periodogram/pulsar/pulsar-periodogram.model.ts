// EXTRACTED from astromancer:
//   src/app/tools/pulsar/pulsar.service.util.ts  (910 lines total)
//   - PulsarDataDict                  (lines 5-9,    verbatim)
//   - PulsarPeriodogramStorageObject  (lines 318-329, verbatim)
//   - PulsarPeriodogramInterface      (lines 332-368, verbatim)
//   - PulsarPeriodogram               (lines 371-521, verbatim)
//
// These are the input/output data models of the pulsar periodogram: the
// per-row sample shape that feeds Lomb-Scargle, and the parameter block
// (start/end period, step count, period-vs-frequency mode) that defines the
// grid the transform is evaluated on.
//
// Framework seams: none in this file — pulsar.service.util.ts imports only
// MyData / MyStorage / ChartInfo interfaces, and none of the types below
// implement them. The classes are plain TS with no decorators.
//
// LEFT BEHIND from the same file (not periodogram algorithm):
//   PulsarInterfaceImpl, PulsarChartInfo   - UI/label state
//   PulsarData                             - light-curve data container
//                                            (owned by the lightcurve
//                                            extraction; it does also hold
//                                            chartComputedPeriodogramDataArray,
//                                            which is a persistence cache of
//                                            this tool's output)
//   PulsarPeriodFolding / PulsarStorage    - folding state + localStorage
//
// OVERLAP: PulsarDataDict is duplicated into the lightcurve extraction by
// design — it is the shared row type for both tools.

export interface PulsarDataDict {
  jd: number | null;
  source1: number | null;
  source2: number | null;
}


export interface PulsarPeriodogramStorageObject {
  title: string;
  xAxisLabel: string;
  yAxisLabel: string;
  dataLabel: string;
  points: number;
  method: boolean;
  startPeriodLabel: string;
  endPeriodLabel: string;
  startPeriod: number;
  endPeriod: number;
}


export interface PulsarPeriodogramInterface {
  getPeriodogramTitle(): string;

  getPeriodogramXAxisLabel(): string;

  getPeriodogramYAxisLabel(): string;

  getPeriodogramDataLabel(): string;

  getPeriodogramPoints(): number;

  getPeriodogramMethod(): boolean;

  getPeriodogramStartPeriod(): number;

  getPeriodogramEndPeriod(): number;

  getPeriodogramStorageObject(): PulsarPeriodogramStorageObject;

  setPeriodogramTitle(title: string): void;

  setPeriodogramXAxisLabel(xAxis: string): void;

  setPeriodogramYAxisLabel(yAxis: string): void;

  setPeriodogramDataLabel(data: string): void;

  setPeriodogramPoints(points: number): void;

  setPeriodogramMethod(method: boolean): void;

  setPeriodogramStartPeriod(startPeriod: number): void;

  setPeriodogramEndPeriod(endPeriod: number): void;

  setPeriodogramStorageObject(storageObject: PulsarPeriodogramStorageObject): void;
}


// NOTE on `method`: it is the period-vs-frequency mode flag, threaded all the
// way down to lombScargle()'s `freqMode` parameter.
//   method === false -> period mode    (x axis is period in seconds)
//   method === true  -> frequency mode (x axis is frequency in Hz)
export class PulsarPeriodogram implements PulsarPeriodogramInterface {
  public static readonly defaultHash: string = "XQGeSlw7M6";
  private title: string;
  private xAxisLabel: string;
  private yAxisLabel: string;
  private dataLabel: string;
  private points: number;
  private method: boolean;
  private startPeriodLabel: string;
  private endPeriodLabel: string;
  private startPeriod: number;
  private endPeriod: number;


  constructor() {
    this.title = PulsarPeriodogram.getDefaultPeriodogram().title;
    this.xAxisLabel = PulsarPeriodogram.getDefaultPeriodogram().xAxisLabel;
    this.yAxisLabel = PulsarPeriodogram.getDefaultPeriodogram().yAxisLabel;
    this.dataLabel = PulsarPeriodogram.getDefaultPeriodogram().dataLabel;
    this.points = PulsarPeriodogram.getDefaultPeriodogram().points;
    this.method = PulsarPeriodogram.getDefaultPeriodogram().method;
    this.startPeriodLabel = PulsarPeriodogram.getDefaultPeriodogram().startPeriodLabel;
    this.endPeriodLabel = PulsarPeriodogram.getDefaultPeriodogram().endPeriodLabel;
    this.startPeriod = PulsarPeriodogram.getDefaultPeriodogram().startPeriod;
    this.endPeriod = PulsarPeriodogram.getDefaultPeriodogram().endPeriod;
  }

  public static getDefaultPeriodogram(): PulsarPeriodogramStorageObject {
    return {
      title: "Title",
      xAxisLabel: "Period (s)",
      yAxisLabel: "Intensity",
      dataLabel: PulsarPeriodogram.defaultHash,
      points: 1000,
      method: false,
      startPeriodLabel: "Start Period (s)",
      endPeriodLabel: "End Period (s)",
      startPeriod: 0.1,
      endPeriod: 3,
    }
  }

  getPeriodogramDataLabel(): string {
    return this.dataLabel;
  }

  getPeriodogramPoints(): number {
    return this.points;
  }

  getPeriodogramMethod(): boolean {
    return this.method;
  }

  getPeriodogramStartPeriodLabel(): string {
    return this.startPeriodLabel;
  }

  getPeriodogramEndPeriodLabel(): string {
    return this.endPeriodLabel;
  }

  getPeriodogramStartPeriod(): number {
    return this.startPeriod;
  }

  getPeriodogramEndPeriod(): number {
    return this.endPeriod;
  }

  getPeriodogramStorageObject(): PulsarPeriodogramStorageObject {
    return {
      title: this.title,
      xAxisLabel: this.xAxisLabel,
      yAxisLabel: this.yAxisLabel,
      dataLabel: this.dataLabel,
      points: this.points,
      method: this.method,
      startPeriodLabel: this.startPeriodLabel,
      endPeriodLabel: this.endPeriodLabel,
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

  setPeriodogramPoints(points: number): void {
    this.points = points;
  }

  setPeriodogramMethod(method: boolean): void {
    this.method = method;
  }

  setPeriodogramStartPeriodLabel(startPeriodLabel: string): void {
    this.startPeriodLabel = startPeriodLabel;
  }

  setPeriodogramEndPeriodLabel(endPeriodLabel: string): void {
    this.endPeriodLabel = endPeriodLabel;
  }

  setPeriodogramEndPeriod(endPeriod: number): void {
    this.endPeriod = endPeriod;
  }

  setPeriodogramStartPeriod(startPeriod: number): void {
    this.startPeriod = startPeriod;
  }

  setPeriodogramStorageObject(storageObject: PulsarPeriodogramStorageObject): void {
    this.title = storageObject.title;
    this.xAxisLabel = storageObject.xAxisLabel;
    this.yAxisLabel = storageObject.yAxisLabel;
    this.points = storageObject.points;
    this.method = storageObject.method;
    this.dataLabel = storageObject.dataLabel;
    this.startPeriod = storageObject.startPeriod;
    this.endPeriod = storageObject.endPeriod;
    this.startPeriodLabel = storageObject.startPeriodLabel;
    this.endPeriodLabel = storageObject.endPeriodLabel;
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
