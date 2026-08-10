// EXTRACTED from astromancer:
//   src/app/tools/cluster/result/result-summary/result-summary.component.ts
//   (275 lines; the ~33-line init() derivation lifted here)
//
// ResultSummaryComponent is mostly buttons — five download handlers, an
// Astronomicon POST, an honor-code modal and four RxJS re-run triggers. Its
// init() method, however, is the terminal derivation of the whole tool: it
// takes the fitted isochrone parameters plus the member sources and produces
// every reported cluster property. That orchestration is the algorithm and is
// carried over here, body unchanged.
//
// Chain, in order:
//   member count -> half-light (angular) radius -> centre RA/Dec -> galactic
//   (l, b) -> physical radius from the FITTED distance -> median proper motion
//   -> velocity dispersion -> virial mass.
//
// Note the original passes `getPmra` over the pm_DEC array as well (line 108 of
// the source: `this.pmdec = getPmra(this.dataService.getPmdec())`). getPmra and
// getPmdec have identical bodies so this is harmless, and it is preserved.
//
// LEFT BEHIND: downloadSummary / downloadData / downloadPlots /
// downloadFsrPlots / downloadPlotData (CSV + PNG export through
// HonorCodePopupService and HonorCodeChartService), submitData (HttpClient
// POST to the Astronomicon submissions API), the d2HMS/d2DMS string formatting
// of every value (presentation — the helpers themselves are available in
// ../shared/angle.util if a host wants them), and the tab-index/RxJS
// subscriptions that decided when to re-run.

import {IsochroneParams, PlotParams, Source} from "../cluster.util";
import {
    equatorial2Galactic,
    getHalfLightRadius,
    getMass,
    getPhysicalRadius,
    getPmra,
    getVelocityDispersion
} from "./result.utils";

export interface ClusterSummary {
    numberOfStars: number;
    /** degrees */
    angularRadius: number;
    /** degrees */
    ra: number;
    /** degrees */
    dec: number;
    /** galactic longitude, degrees */
    l: number;
    /** galactic latitude, degrees */
    b: number;
    /** light years */
    physicalRadius: number;
    /** mas/yr */
    pmra: number;
    /** mas/yr */
    pmdec: number;
    /** mas/yr */
    velocityDispersion: number;
    /** solar masses */
    mass: number;
    /** kpc, as fitted */
    distance: number;
    /** log10(years), as fitted */
    age: number;
    /** solar, as fitted */
    metallicity: number;
    /** E(B-V) magnitudes, as fitted */
    reddening: number;
}

// EXTRACTED: was `init()` on ResultSummaryComponent. The service reads
//            (dataService.getSources(true), getClusterRa(), getClusterDec(),
//            computeGalacticCoordinates(), getPmra(), getPmdec(),
//            isochroneService.getPlotParams(), getIsochroneParams()) are now
//            parameters. Assignment order and every call are unchanged.
//
//            `sources` must be the CLUSTER MEMBER partition
//            (ClusterDataService.getSources(true)), and `pmras` / `pmdecs`
//            the sorted member proper motions.
export function computeClusterSummary(
    sources: Source[],
    clusterRa: number,
    clusterDec: number,
    pmras: number[],
    pmdecs: number[],
    plotParams: PlotParams,
    isochroneParams: IsochroneParams): ClusterSummary {

    const numberOfStars = sources.length;
    const angularRadius = getHalfLightRadius(sources, clusterRa, clusterDec);
    const ra = clusterRa;
    const dec = clusterDec;
    // EXTRACTED: was this.dataService.computeGalacticCoordinates(), which
    //            wrapped equatorial2Galactic and cached l/b on the service.
    const lb = equatorial2Galactic(clusterRa, clusterDec);
    const l = lb.l;
    const b = lb.b;
    const distance = plotParams.distance;
    const reddening = plotParams.reddening;
    const age = isochroneParams.age;
    const metallicity = isochroneParams.metallicity;
    const physicalRadius = getPhysicalRadius(distance, angularRadius);
    const pmra = getPmra(pmras);
    const pmdec = getPmra(pmdecs);
    const velocityDispersion = getVelocityDispersion(sources, pmra, pmdec);
    const mass = getMass(velocityDispersion, distance, physicalRadius);

    return {
        numberOfStars, angularRadius, ra, dec, l, b, physicalRadius,
        pmra, pmdec, velocityDispersion, mass,
        distance, age, metallicity, reddening,
    };
}

// EXTRACTED: was inline in result-summary.component.html:83
//            `{{(Math.pow(10, age) / 1000000).toFixed(2)}} (Myrs)`.
//            The tool fits log10(age/yr); this is the only place the reported
//            linear age is formed.
export function logAgeToMyr(logAge: number): number {
    return Math.pow(10, logAge) / 1000000;
}
