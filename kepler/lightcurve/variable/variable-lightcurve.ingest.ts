// EXTRACTED from astromancer:
//   src/app/tools/variable/light-curve/variable-light-curve/
//     variable-light-curve.component.ts   (151 lines; the fileParser.data$
//                                          subscription body, lines 35-114)
//
// The algorithm here is a two-pointer MERGE JOIN that time-aligns two
// independently-sampled photometric sources onto a common MJD grid. Rows whose
// MJDs agree to within `mjdThreshold` become paired samples; unmatched rows are
// emitted with a null on the missing side. That alignment is what makes
// differential photometry (VariableLightCurveAlgorithms.getChartVariableDataArray)
// possible, so it belongs with the algorithms rather than the UI.
//
// FRAMEWORK SEAMS CUT:
//   - `@Component({...})` decorator and the `@angular/core` import
//   - Angular DI over VariableService / HonorCodePopupService /
//     HonorCodeChartService / MatDialog
//   - the RxJS `fileParser.data$.pipe(takeUntil(destroy$)).subscribe(...)`
//     wrapper — the callback body is now a plain function
//   - the trailing `this.service.setData(result)`, replaced by returning
//     `result` to the caller
//   - `actionHandler()` and `saveGraph()` (toolbar dispatch + honor-code
//     popup + Highcharts PNG export)
//
// NOT EXTRACTED: `MyFileParser` / `FileType.CSV`
// (src/app/tools/shared/data/FileParser/*). That is generic CSV/TXT/FITS
// tokenizing infrastructure shared by every astromancer tool, not light-curve
// math. This function consumes its output: an array of row objects with the
// string fields "id", "mjd", "mag", "mag_error", declared in the original as
//     new MyFileParser(FileType.CSV, ["id", "mjd", "mag", "mag_error"])
//
// PULSAR vs VARIABLE: the pulsar ingest
// (../pulsar/pulsar-lightcurve.ingest.ts) reads a fixed-column instrument file
// with a '#' metadata header and gets both polarizations from the SAME row, so
// it needs no alignment pass at all. The variable ingest reads a CSV where the
// two sources are interleaved rows distinguished by an `id` column, which is
// why it needs this merge.

import {VariableDataDict} from "./variable-lightcurve.types";

/**
 * Verbatim from variable-light-curve.component.ts:38-113.
 *
 * EXTRACTED: was the `(data: any) => {...}` handler passed to
 * `this.fileParser.data$.subscribe`. `alert(...)` and `console.log(...)` are
 * browser APIs (not framework) and are preserved as-is; on the <2-source
 * error path the original simply `return`ed, which here yields `undefined`.
 */
export function mergeSourcesByMjd(data: any): VariableDataDict[] | undefined {
  const sources = Array.from(new Set(data.map((d: any) => d.id)));
  console.log(sources);
  if (sources.length < 2) {
    alert("Error" + "Please upload at least two sources")
    return;
  }
  const result: VariableDataDict[] = [];
  const src0data = data.filter((d: any) => d.id === sources[0])
    .map((d: any) => [parseFloat(d.mjd), parseFloat(d.mag), parseFloat(d.mag_error)])
    .filter((d: any) => !isNaN(d[0]) && !isNaN(d[1]) && !isNaN(d[2]))
    .sort((a: any, b: any) => a[0] - b[0]);
  const src1data = data.filter((d: any) => d.id === sources[1])
    .map((d: any) => [parseFloat(d.mjd), parseFloat(d.mag), parseFloat(d.mag_error)])
    .filter((d: any) => !isNaN(d[0]) && !isNaN(d[1]) && !isNaN(d[2]))
    .sort((a: any, b: any) => a[0] - b[0]);
  let left = 0;
  let right = 0;
  const mjdThreshold = 0.00000001;
  while (left < src0data.length && right < src1data.length) {
    if (Math.abs(src0data[left][0] - src1data[right][0]) < mjdThreshold) {
      result.push({
        jd: src0data[left][0] as number,
        source1: src0data[left][1] as number,
        source2: src1data[right][1] as number,
        error1: src0data[left][2] as number,
        error2: src1data[right][2] as number,
        errorMSE: null,
      });
      left++;
      right++;
    } else if (src0data[left][0] < src1data[right][0]) {
      result.push({
        jd: src0data[left][0] as number,
        source1: src0data[left][1] as number,
        source2: null,
        error1: src0data[left][2] as number,
        error2: null,
        errorMSE: null,
      });
      left++;
    } else {
      result.push({
        jd: src1data[right][0] as number,
        source1: null,
        source2: src1data[right][1] as number,
        error1: null,
        error2: src1data[right][2] as number,
        errorMSE: null
      });
      right++;
    }
  }
  while (left < src0data.length) {
    result.push({
      jd: src0data[left][0] as number,
      source1: src0data[left][1] as number,
      source2: null,
      error1: src0data[left][2] as number,
      error2: null,
      errorMSE: null
    });
    left++;
  }
  while (right < src1data.length) {
    result.push({
      jd: src1data[right][0] as number,
      source1: null,
      source2: src1data[right][1] as number,
      error1: null,
      error2: src1data[right][2] as number,
      errorMSE: null
    });
    right++;
  }
  // EXTRACTED: was `this.service.setData(result);`
  // VariableData.setData fills in each row's `errorMSE` from error1/error2,
  // which is why every row above leaves it null.
  return result;
}
