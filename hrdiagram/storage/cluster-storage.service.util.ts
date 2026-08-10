// EXTRACTED from astromancer:
//   src/app/tools/cluster/storage/cluster-storage.service.util.ts  (75 lines)
//
// Pure interface file — these are the data shapes the algorithm reads and
// writes. ClusterMWSC in particular is the Milky Way Star Cluster catalogue
// record (distance / metallicity / e_bv / age / radius / star counts) that the
// result stage compares the user's fit against. StarCount / StarCounts are the
// per-catalog cluster/field/unused tallies produced by
// ../photometry/cluster-data.service.util.ts::getStarCountsByFilter.
//
// Copied byte-for-byte apart from the two import seams below.
//
// Framework seams: none in the body (no Angular decorators here). The parent
// ClusterStorageService that consumed these shapes was localStorage
// persistence plumbing and is NOT extracted — see ../EXTRACTION.md. Its
// default-value block IS preserved, in
// ../isochrone-matching/cluster-isochrone.service.ts.

// EXTRACTED: import path only (../FSR/fsr.util -> ../fsr/fsr.util).
import {FsrParameters} from "../fsr/fsr.util";
import {IsochroneParams, PlotConfig, PlotParams} from "../cluster.util";

// EXTRACTED: was `import {ClusterLookUpData} from "../data-source/cluster-data-source.service.util"`.
//            ClusterLookUpData / ClusterLookUpStackImpl are the UI "recent
//            searches" LRU stack for the cluster name lookup box — UI history,
//            not algorithm. Left behind; aliased here to keep the shape valid.
type ClusterLookUpData = unknown;
// EXTRACTED: was `import {JobStorageObject} from "../../../shared/job/job"`.
//            Job is the Angular HttpClient async-polling wrapper around the
//            backend /cluster/catalog and /cluster/fsr endpoints. Left behind
//            (network plumbing); aliased here to keep the shape valid.
type JobStorageObject = unknown;


export interface ClusterStorageObject {
    step: number;
    name: string;
    dataSource: DataSourceStorageObject;
    isochrone: IsochroneStorageObject;
    fsrValues: fsrUserValues;
}

export interface DataSourceStorageObject {
    recentSearches: ClusterLookUpData[];
    dataJob: JobStorageObject | null;
    cluster: ClusterMWSC | null;
    starCounts: StarCounts | null;
}

export interface IsochroneStorageObject {
    plotConfigs: PlotConfig[];
    plotParams: PlotParams;
    isochroneParams: IsochroneParams;
    maxMagError: number;
}

export interface fsrUserValues {
    parameters: FsrParameters,
    framing: FsrParameters,
    bin: fsrHistogramBin,
}

export interface fsrHistogramBin {
    distance: number | null,
    pm_ra: number | null,
    pm_dec: number | null,
}

export interface ClusterMWSC {
    id: number;
    galactic_longitude: number;
    galactic_latitude: number;
    radius: number;
    num_cluster_stars: number;
    num_total_stars: number;
    num_APASS_stars: number;
    num_TWO_MASS_stars: number;
    num_WISE_stars: number;
    pm_ra: number;
    pm_dec: number;
    ra: number;
    dec: number;
    type: string;
    distance: number;
    metallicity: number;
    e_bv: number;
    age: number;
}

export interface StarCounts {
    "user": StarCount;
    "GAIA": StarCount;
    "APASS": StarCount;
    "TWO_MASS": StarCount;
    "WISE": StarCount;

}

export interface StarCount {
    cluster_stars: number;
    field_stars: number;
    unused_stars: number;
}
