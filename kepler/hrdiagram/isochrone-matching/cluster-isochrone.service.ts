// EXTRACTED from astromancer:
//   src/app/tools/cluster/isochrone-matching/cluster-isochrone.service.ts
//   (121 lines; ~70 carried over)
//
// This service is the parameter store for isochrone matching: the four fitted
// quantities (age, metallicity, distance, reddening), the photometric-error
// cut, and the list of PlotConfigs (which filter triples are plotted, and as
// CM or HR). It is mostly state plumbing rather than math — but it is the
// canonical definition of the algorithm's input surface, so it is carried over
// with the framework stripped.
//
// The one genuine computation is resetDistance(): seed the distance from the
// midpoint of the FSR parallax-distance selection, falling back to 0.1 kpc.
//
// The parseFloat() coercions in setIsochroneParams / setPlotParams are NOT
// cosmetic and are preserved: astromancer's Material sliders hand back strings,
// and the CMD/HR offset math would silently string-concatenate without them.
//
// Framework seams cut:
//   @Injectable()                              - Angular DI
//   Subject/Observable pairs (plotParams$, isochroneParams$, maxMagError$,
//     addPlotConfig$, plotConfig$, resetPlotConfig$)
//                                              - RxJS change fan-out to the
//                                                Highcharts components
//   ClusterStorageService                      - localStorage persistence; its
//                                                init() defaults are preserved
//                                                below as DEFAULT_ISOCHRONE_STORAGE
//   ClusterService (reset$ subscription, getFsrParams)
//                                              - tool-wide session state
//   highCharts[] / setHighChart / getHighCharts- a registry of live
//                                                Highcharts.Chart handles used
//                                                only for PNG export. Pure
//                                                rendering; dropped entirely.

import {IsochroneParams, PlotConfig, PlotFraming, PlotParams} from "../cluster.util";
import {FsrParameters} from "../fsr/fsr.util";
import {IsochroneStorageObject} from "../storage/cluster-storage.service.util";

// EXTRACTED: was the `isochrone` block of ClusterStorageService.init()
//            (src/app/tools/cluster/storage/cluster-storage.service.ts:152-193).
//            These are the values a fresh session starts from. The UI slider
//            domains that bound them (isochrone-plotting-controls.component.html)
//            are recorded in ../EXTRACTION.md, not enforced here — astromancer
//            did not enforce them in code either.
export const DEFAULT_ISOCHRONE_STORAGE: IsochroneStorageObject = {
    plotConfigs: [],
    plotParams: {
        distance: 0.1,
        reddening: 0,
    },
    isochroneParams: {
        age: 6.60,
        metallicity: -2.2,
    },
    maxMagError: 1,
};

// EXTRACTED: was `@Injectable() export class ClusterIsochroneService`.
export class ClusterIsochroneService {
    private plotConfigs!: PlotConfig[];
    private plotParams!: PlotParams;
    private isochroneParams!: IsochroneParams;
    private maxMagError!: number;

    constructor() {
        this.init();
        // EXTRACTED: was `this.service.reset$.subscribe(() => { this.init();
        //            this.resetPlotConfigSubject.next(this.plotConfigs); })`.
        //            Call init() directly to reset.
    }

    public init() {
        // EXTRACTED: was four reads from ClusterStorageService (localStorage).
        //            Seeded from the same defaults that service initialised to.
        this.plotConfigs = [...DEFAULT_ISOCHRONE_STORAGE.plotConfigs];
        this.plotParams = {...DEFAULT_ISOCHRONE_STORAGE.plotParams};
        this.isochroneParams = {...DEFAULT_ISOCHRONE_STORAGE.isochroneParams};
        this.maxMagError = DEFAULT_ISOCHRONE_STORAGE.maxMagError;
    }

    public getIsochroneParams() {
        return this.isochroneParams;
    }

    public setIsochroneParams(isochroneParams: IsochroneParams) {
        if (isochroneParams) {
            this.isochroneParams.age = parseFloat(isochroneParams.age as any);
            this.isochroneParams.metallicity = parseFloat(isochroneParams.metallicity as any);
        } else {
            this.isochroneParams = isochroneParams;
        }
        // EXTRACTED: was this.storageService.setIsochroneParams(isochroneParams)
        //            followed by this.isochroneParamsSubject.next(...).
    }

    public getMaxMagError() {
        return this.maxMagError;
    }

    public setMaxMagError(maxMagError: number) {
        this.maxMagError = maxMagError;
        // EXTRACTED: was storage write + maxMagErrorSubject.next(...).
    }

    public getPlotParams() {
        return this.plotParams;
    }

    public setPlotParams(plotParams: PlotParams) {
        if (plotParams) {
            this.plotParams.distance = parseFloat(plotParams.distance as any);
            this.plotParams.reddening = parseFloat(plotParams.reddening as any);
        } else {
            this.plotParams = plotParams;
        }
        // EXTRACTED: was storage write + plotParamsSubject.next(...).
    }

    public getPlotConfigs() {
        return this.plotConfigs;
    }

    public setPlotConfigs(plotConfigs: PlotConfig[]) {
        this.plotConfigs = plotConfigs;
        // EXTRACTED: was storage write + plotConfigSubject.next(...).
    }

    public addPlotConfigs(plotConfig: PlotConfig) {
        this.plotConfigs.push(plotConfig);
        // EXTRACTED: was storage write + addPlotConfigSubject.next(...) +
        //            plotConfigSubject.next(...).
    }

    public updatePlotFraming(plotFraming: PlotFraming, index: number) {
        this.plotConfigs[index].plotFraming = plotFraming;
        // EXTRACTED: was this.storageService.setPlotConfigs(this.plotConfigs).
    }

    // EXTRACTED: `distance` was read as `this.service.getFsrParams().distance`
    //            (ClusterService). Passed in explicitly here.
    public resetDistance(fsrParams: FsrParameters) {
        const distance = fsrParams.distance
        if (distance) {
            this.plotParams.distance = parseFloat(((distance.max + distance.min) / 2).toFixed(2));
        } else {
            this.plotParams.distance = 0.1;
        }
    }
}
