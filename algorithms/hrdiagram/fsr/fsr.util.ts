// EXTRACTED from astromancer:
//   src/app/tools/cluster/FSR/fsr.util.ts  (22 lines, copied byte-for-byte)
//
// Field Star Removal parameter shapes. FsrParameters is the actual selection
// criterion consumed by
// ../photometry/cluster-data.service.util.ts::updateClusterFieldSources — an
// elliptical cut in (pm_ra, pm_dec) plus a distance interval.
//
// Framework seams: none in the body.

// EXTRACTED: was `import {range} from "./histogram-slider-input/histogram-slider-input.component"`.
//            In astromancer the `range` interface is declared at the bottom of
//            an Angular component file (HistogramSliderInputComponent). The
//            component itself is a Highcharts histogram + Material slider pair
//            and is NOT extracted; only this type and the two statistical
//            helpers in ./fsr-histogram.util.ts came across. `range` is
//            reproduced verbatim here so this package has no component import.
export interface range {
  min: number,
  max: number,
}

export interface FsrParameters {
  distance: range | null,
  pm_ra: range | null,
  pm_dec: range | null,
}

export interface FsrComponents {
  bin: number,
  range: range,
  histogramRange: range
}

export interface FsrHistogramPayload {
  data: number[],
  isNew: boolean,
  fullData?: number[],
  histogramRange?: range | null,
  range?: range | null,
  bin?: number | null,
}
