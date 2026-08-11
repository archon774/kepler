// EXTRACTED from astromancer:
//   src/app/tools/cluster/FSR/cmd-fsr/cmd-fsr.component.ts  (135 lines;
//   the ~45-line getCmdData body lifted here)
//
// CmdFsrComponent renders the preview colour-magnitude diagram shown beside
// the field-star-removal histograms. The Highcharts options block, the
// axis-label setter and the debounced subscription are UI and are left behind.
//
// getCmdData is genuine algorithm: it picks a colour index from a fixed
// preference list of filter pairs (BP-RP, W1-W2, g'-i', J-H, else the first two
// available filters), builds blue-red vs red for every source that has both
// filters, and then selects whichever candidate pair yielded the most points.
// Body copied verbatim; only the `this.*` accesses are parameterised.

import {CMDFilterSet, FILTER, Source} from "../cluster.util";

export interface CmdData {
  // colour-magnitude points as [blueMag - redMag, redMag]
  data: number[][];
  // the filter pair that won the "most points" selection
  blueFilter: FILTER;
  redFilter: FILTER;
}

// EXTRACTED: was `private getCmdData(): number[][]` on CmdFsrComponent.
//            `sources` was `this.dataService.getSources(true)` (cluster-only
//            sources) and `filters` was `this.dataService.getFilters()`; both
//            are now explicit parameters. The original assigned the winning
//            pair to `this.blueFilter` / `this.redFilter` as a side effect
//            purely so the axis labels could read them — here they are
//            returned alongside the data instead.
export function getCmdData(sources: Source[], filters: FILTER[]): CmdData {
  const availableFilterSets: CMDFilterSet[] = []
  const result: number[][][] = []
  if (filters.includes(FILTER.BP) && filters.includes(FILTER.RP)) {
    availableFilterSets.push({blue: FILTER.BP, red: FILTER.RP});
    result.push([]);
  }
  if (filters.includes(FILTER.W1) && filters.includes(FILTER.W2)) {
    availableFilterSets.push({blue: FILTER.W1, red: FILTER.W2});
    result.push([]);
  }
  if (filters.includes(FILTER.G_PRIME) && filters.includes(FILTER.I_PRIME)) {
    availableFilterSets.push({blue: FILTER.G_PRIME, red: FILTER.I_PRIME});
    result.push([]);
  }
  if (filters.includes(FILTER.J) && filters.includes(FILTER.H)) {
    availableFilterSets.push({blue: FILTER.J, red: FILTER.H});
    result.push([]);
  }
  if (availableFilterSets.length === 0) {
    availableFilterSets.push({blue: filters[0], red: filters[1]});
    result.push([]);
  }
  for (const source of sources) {
    if (source.photometries) {
      const sourceFilters: FILTER[] = source.photometries.map(p => p.filter);
      for (let i = 0; i < availableFilterSets.length; i++) {
        const filterSet = availableFilterSets[i];
        let blueMag: number | undefined;
        let redMag: number | undefined;
        if (sourceFilters.includes(filterSet.blue) && sourceFilters.includes(filterSet.red)) {
          blueMag = source.photometries.find(p => p.filter === filterSet.blue)?.mag;
          redMag = source.photometries.find(p => p.filter === filterSet.red)?.mag;
          result[i].push([blueMag! - redMag!, redMag!]);
        }
      }
    }
  }
  const resultLengths = result.map(r => r.length);
  const maxLengthIndex = resultLengths.indexOf(Math.max(...resultLengths));
  return {
    data: result[maxLengthIndex],
    blueFilter: availableFilterSets[maxLengthIndex].blue,
    redFilter: availableFilterSets[maxLengthIndex].red,
  };
}
