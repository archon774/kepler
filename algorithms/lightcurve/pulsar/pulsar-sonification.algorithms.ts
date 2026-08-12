// EXTRACTED from astromancer:
//   src/app/tools/pulsar/pulsar.service.ts                    (1263 lines total)
//   - sonification         889-1054   amplitude-modulated-noise -> WAV bytes
//   - sonificationBrowser 1056-1224   the same synthesis, into an AudioContext
//   - writeString         1243-1247   DataView ASCII helper for the RIFF header
//   src/app/tools/pulsar/light-curve/pulsar-light-curve-sonifier/
//     pulsar-light-curve-sonifier.component.ts                (88 lines)
//   - sonification / sonificationBrowser  21-53, 60-87  (input windowing only)
//
// This is the pulsar tool's sonification: the light curve is normalized to
// [0,1] across both polarizations and used as an amplitude envelope on white
// noise, giving the "TV static that pulses" rendering.
//
// `period` MEANS DIFFERENT THINGS AT THE TWO ENTRY POINTS. The synthesis
// itself fits nothing; it just loops its input over `period` seconds. What the
// caller passes decides what you hear:
//
//   1. pulsar-period-folding-form.component.ts (4 call sites) — the PRIMARY
//      path. Passes `getPeriodFoldingPeriod()`, the pulsar's actual period,
//      over the folded and phase-binned profile. The profile is upsampled to
//      fill one cycle and looped, so you hear the pulse at its true rate.
//      Reached only after the periodogram has produced a period, which is why
//      `cal` and `speed` below are period-FOLDING parameters and why the
//      `frequency < 4000` guard is a real branch (a millisecond pulsar lands
//      at a few hundred Hz).
//   2. pulsar-light-curve-sonifier.component.ts — the secondary path. Passes
//      the windowed observation *duration* (capped at 60 s) over the raw
//      background-subtracted light curve, so one pass plays the scan through
//      once. No period involved.
//
// Both call sites are extracted below: windowSonificationInput() is (2)'s
// input preparation, foldedSonificationInput() is (1)'s.
//
// docs/extraction.md previously listed sonification under "left behind as out
// of scope" (Light Curve, §6). That is now superseded: this file extracts it.
//
// FRAMEWORK SEAMS CUT:
//   - `@Injectable()` decorator and the `@angular/core` import
//   - every `this.get*()` service read (getPeriodFoldingCal,
//     getPeriodFoldingSpeed, getChartTitle) — now explicit parameters, the
//     same treatment pulsar-periodogram.compute.ts gave its getters
//   - the `Blob` / `URL.createObjectURL` / `document.createElement('a')`
//     download tail of `sonification()` — the math now ends by returning the
//     WAV `ArrayBuffer`, and `downloadWav()` below is the browser tail kept
//     separate and clearly marked, so a headless caller can use the bytes.
//     This is the same treatment pulsar-period-folding.algorithms.ts gave the
//     math that was interleaved with Highcharts calls.
//   - `isPlaying` / `audioCtx` / `audioSource` mutable service state and the
//     play/stop toggle at the head of `sonificationBrowser()` — state, not
//     math. The synthesis body is kept; the caller owns the handles.
//
// NOT EXTRACTED: `src/app/tools/shared/sonification/sonification.ts`
// (the 173-line `Sonifier` class). It is dead code — nothing in astromancer
// imports it, and it is superseded by the two methods here. It differs in
// ways that matter, so it is recorded rather than carried: a 440 Hz sine
// carrier instead of noise, 88200 Hz, mono only, `interpolationFactor` fixed
// at 4, and it repeats the data `ceil(60 / period)` times instead of looping
// on a sample index.

// EXTRACTED: duplicated from PulsarLightCurveAlgorithms.interpolateLinear
// (pulsar.service.ts:1227-1240, also extracted into
// ./pulsar-lightcurve.algorithms.ts). Upstream this is one method on one
// class, reached by both the light-curve and the sonification paths; the
// extraction splits those paths across two files, so the body is carried
// twice rather than making one extraction depend on the other's class
// instance. Both copies are byte-identical and must stay that way.
function interpolateLinear(data: number[], factor: number): number[] {
    const result: number[] = [];
    for (let i = 0; i < data.length - 1; i++) {
        const start = data[i];
        const end = data[i + 1];
        result.push(start);
        for (let j = 1; j <= factor; j++) {
            const t = j / (factor + 1);
            result.push(start * (1 - t) + end * t);
        }
    }
    result.push(data[data.length - 1]);
    return result;
}


/**
 * EXTRACTED: was `this.getPeriodFoldingCal()` / `this.getPeriodFoldingSpeed()`
 * read off PulsarPeriodFolding. Defaults are that class's own
 * (pulsar.service.util.ts:623-624).
 */
export interface SonificationOptions {
    /** Gain applied to the second polarization before normalization. */
    cal: number;
    /** Divides the pass duration: 2 plays the data twice as fast. */
    speed: number;
}

export const SONIFICATION_DEFAULTS: SonificationOptions = {
    cal: 1.0,
    speed: 1.0,
};

const SAMPLE_RATE = 44100;
const DURATION_SECONDS = 60;

/**
 * The `frequency < 4000` guard in both methods. The inline upstream comment
 * reads "Set to 4000 to deprecate burst mode" — i.e. the threshold was raised
 * until burst mode always wins. Waveform mode is only reachable when one pass
 * lasts under 0.25 ms, which no call site produces; it is carried anyway
 * because it is upstream code, not because it runs.
 */
const BURST_MODE_MAX_FREQUENCY_HZ = 4000;


/**
 * Verbatim from PulsarLightCurveSonifierComponent (both methods open with the
 * identical block, 21-53 and 60-87).
 *
 * Drops rows with a null/NaN time or flux, then truncates to the first 60
 * seconds of data — `findIndex(x => x - start > 60)` — and returns the
 * remaining span as the `period` argument the service methods take. So the
 * "period" fed to the synthesis is the *windowed observation duration*.
 */
export function windowSonificationInput(
    data: { jd: number | null, source1: number, source2: number }[],
): { xValues: number[], yValues: number[], yValues2: number[], duration: number } {
    const chartData = data.filter(
        (d): d is { jd: number; source1: number; source2: number } => d.jd !== null
    );

    const filtered = chartData.filter(d =>
        !isNaN(d.jd) && !isNaN(d.source1) && !isNaN(d.source2)
    );

    let xValues = filtered.map(d => d.jd);
    let yValues = filtered.map(d => d.source1);
    let yValues2 = filtered.map(d => d.source2);

    const start = xValues[0];
    let duration = xValues[xValues.length - 1] - start;

    if (duration > 60) {
        // Find first index where x - start > 60
        const cutIndex = xValues.findIndex(x => x - start > 60);

        // Slice all arrays up to that index
        const end = cutIndex !== -1 ? cutIndex : xValues.length;
        xValues = xValues.slice(0, end);
        yValues = yValues.slice(0, end);
        yValues2 = yValues2.slice(0, end);

        duration = xValues[xValues.length - 1] - start;
    }

    return {xValues, yValues, yValues2, duration};
}


/**
 * EXTRACTED: the seam replacing the Angular-injected `PulsarService` in
 * `PulsarPeriodFoldingFormComponent`. Every member is one the extracted body
 * below actually calls; all four already exist on
 * `PulsarLightCurveAlgorithms`.
 */
export interface PulsarFoldingSonificationHost {
    getPeriodFoldingChartData(): { [key: string]: number[][] };
    binData(data: number[][], bins: number): number[][];
    getPeriodFoldingBins(): number;
    getData(): { jd: number | null, source1: number | null, source2: number | null }[];
}


/**
 * EXTRACTED from `PulsarPeriodFoldingFormComponent.sonification` (233-254) and
 * `.sonificationBrowser` (260-280) — the two bodies are identical apart from
 * which service method they dispatch to, so the shared input preparation is
 * extracted once and the dispatch is left to the caller.
 *
 * THIS IS THE PRIMARY SONIFICATION INPUT. A cal file is folded and binned
 * first, so what gets rendered is the phase profile, and the `period` the
 * caller then passes to `sonification()` is
 * `getPeriodFoldingPeriod()` — the pulsar's period, which the periodogram
 * produced. A standard (prefolded) file is already in phase, so it skips
 * straight to the raw columns.
 *
 * @param calFile  was `this.calFile` on the form component
 * @returns the arrays to hand to `sonification()` / `sonificationBrowser()`
 */
export function foldedSonificationInput(
    service: PulsarFoldingSonificationHost,
    calFile: boolean,
): { xValues: number[], yValues: number[], yValues2: number[] | null } {
    if (calFile) {
        const data = service.getPeriodFoldingChartData();
        let binnedData = service.binData(data['data'], service.getPeriodFoldingBins());
        const xValues = binnedData.map(point => point[0]);
        const yValues = binnedData.map(point => point[1]);

        let binnedData2 = service.binData(data['data2'], service.getPeriodFoldingBins());
        const yValues2 = binnedData2.map(point => point[1]);

        return {xValues, yValues, yValues2};
    } else {
        const rawData = service.getData()
        .filter(item => item.jd !== null && item.source1 !== null);

        const xValues = rawData.map(item => Number(item.jd));
        const yValues = rawData.map(item => Number(item.source1));

        return {xValues, yValues, yValues2: null};
    }
}


/**
 * EXTRACTED: was `PulsarService.sonification(_xValues, yValues, yValues2,
 * period, title)`, body verbatim through the PCM conversion and RIFF header.
 * The `Blob`/anchor download tail (1043-1053) is split into `downloadWav()`.
 *
 * `_xValues` is unused upstream and is dropped rather than carried.
 *
 * @param yValues   source1 samples (background-subtracted light curve)
 * @param yValues2  source2 samples, or null for a single-polarization file
 * @param period    seconds for one pass through the data — see the file header
 * @param options   was this.getPeriodFoldingCal() / getPeriodFoldingSpeed()
 * @returns the complete 16-bit PCM WAV file, or null when there is no data
 */
export function sonification(
    yValues: number[],
    yValues2: number[] | null,
    period: number,
    options: SonificationOptions = SONIFICATION_DEFAULTS,
): ArrayBuffer | null {
    if (yValues.length === 0) {
        console.error("No data to sonify.");
        return null;
    }

    const cal = options.cal;
    const sampleRate = SAMPLE_RATE;
    const durationSeconds = DURATION_SECONDS;
    const numChannels = yValues2 ? 2 : 1;

    // --- Period folding ---
    period *= 1 / options.speed;

    // --- Apply calibration to yValues2 (on a copy so the caller's array
    //     is not mutated; repeated saves would otherwise compound the
    //     calibration each time). ---
    let yValues2Cal: number[] | null = null;
    if (yValues2) {
        yValues2Cal = new Array(yValues2.length);
        for (let i = 0; i < yValues2.length; i++) yValues2Cal[i] = yValues2[i] * cal;
    }

    // --- Compute global min and max across both channels ---
    // Use a loop instead of Math.min/max(...) — the spread form blows the
    // call stack on large arrays.
    const allValues = yValues2Cal ? yValues.concat(yValues2Cal) : yValues;
    let globalMin = allValues[0], globalMax = allValues[0];
    for (let i = 1; i < allValues.length; i++) {
        const v = allValues[i];
        if (v < globalMin) globalMin = v;
        if (v > globalMax) globalMax = v;
    }

    // --- Normalize function using global min/max ---
    const normalizeGlobal = (arr: number[]) => {
        return arr.map(y => (y - globalMin) / (globalMax - globalMin || 1));
    };

    // --- Apply global normalization ---
    const normY1 = normalizeGlobal(yValues);
    const normY2 = yValues2Cal ? normalizeGlobal(yValues2Cal) : null;

    // --- Adaptive interpolation ---
    // NOTE: one factor, sized off normY1 only, is applied to BOTH channels
    // here — sonificationBrowser() sizes a separate factor per channel. The
    // two are equal whenever the channels are the same length, which is
    // always true for a cal file, so the paths agree in practice. Preserved
    // as found; see docs/extraction.md, Pulsar (sonification).
    const minSamplesPerCycle = Math.max(64, Math.floor(sampleRate / (1 / period)));
    const interpFactor = Math.ceil(minSamplesPerCycle / normY1.length);
    const interpolateArray = (arr: number[]) => interpolateLinear(arr, interpFactor);

    const audioData1 = new Float32Array(durationSeconds * sampleRate);
    const audioData2 = numChannels === 2 ? new Float32Array(durationSeconds * sampleRate) : null;

    // --- Generate audio ---
    const frequency = 1 / period;
    if (frequency < BURST_MODE_MAX_FREQUENCY_HZ) { // Set to 4000 to deprecate burst mode
        // --- Burst mode (TV static style) ---
        const interp1 = interpolateArray(normY1);
        const interp2 = normY2 ? interpolateArray(normY2) : null;

        const numPoints = interp1.length;
        const durationPerPoint = period / numPoints;
        const samplesPerPoint = Math.max(1, Math.floor(sampleRate * durationPerPoint));
        const totalSamples = audioData1.length;

        for (let i = 0; i < totalSamples; i++) {
            // Pick index into interpolated data
            const pointIndex = Math.floor((i % (numPoints * samplesPerPoint)) / samplesPerPoint);

            // Amplitude modulation values [0..1]
            const amp1 = interp1[Math.min(pointIndex, numPoints - 1)];
            const amp2 = interp2 ? interp2[Math.min(pointIndex, numPoints - 1)] : 0;

            // Independent white noise carriers per channel for stereo spread.
            const noise1 = Math.random() * 2 - 1;
            const noise2 = Math.random() * 2 - 1;

            // Modulate noise by data
            audioData1[i] = noise1 * amp1;
            if (numChannels === 2 && interp2) {
                audioData2![i] = noise2 * amp2;
            }
        }
    } else {
        // Waveform mode
        const interp1 = interpolateArray(normY1);
        const interp2 = normY2 ? interpolateArray(normY2) : null;
        const numPoints = interp1.length;

        for (let i = 0; i < audioData1.length; i++) {
            const t = i / sampleRate;
            const phase = (t % period) / period;
            // Clamp against numPoints — floating-point rounding can let
            // phase * numPoints land exactly on numPoints at the period
            // boundary, which would index past the end of interp1.
            const index = Math.min(Math.floor(phase * numPoints), numPoints - 1);
            audioData1[i] = interp1[index] * 2 - 1;
            if (numChannels === 2 && interp2) {
                audioData2![i] = interp2[index] * 2 - 1;
            }
        }
    }

    let globalMaxAbs = 0;
    for (let i = 0; i < audioData1.length; i++) {
        globalMaxAbs = Math.max(globalMaxAbs, Math.abs(audioData1[i]));
        if (numChannels === 2 && audioData2) globalMaxAbs = Math.max(globalMaxAbs, Math.abs(audioData2[i]));
    }
    if (globalMaxAbs > 0) {
        const scale = 0.95 / globalMaxAbs;
        for (let i = 0; i < audioData1.length; i++) {
            audioData1[i] *= scale;
            if (numChannels === 2 && audioData2) audioData2[i] *= scale;
        }
    }

    // --- Convert to interleaved 16-bit PCM ---
    const int16Data = new Int16Array(audioData1.length * numChannels);
    const gain = 1;
    for (let i = 0; i < audioData1.length; i++) {
        int16Data[i * numChannels] = Math.floor(audioData1[i] * gain * 32767);
        if (numChannels === 2 && audioData2) {
            int16Data[i * 2 + 1] = Math.floor(audioData2[i] * gain * 32767);
        }
    }

    // --- Write WAV header ---
    const bytesPerSample = 2;
    const dataSize = int16Data.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeString(view, 8, "WAVE");
    writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true); // fmt chunk size
    view.setUint16(20, 1, true); // PCM format
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * bytesPerSample, true);
    view.setUint16(32, numChannels * bytesPerSample, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, "data");
    view.setUint32(40, dataSize, true);

    for (let i = 0, offset = 44; i < int16Data.length; i++, offset += 2) {
        view.setInt16(offset, int16Data[i], true);
    }

    return buffer;
}


/**
 * EXTRACTED: was `PulsarService.sonificationBrowser(...)`, the live-playback
 * twin of `sonification()`. Body verbatim from the `cal` read (1080) through
 * the peak normalization (1197), with the AudioContext plumbing left to the
 * caller — this returns the per-channel Float32 buffers instead.
 *
 * The play/stop toggle (1062-1075) is service state and is not extracted;
 * `isPlaying`, `audioCtx` and `audioSource` belong to whoever owns playback.
 *
 * Three deliberate differences from `sonification()` above, all upstream and
 * all preserved (see docs/extraction.md, Pulsar (sonification)):
 *   1. a separate interpolation factor per channel, not one sized off channel 1;
 *   2. an extra `gain = 0.7` on the peak normalization, so playback is
 *      quieter than the saved WAV;
 *   3. waveform mode wraps its index with `%` instead of clamping it.
 */
export function sonificationBrowser(
    yValues: number[],
    yValues2: number[] | null,
    period: number,
    options: SonificationOptions = SONIFICATION_DEFAULTS,
): Float32Array[] | null {
    if (yValues.length === 0) {
        console.error("No data to sonify.");
        return null;
    }

    const cal = options.cal;
    const numChannels = yValues2 ? 2 : 1;
    const sampleRate = SAMPLE_RATE;
    const durationSeconds = DURATION_SECONDS;

    // --- Apply period folding ---
    period *= 1 / options.speed;

    // --- Apply calibration to yValues2 on a copy (so the caller's array
    //     isn't mutated; clicking Play repeatedly used to compound cal). ---
    let yValues2Cal: number[] | null = null;
    if (yValues2) {
        yValues2Cal = new Array(yValues2.length);
        for (let i = 0; i < yValues2.length; i++) yValues2Cal[i] = yValues2[i] * cal;
    }

    // --- Compute global min and max across both channels ---
    // Loop instead of spread to avoid stack overflow on large arrays.
    const allValues = yValues2Cal ? yValues.concat(yValues2Cal) : yValues;
    let globalMin = allValues[0], globalMax = allValues[0];
    for (let i = 1; i < allValues.length; i++) {
        const v = allValues[i];
        if (v < globalMin) globalMin = v;
        if (v > globalMax) globalMax = v;
    }

    // --- Normalize function using global min/max ---
    const normalizeGlobal = (arr: number[]) => {
        return arr.map(y => (y - globalMin) / (globalMax - globalMin || 1));
    };

    // --- Apply global normalization ---
    const normY1 = normalizeGlobal(yValues);
    const normY2 = yValues2Cal ? normalizeGlobal(yValues2Cal) : null;

    // --- Adaptive interpolation ---
    const frequency = 1 / period;
    const minSamplesPerCycle = Math.max(64, Math.floor(sampleRate / frequency));
    const interpFactor1 = Math.ceil(minSamplesPerCycle / normY1.length);
    const interpFactor2 = normY2 ? Math.ceil(minSamplesPerCycle / normY2.length) : 1;

    const interp1 = interpolateLinear(normY1, interpFactor1);
    const interp2 = normY2 ? interpolateLinear(normY2, interpFactor2) : null;

    const totalSamples = durationSeconds * sampleRate;
    const audioData1 = new Float32Array(totalSamples);
    const audioData2 = numChannels === 2 ? new Float32Array(totalSamples) : null;

    // --- Generate audio data ---
    if (frequency < BURST_MODE_MAX_FREQUENCY_HZ) { // Set to 4000 to deprecate burst mode
        // --- Burst mode using noise (TV static style) ---
        const numPoints1 = interp1.length;
        const numPoints2 = interp2 ? interp2.length : 0;

        const durationPerPoint1 = period / numPoints1;
        const samplesPerPoint1 = Math.max(1, Math.floor(sampleRate * durationPerPoint1));

        const durationPerPoint2 = interp2 ? period / numPoints2 : 1;
        const samplesPerPoint2 = interp2 ? Math.max(1, Math.floor(sampleRate * durationPerPoint2)) : 1;

        for (let i = 0; i < totalSamples; i++) {
            // Independent white noise per channel for stereo spread —
            // matches the saved-WAV path in sonification().
            const noise1 = Math.random() * 2 - 1;
            const noise2 = Math.random() * 2 - 1;

            // Channel 1 (modulated noise)
            const idx1 = Math.min(
                Math.floor((i % (numPoints1 * samplesPerPoint1)) / samplesPerPoint1),
                numPoints1 - 1,
            );
            const volume1 = interp1[idx1]; // [0..1]
            audioData1[i] = noise1 * volume1;

            if (numChannels === 2 && interp2) {
                const idx2 = Math.min(
                    Math.floor((i % (numPoints2 * samplesPerPoint2)) / samplesPerPoint2),
                    numPoints2 - 1,
                );
                const volume2 = interp2[idx2];
                audioData2![i] = noise2 * volume2;
            }
        }
    } else {
        // Waveform mode
        for (let i = 0; i < totalSamples; i++) {
            const t = i / sampleRate;

            const idx1 = Math.floor((t / period) * interp1.length) % interp1.length;
            audioData1[i] = (interp1[idx1] * 2 - 1);

            if (numChannels === 2 && interp2) {
                const idx2 = Math.floor((t / period) * interp2.length) % interp2.length;
                audioData2![i] = (interp2[idx2] * 2 - 1);
            }
        }
    }

    // --- Global normalization to [-0.95, 0.95] across all channels ---
    const normalizeFloat32Global = (channels: Float32Array[]) => {
        const gain = 0.7;

        // Find the global maximum absolute value across all channels
        let maxAbs = 0;
        for (const arr of channels) {
            for (const v of arr) maxAbs = Math.max(maxAbs, Math.abs(v));
        }

        if (maxAbs > 0) {
            const scale = (0.95 / maxAbs) * gain;
            for (const arr of channels) {
                for (let i = 0; i < arr.length; i++) arr[i] *= scale;
            }
        }
    };

    // Usage
    const channels: Float32Array[] = [audioData1];
    if (numChannels === 2 && audioData2) channels.push(audioData2);

    normalizeFloat32Global(channels);

    return channels;
}


/** Verbatim from PulsarService.writeString (1243-1247). */
function writeString(view: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i));
    }
}


/**
 * EXTRACTED: the browser download tail of `sonification()` (1043-1053), split
 * out so the synthesis above returns bytes a headless caller can use. Body
 * otherwise verbatim, including the `${title}.wav` filename.
 *
 * This is the only function in this file that touches the DOM.
 */
export function downloadWav(buffer: ArrayBuffer, title: string): void {
    const blob = new Blob([new Uint8Array(buffer)], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title}.wav`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
