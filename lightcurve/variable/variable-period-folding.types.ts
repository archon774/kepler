// EXTRACTED from astromancer: src/app/tools/variable/variable.service.util.ts
//   - VariableDisplayPeriod                (lines 440-443)
//   - VariablePeriodFoldingStorageObject   (lines 446-454)
//   - VariablePeriodFoldingInterface       (lines 457-485)
//   - VariablePeriodFolding                (lines 488-598)
//
// All bodies verbatim.
//
// PULSAR vs VARIABLE: this parameter set is much smaller than the pulsar one.
// It has only `displayPeriod`, `period` and `phase` — no `bins` (the variable
// fold plots individual points with error bars rather than binned averages),
// no `cal` (there is only one folded series, not two polarizations), no
// `speed` (that is a sonification playback rate, and only pulsar sonifies),
// and no `periodMin`/`periodMax` (the variable tool has no Nyquist-derived
// slider bounds). The default `period: -1` is a sentinel — see
// VariableLightCurveAlgorithms.getPeriodFoldingPeriod, which substitutes the
// full JD range when it sees a negative value. Its pulsar counterpart defaults
// to a real 0.2 s instead.
//
// JUDGMENT CALL: as with the pulsar sibling, `title` / `xAxisLabel` /
// `yAxisLabel` / `dataLabel` are chart labels retained only to keep this a
// verbatim copy rather than a rewrite.

export enum VariableDisplayPeriod {
  ONE = '1',
  TWO = '2',
}


export interface VariablePeriodFoldingStorageObject {
  displayPeriod: VariableDisplayPeriod;
  period: number;
  phase: number;
  title: string;
  xAxisLabel: string;
  yAxisLabel: string;
  dataLabel: string;
}


export interface VariablePeriodFoldingInterface {
  getPeriodFoldingDisplayPeriod(): VariableDisplayPeriod;

  getPeriodFoldingPeriod(): number;

  getPeriodFoldingPhase(): number;

  getPeriodFoldingTitle(): string;

  getPeriodFoldingXAxisLabel(): string;

  getPeriodFoldingYAxisLabel(): string;

  getPeriodFoldingDataLabel(): string;

  setPeriodFoldingDisplayPeriod(displayPeriod: VariableDisplayPeriod): void;

  setPeriodFoldingPeriod(period: number): void;

  setPeriodFoldingPhase(phase: number): void;

  setPeriodFoldingTitle(title: string): void;

  setPeriodFoldingXAxisLabel(xAxis: string): void;

  setPeriodFoldingYAxisLabel(yAxis: string): void;

  setPeriodFoldingDataLabel(data: string): void;
}


export class VariablePeriodFolding implements VariablePeriodFoldingInterface {
  public static readonly defaultHash: string = "XQGeSlw7M6";
  private displayPeriod: VariableDisplayPeriod;
  private period: number;
  private phase: number;
  private title: string;
  private xAxisLabel: string;
  private yAxisLabel: string;
  private dataLabel: string;

  constructor() {
    this.displayPeriod = VariablePeriodFolding.getDefaultStorageObject().displayPeriod;
    this.period = VariablePeriodFolding.getDefaultStorageObject().period;
    this.phase = VariablePeriodFolding.getDefaultStorageObject().phase;
    this.title = VariablePeriodFolding.getDefaultStorageObject().title;
    this.xAxisLabel = VariablePeriodFolding.getDefaultStorageObject().xAxisLabel;
    this.yAxisLabel = VariablePeriodFolding.getDefaultStorageObject().yAxisLabel;
    this.dataLabel = VariablePeriodFolding.getDefaultStorageObject().dataLabel;
  }

  public static getDefaultStorageObject(): VariablePeriodFoldingStorageObject {
    return {
      displayPeriod: VariableDisplayPeriod.TWO,
      period: -1,
      phase: 0,
      title: "Title",
      xAxisLabel: "x",
      yAxisLabel: "y",
      dataLabel: VariablePeriodFolding.defaultHash,
    }
  }

  getPeriodFoldingDataLabel(): string {
    return this.dataLabel;
  }

  getPeriodFoldingDisplayPeriod(): VariableDisplayPeriod {
    return this.displayPeriod;
  }

  getPeriodFoldingPeriod(): number {
    return this.period;
  }

  getPeriodFoldingPhase(): number {
    return this.phase;
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

  setPeriodFoldingDisplayPeriod(displayPeriod: VariableDisplayPeriod): void {
    this.displayPeriod = displayPeriod;
  }

  setPeriodFoldingPeriod(period: number): void {
    this.period = period;
  }

  setPeriodFoldingPhase(phase: number): void {
    this.phase = phase;
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

  getPeriodFoldingStorageObject(): VariablePeriodFoldingStorageObject {
    return {
      displayPeriod: this.displayPeriod,
      period: this.period,
      phase: this.phase,
      title: this.title,
      xAxisLabel: this.xAxisLabel,
      yAxisLabel: this.yAxisLabel,
      dataLabel: this.dataLabel,
    }
  }

  setPeriodFoldingStorageObject(storageObject: VariablePeriodFoldingStorageObject): void {
    this.displayPeriod = storageObject.displayPeriod;
    this.period = storageObject.period;
    this.phase = storageObject.phase;
    this.title = storageObject.title;
    this.xAxisLabel = storageObject.xAxisLabel;
    this.yAxisLabel = storageObject.yAxisLabel;
    this.dataLabel = storageObject.dataLabel;
  }

}
