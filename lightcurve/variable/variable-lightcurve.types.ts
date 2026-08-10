// EXTRACTED from astromancer: src/app/tools/variable/variable.service.util.ts
//   - VariableDataDict              (lines 5-12)
//   - errorMSE                      (lines 14-20)
//   - VariableData                  (lines 22-109)
//   - VariableStarOptions           (lines 112-116)
//   - VariableInterface             (lines 118-128)
//   - VariableInterfaceStorageObject(lines 131-134)
//   - VariableInterfaceImpl         (lines 137-185)
//
// All bodies verbatim.
//
// PULSAR vs VARIABLE: the variable record carries per-source photometric
// errors (`error1`, `error2`) and their combined `errorMSE`; the pulsar record
// (PulsarDataDict) has no error columns at all. That difference propagates all
// the way through — the variable light curve and its period fold both carry
// error bars, the pulsar ones do not. `referenceStarMagnitude` here is the
// zero-point added back after differential photometry; its pulsar counterpart
// (`backScale`) is a background-subtraction window width. Same slot in the
// design, completely different physics.
//
// NOTE (duplication): `errorMSE` is byte-identical to the copy in
// pulsar.service.util.ts (extracted to ../pulsar/pulsar-lightcurve.types.ts).
// The duplication exists in astromancer itself; it is preserved here.
//
// LEFT BEHIND from the same source file:
//   - VariableChartInfo / VariableChartInfoStorageObject — chart labels
//   - VariablePeriodogram / ...StorageObject / ...Interface — periodogram
//   - VariableStorage — localStorage read/write

// EXTRACTED: was `import {MyData} from "../shared/data/data.interface"`
import {MyData} from "../shared/data.interface";

export interface VariableDataDict {
  jd: number | null;
  source1: number | null;
  source2: number | null;
  error1: number | null;
  error2: number | null;
  errorMSE: number | null;
}

export function errorMSE(error1: number | null, error2: number | null): number | null {
  if (error1 == null || error2 == null) {
    return null;
  } else {
    return Math.sqrt(error1 ** 2 + error2 ** 2) / 2;
  }
}

export class VariableData implements MyData {
  private dataDict: VariableDataDict[];

  constructor() {
    this.dataDict = VariableData.getDefaultDataDict();
  }

  public static getDefaultDataDict(): VariableDataDict[] {
    const data: VariableDataDict[] = [];
    for (let i = 0; i < 14; i++) {
      data.push({
        jd: i * 10 + Math.random() * 10 - 5,
        source1: Math.random() * 20,
        source2: Math.random() * 20,
        error1: 1,
        error2: 1,
        errorMSE: errorMSE(1, 1)
      });
    }
    return data;
  }

  addRow(index: number, amount: number): void {
    if (index > 0) {
      for (let i = 0; i < amount; i++) {
        this.dataDict.splice(index + i, 0,
          {jd: null, source1: null, source2: null, error1: null, error2: null, errorMSE: null});
      }
    } else {
      this.dataDict.push({jd: null, source1: null, source2: null, error1: null, error2: null, errorMSE: null});
    }
  }

  getData(): VariableDataDict[] {
    return this.dataDict;
  }

  getDataArray(): (number | null)[][] {
    return this.dataDict.map((entry: VariableDataDict) =>
      [entry.jd, entry.source1, entry.source2, entry.error1, entry.error2]);
  }

  getChartSourcesDataArray(): (number | null)[][][] {
    return [
      this.dataDict.filter(
        (entry: VariableDataDict) => entry.jd !== null && entry.source1 !== null)
        .map(
          (entry: VariableDataDict) => [entry.jd, entry.source1]),
      this.dataDict.filter(
        (entry: VariableDataDict) => entry.jd !== null && entry.source2 !== null)
        .map(
          (entry: VariableDataDict) => [entry.jd, entry.source2])
    ]
  }

  getChartSourcesErrorArray(): (number | null)[][][] {
    return [
      this.dataDict.filter(
        (entry: VariableDataDict) => entry.jd !== null && entry.source1 !== null && entry.errorMSE !== null)
        .map(
          (entry: VariableDataDict) => [entry.jd, entry.source1! - entry.errorMSE!, entry.source1! + entry.errorMSE!]),
      this.dataDict.filter(
        (entry: VariableDataDict) => entry.jd !== null && entry.source2 !== null && entry.errorMSE !== null)
        .map(
          (entry: VariableDataDict) => [entry.jd, entry.source2! - entry.errorMSE!, entry.source2! + entry.errorMSE!]),
    ];
  }

  removeRow(index: number, amount: number): void {
    this.dataDict = this.dataDict.slice(0, index).concat(this.dataDict.slice(index + amount));
  }

  setData(data: VariableDataDict[]): void {
    this.dataDict = data;
    this.dataDict = this.dataDict.map(
        (entry: VariableDataDict) => {
            return {
                jd: entry.jd,
                source1: entry.source1,
                source2: entry.source2,
                error1: entry.error1,
                error2: entry.error2,
                errorMSE: errorMSE(entry.error1, entry.error2)
            }
        }
    );
  }
}


export enum VariableStarOptions {
  NONE = "None",
  SOURCE1 = "Source 1",
  SOURCE2 = "Source 2",
}

export interface VariableInterface {
  getVariableStar(): VariableStarOptions;

  setVariableStar(variableStar: VariableStarOptions): void;

  getReferenceStarMagnitude(): number;

  setReferenceStarMagnitude(magnitude: number): void;

  getIsLightCurveOptionValid(): boolean;
}


export interface VariableInterfaceStorageObject {
  variableStar: VariableStarOptions;
  referenceStarMagnitude: number;
}


export class VariableInterfaceImpl implements VariableInterface {
  private variableStar: VariableStarOptions;
  private referenceStarMagnitude: number;

  constructor() {
    this.variableStar = VariableInterfaceImpl.getDefaultInterface().variableStar;
    this.referenceStarMagnitude = VariableInterfaceImpl.getDefaultInterface().referenceStarMagnitude;
  }

  public static getDefaultInterface(): VariableInterfaceStorageObject {
    return {
      variableStar: VariableStarOptions.NONE,
      referenceStarMagnitude: 0,
    };
  }

  getStorageObject(): VariableInterfaceStorageObject {
    return {
      variableStar: this.variableStar,
      referenceStarMagnitude: this.referenceStarMagnitude,
    };
  }

  setStorageObject(storageObject: VariableInterfaceStorageObject): void {
    this.variableStar = storageObject.variableStar;
    this.referenceStarMagnitude = storageObject.referenceStarMagnitude;
  }

  getVariableStar(): VariableStarOptions {
    return this.variableStar;
  }

  setVariableStar(variableStar: VariableStarOptions): void {
    this.variableStar = variableStar;
  }

  getReferenceStarMagnitude(): number {
    return this.referenceStarMagnitude;
  }

  setReferenceStarMagnitude(magnitude: number): void {
    this.referenceStarMagnitude = magnitude;
  }

  getIsLightCurveOptionValid(): boolean {
    return this.variableStar !== VariableStarOptions.NONE
      && !isNaN(this.referenceStarMagnitude);
  }
}
