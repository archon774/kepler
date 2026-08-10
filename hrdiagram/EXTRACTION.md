# HR Diagram / Isochrone Matching — extraction record

Algorithmic TypeScript lifted out of the **Astromancer** "cluster" tool
(`/home/claude/astromancer`, Angular 16) into `Kepler/hrdiagram/`.

This is an **extraction, not a port**. Function bodies, comments, constants and
the author's quirks (including several bugs, flagged below) are preserved as
written. The only edits are import paths, the removal of Angular/RxJS/Highcharts
wrappers, and the lifting of methods out of components into free functions. Every
severed dependency carries an inline `// EXTRACTED: was …` seam comment at the
point it was cut.

Astromancer was **not modified**.

---

## 1. What the algorithm actually is

Understanding the split below is easier with the pipeline in front of you:

1. **Ingest** — sources arrive with astrometry (RA/Dec), parallax distance,
   proper motion, and multi-band photometry. Photometry is cleaned (NaN and
   unknown filters dropped) and sorted by effective wavelength.
2. **Field star removal (FSR)** — an *elliptical* acceptance region in
   (pm_ra, pm_dec) intersected with a distance interval partitions sources into
   cluster members vs field.
3. **Isochrone matching** — for a chosen filter triple (blue, red, luminosity),
   members are plotted as colour `blue − red` against luminosity magnitude. The
   student varies four parameters — **age**, **metallicity**, **distance**,
   **reddening** — until a model isochrone overlays the main sequence. Distance
   and reddening enter as a rigid *offset* between the observed CM plane and the
   absolute HR plane; age and metallicity select which model track is fetched.
4. **Result** — the fitted distance plus member astrometry yield half-light
   radius, physical radius, galactic coordinates, velocity dispersion, and a
   virial mass.

The single most important function is
`isochrone-matching/isochrone-plot.util.ts::computePlotDelta`:

```
dx = A(red) − A(blue)                        colour excess
dy = −A(lum) − 5·log10(d_pc) + 5             distance modulus
```

with `A(λ)` from `cluster.util.ts::getExtinction` (Cardelli–Clayton–Mathis
parameterisation). HR mode shifts the *stars* by `+delta`; CM mode shifts the
*isochrone* by `−delta`. Same fit, opposite frame.

---

## 2. Files copied

Line counts are of the **astromancer source file**; the "carried" column is how
much of it landed here.

| Destination | Source (under `/home/claude/astromancer/`) | Src lines | Carried |
|---|---|---|---|
| `cluster.util.ts` | `src/app/tools/cluster/cluster.util.ts` | 228 | 228 (verbatim) |
| `shared/angle.util.ts` | `src/app/tools/shared/data/utils.ts` | 278 | 24 (4 functions) |
| `storage/cluster-storage.service.util.ts` | `src/app/tools/cluster/storage/cluster-storage.service.util.ts` | 75 | 75 (verbatim) |
| `fsr/fsr.util.ts` | `src/app/tools/cluster/FSR/fsr.util.ts` | 22 | 22 (verbatim) + `range` |
| `fsr/fsr-histogram.util.ts` | `.../FSR/histogram-slider-input/histogram-slider-input.component.ts` | 467 | ~35 (2 functions) |
| `fsr/cmd-fsr.util.ts` | `.../FSR/cmd-fsr/cmd-fsr.component.ts` | 135 | ~45 (1 function) |
| `photometry/cluster-data.service.util.ts` | `src/app/tools/cluster/cluster-data.service.util.ts` | 133 | 133 (verbatim) |
| `photometry/cluster-data.service.ts` | `src/app/tools/cluster/cluster-data.service.ts` | 408 | ~180 |
| `isochrone-matching/cluster-isochrone.service.ts` | `.../isochrone-matching/cluster-isochrone.service.ts` | 121 | ~70 |
| `isochrone-matching/isochrone-plot.util.ts` | `.../isochrone-matching/plots/plot/plot.component.ts` | 447 | ~150 |
| ″ (`isValidFilterSelection`) | `.../control-panel/filter-selector/filter-selector.component.ts` | 53 | 3 |
| `result/result.utils.ts` | `src/app/tools/cluster/result/result.utils.ts` | 131 | 107 |
| `result/cluster-summary.ts` | `.../result/result-summary/result-summary.component.ts` | 275 | ~33 |
| ″ (`logAgeToMyr`) | `.../result/result-summary/result-summary.component.html` | 121 | 1 expression |
| `result/galaxy-projection.ts` | `.../result-graphics/galaxy-faceon/…component.ts` + `galaxy-edgeon/…component.ts` | 66 + 68 | ~20 |
| `result/mwsc-distributions.ts` | `.../result-graphics/{age,distance,metallicity,reddening,number-of-stars}/…component.ts` | 149+163+105+105+111 | ~50 |

`.spec.ts` files were not examined for content and none were copied.

### Directory layout created

```
hrdiagram/
├── EXTRACTION.md
├── cluster.util.ts                 domain model, filter tables, extinction
├── shared/
│   └── angle.util.ts               rad, deg, d2HMS, d2DMS
├── storage/
│   └── cluster-storage.service.util.ts   ClusterMWSC, StarCounts, storage shapes
├── fsr/
│   ├── fsr.util.ts                 FsrParameters, range
│   ├── fsr-histogram.util.ts       Freedman–Diaconis binning, 2.5σ clip
│   └── cmd-fsr.util.ts             preview CMD construction
├── photometry/
│   ├── cluster-data.service.util.ts  the FSR membership cut, star counts
│   └── cluster-data.service.ts       in-memory source catalogue + projections
├── isochrone-matching/
│   ├── cluster-isochrone.service.ts  fitted-parameter store + defaults
│   └── isochrone-plot.util.ts        ★ the CM/HR transform
└── result/
    ├── result.utils.ts             half-light radius, galactic coords, mass
    ├── cluster-summary.ts          the terminal derivation chain
    ├── galaxy-projection.ts        (l, b, d) → galactic-plane position
    └── mwsc-distributions.ts       catalogue histogram prep + unit conversions
```

---

## 3. What was left behind, and why

### 3.1 Entire files excluded — pure Angular UI

Every `*.component.html`, `*.component.scss`, `*.component.spec.ts` and
`cluster.module.ts`, plus these `*.component.ts` files which contain **no**
computation at all:

`isochrone-matching.component.ts` (9 lines, empty shell), `result.component.ts`
(13, empty), `filter-controls.component.ts` (10, empty), `cluster.component.ts`,
`cluster-stepper.component.ts`, `cluster-plot-grid.component.ts` (grid arity from
`plotConfigs.length`), `plot-lists.component.ts` (CDK drag-reorder of plot
configs), `hrd-result.component.ts` (a `FormGroup` that builds one `PlotConfig`),
`result-graphics.component.ts` (fetches `/cluster/allMWSC`),
`archive-fetching-graphics.component.ts` (stacked column chart of star counts —
checked specifically, it only re-reads `getInterfaceStarCounts()`),
`field-star-removal.component.ts` (wires three histogram sliders to
`setFsrParams`), `pm-chart.component.ts`, `pie-chart.component.ts`,
`data-source/*` (file upload, drag-n-drop directive, name lookup, five modal
pop-ups), `archive-feetching/*` (fetch dialogs).

### 3.2 Services excluded — framework state, not algorithm

- **`cluster.service.ts`** (101) — session state: cluster name, FSR params,
  tab index, loading flag, a registry of `Highcharts.Chart` handles, and six
  RxJS `Subject`s. The only thing downstream math needed from it was
  `getFsrParams()`, now a field on the extracted `ClusterDataService` and a
  parameter to `resetDistance()`.
- **`storage/cluster-storage.service.ts`** (194) — a `localStorage`
  get/set wrapper. **Its `init()` default block was preserved**, as
  `DEFAULT_ISOCHRONE_STORAGE` in `isochrone-matching/cluster-isochrone.service.ts`,
  because those are the algorithm's starting parameter values.
- **`data-source/cluster-data-source.service.ts`** (165) and
  **`.util.ts`** (77) — file upload/parse orchestration and
  `ClusterLookUpStackImpl`, an LRU stack of recent cluster-name searches. UI
  history. Left behind; `ClusterLookUpData` is aliased to `unknown` in
  `storage/cluster-storage.service.util.ts` with a seam comment.
- **`src/app/shared/job/job.ts`** — an `HttpClient` + `interval()` polling
  wrapper for async backend jobs. Network plumbing. `JobStorageObject` is
  likewise aliased to `unknown`.

### 3.3 Functions deliberately dropped from files that were otherwise copied

| Dropped | From | Why |
|---|---|---|
| `drawStar(ctx, …)` | `result/result.utils.ts` | Canvas2D star-polygon rasteriser. Pure rendering. |
| `downloadCsv(cols, data, name)` | `result/result.utils.ts` | `Blob` + `<a download>` browser file save. Pure IO. |
| `lombScargle`, `lombScargleWithError`, `ArrMath`, `floatMod`, `UpdateSource` | `shared/data/utils.ts` | Periodogram / light-curve math, unreachable from the cluster tool. Already extracted under `Kepler/periodogram/core/` and `Kepler/lightcurve/shared/`. |
| `fetchCatalog`, `fetchFieldStarRemoval`, `getCatalogResults`, `getFSRResults`, `initValues`, `downloadSources` | `cluster-data.service.ts` | HTTP job submission/polling, response callbacks, localStorage job replay, CSV download. See §5 for the response contracts. |
| `setHighChart` / `getHighCharts` / `highCharts[]` | `cluster-isochrone.service.ts` | A registry of live chart handles used only for PNG export. |
| `downloadSummary`, `downloadData`, `downloadPlots`, `downloadFsrPlots`, `downloadPlotData`, `submitData` | `result-summary.component.ts` | Export handlers and an Astronomicon `POST`. `downloadPlotData` in particular reads points back out of the Highcharts series — it is a chart reader, not a producer. |

### 3.4 Judgment calls on the UI-vs-algorithm boundary

The brief flagged `result/result-graphics/` as ambiguous. Findings, per file:

- **`galaxy-faceon` / `galaxy-edgeon`** — **contained real math; extracted.**
  Under the image blit and `drawStar` calls sits a genuine projection of
  (l, b, distance) into the galactic plane. Lifted to
  `result/galaxy-projection.ts`. The pixel scale factors (32, 16), the ±500
  clamp and the two canvas anchor points came along, because the returned
  offsets are meaningless without them — they are tagged as rendering constants.
- **`age`** — **contained a real conversion; extracted.** `10^age / 1e6`
  converts the catalogue's log10(years) to Gyr. Same expression appears in the
  summary template for Myr; both are in the extraction.
- **`distance`** — **contained a real conversion; extracted.** `distance/1000`
  is the *only* place the catalogue's parsecs meet the tool's kiloparsecs. Easy
  to lose, so it is called out explicitly in `mwsc-distributions.ts`.
- **`metallicity`, `reddening`, `number-of-stars`** — **borderline; extracted
  the clip, dropped everything else.** Each contributes only a domain filter
  (`−2.3 < Z < 0.8`, `0 ≤ E(B−V) ≤ 1`) or an outlier trim
  (`slice(0.0015·n, 0.99985·n)`). These match the charts' fixed axis bounds, but
  they function as catalogue-quality cuts that discard sentinel rows, so they
  were kept rather than discarded as styling.
- **`hrd-result`, `result-graphics`, `number-of-stars`'s marker update** — **no
  math; dropped.**

Three further calls worth recording:

- **`plot.component.ts` was the biggest judgment call.** It is a 448-line
  Highcharts component, and on a filename-only reading it would have been
  skipped as UI. It is in fact where the entire CM↔HR transform lives. Six
  private methods were lifted; the chart options, `setExtremes`/`setData`
  calls, the axis-title string building (with its `"prime"` → `'` prettifying
  and `<sub>0</sub>` markup) and the `try/catch` blocks — whose only purpose was
  "chart not built yet, write to the options literal instead" — were dropped.
- **`histogram-slider-input.component.ts`**: 467 lines of Material sliders and
  reactive forms wrapping ~35 lines of statistics. Only the statistics came.
- **`cluster-isochrone.service.ts` is mostly state plumbing**, not math. It was
  extracted anyway because it is the canonical definition of the algorithm's
  input surface (the four fitted parameters, the error cut, the plot configs)
  and the parameter defaults live there.

---

## 4. Framework seams cut

Every one of these is marked inline with `// EXTRACTED: was …`.

| Seam | Where | Replacement |
|---|---|---|
| `@Injectable()` | `ClusterDataService`, `ClusterIsochroneService` | Plain classes, constructed directly. |
| `@Component` / `@Input` / `@ViewChild` | all lifted component methods | Free functions with explicit parameters. |
| RxJS `Subject`/`Observable` fan-out (`plotParams$`, `isochroneParams$`, `maxMagError$`, `plotConfig$`, `addPlotConfig$`, `resetPlotConfig$`, `sources$`, `clusterSources`) | both services | Removed. Setters mutate state; the host schedules recomputation. |
| `ClusterStorageService` (localStorage) | both services | Defaults inlined as `DEFAULT_ISOCHRONE_STORAGE`; `fsrParams` held as a field on `ClusterDataService` (`getFsrParams()` added). |
| `ClusterService.getFsrParams()` | `ClusterIsochroneService.resetDistance()` | Now an explicit `FsrParameters` parameter. |
| `ClusterService.reset$` | `ClusterIsochroneService` constructor | Call `init()` directly. |
| `HttpClient` + `environment.apiUrl` | `cluster-data.service.ts`, `plot.component.ts`, `result-graphics.component.ts` | Removed. Contracts documented in §5. `setUserPhotometry` / `setCluster` / `setStarCounts` were made public as the injection seam for what used to arrive in responses. |
| `Job` (async polling) | `cluster-data.service.ts` | Removed; `JobStorageObject` aliased to `unknown`. |
| `Highcharts` (options, `Chart` handles, `series[n].setData`, `axis.setExtremes`) | every chart component | Removed. Range computation retained as `getStandardViewRange` / `getDataRange`. |
| `@angular/forms` `ValidatorFn` | `filterValidator` | Kept as the plain predicate `isValidFilterSelection`. |
| `@angular/material` `MatSlider` `ViewChild` writes | `setExtremes` | Removed; `getHistogramExtremes` returns the range. |
| `@angular/cdk` `moveItemInArray` | `plot-lists.component.ts` | Whole component dropped. |
| DOM `Blob` / `document.createElement('a')` / `window.URL` | `downloadCsv` | Dropped. |
| Canvas2D `ctx` | `drawStar`, both galaxy `draw()` | Dropped; projection math retained. |
| `import {ClusterLookUpData}` | `cluster-storage.service.util.ts` | `type ClusterLookUpData = unknown` |

**No behaviour was silently dropped.** Where a cut removed a side effect (a
storage write, an observable emission, a chart update), the seam comment names
the exact statement removed.

---

## 5. Data and asset dependencies

### Isochrone model grids — **NOT PRESENT, and not copyable from this repo**

This is the most important dependency to flag. Astromancer ships **no** isochrone
data: no lookup tables, no model grids, nothing under `src/assets/` (which
contains only two font families and a `static/` folder). Verified by searching
the whole repo for `*isochrone*` — only the TypeScript files listed above match.

The model track is fetched per parameter change from a backend:

```
GET {environment.apiUrl}/cluster/isochrone
    ?age=<log10 yr>&metallicity=<solar>
    &blue_filter=<FILTER>&red_filter=<FILTER>&lum_filter=<FILTER>
→ { data: number[][], iSkip: number }
```

`data` arrives **already in `[colour, absolute magnitude]` pairs for the
requested filter triple** — i.e. the server does the grid interpolation and the
synthetic photometry. `iSkip` marks an index where the evolutionary track is
discontinuous and the polyline must be broken.

**Consequence:** `hrdiagram/` reproduces the client-side transform faithfully,
but a standalone system needs its own isochrone source (e.g. PARSEC / MIST
grids) plus the interpolation and bolometric-correction step that the
astromancer backend performs. That backend is not in this repository.

### Other backend endpoints referenced (all cut)

| Endpoint | Was used for |
|---|---|
| `POST/GET {apiUrl}/cluster/catalog` | catalogue cone search; response supplies `output_sources`, `input_sources`, `cluster` (a `ClusterMWSC`), `star_counts` |
| `POST/GET {apiUrl}/cluster/fsr` | field-star-removal astrometry; response supplies `sources` and `FSR`, merged by `appendFSRResults` |
| `GET {apiUrl}/cluster/allMWSC` | the full Milky Way Star Cluster catalogue, `ClusterMWSC[]`, feeding `result/mwsc-distributions.ts` |
| `POST {astronomiconApiUrl}/submissions` | student result submission |

`environment.apiUrl` defaults to `http://127.0.0.1:5001` in dev.

### Data tables that DID come along (embedded in source, not external files)

- `filterWavelength` — effective wavelength (µm) for 20 filters. Drives both
  extinction and the photometry sort order.
- `filterFramingValue` — per-filter `blue`/`red`/`faint`/`bright` extremes
  defining the "Standard View" axis window.
- `APASS_FILTERS`, `TWO_MASS_FILTERS`, `WISE_FILTERS`, `GAIA_FILTERS` — catalogue
  groupings used for per-survey star counts.
- The CCM extinction polynomial coefficients inside `getExtinction`.

### Parameter domains (UI-enforced in astromancer, documented here only)

From `isochrone-plotting-controls.component.html`. The extracted code does **not**
enforce these — neither did astromancer's TypeScript.

| Parameter | Min | Max | Step | Default | Note |
|---|---|---|---|---|---|
| Distance (kpc) | 0.1 | 100 | 0.01 | 0.1 | log-scaled slider |
| log(Age (yrs)) | 6.60 | 10.20 | 0.05 | 6.60 | |
| Metallicity (solar) | −2.2 | 0.7 | 0.05 | −2.2 | |
| E(B−V) | 0 | 1 | — | 0 | |
| Max Error (mag) | 0 | 1 | — | 1 | photometric-error cut |

---

## 6. External npm dependencies

**Required by the extracted code: none.** Every file here compiles against the
TypeScript standard library alone — no runtime imports outside `hrdiagram/`.

Dependencies of the *original* files, all severed:

| Package | Used for | Status |
|---|---|---|
| `@angular/core` | `@Injectable`, `@Component`, `@Input`, `@ViewChild` | cut |
| `@angular/common/http` | `HttpClient` | cut |
| `@angular/forms` | `FormGroup`, `FormControl`, `Validators`, `ValidatorFn` | cut |
| `@angular/material` | `MatSlider`, `MatDialog`, `mat-divider` | cut |
| `@angular/cdk` | `moveItemInArray`, drag-drop | cut |
| `rxjs` (~7.5) | `Subject`, `Observable`, `debounceTime`, `takeUntil`, `combineLatestWith`, … | cut |
| `highcharts` (^11.1) + `highcharts-angular` + `highcharts/modules/histogram-bellcurve` | every chart | cut |
| `piexif-ts` | EXIF stamping on exported PNGs | cut (never reached) |
| `chart.js` | `updateLine` in `shared/charts/utils.ts` | cut (never reached) |

`tslib` may be needed depending on the consuming project's `importHelpers`
setting; nothing here requires it directly.

---

## 7. Preserved defects — do not "fix" these silently

Faithfulness was chosen over correctness. Each is flagged inline at its site.

1. **`getExtinction` ignores its own `rv` parameter in the leading term.**
   Returns `3.1 * reddening * (a + b / rv)` — the `3.1` is hard-coded even
   though `rv` is a parameter defaulting to `3.1`. Only matters for a non-3.1
   caller; there are none today. — `cluster.util.ts`
2. **`getStandardViewRange` mixes `lum` and `red` in the y-minimum.** The
   `y.min` expression subtracts `filterFramingValue[red].faint` where every
   sibling term uses `lum`. — `isochrone-matching/isochrone-plot.util.ts`
3. **Off-by-one in the isochrone break splice.** `slice(0, iSkip - 1)` drops one
   point before inserting the `[null, null]` gap. — `applyIsochroneTransform`
4. **Dead `else if (maxMagError === null)` branches** in `generateRawData`
   (three of them, one with an empty body). `maxMagError` is initialised to `0`
   and only ever assigned numbers, so these never fire.
5. **`getPmra` is applied to the pm_dec array** in the summary derivation
   (`result-summary.component.ts:108`). Harmless — `getPmra` and `getPmdec` have
   identical bodies — but it is not what it looks like. — `result/cluster-summary.ts`
6. **`d2DMS` computes a `sign` variable and never uses it.** Negative
   declinations therefore lose their sign in the DMS triple.
   — `shared/angle.util.ts`
7. **Asymmetric percentile bounds in `getVelocityDispersion`.** Low bound uses
   `(1 − p)/2`, high bound uses `(1 − p/2)` — not mirror images, so the retained
   band is not the intended central 68.3%. — `result/result.utils.ts`
8. **`updateClusterFieldSources` takes `sqrt` of a possibly negative value.**
   For a star outside the pm_ra semi-axis, `1 − ((pm_ra − c)/a)²` is negative and
   `decDiff` is `NaN`; the subsequent comparisons then yield `false`, which
   happens to be the correct rejection. Correct by accident.
   — `photometry/cluster-data.service.util.ts`

---

## 8. Structural notes for a consumer

- **Circular type import, inherited.** `cluster.util.ts` imports `ClusterMWSC`
  from `storage/cluster-storage.service.util.ts`, which imports `PlotConfig`
  et al. back from `cluster.util.ts`. This cycle exists in astromancer and is
  type-only, so it erases at compile time. The `ClusterMWSC` import in
  `cluster.util.ts` is in fact **unused** — preserved to keep that file verbatim.
- **Sorting is a precondition, not an implementation detail.** `getDefaultBin`,
  `getHistogramExtremes`, `getPmra`, `getPmdec`, `getHalfLightRadius` and the
  `getClusterRa`/`getClusterDec` medians all assume ascending-sorted input. The
  `ClusterDataService` projections sort before returning; any replacement data
  path must do the same.
- **The cluster centre is an element-wise median** of member RA and Dec
  independently — not a spherical mean. Fine for compact clusters, wrong near
  the poles or across the RA=0 wrap.
- **No compiler was available in this environment** (`node`/`tsc` absent), so
  the extracted files have been reviewed by hand but not type-checked. Imports
  and paths were verified manually.
