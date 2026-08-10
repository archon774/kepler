// EXTRACTED from astromancer:
//   src/app/tools/cluster/result/result-graphics/galaxy-faceon/galaxy-faceon.component.ts  (66 lines)
//   src/app/tools/cluster/result/result-graphics/galaxy-edgeon/galaxy-edgeon.component.ts  (68 lines)
//
// Both components draw a Milky Way backdrop image onto a 1000x1000 canvas and
// mark two positions on it: the Sun and the cluster. The image blit, the
// canvas sizing, the drawStar() polygon rasteriser and the RxJS redraw
// triggers are rendering and are left behind.
//
// What IS algorithm is the projection: converting the cluster's galactic
// coordinates (l, b) plus the FITTED distance into a position in the galactic
// plane. That is lifted here verbatim.
//
//   face-on  (looking down on the disc)
//       d  = distance * cos(b)            in-plane distance from the Sun
//       dx =  d * sin(l)
//       dy = -d * cos(l)
//   edge-on  (looking along the disc)
//       d  = distance * cos(b)
//       dx = -d * cos(l)
//       dy =  distance * sin(b)           height above/below the plane
//
// The scale factors (32 and 16) and the +-500 clamp are pixel-space, not
// physics, but they are inseparable from the returned offsets so they are kept
// as written — including the author's "one pixel is 32 kpc" comment, which
// describes the reciprocal of what the code does (32 px per kpc). Preserved
// verbatim rather than corrected.

import {rad} from "../shared/angle.util";

// EXTRACTED: canvas anchor points from the two draw() methods. The Sun is
//            drawn at these coordinates on a 1000x1000 canvas and the cluster
//            offset below is measured from them. Rendering constants, but the
//            offsets are meaningless without them.
export const GALAXY_CANVAS_SIZE = 1000;
export const SUN_FACE_ON_CENTER = {x: 500, y: 720};
export const SUN_EDGE_ON_CENTER = {x: 750, y: 500};

// EXTRACTED: was the tail of `draw()` in GalaxyFaceonComponent. `l`/`b` came
//            from dataService.getGalacticLongitude()/getGalacticLatitude()
//            (degrees) and `distance` from
//            isochroneService.getPlotParams().distance (kpc).
export function galaxyFaceOnOffset(galacticLongitude: number,
                                   galacticLatitude: number,
                                   distance: number): { delta_x: number, delta_y: number } {
  const l: number = rad(galacticLongitude);
  const b: number = rad(galacticLatitude);
  const d: number = distance * Math.cos(b) * 32; // one pixel is 32 kpc
  const delta_x: number = d * Math.sin(l);
  const delta_y: number = -d * Math.cos(l);
  return {delta_x, delta_y};
}

// EXTRACTED: was the tail of `draw()` in GalaxyEdgeonComponent. Same inputs.
//            The +-500 clamp keeps the marker on-canvas for high-|b| clusters.
export function galaxyEdgeOnOffset(galacticLongitude: number,
                                   galacticLatitude: number,
                                   distance: number): { delta_x: number, delta_y: number } {
  const l: number = rad(galacticLongitude);
  const b: number = rad(galacticLatitude);
  const d: number = distance * Math.cos(b);
  const delta_x: number = -d * Math.cos(l) * 32;
  let delta_y: number = distance * Math.sin(b) * 16;
  if (delta_y > 500)
    delta_y = 500;
  if (delta_y < -500)
    delta_y = -500;
  return {delta_x, delta_y};
}
