// EXTRACTED from astromancer:
//   src/app/tools/cluster/FSR/histogram-slider-input/histogram-slider-input.component.ts
//   (467 lines total; ~35 algorithmic lines lifted here)
//
// HistogramSliderInputComponent is overwhelmingly UI: a Highcharts histogram
// series, two Angular Material range sliders, four reactive FormGroups, and
// three debounced RxJS output buffers. None of that is reproduced.
//
// Two genuine statistics live inside it and are lifted here verbatim:
//
//   getDefaultBin      - Freedman-Diaconis bin-count rule, driving the default
//                        binning of the distance / pm_ra / pm_dec histograms
//                        the student uses to pick the field-star cut.
//   getHistogramExtremes - a 2.5-sigma (98.76%) central percentile clip that
//                        defines the plottable/selectable domain, with the
//                        (-999, 999) empty-data fallback.
//
// Both assume their input array is ALREADY SORTED ASCENDING — that is how the
// callers supply it (ClusterDataService.getDistance/getPmra/getPmdec all sort
// before returning). This precondition is inherited, not introduced.

import {range} from "./fsr.util";

// EXTRACTED: was `private getDefaultBin(plotData?: number[]): number` on
//            HistogramSliderInputComponent. The `plotData == null` branch fell
//            back to the component's `this.data` field; with no component
//            there is no fallback, so the parameter is now required.
export function getDefaultBin(plotData: number[]): number {
  if (plotData.length === 0)
    return 10;
  const n = plotData.length;
  const iqr = plotData[Math.floor(n * 0.75)] - plotData[Math.floor(n * 0.25)];
  const binWidth = 2 * iqr * Math.pow(n, -1 / 3);
  return Math.ceil((plotData[plotData.length - 1] - plotData[0]) / binWidth);
}

// EXTRACTED: was the first half of `private setExtremes(payload: FsrHistogramPayload)`.
//            The original then assigned the result to four component fields
//            (fullDataRange / histogramRange / dataRange / histogramBin),
//            merged any persisted user overrides from the payload, and finally
//            pushed min/max onto two MatSlider ViewChildren. All of that is
//            state + UI plumbing and is left behind; only the percentile
//            computation is carried over, returning the range instead.
//
//            `data` is `payload.fullData ?? payload.data` at the call site; the
//            emptiness test still keys off the (possibly narrower) selected
//            array, exactly as in the original.
export function getHistogramExtremes(data: number[], selectedData: number[]): range {
  let min: number;
  let max: number;
  const sigma = 0.9876; // 2.5 sigma
  const lower = Math.ceil(data.length * (0.5 - sigma / 2));
  const upper = Math.floor(data.length * (0.5 + sigma / 2));
  if (selectedData.length > 0) {
    min = data[lower];
    max = data[upper];
  } else {
    min = -999;
    max = 999;
  }
  return {min: min, max: max};
}
