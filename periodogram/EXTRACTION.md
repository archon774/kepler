# Periodogram extraction

Algorithmic periodogram source lifted out of the Astromancer Angular app.

- **Source repo:** `/home/claude/astromancer` (read-only for this task; untouched)
- **Source commit:** `657b709` — *Merge pull request #73 from SkynetRTN/pulsar-bug-fix* (branch `main`, clean tree)
- **Extracted:** 2026-08-10

This is an **extraction, not a port**. Algorithms and comments are preserved
verbatim wherever the framework allowed it. Nothing was redesigned,
reimplemented, or translated. Where a framework dependency had to be severed,
the seam is marked in-file with an `// EXTRACTED:` comment.

---

## Structure

```
periodogram/
├── core/
│   ├── lomb-scargle.ts                    ← the shared algorithmic heart
│   └── peak-detection.ts                  ← peak + false-alarm thresholds
├── pulsar/
│   ├── pulsar-periodogram.model.ts        ← input/output types, parameter block
│   ├── pulsar-periodogram.compute.ts      ← driver: column prep → lombScargle
│   ├── pulsar-periodogram-range.ts        ← Nyquist-derived default grid bounds
│   └── pulsar-periodogram-folding-link.ts ← periodogram output → folding input
├── variable/
│   ├── variable-periodogram.model.ts      ← input/output types (error-carrying)
│   └── variable-periodogram.compute.ts    ← driver: → lombScargleWithError
└── EXTRACTION.md
```

`core/` is deliberately central: both tools call the same transform, and both
tool folders import *upward* into `core/`. Nothing in `core/` imports from
`pulsar/` or `variable/`.

---

## What was copied

| Destination | Source path (under `/home/claude/astromancer/`) | Source lines | Fidelity |
|---|---|---|---|
| `core/lomb-scargle.ts` | `src/app/tools/shared/data/utils.ts` | 1–278 (whole file) | **Byte-identical**, 20-line provenance header prepended |
| `core/peak-detection.ts` | `src/app/tools/pulsar/periodogram/pulsar-periodogram-highcharts/pulsar-periodogram-highcharts.component.ts` | 152–162, 234–247 | `findLocalMax` verbatim; confidence math lifted out of Highcharts calls |
| `pulsar/pulsar-periodogram.model.ts` | `src/app/tools/pulsar/pulsar.service.util.ts` | 5–9, 318–329, 332–368, 371–521 | Verbatim |
| `pulsar/pulsar-periodogram.compute.ts` | `src/app/tools/pulsar/pulsar.service.ts` | 442–445, 455–468, 470–493, 609–613, 663–700 | Bodies verbatim; `this.` reads → parameters |
| `pulsar/pulsar-periodogram-range.ts` | `src/app/tools/pulsar/light-curve/pulsar-light-curve/pulsar-light-curve.component.ts` | 139–150, 270–300 | Math + comments verbatim; lifted out of a FileReader handler |
| `pulsar/pulsar-periodogram-folding-link.ts` | `src/app/tools/pulsar/period-folding/pulsar-period-folding-form/pulsar-period-folding-form.component.ts` | 157–183, 299–306 | Verbatim; lifted out of an RxJS subscriber |
| `variable/variable-periodogram.model.ts` | `src/app/tools/variable/variable.service.util.ts` | 5–12, 14–20, 298–305, 308–336, 339–437 | Verbatim |
| `variable/variable-periodogram.compute.ts` | `src/app/tools/variable/variable.service.ts` + `variable.service.util.ts` | 403–415, 465–473 (+ util 112–116) | Bodies verbatim; `this.` reads → parameters; one local renamed (marked in-file) |

**`core/lomb-scargle.ts` is the highest-value artifact and is a byte-for-byte
copy** — verified with `diff` against the original after stripping the header.
It contains `lombScargleWithError`, `lombScargle`, the private `ArrMath`
vector helper object (`errorMean`, `errordot`, `weightedSum`, `dot`, `var`, …),
plus `rad`, `deg`, `floatMod`, `d2HMS`, `d2DMS`, and the `UpdateSource` enum.

---

## The algorithm, briefly

Both tools evaluate Lomb-Scargle on a **logarithmically spaced** grid, not the
linear grid the loop header suggests. The loop iterates `xVal` linearly from
`start` to `stop`, but the value actually used is recomputed from the loop
counter:

```ts
let logXVal = Math.exp(Math.log(start) + (Math.log(stop) - Math.log(start)) * i / (steps))
```

The linear `xVal` is vestigial in `lombScargleWithError` and only used in
`lombScargle`'s `freqMode === true` branch, which overrides `logXVal` back to
the linear value. So **frequency mode samples linearly and period mode samples
logarithmically** — an asymmetry worth knowing before anyone "cleans up" that
loop. Both original in-code comments about this ("Huge MISTAKE was here…",
"Nyquist is not used here…") are preserved.

Error weighting (`lombScargleWithError` only) replaces the plain mean with
`ArrMath.errorMean` (inverse-variance weighted) and the plain dot product with
`ArrMath.errordot` (weights `1/σ²`, normalised by the weight sum).

The two functions also differ in **output shape**, which matters downstream:
`lombScargleWithError` returns `[x, y]` tuples; `lombScargle` returns
`{x, y}` objects. That difference is the direct cause of the recent bug fix
described below.

---

## Pulsar vs. variable — the split

The two tools are genuinely different algorithms, not a copy-paste pair:

| | **pulsar** | **variable** |
|---|---|---|
| Transform | `lombScargle` (unweighted) | `lombScargleWithError` (inverse-variance weighted) |
| Input | `PulsarDataDict{jd, source1, source2}` — no errors | `VariableDataDict{jd, source1, source2, error1, error2, errorMSE}` |
| Input prep | raw sources, both polarisation channels independently | differential: target − reference + reference magnitude |
| Channels | **two** periodograms (XX / YY), second is optional | **one** periodogram |
| Grid steps | user-controlled `points` (default 1000) | hardcoded 2000 (`// Maximum points for html2canvas … is 2000`) |
| Period/frequency mode | yes — `method` flag → `freqMode` | no, period only |
| Default range | 0.1–3 s, overridden from data Nyquist on upload | 0.1–1, fixed |
| Peak detection | yes — global max marker + 3 confidence lines | none |
| Output shape | `{x, y}` objects | `[x, y]` tuples |

The pulsar tool is the more developed of the two. The variable tool has no
peak detection, no false-alarm thresholds, and no Nyquist-derived defaults —
so `core/peak-detection.ts` and `pulsar/pulsar-periodogram-range.ts` have no
variable counterpart. That absence is real, not an extraction gap.

---

## Recent bug-fix findings

Checked `git log` / `git show` on all periodogram paths.

**`226baed` "Fix periodogram display bug" — display only. The Lomb-Scargle
math was not touched.** The commit modifies exactly one source file
(`pulsar-periodogram-highcharts.component.ts`, +25/−25) plus `.gitignore`. It
converts `lombScargle`'s `{x, y}` object output into `[x, y]` tuples before
handing it to Highcharts. The retained comment explains why:

> On Highcharts 11.1.0 (which is what production runs), line series given
> `{x, y}` object data on a logarithmic x-axis can fail to render their SVG
> path entirely for certain data shapes — the series group exists in the DOM
> but no path element is created.

It also replaced an `Object.entries(periodogramData)` iteration with an
explicit `[data1, data2]` array. That is a genuine behavioural fix but still
on the rendering side: `Object.entries` iterated the `{data1, data2}` return
object, so when `data2` was `undefined` the series indexing and the
"remove excess series" `slice(index)` could disagree.

**`86bb5f9` "Minor formatting"** — despite the name, this is where the
*reload* half of the fix landed (+27 in the same component): the `setData()`
guard against the `[[0], [0]]` storage placeholder, the same object→tuple
conversion on the persisted-data path, and recomputation of the "Global
Maxima" series on reload. Also +5 lines in `pulsar.service.ts`.

**`657b709`** is just the merge of those two (plus a gitignore commit).

**Net finding: the current periodogram numerics are identical to what they
were before the bug-fix branch. Nothing in `utils.ts` has changed in either
commit** — its last functional touch is much older (`52decba` "Change step
size", `840d003` "variable: periodogram is now logarithmically scaled").

Everything here reflects the **current fixed state** at `657b709`. The
tuple-conversion logic itself was *not* extracted — it is Highcharts
workaround code, documented here instead.

---

## What was left behind, and why

**Angular UI / rendering (the bulk of both `periodogram/` folders):**

- `*.component.html`, `*.component.scss`, `*.component.spec.ts` — all of them.
- `pulsar-periodogram.component.ts` / `variable-periodogram.component.ts` —
  empty shell components (10 and ~10 lines, no logic at all).
- `pulsar-periodogram-form.component.ts` (160 lines) /
  `variable-periodogram-form.component.ts` (90 lines) — Angular
  `FormGroup`/`FormControl` wiring, debounce timings, honor-code save-graph
  hooks. The only non-UI content is the compute-button guard
  `if (start < end) service.compute()`, noted here rather than extracted.
- `pulsar-periodogram-highcharts.component.ts` (319 lines) /
  `variable-periodogram-highcharts.component.ts` (120 lines) — Highcharts
  options, series management, axis titles, zoom handling, and the
  object→tuple workaround above. Peak detection and the confidence-threshold
  formula were the only algorithmic content; both extracted to
  `core/peak-detection.ts`.

**State plumbing and persistence:**

- `PulsarStorage` / `VariableStorage` — `localStorage` get/save/reset.
- `PulsarData` / `VariableData` — light-curve data containers. `PulsarData`
  does hold `chartComputedPeriodogramDataArray`, but that is a persistence
  cache of this tool's output, not part of computing it.
- `PulsarChartInfo`, `VariableChartInfo`, `PulsarInterfaceImpl`,
  `VariableInterfaceImpl` — label/interface state.
- All RxJS `BehaviorSubject` / `Subject` / `takeUntil` / `debounceTime`
  plumbing, and the `Highcharts.Chart` handles held by the services.

**File parsing:** the pulsar upload handler's `P_topo` / `SRC_NAME` / `UTC` /
`DATE_OBS` header scraping and column mapping stays with the light curve. Only
the Nyquist bounds math was taken.

---

## Period folding — judgment call

**Not extracted here** (beyond the interface seam), on the judgment that
folding is primarily light-curve territory: it phase-folds the light curve and
its output is a folded light curve. A separate agent owns `lightcurve/`, and
duplicating the folding transform would be the heavy kind of duplication worth
avoiding.

What *was* taken is only the coupling, in
`pulsar/pulsar-periodogram-folding-link.ts`:

- `foldingRangeFromPeriodogram()` — maps the periodogram's search window onto
  the folding slider bounds on Compute, including the frequency-mode
  inversion. This has to know the period/frequency mode flag, which is
  periodogram semantics.
- `getPeriodStep()` — folding step size, derived from `getJdRange()` which is
  extracted here.

**Left for the lightcurve extraction:** `PulsarService.getPeriodFoldingChartData()`
(pulsar.service.ts 273–314), `VariableService`'s folding equivalent
(variable.service.ts ~165–195), and the `PulsarPeriodFolding` /
`VariablePeriodFolding` model classes. Note that the actual folding transform
depends on **`floatMod`**, which lives in `core/lomb-scargle.ts` here —
whoever owns folding needs that helper, and it is expected to be duplicated.

Also note the coupling recorded in `pulsar.service.util.ts` (lines 617–619):
`PulsarPeriodFolding`'s `periodMin`/`periodMax` defaults (0.1 / 3)
intentionally mirror the periodogram's `startPeriod`/`endPeriod` defaults.
Changing one side silently desynchronises the other.

---

## Overlap with the lightcurve extraction

Duplication is intentional and expected — these are copied, not shared:

| Symbol | Also needed by lightcurve | Where it is here |
|---|---|---|
| `floatMod` | **yes** — period folding depends on it | `core/lomb-scargle.ts` |
| `rad`, `deg`, `d2HMS`, `d2DMS` | probably (coordinate display) | `core/lomb-scargle.ts` |
| `UpdateSource` enum | yes — form reset plumbing | `core/lomb-scargle.ts` |
| `PulsarDataDict` | **yes** — shared row type | `pulsar/pulsar-periodogram.model.ts` |
| `VariableDataDict`, `errorMSE` | **yes** — shared row type | `variable/variable-periodogram.model.ts` |
| `VariableStarOptions` | **yes** | `variable/variable-periodogram.compute.ts` |
| `getChartVariableDataArray` | **yes** — it *is* the light curve | `variable/variable-periodogram.compute.ts` |
| `getChartPulsarDataArray` | **yes** | `pulsar/pulsar-periodogram.compute.ts` |
| `getJdRange` | likely | `pulsar/pulsar-periodogram.compute.ts` |
| Nyquist bounds math | shares its source function (the upload handler) | `pulsar/pulsar-periodogram-range.ts` |

Nothing under `/home/claude/Kepler/lightcurve/` was read or written.

---

## Framework seams cut

Every seam is marked in-file with `// EXTRACTED:`. Summary:

1. **`@Injectable` / Angular DI** — `PulsarService` and `VariableService` were
   root-provided singletons. Their periodogram methods are now free functions;
   every `this.<getter>()` read became an explicit parameter. Method bodies are
   otherwise unchanged.
2. **RxJS** — `BehaviorSubject` / `Subject` / `takeUntil` / `skip` /
   `debounceTime` all dropped. `PulsarService.compute()` was *only*
   `isComputingSubject.next(!getValue())` (an RxJS toggle telling the chart to
   recompute), so it is documented rather than reproduced.
3. **localStorage write-through** — `setChartComputedPeriodogramDataArray()`
   became an optional `onComputed` callback on the pulsar compute function, so
   the caching side effect stays visible without importing storage.
4. **Angular `@Component`** — `findLocalMax` and the confidence math were
   private methods of the Highcharts component; the surrounding
   `chartObject.addSeries(...)` / `setData(...)` calls are gone.
5. **`FileReader` handler** — the Nyquist bounds math was inline in an upload
   callback; it now takes a `number[]` and returns the bounds instead of
   pushing them through the service.
6. **`ChangeDetectorRef` / `InputSliderValue`** — Angular change-detection
   workarounds (the `Promise.resolve().then(() => cdr.detectChanges())`
   NG0100 dance) dropped entirely.
7. **Highcharts** — no import survives in this folder.

**One deliberate non-cut:** `lombScargle` and `lombScargleWithError` call the
DOM `alert()` on a `ts.length != ys.length` mismatch. That is original
behaviour inside the verbatim core, so it was left in place. A non-browser
host must shim `alert` or that path throws.

**One rename:** in `variable-periodogram.compute.ts` a local named `data`
became `filtered`, because `data` is now the parameter that replaced
`this.getData()`. Marked in-file.

---

## External npm dependencies

**The extracted code has zero runtime npm dependencies.** It is plain
TypeScript over `Math`, arrays, and (in the two guard clauses) the DOM
`alert`. All imports are relative, within this folder.

Dependencies of the *original* files, all left behind:

| Package | Version in astromancer | Why it did not come along |
|---|---|---|
| `@angular/core` | `^16.2.0` | `@Injectable`, `@Component`, `ChangeDetectorRef` |
| `@angular/forms` | `^16.2.0` | `FormGroup` / `FormControl` in the form components |
| `highcharts` | `^11.1.0` | all rendering; also the subject of the recent bug fix |
| `rxjs` | `~7.5.0` | service subjects, debouncing |
| `typescript` | `~4.9.5` | build only |

Target language level: the code uses `**`, optional chaining, and
`Array.prototype.reduce` — ES2020 is sufficient.

---

## Known limitations of this extraction

- **Not compiled or type-checked.** No Node/npm/tsc is available in this
  environment (`node`, `npm`, `npx`, `tsc` all absent; astromancer has no
  `node_modules`). The verbatim core was verified by `diff`; the
  parameter-threaded driver functions have been reviewed by eye but not
  compiled. Worth a `tsc --noEmit` pass on a machine with a toolchain.
- **No tests.** The astromancer `*.spec.ts` files are Angular TestBed
  scaffolding with no algorithmic assertions, so there was nothing to bring.
- The `AgentVault` shared memory at `/srv/agent-vault` referenced in the
  operating instructions was **not accessible** from this environment, so no
  vault notes were consulted or updated. The repo was treated as the source
  of truth.
