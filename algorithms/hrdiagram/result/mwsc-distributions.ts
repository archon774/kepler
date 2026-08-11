// EXTRACTED from astromancer:
//   src/app/tools/cluster/result/result-graphics/age/age.component.ts           (149 lines)
//   src/app/tools/cluster/result/result-graphics/distance/distance.component.ts (163 lines)
//   src/app/tools/cluster/result/result-graphics/metallicity/metallicity.component.ts (105 lines)
//   src/app/tools/cluster/result/result-graphics/reddening/reddening.component.ts    (105 lines)
//   src/app/tools/cluster/result/result-graphics/number-of-stars/number-of-stars.component.ts (111 lines)
//
// These five components each render one histogram of the whole Milky Way Star
// Cluster catalogue with the student's own cluster marked on it. ~90% of each
// file is a Highcharts options literal — titles, axis bounds, marker symbols,
// reference points (Sun, Big Bang, Magellanic Clouds, Galactic Centre) — plus
// a log-scale toggle. All of that is left behind.
//
// What each one does contain is a small ngOnChanges body that converts and
// clips the catalogue column before handing it to the histogram. Those are
// real data preparation and are lifted here, bodies unchanged.
//
// The unit conversions are load-bearing and easy to lose:
//   age       ClusterMWSC.age is log10(years); reported in Gyr.
//   distance  ClusterMWSC.distance is PARSECS; the tool's own fitted distance
//             (PlotParams.distance) is KILOPARSECS. This /1000 is the only
//             place the two meet.
//
// The clip windows match each chart's fixed x-axis bounds, which is why they
// are hard-coded rather than derived. They are catalogue-quality cuts in
// effect (they discard sentinel/no-value rows), so they are preserved as
// written rather than parameterised.
//
// Framework seams cut: @Component/@Input, Highcharts import + chartOptions +
// chartObject.series[n].setData, ClusterService.getClusterName() used as a
// series name, the `update$` Observable that re-marked the student's value,
// and DistanceComponent.toggleLogScale (axis type swap).

import {ClusterMWSC} from "../storage/cluster-storage.service.util";

// EXTRACTED: was AgeComponent.ngOnChanges (age.component.ts:124-137).
//            x-axis window in the chart was 0..13.8 Gyr; the same bounds are
//            the filter here, as in the original.
export function getMwscAgeDistribution(allClusters: ClusterMWSC[]): number[] {
  let ages: number[] = [];
  allClusters.forEach((cluster: ClusterMWSC) => {
    if (cluster.age !== null && cluster.age !== undefined) {
      const age = Math.pow(10, cluster.age) / 1000000;
      if (age > 0 && age < 13.8)
        ages.push(age);
    }
  });
  ages.sort((a, b) => a - b);
  return ages;
}

// EXTRACTED: was DistanceComponent.ngOnChanges (distance.component.ts:141-151).
//            NOTE the /1000: catalogue distances are parsecs, the chart (and
//            the tool's fitted distance) are kiloparsecs.
export function getMwscDistanceDistribution(allClusters: ClusterMWSC[]): number[] {
  let distance: number[] = [];
  allClusters.forEach((cluster: ClusterMWSC) => {
    if (cluster.distance > 0)
      distance.push(cluster.distance / 1000);
  });
  distance.sort((a, b) => a - b);
  return distance;
}

// EXTRACTED: was MetallicityComponent.ngOnChanges (metallicity.component.ts:84-95).
export function getMwscMetallicityDistribution(allClusters: ClusterMWSC[]): number[] {
  let metallicities: number[] = [];
  allClusters.forEach((cluster: ClusterMWSC) => {
    if (cluster.metallicity !== null && cluster.metallicity !== undefined
      && cluster.metallicity > -2.3 && cluster.metallicity < 0.8)
      metallicities.push(cluster.metallicity);
  });
  metallicities.sort((a, b) => a - b);
  return metallicities;
}

// EXTRACTED: was ReddeningComponent.ngOnChanges (reddening.component.ts:84-95).
export function getMwscReddeningDistribution(allClusters: ClusterMWSC[]): number[] {
  let reddening: number[] = [];
  allClusters.forEach((cluster: ClusterMWSC) => {
    if (cluster.e_bv !== null && cluster.e_bv !== undefined
      && cluster.e_bv >= 0 && cluster.e_bv <= 1)
      reddening.push(cluster.e_bv);
  });
  reddening.sort((a, b) => a - b);
  return reddening;
}

// EXTRACTED: was NumberOfStarsComponent.ngOnChanges (number-of-stars.component.ts:83-94).
//            The trailing slice is an asymmetric outlier trim (drops the
//            bottom 0.15% and top 0.015% of the sorted counts) — original,
//            preserved as written.
export function getMwscStarCountDistribution(allClusters: ClusterMWSC[]): number[] {
  let counts: number[] = [];
  allClusters.forEach((cluster: ClusterMWSC) => {
    if (cluster.num_cluster_stars && cluster.num_cluster_stars > 0)
      counts.push(cluster.num_cluster_stars);
  });
  counts.sort((a, b) => a - b);
  counts = counts.slice(Math.floor(0.0015 * counts.length), Math.ceil(0.99985 * counts.length))
  return counts;
}
