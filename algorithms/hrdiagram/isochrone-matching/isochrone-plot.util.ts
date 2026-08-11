// EXTRACTED from astromancer:
//   src/app/tools/cluster/isochrone-matching/plots/plot/plot.component.ts
//   (447 lines; ~150 algorithmic lines lifted here)
//
// ==========================================================================
// THIS IS THE HEART OF THE HR-DIAGRAM TOOL.
// ==========================================================================
//
// PlotComponent is an Angular/Highcharts scatter+line chart, but the actual
// isochrone-matching transform is buried inside it. Everything below is that
// transform, with the chart removed.
//
// The physics, in the order the component applies it:
//
//   generateRawData    Build raw observed points per source: colour index
//                      (blueMag - redMag) against the luminosity-filter
//                      apparent magnitude, carrying the worst per-filter
//                      magnitude error so it can be cut on later.
//
//   computePlotDelta   The distance + reddening offset between the OBSERVED
//                      colour-magnitude plane and the ABSOLUTE (dereddened)
//                      HR plane:
//                        dx = A(red) - A(blue)            [colour excess]
//                        dy = -A(lum) - 5*log10(d_pc) + 5 [distance modulus]
//                      where A(lambda) is cluster.util::getExtinction and
//                      distance is in kpc (hence the *1000).
//
//   getPlotData        HR mode: shift the OBSERVED stars by +delta into the
//                      absolute plane, and leave the isochrone untouched.
//                      CM mode: leave the stars in observed magnitudes, and
//                      shift the ISOCHRONE by -delta instead (see
//                      applyIsochroneTransform). The two modes are the same
//                      fit viewed from either side. Both modes first drop any
//                      point whose worst magnitude error exceeds maxMagError.
//
//   applyIsochroneTransform
//                      Applies that -delta shift to the model isochrone in CM
//                      mode, and honours the backend's `iSkip` index by
//                      splicing a [null, null] break into the polyline (this
//                      is how a discontinuous evolutionary track is drawn
//                      without a bogus connecting segment).
//
//   getStandardViewRange
//                      The fixed "Standard View" axis window, derived from the
//                      per-filter blue/red/faint/bright extremes in
//                      cluster.util::filterFramingValue with a 1/8 margin.
//   getDataRange       The "Frame on Data" window: bounding box of the plotted
//                      points with a 10% pad.
//
// Framework seams cut: @Component/@Input, Highcharts options + chartObject
// (all series/axis/tooltip config, setExtremes, setData, setTitle), the three
// RxJS subscriptions that re-ran these functions on parameter change, the
// try/catch pairs whose only purpose was "chart not built yet -> write to the
// options literal instead", the axis-title string building (with its
// "prime" -> "'" prettifying and <sub>0</sub> markup), and the HttpClient GET
// of the isochrone itself (see ISOCHRONE DATA note below).
//
// ISOCHRONE DATA: astromancer does NOT ship isochrone grids. The model track
// is fetched per parameter change from the backend:
//     GET {apiUrl}/cluster/isochrone
//         ?age&metallicity&blue_filter&red_filter&lum_filter
//     -> { data: number[][], iSkip: number }
// with `data` already in [colour, absolute magnitude] pairs for the requested
// filter triple. Nothing to copy; the grid lives server-side. See
// docs/extraction.md, HR Diagram / Isochrone Matching.

import {
  ClusterPlotType,
  filterFramingValue,
  getExtinction,
  PlotConfig,
  PlotParams,
  Source
} from "../cluster.util";

export interface PlotRange {
  x: {
    min: number,
    max: number
  },
  y: {
    min: number,
    max: number
  }
}

export interface rawDataPoint {
  id: string,
  x: number,
  y: number,
  maxMagError: number,
}

// The shape returned by GET {apiUrl}/cluster/isochrone.
export interface IsochroneResponse {
  data: number[][],
  iSkip: number,
}

// EXTRACTED: was `private generateRawData()` on PlotComponent, which read
//            `this.dataService.getSources(true)` (cluster members only) and
//            the three `this.*Filter` fields, and wrote `this.rawPlotData`.
//            Body otherwise unchanged — including the three
//            `else if (maxMagError === null)` branches, which are dead code
//            (maxMagError is initialised to 0 and only ever assigned numbers)
//            and are preserved as-is rather than "fixed".
export function generateRawData(sources: Source[], plotFilters: PlotConfig['filters']): rawDataPoint[] {
  const blueFilter = plotFilters.blue;
  const redFilter = plotFilters.red;
  const lumFilter = plotFilters.lum;
  const rawPlotData: rawDataPoint[] = [];
  for (const source of sources) {
    let blueMag: number | null = null;
    let redMag: number | null = null;
    let lumMag: number | null = null;
    let maxMagError: number = 0;
    for (const photometry of source.photometries) {
      if (photometry.filter === blueFilter) {
        blueMag = photometry.mag;
        if (photometry.mag_error > maxMagError) {
          maxMagError = photometry.mag_error;
        } else if (maxMagError === null) {
          continue;
        }
      }
      if (photometry.filter === redFilter) {
        redMag = photometry.mag;
        if (photometry.mag_error > maxMagError) {
          maxMagError = photometry.mag_error;
        } else if (maxMagError === null) {
          continue;
        }
      }
      if (photometry.filter === lumFilter) {
        lumMag = photometry.mag;
        if (photometry.mag_error > maxMagError) {
          maxMagError = photometry.mag_error;
        } else if (maxMagError === null) {

        }
      }
    }
    if (blueMag !== null && redMag !== null && lumMag !== null) {
      rawPlotData.push({id: source.id, x: blueMag - redMag, y: lumMag, maxMagError: maxMagError});
    }
  }
  return rawPlotData;
}

// EXTRACTED: was `private computePlotDelta(): {x: number, y: number}`, reading
//            `this.isochroneService.getPlotParams()` and the `this.*Filter`
//            fields. Body unchanged.
export function computePlotDelta(plotFilters: PlotConfig['filters'], plotParams: PlotParams): { x: number, y: number } {
  const blueExtinction = getExtinction(plotFilters.blue, plotParams.reddening);
  const redExtinction = getExtinction(plotFilters.red, plotParams.reddening);
  const lumExtinction = getExtinction(plotFilters.lum, plotParams.reddening);
  return {
    x: redExtinction - blueExtinction,
    y: -lumExtinction - 5 * Math.log10(plotParams.distance * 1000) + 5,
  }
}

// EXTRACTED: was `private getPlotData(): [number[][], string[]]`, reading
//            `this.rawPlotData`, `this.plotConfig.plotType` and
//            `this.isochroneService.getMaxMagError()`. Body unchanged; the
//            `this.plotConfig !== null` guard collapsed into the parameters.
//            Returns [points, sourceIds] — the ids existed only to feed the
//            Highcharts tooltip, but they are the point<->source mapping so
//            they are kept.
export function getPlotData(rawPlotData: rawDataPoint[],
                            plotType: ClusterPlotType,
                            plotFilters: PlotConfig['filters'],
                            plotParams: PlotParams,
                            maxMagError: number): [number[][], string[]] {
  const data = rawPlotData.filter(
    (point) => point.maxMagError < maxMagError);
  let result: number[][] = [];
  let ids: string[] = [];
  if (plotType === ClusterPlotType.CM) {
    result = data.map((point) => [point.x, point.y]);
    ids = data.map(point => point.id)
  }
  if (plotType === ClusterPlotType.HR) {
    const delta = computePlotDelta(plotFilters, plotParams);
    for (const point of data) {
      let x = point.x + delta.x;
      let y = point.y + delta.y;
      result.push([x, y]);
      ids.push(point.id);
    }
  }
  return [result, ids];
}

// EXTRACTED: was the body of the HttpClient subscribe callback inside
//            `private setIsochrone()`. The GET, the two chartObject.series[1]
//            .setData calls and their try/catch fallback into chartOptions are
//            cut; the transform is unchanged.
//
//            Note the off-by-one in the splice (`slice(0, data.iSkip - 1)`)
//            is original behaviour and is preserved.
export function applyIsochroneTransform(response: IsochroneResponse,
                                        plotType: ClusterPlotType,
                                        plotFilters: PlotConfig['filters'],
                                        plotParams: PlotParams): (number | null)[][] {
  const data = response;
  let isochroneData: (number | null)[][] = data.data;
  if (plotType === ClusterPlotType.CM) {
    const delta = computePlotDelta(plotFilters, plotParams);
    isochroneData = isochroneData.map((point: (number | null)[]) => {
      return [(point[0] as number) - delta.x, (point[1] as number) - delta.y];
    });
  }
  if (data.iSkip > 0 && data.data.length > data.iSkip) {
    isochroneData = [
        ...isochroneData.slice(0, data.iSkip - 1),
        [null, null],
        ...isochroneData.slice(data.iSkip)
    ];
  }
  return isochroneData;
}

// EXTRACTED: was `private updateStandardViewRange()`, which wrote
//            `this.standardViewRange`. Body unchanged; returns instead.
//            (The `filters['red']` in the y.min expression, where every other
//            term uses `filters['lum']`, is original — preserved verbatim.)
export function getStandardViewRange(plotFilters: PlotConfig['filters']): PlotRange {
  let filters: {
    [key: string]: string
  } = {
    'red': plotFilters.red,
    'blue': plotFilters.blue,
    'lum': plotFilters.lum
  }
  let color_red: number = filterFramingValue[filters['blue']]['red'] - filterFramingValue[filters['red']]['red'];
  let color_blue: number = filterFramingValue[filters['blue']]['blue'] - filterFramingValue[filters['red']]['blue'];

  let minX = color_blue - (color_red - color_blue) / 8;
  let maxX = color_red + (color_red - color_blue) / 8;
  return {
    x: {
      min: minX <= maxX ? minX : maxX,
      max: maxX >= minX ? maxX : minX,
    },
    y: {
      min: filterFramingValue[filters['lum']]['bright']
        + (filterFramingValue[filters['lum']]['bright'] - filterFramingValue[filters['red']]['faint']) / 8,
      max: filterFramingValue[filters['lum']]['faint']
        - (filterFramingValue[filters['lum']]['bright'] - filterFramingValue[filters['lum']]['faint']) / 8,
    }
  }
}

// EXTRACTED: was `private updateDataRange(data: number[][])`, which wrote
//            `this.dataRange`. Body unchanged; returns instead.
export function getDataRange(data: number[][]): PlotRange {
  if (data.length === 0) {
    return {
      x: {
        min: 0,
        max: 0,
      },
      y: {
        min: 0,
        max: 0,
      }
    }
  }
  const dataRange: PlotRange = {
    x: {
      min: data[0][0],
      max: data[0][0],
    },
    y: {
      min: data[0][1],
      max: data[0][1],
    }
  }
  for (const point of data) {
    if (point[0] < dataRange.x.min) {
      dataRange.x.min = point[0];
    }
    if (point[0] > dataRange.x.max) {
      dataRange.x.max = point[0];
    }
    if (point[1] < dataRange.y.min) {
      dataRange.y.min = point[1];
    }
    if (point[1] > dataRange.y.max) {
      dataRange.y.max = point[1];
    }
  }
  const xDelta = (dataRange.x.max - dataRange.x.min) * 0.1;
  const yDelta = (dataRange.y.max - dataRange.y.min) * 0.1;
  if (xDelta > 0 && yDelta > 0) {
    dataRange.x.min -= xDelta;
    dataRange.x.max += xDelta;
    dataRange.y.min -= yDelta;
    dataRange.y.max += yDelta;
  }
  return dataRange;
}

// EXTRACTED: was `export const filterValidator: ValidatorFn` in
//   src/app/tools/cluster/isochrone-matching/control-panel/filter-selector/
//   filter-selector.component.ts:51-53
// The sole validity constraint on a filter triple: the two colour filters must
// differ (the luminosity filter is unconstrained and may equal either). The
// Angular ValidatorFn wrapper is dropped; the rule is kept because it is a
// precondition of computePlotDelta producing a non-degenerate colour axis.
export function isValidFilterSelection(plotFilters: PlotConfig['filters']): boolean {
  return plotFilters.blue !== plotFilters.red;
}
