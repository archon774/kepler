// EXTRACTED from astromancer:
//   src/app/tools/cluster/result/result.utils.ts  (131 lines; 107 carried over)
//
// The derived-quantity math of the result stage. Every function below is
// copied byte-for-byte.
//
//   getHalfLightRadius   - median angular separation of members from the
//                          cluster centre (the comment calling it a "50%
//                          median" is the author's, preserved).
//   equatorial2Galactic  - RA/Dec -> galactic (l, b), NGP constants and the
//                          arctan quadrant shifts as written. Source link is
//                          the author's.
//   getPhysicalRadius    - angular radius + distance -> radius. The 3261.56
//                          factor is kpc -> light-year.
//   getPmra / getPmdec   - median proper motion (assumes a sorted input; the
//                          callers pass ClusterDataService.getPmra/getPmdec,
//                          which sort).
//   getVelocityDispersion- the 68.3% central band of the per-star proper-motion
//                          residual magnitude, then its mean. Note the
//                          asymmetric slice bounds ((1-p)/2 low, (1-p/2) high)
//                          are original and preserved.
//   getMass              - virial mass from velocity dispersion, distance and
//                          physical radius, with eta = 10 and G in
//                          pc/M_sun (km/s)^2.
//
// LEFT BEHIND from this file (not algorithm):
//   drawStar(ctx, ...)   - Canvas2D star-polygon rasteriser used by the two
//                          galaxy diagrams. Pure rendering.
//   downloadCsv(...)     - Blob + <a download> browser file save. Pure IO.
//
// Framework seams: none in the retained bodies — result.utils.ts had no
// Angular/RxJS/Highcharts imports. The getDateString import it carried was
// only used by downloadCsv and goes away with it.

// EXTRACTED: import paths only. `getDateString` from
//            ../../shared/charts/utils is dropped along with downloadCsv.
import {haversine, Source} from "../cluster.util";
import {deg, rad} from "../shared/angle.util";

/*
    * Returns the half-light radius of the cluster in degrees
    * 50% median of the angular distance (using haversine) between the cluster center and the sources
 */
export function getHalfLightRadius(sources: Source[], centerRa: number, centerDec: number): number {
    const angularDistance: number[] = [];
    sources.forEach(source => {
        angularDistance.push(haversine(centerDec, source.astrometry.dec, centerRa, source.astrometry.ra));
    });
    angularDistance.sort((a, b) => a - b);
    return angularDistance[Math.floor(angularDistance.length / 2)];
}

// https://en.wikipedia.org/wiki/Galactic_coordinate_system#cite_note-5
export function equatorial2Galactic(ra: number, dec: number): { l: number, b: number } {
    const ra_ngp: number = rad(192.8595);
    const dec_ngp: number = rad(27.1284);
    const l_ngp: number = rad(122.93314);

    const ra_rad: number = rad(ra);
    const dec_rad: number = rad(dec);
    const b = Math.asin(Math.sin(dec_ngp) * Math.sin(dec_rad)
        + Math.cos(dec_ngp) * Math.cos(dec_rad) * Math.cos(ra_rad - ra_ngp));
    let temp = Math.cos(dec_rad) * Math.sin(ra_rad - ra_ngp) /
        (Math.sin(dec_rad) * Math.cos(dec_ngp) - Math.cos(dec_rad) * Math.sin(dec_ngp) * Math.cos(ra_rad - ra_ngp));
    temp = Math.atan(temp)
    temp = temp < 0 ? temp + Math.PI : temp; //shift arctan to [0, 2pi]
    let l = l_ngp - temp;
    l = l < 0 ? l + 2 * Math.PI : l; //shift to [0, 2pi]
    return {l: deg(l), b: deg(b)};
}

export function getPhysicalRadius(distance: number, angularRadius: number): number {
    return 2 * distance * Math.tan(rad(angularRadius) / 2) * 3261.56;
}

export function getPmra(pmras: number[]): number {
    const size: number = pmras.length;
    return pmras[Math.floor(size / 2)];
}

export function getPmdec(pmdecs: number[]): number {
    const size: number = pmdecs.length;
    return pmdecs[Math.floor(size / 2)];
}

export function getVelocityDispersion(sources: Source[], pmra: number, pmdec: number): number {
    const dispersion: number[] = [];
    sources.forEach(source => {
        if (source.fsr !== null && source.fsr.pm_ra !== null && source.fsr.pm_dec !== null) {
            const pmraDelta = source.fsr!.pm_ra - pmra;
            const pmdecDelta: number = source.fsr!.pm_dec - pmdec;
            dispersion.push(Math.sqrt(pmraDelta * pmraDelta + pmdecDelta * pmdecDelta));
        }
    });
    dispersion.sort((a, b) => a - b);
    const percentile = 0.683
    const dispersionSliced = dispersion.slice(
        Math.floor(dispersion.length * (1 - percentile) / 2),
        Math.ceil(dispersion.length * (1 - percentile / 2)));
    let sum: number = 0;
    dispersionSliced.forEach(d => sum += d);
    return sum / dispersionSliced.length;
}

export function getMass(velocityDispersion: number, distance: number, physicalRadius: number): number {
    const sigma = 3.086 * Math.pow(10, 13) * distance
        * rad(velocityDispersion) / (3600 * 365.25 * 24 * 3600);
    const r = physicalRadius * 0.3066; // pc
    const G = 0.004302; // pc / M_sun (km/s)^2
    const eta = 10;
    return eta * sigma * sigma * r / G;
}
