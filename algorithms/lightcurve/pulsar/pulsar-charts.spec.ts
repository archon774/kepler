// EXTRACTED from astromancer:
//   src/app/tools/pulsar/light-curve/pulsar-light-curve-highchart/
//     pulsar-light-curve-highchart.component.ts                    (206 lines)
//   src/app/tools/pulsar/periodogram/pulsar-periodogram-highcharts/
//     pulsar-periodogram-highcharts.component.ts                   (319 lines)
//   src/app/tools/pulsar/period-folding/pulsar-period-folding-highchart/
//     pulsar-period-folding-highchart.component.ts                 (331 lines)
//   src/app/tools/pulsar/pulsar.service.util.ts
//     - PulsarChartInfo.getDefaultChartInfo        133-138
//     - PulsarPeriodogram.getDefaultPeriodogram    400-411
//     - PulsarPeriodFolding defaults               620-631
//
// docs/extraction.md previously listed all three Highcharts components under
// "left behind as UI / rendering", and `updateXAxisScale` specifically as a
// flagged judgment call. That was correct while nothing rendered. Now that
// `tools.pulsar.plot_pulsar` draws these plots, the parts that decide WHAT is
// drawn — series identity, axis semantics, default labels, and the folded
// x-axis extent — are algorithm, not decoration, and are extracted here.
//
// STILL LEFT BEHIND, and deliberately: everything that is Highcharts plumbing
// rather than chart meaning — `Highcharts.Chart` handles, `addSeries` /
// `upsertSeries` / `setData` / `setExtremes` calls, the boost module config
// (`seriesThreshold: 5000`), `turboThreshold: 20000`, export-button options,
// RxJS form subscriptions, and the tooltip `pointFormat` strings. A renderer
// needs the spec below, not the widget.
//
// This file is data, not behaviour: one exported constant per chart plus the
// single numeric helper. It has no imports and no framework contact.

/** Colour, dash and z-order carried from the original literals. */
export interface SeriesSpec {
    /** Series name exactly as the legend shows it. */
    name: string;
    /** Which column of the source table it draws. */
    column: string;
    /** Highcharts series type; 'line' everywhere except the periodogram peak. */
    type: "line" | "scatter";
    /** false where upstream adds the series with `visible: false`. */
    visible: boolean;
    lineWidth?: number;
    marker?: string | null;
    markerRadius?: number;
    color?: string;
    dashStyle?: string;
    zIndex?: number;
}

export interface ChartSpec {
    /** `PulsarChartInfo`-family default; the form lets a user override it. */
    title: string;
    xAxisLabel: string;
    yAxisLabel: string;
    /** 'linear' or 'logarithmic' — only the periodogram is logarithmic. */
    xAxisType: "linear" | "logarithmic";
    legend: boolean;
    series: SeriesSpec[];
}


/**
 * Light curve — flux against time, both polarizations.
 *
 * Labels are `PulsarChartInfo.getDefaultChartInfo()` (util 133-138); the
 * series options are the `seriesOptions` literal in the component (144-161).
 *
 * NOTE the label order. `dataLabels` is `["Polarization XX", "Polarization
 * YY"]`, and the component assigns `dataLabel1` to the FIRST data column and
 * `dataLabel2` to the second. Kepler's ingest reads the file's *XX1* column
 * into `source1` and its *YY1* column into `source2` (see
 * pulsar-lightcurve.ingest.ts, CAL_COLUMNS), so the label and the data agree —
 * both are transposed the same way, and the plot shows XX where the file says
 * XX. Do not "fix" one without the other.
 */
export const PULSAR_LIGHT_CURVE_CHART: ChartSpec = {
    title: "Title",
    xAxisLabel: "Time (s)",
    yAxisLabel: "Intensity",
    xAxisType: "linear",
    legend: true,
    series: [
        {
            name: "Polarization XX",
            column: "source1",
            type: "line",
            visible: true,
            lineWidth: 0.1,
            marker: null,
        },
        {
            name: "Polarization YY",
            column: "source2",
            type: "line",
            visible: true,
            lineWidth: 0.1,
            marker: null,
        },
    ],
};


/**
 * Periodogram — spectral power against period, on a LOGARITHMIC x axis
 * (`xAxis: { type: 'logarithmic' }`, component line 41). That is not
 * cosmetic: `lombScargle` evaluates a logarithmic period grid in period mode,
 * so a linear axis misrepresents the sampling.
 *
 * Labels from `PulsarPeriodogram.getDefaultPeriodogram()` (util 400-411).
 * Series names from the ternary at 128-130, which falls through to
 * `Channel N` for any third-or-later channel.
 */
export const PULSAR_PERIODOGRAM_CHART: ChartSpec = {
    title: "Title",
    xAxisLabel: "Period (s)",
    yAxisLabel: "Intensity",
    xAxisType: "logarithmic",
    legend: true,
    series: [
        {
            name: "Polarization XX",
            column: "power",
            type: "line",
            visible: true,
            marker: "circle",
            markerRadius: 3,
        },
    ],
};

/**
 * The peak marker, from `addSeries` at 276-291. Upstream's series is named
 * "Global Maxima" even though `findLocalMax` returns a single point.
 */
export const PULSAR_PERIODOGRAM_PEAK_SERIES: SeriesSpec = {
    name: "Global Maxima",
    column: "peak",
    type: "scatter",
    visible: true,
    color: "red",
    zIndex: 10,
};

/**
 * False-alarm lines, from `addConfidenceLines` (234-260). Drawn as horizontal
 * dashed lines across the plot at the thresholds `confidenceThreshold()`
 * returns. The colours and `ShortDash` are the original literals.
 *
 * See docs/extraction.md, Pulsar Sonification §8: these thresholds assume
 * white noise, so a peak clearing the green line is NOT thereby a pulsar.
 */
export const PULSAR_CONFIDENCE_LINES: SeriesSpec[] = [
    {name: "67.3% Confidence", column: "conf-1-sigma", type: "line", visible: true,
     color: "red", dashStyle: "ShortDash"},
    {name: "95.4% Confidence", column: "conf-2-sigma", type: "line", visible: true,
     color: "orange", dashStyle: "ShortDash"},
    {name: "99.73% Confidence", column: "conf-3-sigma", type: "line", visible: true,
     color: "green", dashStyle: "ShortDash"},
];


/**
 * Folded pulse profile. Labels from the `PulsarPeriodFolding` defaults (util
 * 620-631) — note the x axis is still "Time (s)", not "Phase": upstream plots
 * seconds within one period, not a 0-1 phase.
 *
 * Series from `upsertSeries` at 234-237 and the single-source fallback at 268.
 * `Difference` and `Sum` are added with `visible: false`, so they exist in the
 * legend but are hidden until the user clicks them — preserved here as
 * `visible: false` rather than dropped, because which series are *available*
 * is chart meaning.
 */
export const PULSAR_FOLDED_CHART: ChartSpec = {
    title: "Title",
    xAxisLabel: "Time (s)",
    yAxisLabel: "Intensity",
    xAxisType: "linear",
    legend: true,
    series: [
        {name: "Polarization XX", column: "source1", type: "line", visible: true, marker: null},
        {name: "Polarization YY", column: "source2", type: "line", visible: true, marker: null},
        {name: "Difference", column: "difference", type: "line", visible: false, marker: null},
        {name: "Sum", column: "sum", type: "line", visible: false, marker: null},
    ],
};

/** Single-polarization files label the one series 'Data' (component line 268). */
export const PULSAR_FOLDED_SINGLE_SOURCE_NAME = "Data";


/**
 * EXTRACTED: `PulsarPeriodFoldingHighChartComponent.updateXAxisScale()`
 * (the body verbatim, minus the closing `setExtremes` call).
 *
 * docs/extraction.md flagged this as a judgment call and left it behind as a
 * viewport computation. It is extracted now because it decides the x extent of
 * the folded plot, and without it a rendered profile does not match the one
 * Astromancer draws.
 *
 * What it does: rounds the axis maximum UP to the period plus a
 * magnitude-matched `delta`, but only when the period's fractional part is
 * already smaller than that delta. So P = 0.7145 is left alone (frac 0.7145 >
 * delta 0.1) while P = 1.0001 becomes 1.1 — a near-integer period gets a
 * padded axis rather than a hairline sliver at the right edge.
 *
 * `parseInt(p.toString())` truncates toward zero, which for a positive period
 * is the integer part; reproduced with a floor.
 *
 * @param period         was this.service.getPeriodFoldingPeriod()
 * @param displayPeriod  was this.service.getPeriodFoldingDisplayPeriod()
 * @returns the axis maximum; the axis always starts at 0
 */
export function foldedXAxisMaximum(period: number, displayPeriod: number): number {
    let p = period;
    let delta = 0;

    if (p > 4.95) {
        delta = 0.15;
    } else if (p > 0.5) {
        delta = 0.1;
    } else if (p > 0.05) {
        delta = 0.01;
    } else if (p > 0.005) {
        delta = 0.001;
    } else if (p > 0.0005) {
        delta = 0.0001;
    } else if (p > 0.00005) {
        delta = 0.00001;
    } else {
        delta = 0.000001;
    }

    if (p - parseInt(p.toString()) < delta) {
        p = parseInt(p.toString()) + delta;
    }

    // PulsarDisplayPeriod.TWO
    if (displayPeriod === 2) {
        p = p * 2;
    }

    return p;
}
