// EXTRACTED from astromancer: src/app/tools/pulsar/pulsar.service.util.ts
//   - PulsarDisplayPeriod                (lines 524-527)
//   - PulsarPeriodFoldingStorageObject   (lines 530-543)
//   - PulsarPeriodFoldingInterface       (lines 546-580)
//   - PulsarPeriodFolding                (lines 583-760)
//
// All bodies verbatim. This is the parameter model for the period-folding
// algorithm: `period`, `phase`, `bins`, `cal` (relative calibration applied to
// the second polarization before differencing) and `displayPeriod` (how many
// periods to plot) are all algorithm inputs. `periodMin`/`periodMax` are the
// bounds the light-curve ingest derives from the data's Nyquist limit.
//
// JUDGMENT CALL: `title` / `xAxisLabel` / `yAxisLabel` / `dataLabel` and their
// accessors are chart labels, i.e. UI. They are retained here only because
// splitting them out would have meant rewriting the class rather than
// extracting it — this file is a verbatim copy, not a redesign.

export enum PulsarDisplayPeriod {
  ONE = '1',
  TWO = '2',
}


export interface PulsarPeriodFoldingStorageObject {
  displayPeriod: PulsarDisplayPeriod;
  period: number;
  periodMin: number;
  periodMax: number;
  phase: number;
  cal: number;
  speed: number;
  bins: number;
  title: string;
  xAxisLabel: string;
  yAxisLabel: string;
  dataLabel: string;
}


export interface PulsarPeriodFoldingInterface {
  getPeriodFoldingDisplayPeriod(): PulsarDisplayPeriod;

  getPeriodFoldingPeriod(): number;

  getPeriodFoldingPhase(): number;

  getPeriodFoldingCal(): number;

  getPeriodFoldingTitle(): string;

  getPeriodFoldingXAxisLabel(): string;

  getPeriodFoldingYAxisLabel(): string;

  getPeriodFoldingDataLabel(): string;

  setPeriodFoldingDisplayPeriod(displayPeriod: PulsarDisplayPeriod): void;

  setPeriodFoldingPeriod(period: number): void;

  setPeriodFoldingPeriodMin(periodMin: number): void;

  setPeriodFoldingPeriodMax(periodMax: number): void;

  setPeriodFoldingPhase(phase: number): void;

  setPeriodFoldingTitle(title: string): void;

  setPeriodFoldingXAxisLabel(xAxis: string): void;

  setPeriodFoldingYAxisLabel(yAxis: string): void;

  setPeriodFoldingDataLabel(data: string): void;
}


export class PulsarPeriodFolding implements PulsarPeriodFoldingInterface {
  public static readonly defaultHash: string = "XQGeSlw7M6";
  private displayPeriod: PulsarDisplayPeriod;
  private period: number;
  private periodMin: number;
  private periodMax: number;
  private phase: number;
  private cal: number;
  private speed: number;
  private bins: number;
  private title: string;
  private xAxisLabel: string;
  private yAxisLabel: string;
  private dataLabel: string;

  constructor() {
    this.displayPeriod = PulsarPeriodFolding.getDefaultStorageObject().displayPeriod;
    this.period = PulsarPeriodFolding.getDefaultStorageObject().period;
    this.periodMin = PulsarPeriodFolding.getDefaultStorageObject().periodMin;
    this.periodMax = PulsarPeriodFolding.getDefaultStorageObject().periodMax;
    this.phase = PulsarPeriodFolding.getDefaultStorageObject().phase;
    this.cal = PulsarPeriodFolding.getDefaultStorageObject().cal;
    this.speed = PulsarPeriodFolding.getDefaultStorageObject().speed;
    this.bins = PulsarPeriodFolding.getDefaultStorageObject().bins;
    this.title = PulsarPeriodFolding.getDefaultStorageObject().title;
    this.xAxisLabel = PulsarPeriodFolding.getDefaultStorageObject().xAxisLabel;
    this.yAxisLabel = PulsarPeriodFolding.getDefaultStorageObject().yAxisLabel;
    this.dataLabel = PulsarPeriodFolding.getDefaultStorageObject().dataLabel;
  }

  public static getDefaultStorageObject(): PulsarPeriodFoldingStorageObject {
    return {
      displayPeriod: PulsarDisplayPeriod.ONE,
      period: 0.2,
      // periodMin/periodMax intentionally mirror the periodogram's
      // startPeriod/endPeriod defaults — the period-folding slider should
      // span the same range a fresh periodogram would default to.
      periodMin: 0.1,
      periodMax: 3,
      phase: 0,
      cal: 1.0,
      speed: 1.0,
      bins: 100,
      title: "Title",
      xAxisLabel: "Time (s)",
      yAxisLabel: "Intensity",
      dataLabel: PulsarPeriodFolding.defaultHash,
    }
  }

  getPeriodFoldingDataLabel(): string {
    return this.dataLabel;
  }

  getPeriodFoldingDisplayPeriod(): PulsarDisplayPeriod {
    return this.displayPeriod;
  }

  getPeriodFoldingPeriod(): number {
    return this.period;
  }

  getPeriodFoldingPeriodMin(): number {
    return this.periodMin;
  }

  getPeriodFoldingPeriodMax(): number {
    return this.periodMax;
  }

  getPeriodFoldingPhase(): number {
    return this.phase;
  }

  getPeriodFoldingCal(): number {
    return this.cal;
  }

  getPeriodFoldingSpeed(): number {
    return this.speed;
  }

  getPeriodFoldingBins(): number {
    return this.bins;
  }

  getPeriodFoldingTitle(): string {
    return this.title;
  }

  getPeriodFoldingXAxisLabel(): string {
    return this.xAxisLabel;
  }

  getPeriodFoldingYAxisLabel(): string {
    return this.yAxisLabel;
  }

  setPeriodFoldingDataLabel(data: string): void {
    this.dataLabel = data;
  }

  setPeriodFoldingDisplayPeriod(displayPeriod: PulsarDisplayPeriod): void {
    this.displayPeriod = displayPeriod;
  }

  setPeriodFoldingPeriod(period: number): void {
    this.period = period;
  }

  setPeriodFoldingPeriodMin(period: number): void {
    this.periodMin = period;
  }

  setPeriodFoldingPeriodMax(period: number): void {
    this.periodMax = period;
  }

  setPeriodFoldingPhase(phase: number): void {
    this.phase = phase;
  }

  setPeriodFoldingCal(cal: number): void {
    this.cal = cal;
  }

  setPeriodFoldingSpeed(speed: number): void {
    this.speed = speed;
  }

  setPeriodFoldingBins(bins: number): void {
    this.bins = bins;
  }

  setPeriodFoldingTitle(title: string): void {
    this.title = title;
  }

  setPeriodFoldingXAxisLabel(xAxis: string): void {
    this.xAxisLabel = xAxis;
  }

  setPeriodFoldingYAxisLabel(yAxis: string): void {
    this.yAxisLabel = yAxis;
  }

  getPeriodFoldingStorageObject(): PulsarPeriodFoldingStorageObject {
    return {
      displayPeriod: this.displayPeriod,
      period: this.period,
      periodMin: this.periodMin,
      periodMax: this.periodMax,
      phase: this.phase,
      cal: this.cal,
      speed: this.speed,
      bins: this.bins,
      title: this.title,
      xAxisLabel: this.xAxisLabel,
      yAxisLabel: this.yAxisLabel,
      dataLabel: this.dataLabel,
    }
  }

  setPeriodFoldingStorageObject(storageObject: PulsarPeriodFoldingStorageObject): void {
    this.displayPeriod = storageObject.displayPeriod;
    this.period = storageObject.period;
    this.periodMin = storageObject.periodMin;
    this.periodMax = storageObject.periodMax;
    this.phase = storageObject.phase;
    this.cal = storageObject.cal;
    this.speed = storageObject.speed;
    this.bins = storageObject.bins;
    this.title = storageObject.title;
    this.xAxisLabel = storageObject.xAxisLabel;
    this.yAxisLabel = storageObject.yAxisLabel;
    this.dataLabel = storageObject.dataLabel;
  }
}
