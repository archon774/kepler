// EXTRACTED from astromancer: src/app/tools/shared/data/data.interface.ts
//
// Verbatim. This is the data-container contract implemented by both
// PulsarData and VariableData, i.e. the shape the light-curve algorithms
// read from and write to.
//
// Sibling interfaces in the same astromancer folder were NOT extracted:
//   - MyStorage  (shared/storage/storage.interface.ts) — localStorage persistence
//   - ChartInfo  (shared/charts/chart.interface.ts)    — chart titles/axis labels

export interface MyData {
  getData(): any[];

  getDataArray(): any[];

  setData(data: any[]): void;

  addRow(index: number, amount: number): void;

  removeRow(index: number, amount: number): void;
}
