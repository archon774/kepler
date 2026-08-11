// EXTRACTED from astromancer: src/app/tools/shared/data/utils.ts (278 lines)
//
// Only the celestial-angle helpers the CLUSTER / HR-DIAGRAM path uses are
// carried over here, copied byte-for-byte:
//   rad    -> cluster.util.haversine, result.utils.equatorial2Galactic,
//             result.utils.getPhysicalRadius, result.utils.getMass,
//             galaxy edge-on / face-on projection
//   deg    -> result.utils.equatorial2Galactic
//   d2HMS  -> result summary RA formatting
//   d2DMS  -> result summary Dec / l / b / angular-radius formatting
//
// Left behind from that file (not reachable from the cluster tool):
//   lombScargle, lombScargleWithError, the private ArrMath object and
//   floatMod  -> periodogram / light-curve math, already extracted under
//                ../../periodogram/core/lomb-scargle.ts and
//                ../../lightcurve/shared/numeric-utils.ts
//   UpdateSource -> an RxJS form-refresh discriminator, framework plumbing.
//
// Framework seams: none. utils.ts had zero Angular/RxJS/Highcharts imports.

/**
 *  This function takes an angle in degrees and returns it in radians.
 *  @param degree:  An angle in degrees
 *  @returns {number}
 */
export function rad(degree: number): number {
    return degree / 180 * Math.PI;
}

export function deg(degree: number): number {
    return degree / Math.PI * 180;
}

export function d2HMS(d: number): number[] {
    const hours = Math.floor(d / 15);
    const minutes = Math.floor((d - hours * 15) * 4);
    const seconds = ((d - hours * 15) * 4 - minutes) * 60;
    return [hours, minutes, seconds];
}

export function d2DMS(d: number): number[] {
    const sign = d < 0 ? '-' : '+';
    d = Math.abs(d);
    const degrees = Math.floor(d);
    const minutes = Math.floor((d - degrees) * 60);
    const seconds = ((d - degrees) * 60 - minutes) * 60;
    return [degrees, minutes, seconds];
}
