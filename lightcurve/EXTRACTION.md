# Light Curve extraction from Astromancer

Algorithmic TypeScript for the **light curve** and **period folding** stages of
Astromancer's two light-curve tools, extracted into Kepler.

- **Source repo:** `/home/claude/astromancer` (Angular 16 / TypeScript). Read-only for this task; nothing there was modified.
- **Destination:** `/home/claude/Kepler/lightcurve/`
- **Nature of the work:** extraction, not a port. Algorithms and comments are
  preserved verbatim. Angular decorators, DI, RxJS, `localStorage` and Highcharts
  handles were cut; every cut is marked in-file with an `// EXTRACTED:` comment.

---

## 1. Structure created

```
lightcurve/
├── EXTRACTION.md
├── shared/
│   ├── numeric-utils.ts                     26 lines
│   └── data.interface.ts                    21 lines
├── pulsar/
│   ├── pulsar-lightcurve.types.ts          222 lines
│   ├── pulsar-lightcurve.algorithms.ts     392 lines
│   ├── pulsar-lightcurve.ingest.ts         445 lines
│   ├── pulsar-period-folding.types.ts      254 lines
│   └── pulsar-period-folding.algorithms.ts 169 lines
└── variable/
    ├── variable-lightcurve.types.ts        213 lines
    ├── variable-lightcurve.algorithms.ts   257 lines
    ├── variable-lightcurve.ingest.ts       127 lines
    ├── variable-period-folding.types.ts    182 lines
    └── variable-period-folding.algorithms.ts 46 lines
```

Total 2354 lines across 12 source files. Line counts include the provenance
header comments, which are a meaningful fraction of the smaller files.

The `pulsar/` and `variable/` split is deliberate and complete — no file mixes
the two tools, and nothing is shared between them except `shared/`.

---

## 2. Exact source paths and what was copied

All paths below are relative to `/home/claude/astromancer/src/app/tools/`.

### 2.1 Shared

| Source | Lines in source | Extracted | Destination |
|---|---|---|---|
| `shared/data/utils.ts` | 278 | `floatMod` (15-25) | `shared/numeric-utils.ts` |
| `shared/data/data.interface.ts` | 11 | `MyData` (all) | `shared/data.interface.ts` |

`floatMod` is the only helper in `utils.ts` that the light-curve path reaches;
both tools import it for period folding.

### 2.2 Pulsar

| Source | Lines in source | Extracted symbols (source line ranges) | Destination |
|---|---|---|---|
| `pulsar/pulsar.service.util.ts` | 910 | `PulsarDataDict` 5-9, `errorMSE` 11-17, `PulsarStarOptions` 20-24, `PulsarInterface` 26-36, `PulsarInterfaceStorageObject` 38-42, `PulsarInterfaceImpl` 45-101, `PulsarData` 222-316 | `pulsar-lightcurve.types.ts` |
| `pulsar/pulsar.service.util.ts` | 910 | `PulsarDisplayPeriod` 524-527, `PulsarPeriodFoldingStorageObject` 530-543, `PulsarPeriodFoldingInterface` 546-580, `PulsarPeriodFolding` 583-760 | `pulsar-period-folding.types.ts` |
| `pulsar/pulsar.service.ts` | 1263 | `getPeriodFoldingChartData` 273-314, `getJdRange` 455-468, `getChartPulsarDataArray` 609-613, `getChartSourcesDataArray` 649-660, `median` 715-720, `backgroundSubtraction` 722-739, `binData` 850-886, `interpolateLinear` 1227-1240, `resampleLinear` 1250-1262 | `pulsar-lightcurve.algorithms.ts` |
| `pulsar/light-curve/pulsar-light-curve/pulsar-light-curve.component.ts` | 365 | `uploadHandler` 51-330, `processChartData` 332-358 | `pulsar-lightcurve.ingest.ts` |
| `pulsar/light-curve/pulsar-light-curve-form/pulsar-light-curve-form.component.ts` | 108 | `onBackScaleChange` 70-103 | `pulsar-lightcurve.ingest.ts` |
| `pulsar/period-folding/pulsar-period-folding-highchart/…component.ts` | 331 | `foldAndBin` 182-197, `duplicateIfNeeded` 199-203, difference/sum block 224-232, calibration map 218-220, single-source fold 249-264 | `pulsar-period-folding.algorithms.ts` |
| `pulsar/period-folding/pulsar-period-folding-form/…component.ts` | 307 | `getPeriodStep` 299-306 | `pulsar-period-folding.algorithms.ts` |

### 2.3 Variable

| Source | Lines in source | Extracted symbols (source line ranges) | Destination |
|---|---|---|---|
| `variable/variable.service.util.ts` | 697 | `VariableDataDict` 5-12, `errorMSE` 14-20, `VariableData` 22-109, `VariableStarOptions` 112-116, `VariableInterface` 118-128, `VariableInterfaceStorageObject` 131-134, `VariableInterfaceImpl` 137-185 | `variable-lightcurve.types.ts` |
| `variable/variable.service.util.ts` | 697 | `VariableDisplayPeriod` 440-443, `VariablePeriodFoldingStorageObject` 446-454, `VariablePeriodFoldingInterface` 457-485, `VariablePeriodFolding` 488-598 | `variable-period-folding.types.ts` |
| `variable/variable.service.ts` | 536 | `getPeriodFoldingPeriod` 77-82, `getPeriodFoldingChartDataWithError` 162-194, `getJdRange` 285-289, `getChartVariableDataArray` 403-415, `getChartVariableErrorArray` 446-463 | `variable-lightcurve.algorithms.ts` |
| `variable/light-curve/variable-light-curve/variable-light-curve.component.ts` | 151 | the `fileParser.data$` handler body 38-113 → `mergeSourcesByMjd` | `variable-lightcurve.ingest.ts` |
| `variable/period-folding/variable-period-folding-form/…component.ts` | 129 | `getPeriodStep` 121-128 | `variable-period-folding.algorithms.ts` |

---

## 3. A finding worth flagging up front

The task brief described `pulsar.service.util.ts` (910 lines) and
`variable.service.util.ts` (697 lines) as the files that "hold the math". They
mostly do not. Read in full, both are ~85% data models, chart-label carriers and
`localStorage` serialization. The only arithmetic in either is `errorMSE`, a
seven-line quadrature helper duplicated verbatim in both.

The actual light-curve algorithms live in three other places:

1. **`pulsar.service.ts` / `variable.service.ts`** — background subtraction,
   binning, period folding, differential photometry, JD-range.
2. **The `*.component.ts` files** — despite being nominally UI. The pulsar file
   ingest (Green Bank header parsing, time-axis rebasing, Nyquist derivation) is
   entirely inside `pulsar-light-curve.component.ts`'s `uploadHandler`, and the
   two-source MJD merge join is inside `variable-light-curve.component.ts`'s
   constructor. Both are real algorithms wearing component clothing.
3. **`pulsar-period-folding-highchart.component.ts`** — `foldAndBin` and the
   difference/sum computation are closures inside `updateData()`, surrounded by
   Highcharts series plumbing.

The blanket guidance "`*.component.ts` is UI, not the target" would therefore
have dropped the majority of the pulsar tool's algorithmic content. I extracted
from the components where the math genuinely lives, and documented each call in
§6 below.

---

## 4. Framework seams cut

Every seam is marked in-file with `// EXTRACTED: was <original symbol>`.

| Seam | Where it appeared | How it was cut |
|---|---|---|
| `@Injectable()` + `@angular/core` | `PulsarService`, `VariableService` | Decorator and import removed; classes renamed `PulsarLightCurveAlgorithms` / `VariableLightCurveAlgorithms`. They still compose `PulsarData` / `PulsarInterfaceImpl` / `PulsarPeriodFolding` exactly as the services did, so no method body needed changing. |
| `@Component({...})` + template/style metadata | all light-curve and period-folding components | Removed. |
| Angular constructor DI | `PulsarLightCurveComponent`, `VariableLightCurveComponent`, both period-folding forms | Replaced by a plain constructor argument. For the pulsar ingest this is typed against a local `PulsarIngestHost` interface declaring exactly the 21 service members the verbatim body calls. |
| RxJS `BehaviorSubject` / `Subject` / `.next()` / `takeUntil` / `debounceTime` | ~14 subjects across both services, plus every component subscription | All emissions deleted. The in-memory mutation they announced is retained; only the notification is gone. |
| `localStorage` via `PulsarStorage` / `VariableStorage` | every setter in both services | `this.*Storage.save*()` calls deleted; the storage classes themselves were not extracted. |
| `Highcharts.Chart` handles | `setHighChartLightCurve` / `getHighChartPeriodogram` / `addSeries` / `setData` / `setExtremes` / `upsertSeries` | Not extracted. Where math was interleaved with series calls (pulsar period folding), the math was lifted into free functions. |
| Closure capture | `foldAndBin`, `duplicateIfNeeded`, `getPeriodStep` | These captured `period`, `phase`, `displayPeriod` and `this.service.binData` from their enclosing component. Those captures became explicit parameters. **This is the only place where a signature changed**; no body did. |
| `MatDialog` | chart-info edit dialogs | Not extracted. |
| `HonorCodePopupService` / `HonorCodeChartService` | `saveGraph()` in five components | Not extracted — chart PNG export behind an academic-honesty prompt. |
| `MyFileParser` / `FileType.CSV` | `VariableLightCurveComponent` | Not extracted. Generic CSV/TXT/FITS tokenizer shared by all Astromancer tools. `mergeSourcesByMjd` consumes its output shape (`{id, mjd, mag, mag_error}` rows), documented in-file. |
| `FileReader` | `PulsarLightCurveIngest.uploadHandler` | **Retained deliberately.** A browser API, not a framework dependency — and the whole ingest algorithm lives inside its `onload` callback. Keeping it means the body stays byte-identical. |

---

## 5. Pulsar vs variable — the distinction, preserved

The two tools share a folder layout and a naming scheme, which makes them look
like variants of one implementation. They are not. Recorded here because the
similarity is misleading:

| | Pulsar | Variable |
|---|---|---|
| Sample record | `{jd, source1, source2}` — two polarizations, **no errors** | `{jd, source1, source2, error1, error2, errorMSE}` |
| Science signal | raw intensity with a **running-median background** removed | **differential photometry**: `target − comparison + referenceStarMagnitude` |
| Tuning parameter | `backScale` — background window width in seconds (default 3) | `referenceStarMagnitude` — photometric zero-point (default 0) |
| Background subtraction | yes (`backgroundSubtraction` + `median`) | none |
| Binning | yes (`binData`, default 100 bins/period) | none — plots individual points with error bars |
| Error propagation | none | throughout, via `errorMSE` |
| Period folding | phase and 2×-period duplication applied **after** binning, in the chart component | phase and duplication applied **inside** the fold, in the service |
| Folding params | `period, periodMin, periodMax, phase, cal, speed, bins, displayPeriod` | `period, phase, displayPeriod` only |
| Default period | `0.2` s, real value | `-1`, a sentinel meaning "use the full JD baseline" |
| Slider bounds | persisted on the model, seeded from the data's Nyquist limit at ingest | computed inline from `periodogramStartPeriod … jdRange` |
| Ingest | fixed-column instrument file, `#` metadata header, two flavours (cal / standard) | CSV with interleaved sources, needs a merge join to align |
| Default dataset | 100 synthetic rows | 14 synthetic rows |
| Sonification | yes | no |

Two smaller preserved discrepancies, both left as found:

- `getJdRange` is loop-based in pulsar (a deliberate fix — spread-arg
  `Math.max(...arr)` overflowed V8's stack on ~125k-sample files) but still
  spread-based in variable, whose datasets never got large enough to hit it.
- `getPeriodStep` is arithmetically identical in both tools, but only the
  variable copy carries the explanatory comment. Both copies kept.

---

## 6. What was left behind, and why

### Left behind as UI / rendering

- **All Highcharts components** — `pulsar-light-curve-highchart` (206),
  `variable-light-curve-highchart` (210), `variable-period-folding-highchart`
  (163), and the non-math ~80% of `pulsar-period-folding-highchart` (331).
  Series construction, boost-module config, marker symbols, tooltip formats.
- **`updateXAxisScale()`** (both period-folding highcharts) — a magnitude ladder
  (`delta` 0.15 → 0.000001) picking a rounded axis maximum, then
  `xAxis[0].setExtremes()`. Numeric, but it computes a chart viewport and
  nothing else. **Judgment call**; flagged in-file.
- **Both table components** — `pulsar-table` (179), `variable-table` (103).
  Handsontable grid adapters plus a `limitPrecision` display rounding helper.
- **Chart-info forms** — `pulsar-light-curve-chart-form` (62),
  `variable-light-curve-chart-form` (62), `variable-light-curve-form` (39).
  Pure `FormGroup` wiring for titles, axis labels and star selection.
- **All `*.component.html` / `*.component.scss`.**
- **All `*.component.spec.ts`** — 16 files, each a 21-23 line Angular TestBed
  stub with no assertions about the math.

### Left behind as state / persistence

- **`PulsarStorage`** (`pulsar.service.util.ts` 763-911) and
  **`VariableStorage`** (`variable.service.util.ts` 601-697) — `localStorage`
  get/save/reset for ten and six keys respectively.
- **`PulsarChartInfo`** (104-218) and **`VariableChartInfo`** (188-295) — chart
  titles, axis labels, data labels.
- **`UpdateSource`** enum (`shared/data/utils.ts` 258-262) — an RxJS
  discriminator distinguishing init/reset/interface-driven form refreshes.

### Left behind as out of scope

- **Sonification** — see §7.
- **Periodogram** — see §8.
- **`rad` / `deg` / `d2HMS` / `d2DMS`** (`shared/data/utils.ts` 1-12, 264-278) —
  celestial coordinate conversion. Verified by grep to be unused anywhere under
  `tools/pulsar/` or `tools/variable/`.
- **`Sonifier` class** (`shared/sonification/sonification.ts`, 173 lines) — a
  standalone audio class that no light-curve code imports; the pulsar tool has
  its own copy of this logic inlined in the service.

### Retained despite a plausible case for exclusion

- **`interpolateLinear` / `resampleLinear`** (`pulsar.service.ts` 1227-1262).
  Their only callers in Astromancer are the sonifier. They are nonetheless pure,
  self-contained linear resampling with no audio or framework dependency and
  obvious utility on a binned light curve, so they were kept — with an in-file
  note recording that their sole in-app caller was out-of-scope audio code.
- **Chart-label fields on the period-folding models** (`title`, `xAxisLabel`,
  `yAxisLabel`, `dataLabel`). These are UI, but they are interleaved with the
  algorithm parameters inside `PulsarPeriodFolding` / `VariablePeriodFolding`.
  Stripping them would have meant rewriting the classes rather than copying
  them, so they were kept and flagged in-file.

---

## 7. The sonifier — confirmed out of scope

`pulsar-light-curve-sonifier/` (88 lines) and the two large service methods it
drives, `PulsarService.sonification` (`pulsar.service.ts` 889-1053) and
`sonificationBrowser` (1056-1224), were **not extracted**.

Reviewed rather than assumed. Their content:

- WAV container construction — RIFF/fmt/data chunk headers written into a
  `DataView`, interleaved 16-bit PCM conversion, `Blob` + object-URL download.
- `AudioContext` / `AudioBufferSourceNode` playback, loop and stop handling.
- Two audio synthesis modes — amplitude-modulated white noise ("burst", TV-static
  style) below 4 kHz, and direct waveform playback above it.
- Audio-domain normalization to ±0.95 with a 0.7 gain.

The only genuinely reusable numerics inside are the global min/max normalization
and `interpolateLinear` — and `interpolateLinear` was extracted separately (§6).
The component itself (88 lines) is a button handler that clips the series to the
first 60 seconds before handing off. Everything else is audio rendering, which is
the same category as the Highcharts rendering excluded elsewhere.

`speed` and `cal` on `PulsarPeriodFolding` are retained even though `speed` is
consumed only by sonification — they are fields on an extracted model, not code.

---

## 8. Overlap with the periodogram extraction

A separate agent extracted periodogram code into `/home/claude/Kepler/periodogram/`
from three of the same source files. Nothing was written outside
`/home/claude/Kepler/lightcurve/`. Their output landed before this document was
finalized, so the overlap below is **verified against their actual files**, not
predicted.

### Shared source files, disjoint contents

- **`shared/data/utils.ts`** — I took only `floatMod` (15-25). The periodogram
  side owns `lombScargle` (81-125), `lombScargleWithError` (36-78) and the
  private `ArrMath` object (128-256), in `periodogram/core/lomb-scargle.ts`.
  No overlap in the *periodogram-specific* lines.
- **`pulsar.service.util.ts`** — I took the data/interface/period-folding models;
  they took `PulsarPeriodogram`, `PulsarPeriodogramStorageObject` and
  `PulsarPeriodogramInterface` (318-521). Disjoint.
- **`variable.service.util.ts`** — same split; `VariablePeriodogram` and friends
  (298-437) are theirs. Disjoint.

### Genuinely duplicated symbols — confirmed

Each of these now exists in both `lightcurve/` and `periodogram/`. Per the
coordination note this duplication is expected and acceptable; it is listed so
that a future consolidation knows exactly what to reconcile.

| Symbol | My copy | Their copy |
|---|---|---|
| `floatMod` | `shared/numeric-utils.ts` | `core/lomb-scargle.ts:40` |
| `errorMSE` | both `*/…-lightcurve.types.ts` | `variable/variable-periodogram.model.ts:41` |
| `PulsarDataDict` | `pulsar/pulsar-lightcurve.types.ts` | `pulsar/pulsar-periodogram.compute.ts:30` |
| `VariableDataDict` | `variable/variable-lightcurve.types.ts` | `variable/variable-periodogram.model.ts:27` |
| `VariableStarOptions` | `variable/variable-lightcurve.types.ts` | `variable/variable-periodogram.compute.ts:22` |
| `getJdRange` | method on both algorithm classes | `pulsar/pulsar-periodogram.compute.ts:107` (free function) |
| `getChartPulsarDataArray` | method on `PulsarLightCurveAlgorithms` | `pulsar/pulsar-periodogram.compute.ts:37` (free function) |
| `getChartVariableDataArray` | method on `VariableLightCurveAlgorithms` | `variable/variable-periodogram.compute.ts:40` (free function) |
| `getPeriodStep` | both `*-period-folding.algorithms.ts` | `pulsar/pulsar-periodogram-folding-link.ts:54` |

Two notes on this table:

- `getChartVariableDataArray` is the **differential photometry** routine — the
  variable tool's core light-curve algorithm (§5). It appears on the periodogram
  side because the Lomb-Scargle input is the differential magnitude series, not
  the raw source columns. Both tools genuinely need it; neither claim is wrong.
- Their copies are free functions taking `data` as a parameter; mine are methods
  on a class that composes the data container, matching how `PulsarService` /
  `VariableService` held it. Same bodies, different call shape.

They also carried over `rad`, `deg`, `d2HMS`, `d2DMS` and `UpdateSource` from
`utils.ts` (they copied the file more wholesale); I deliberately dropped those as
unused-by-light-curve — see §6. Not a conflict, just a different cut line.

### Coupling points — behaviour that spans both extractions

These are places where light-curve code legitimately writes periodogram state.
Neither extraction is complete without the other:

1. **Nyquist seeding** (`pulsar-light-curve.component.ts` 139-150 and 270-300).
   The light-curve ingest computes `avgDiff = 2 × mean sample interval` and
   writes it into **both** the period-folding bounds *and* the periodogram's
   start/end period, branching on `getPeriodogramMethod()` for
   frequency-vs-period mode. My `PulsarIngestHost` seam interface declares
   `getPeriodogramMethod`, `setPeriodogramStartPeriod` and
   `setPeriodogramEndPeriod` for exactly this reason, and flags them in-file.

   **This grid math is duplicated, deliberately, against coordinator guidance —
   flagging it explicitly.** The periodogram agent extracted the same lines as
   `nyquistPeriodogramRange` and `nyquistFoldingFloor`
   (`periodogram/pulsar/pulsar-periodogram-range.ts`) and the coordinator asked
   me not to duplicate them. I could not comply without breaking the extraction
   contract, for two reasons:

   - In the source these lines are **physically interleaved** with the file
     parsing inside a single `FileReader.onload` closure — the `avgDiff` loop
     sits between the column-mapping code and the background-subtraction call.
     Excising it would mean rewriting `uploadHandler` rather than copying it,
     which the task explicitly forbids ("preserve algorithms verbatim... do NOT
     redesign or reimplement").
   - The same `avgDiff` also drives `setPeriodFoldingPeriodMin/Max`, which is
     **period-folding state and therefore in my scope** per coordinator point 1.
     The block cannot be assigned wholly to either extraction.

   Resolution: `pulsar-lightcurve.ingest.ts` keeps `uploadHandler` byte-identical
   to the source, grid math included. Treat
   `periodogram/pulsar/pulsar-periodogram-range.ts` as the **canonical, reusable**
   form of that math — it is the same arithmetic, already factored into pure
   functions with `null` guards. My copy exists only as a side effect of keeping
   the surrounding ingest verbatim, and should not be maintained independently.
   If the two are ever reconciled, delete mine and have the ingest call theirs.
2. **Shared defaults.** `PulsarPeriodFolding.getDefaultStorageObject()` sets
   `periodMin: 0.1, periodMax: 3` with a preserved source comment stating these
   intentionally mirror the periodogram's `startPeriod`/`endPeriod` defaults.
   Changing one side silently desynchronizes the other.
3. **Periodogram → period folding.** `pulsar-period-folding-form.component.ts`
   157-183 recomputes the folding slider bounds from the periodogram's
   start/end period after each Compute, inverting them in frequency mode. Not
   extracted (it is RxJS + change-detection plumbing), but recorded here because
   it is the return leg of coupling point 1.

### Not extracted here — periodogram-side, flagged for the other agent

- `PulsarService.getChartPeriodogramDataArray` (`pulsar.service.ts` 663-700)
- `VariableService.getChartPeriodogramDataArray` (`variable.service.ts` 465-473)
- `PulsarService.getLabels` (`pulsar.service.ts` 470-493) — period↔frequency axis
  relabeling that also inverts the periodogram bounds
- `PulsarService.compute` / `clearPeriodogramChart` / the
  `chartComputedPeriodogramDataArray` persistence path

---

## 9. Preserved quirks — suspected bugs left intact

Per the extraction contract, nothing here was fixed. Each item is preserved
verbatim and flagged in-file; this list exists so the behaviour is not mistaken
for something the extraction introduced.

1. **Misaligned parallel filters in the variable period fold** — *most likely to
   bite.* `getPeriodFoldingChartDataWithError`
   (`variable-lightcurve.algorithms.ts`) builds `data` from
   `getChartVariableDataArray` and `error` from `getChartVariableErrorArray`,
   then indexes them in lockstep (`data[i]` / `error[i]`). But the two use
   **different filter predicates**: the error array additionally requires
   `row.errorMSE !== null`. Any row with a null `errorMSE` shortens `error`
   without shortening `data`, after which every subsequent pair is off by one and
   the tail throws on `error[i][1]!`. Rows only reach that state between a
   `mergeSourcesByMjd` result and the `VariableData.setData` call that populates
   `errorMSE`, which is why it rarely surfaces. *(The periodogram agent
   independently flagged the same two-pass pattern on its side.)*
2. **No empty-data guard on the variable fold.** The same method dereferences
   `data[0][0]!` with no length check and throws on an empty table. The pulsar
   equivalent (`getPeriodFoldingChartData`) had a guard added for exactly this —
   the fix was never mirrored across. Preserved as the asymmetry it is.
3. **Inverted `getIsLightCurveOptionValid` on the pulsar model.**
   `PulsarInterfaceImpl.getIsLightCurveOptionValid()` returns
   `!this.LightCurveOptionValid` — negated — while `PulsarService`'s method of
   the same name returns the flag un-negated. The two disagree for every input.
   Only the service version is reachable from the UI, so the model's copy is
   effectively dead code hiding a sign error. Both preserved.
4. **Descending sort immediately re-sorted ascending.** Both fold routines end
   with `sort((a, b) => b[0] - a[0])` (descending), and every caller then
   re-sorts ascending. Wasted work, not incorrect.
5. **`binData` divides by zero on a degenerate range.** If all x values are
   equal, `binSize` is 0 and every `binIndex` is `NaN`, yielding an empty result
   rather than an error. Unguarded in the source.
6. **Dead locals in the pulsar ingest.** `let type = "cal"` is assigned in both
   branches and never read; `let period: number | null = null` in the
   standard-file branch is shadowed by an inner `const period` and never read.
   Preserved so the body stays byte-identical.
7. **Index-based fold on single-source files.** `foldSingleSourceByIndex`
   spreads samples evenly across one period by array index
   (`item.frequency / initialData.length`), ignoring the true JD spacing that
   the dual-source path honours. Intentional-looking but undocumented in the
   source; preserved with a note.

## 10. Source commit history — a caution

The Astromancer history is not a reliable guide to what changed. Verified
against actual diffs rather than messages:

- `226baed "Fix periodogram display bug"` touches only
  `pulsar-periodogram-highcharts.component.ts` and `.gitignore` — rendering
  only, no math, nothing in light-curve scope.
- `86bb5f9 "Minor formatting"` is **badly misnamed**. It carries real behavioural
  change into three files this extraction draws from: it adds
  `setTableType('subtracted')` to both `pulsar-light-curve.component.ts`'s
  upload handler and `PulsarService.resetData`, corrects a stale
  `10s` → `3s` comment on the Nyquist branch, and adds the
  `Promise.resolve().then(() => cdr.detectChanges())` NG0100 workaround to the
  period-folding form.

Both are ancestors of `HEAD` (`657b709`), and this extraction was taken from the
working tree at `HEAD`, so all of the above is already reflected. Recorded only
so that anyone diffing this extraction against an older Astromancer checkout
knows why those lines differ. Neither commit touched `shared/data/utils.ts`.

## 11. External npm dependencies

**The extracted code has zero runtime npm dependencies.** Everything reduces to
plain TypeScript plus these browser globals:

| Global | Where | Note |
|---|---|---|
| `FileReader` | `pulsar-lightcurve.ingest.ts` | Retained deliberately (§4) |
| `alert`, `console` | `variable-lightcurve.ingest.ts` | Preserved verbatim from source |

Dependencies present in the originals and **removed** by this extraction, with the
versions declared in `/home/claude/astromancer/package.json`:

| Package | Version | Used for |
|---|---|---|
| `@angular/core` | ^16.2.0 | `@Injectable`, `@Component`, `ChangeDetectorRef` |
| `@angular/forms` | ^16.2.0 | `FormGroup`, `FormControl`, `Validators`, `FormBuilder` |
| `@angular/material` | ^16.2.0 | `MatDialog` |
| `rxjs` | ~7.5.0 | `BehaviorSubject`, `Subject`, `takeUntil`, `debounceTime`, `combineLatest`, `skip`, `first` |
| `highcharts` | ^11.1.0 | all chart rendering |
| `highcharts-angular` | ^3.1.2 | chart component wrapper |
| `handsontable` / `@handsontable/angular` | 13.0.0 | data tables |
| `chart.js` | ^4.2.1 | typing-only, via `shared/charts/chart.interface.ts` |

`localStorage` was also removed — a Web Storage global rather than a package, but
worth listing alongside these since it was the persistence layer for every model
class extracted here.

---

## 12. Verification status

- Every extracted body was diffed by eye against its source; algorithms and
  comments are unchanged.
- The only signature changes are the closure-capture → parameter conversions
  listed in §4, each marked in-file.
- **Not type-checked.** No Node, npm or `tsc` is available in this environment
  (`/home/claude/astromancer/node_modules` has no `.bin/tsc`, and `node` is not
  on `PATH`). The files are self-consistent by inspection and the import graph is
  closed within `lightcurve/`, but they have not been fed to a compiler. Running
  `tsc --noEmit` over `lightcurve/` is the obvious next step once a toolchain is
  available.
- No test files were extracted; the 16 Astromancer spec files are TestBed stubs
  that assert only `expect(component).toBeTruthy()`.
