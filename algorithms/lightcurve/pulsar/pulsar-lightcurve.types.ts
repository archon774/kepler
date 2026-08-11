// EXTRACTED from astromancer: src/app/tools/pulsar/pulsar.service.util.ts
//   - PulsarDataDict              (lines 5-9)
//   - errorMSE                    (lines 11-17)
//   - PulsarStarOptions           (lines 20-24)
//   - PulsarInterface             (lines 26-36)
//   - PulsarInterfaceStorageObject(lines 38-42)
//   - PulsarInterfaceImpl         (lines 45-101)
//   - PulsarData                  (lines 222-316)
//
// All bodies verbatim. These are the algorithm's input/output models: the
// per-sample record, the star-selection enum, the tunable parameter carrier
// (`backScale` is the background-subtraction window width in seconds), and the
// data container.
//
// LEFT BEHIND from the same source file (see docs/extraction.md, Light Curve):
//   - PulsarChartInfo / PulsarChartInfoStorageObject — chart titles + axis labels
//   - PulsarPeriodogram / PulsarPeriodogramStorageObject / ...Interface — periodogram
//   - PulsarStorage — localStorage read/write

// EXTRACTED: was `import {MyData} from "../shared/data/data.interface"`
import {MyData} from "../shared/data.interface";

export interface PulsarDataDict {
  jd: number | null;
  source1: number | null;
  source2: number | null;
}

export function errorMSE(error1: number | null, error2: number | null): number | null {
  if (error1 == null || error2 == null) {
    return null;
  } else {
    return Math.sqrt(error1 ** 2 + error2 ** 2) / 2;
  }
}


export enum PulsarStarOptions {
  NONE = "None",
  SOURCE1 = "Source 1",
  SOURCE2 = "Source 2",
}

export interface PulsarInterface {
  getPulsarStar(): PulsarStarOptions;

  setPulsarStar(pulsarStar: PulsarStarOptions): void;

  getbackScale(): number;

  setbackScale(magnitude: number): void;

  getIsLightCurveOptionValid(): boolean;
}

export interface PulsarInterfaceStorageObject {
  pulsarStar: PulsarStarOptions;
  backScale: number;
  LightCurveOptionValid: boolean;
}


export class PulsarInterfaceImpl implements PulsarInterface {
  private pulsarStar: PulsarStarOptions;
  private backScale: number;
  private LightCurveOptionValid: boolean;

  constructor() {
    this.pulsarStar = PulsarInterfaceImpl.getDefaultInterface().pulsarStar;
    this.backScale = PulsarInterfaceImpl.getDefaultInterface().backScale;
    this.LightCurveOptionValid = true;
  }

  public static getDefaultInterface(): PulsarInterfaceStorageObject {
    return {
      pulsarStar: PulsarStarOptions.NONE,
      backScale: 3,
      LightCurveOptionValid: true,
    };
  }

  getStorageObject(): PulsarInterfaceStorageObject {
    return {
      pulsarStar: this.pulsarStar,
      backScale: this.backScale,
      LightCurveOptionValid: this.LightCurveOptionValid,
    };
  }

  setStorageObject(storageObject: PulsarInterfaceStorageObject): void {
    this.pulsarStar = storageObject.pulsarStar;
    this.backScale = storageObject.backScale;
    this.LightCurveOptionValid = storageObject.LightCurveOptionValid;
  }

  getPulsarStar(): PulsarStarOptions {
    return this.pulsarStar;
  }

  setPulsarStar(pulsarStar: PulsarStarOptions): void {
    this.pulsarStar = pulsarStar;
  }

  getbackScale(): number {
    return this.backScale;
  }

  setbackScale(backScale: number): void {
    this.backScale = backScale;
  }

  // PRESERVED QUIRK (not fixed — see docs/extraction.md, Light Curve §9.3): the `!` negation is
  // in the source. PulsarService.getIsLightCurveOptionValid returns the same
  // flag WITHOUT negating, so the two disagree for every input. Only the
  // service version is reachable from the UI, which is why the sign error here
  // has never surfaced.
  getIsLightCurveOptionValid(): boolean {
    return !this.LightCurveOptionValid;
  }

  setLightCurveOptionValid(Valid: boolean): void {
    this.LightCurveOptionValid = Valid;
  }
}


// Class for managing data
export class PulsarData implements MyData {
  private frequencyData: number[] = [];
  private channel1Data: number[] = [];
  private pulsarDataDict: PulsarDataDict[] = [];
  private pulsarCombinedDataDict: PulsarDataDict[] = [];
  private pulsarRawDataDict: PulsarDataDict[] = [];
  private pulsarTableType: string = 'subtracted';
  private chartComputedPeriodogramDataArray: [Array<Number>, Array<Number>] = [[0],[0]];

  getData(): PulsarDataDict[] {
    return this.pulsarDataDict;
  }

  getCombinedData(): PulsarDataDict[] {
    return this.pulsarCombinedDataDict;
  }

  getRawData(): PulsarDataDict[] {
    return this.pulsarRawDataDict;
  }

  getChartComputedPeriodogramDataArray(): [Array<Number>, Array<Number>] {
    return this.chartComputedPeriodogramDataArray;
  }

  getTableType(): string {
    return this.pulsarTableType;
  }

  getDataArray(): any[] {
    return [this.frequencyData, this.channel1Data];
  }

  setData(data: PulsarDataDict[]): void {
    this.pulsarDataDict = data;
    this.frequencyData = data.map(d => d.source1 ?? 0);
    this.channel1Data = data.map(d => d.source2 ?? 0);
  }

  setCombinedData(data: PulsarDataDict[]): void {
    this.pulsarCombinedDataDict = data;
  }

  setRawData(data: PulsarDataDict[]): void {
    this.pulsarRawDataDict = data;
  }

  setChartComputedPeriodogramDataArray(data: [Array<Number>, Array<Number>]): void {
    this.chartComputedPeriodogramDataArray = data;
  }

  setTableType(type: string): void {
    this.pulsarTableType = type;
  }

  addRow(index: number, _amount: number): void {
    // Keep raw/combined/subtracted in sync so the new row appears regardless
    // of which table-type view the user is in.
    const newRow = (): PulsarDataDict => ({ jd: null, source1: null, source2: null });
    this.pulsarDataDict.splice(index, 0, newRow());
    this.pulsarRawDataDict.splice(index, 0, newRow());
    this.pulsarCombinedDataDict.splice(index, 0, newRow());
    this.frequencyData.splice(index, 0, 0);
    this.channel1Data.splice(index, 0, 0);
  }

  removeRow(index: number, amount: number): void {
    this.pulsarDataDict.splice(index, amount);
    this.pulsarRawDataDict.splice(index, amount);
    this.pulsarCombinedDataDict.splice(index, amount);
    this.frequencyData.splice(index, amount);
    this.channel1Data.splice(index, amount);
  }

  filterData(predicate: (data: PulsarDataDict) => boolean): PulsarDataDict[] {
    return this.pulsarDataDict.filter(predicate);
  }

  map<T>(callback: (data: PulsarDataDict) => T): T[] {
    return this.pulsarDataDict.map(callback);
  }

  public static getDefaultDataDict(): PulsarDataDict[] {
    const data: PulsarDataDict[] = [];
    for (let i = 0; i < 100; i++) {
      const randomData = (): number => parseFloat((Math.random() * 10000).toFixed(2));
      data.push({
        jd: i,
        source1: randomData(),
        source2: randomData(),
      });
    }
    return data;
  }
}
