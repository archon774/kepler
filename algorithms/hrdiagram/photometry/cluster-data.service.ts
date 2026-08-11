// EXTRACTED from astromancer:
//   src/app/tools/cluster/cluster-data.service.ts  (408 lines; ~180
//   algorithmic lines carried over)
//
// ClusterDataService is the in-memory source catalogue that everything else
// reads from. Roughly half of it is genuine data-shaping algorithm and is
// preserved below verbatim; the other half is Angular HttpClient job
// orchestration, RxJS fan-out and localStorage persistence, and is cut.
//
// KEPT (bodies unchanged):
//   setSources            - drops sources with incomplete astrometry, drops
//                           NaN / unknown-filter photometry, and sorts each
//                           source's photometry by effective wavelength.
//   generateFilterList    - the union of filters present, wavelength-ordered.
//   setFSRCriteria        - applies the field-star cut (delegates to
//                           updateClusterFieldSources).
//   getDistance/getPmra/getPmdec/getRa/getDec
//                         - 2-dp rounded, ascending-sorted projections. The
//                           ascending sort is a precondition of the FSR
//                           histogram statistics and of the medians below.
//   getClusterRa/getClusterDec
//                         - the cluster centre, taken as the MEDIAN of member
//                           RA / Dec (note: an element-wise median of each
//                           coordinate independently, not a spherical mean).
//   get2DpmChartData      - member/field split in proper-motion space.
//   getInterfaceStarCounts- per-catalog cluster/field/unused tallies.
//   computeGalacticCoordinates - equatorial -> galactic for the cluster centre.
//
// CUT (see ../EXTRACTION.md for detail):
//   @Injectable, constructor DI, sourcesSubject / clusterSourcesSubject and
//   their observables, fetchCatalog / fetchFieldStarRemoval (Job polling),
//   getCatalogResults / getFSRResults (HttpClient GETs), initValues (job
//   replay from localStorage), downloadSources (DOM Blob download),
//   setCluster / setStarCounts persistence writes, reset.

// EXTRACTED: import paths only, plus the removal of @angular/core,
//            @angular/common/http, rxjs, ../../shared/job/job,
//            ../../../environments/environment, ./data-source/…,
//            ./storage/cluster-storage.service and ../shared/charts/utils.
import {
    APASS_FILTERS,
    Astrometry,
    FILTER,
    filterWavelength,
    GAIA_FILTERS,
    Source,
    TWO_MASS_FILTERS,
    WISE_FILTERS
} from "../cluster.util";
import {getStarCountsByFilter, updateClusterFieldSources} from "./cluster-data.service.util";
import {FsrParameters} from "../fsr/fsr.util";
import {ClusterMWSC, StarCounts} from "../storage/cluster-storage.service.util";
import {equatorial2Galactic} from "../result/result.utils";

// EXTRACTED: was `@Injectable() export class ClusterDataService`.
export class ClusterDataService {
    private sources: Source[] = []; // always sorted in ascending order by id
    private userSources: Source[] | null = null; // user uploaded photometry
    private cluster_sources: Source[] | null = [];
    private field_sources: Source[] | null = [];
    private filters: FILTER[] = [];
    private cluster: ClusterMWSC | null = null;
    private starCounts: StarCounts | null = null;
    private galacticLongitude: number | null = null;
    private galacticLatitude: number | null = null;

    // EXTRACTED: was `this.storageService.getFsrParams()` (ClusterStorageService,
    //            localStorage-backed). The FSR selection is now held here and
    //            written by setFSRCriteria, which is the only thing that ever
    //            changed it in the original.
    private fsrParams: FsrParameters = {distance: null, pm_ra: null, pm_dec: null};

    // EXTRACTED: was a constructor taking (HttpClient, ClusterDataSourceService,
    //            ClusterStorageService) and subscribing to
    //            dataSourceService.rawData$ to pull sources + filters after a
    //            file upload. Call setSources() directly instead.

    public getSources(isCluster: boolean = false): Source[] {
        if (isCluster && this.cluster_sources !== null)
            return this.cluster_sources!;
        return this.sources;
    }

    public setFSRCriteria(fsr: FsrParameters) {
        const result = updateClusterFieldSources(this.sources, fsr);
        this.cluster_sources = result.fsr;
        this.field_sources = result.not_fsr;
        // EXTRACTED: was this.clusterSourcesSubject.next(this.cluster_sources)
        //            (rxjs fan-out) and this.storageService.setFsrParams(fsr).
        this.fsrParams = fsr;
    }

    public getFsrParams(): FsrParameters {
        return this.fsrParams;
    }

    public getFilters(): FILTER[] {
        return this.filters;
    }

    public setSources(sources: Source[]) {
        this.sources = [];
        for (const source of sources) {
            if (source.fsr == null || source.fsr.distance == null || source.fsr.pm_ra == null || source.fsr.pm_dec == null)
                continue;
            source.photometries = source.photometries.filter((photometry) => {
                return (!isNaN(photometry.mag) && !isNaN(photometry.mag_error) && Object.values(FILTER).includes(photometry.filter));
            }).sort((a, b) => {
                return filterWavelength[a.filter] - filterWavelength[b.filter]
            });
            this.sources.push(source);
        }
        this.filters = this.generateFilterList();
        // EXTRACTED: was this.setFSRCriteria(this.storageService.getFsrParams()).
        this.setFSRCriteria(this.fsrParams);
        // EXTRACTED: was this.sourcesSubject.next(this.sources) (rxjs fan-out).
    }


    public syncUserPhotometry(jobId: number) {
        this.userSources = this.sources;
    }

    public getUserPhotometry(): Source[] | null {
        return this.userSources;
    }

    public setUserPhotometry(sources: Source[] | null) {
        // EXTRACTED: in astromancer `userSources` was assigned inside the
        //            HttpClient callbacks of getCatalogResults / getFSRResults
        //            (`this.userSources = resp['input_sources' | 'sources']`).
        //            Those network calls are cut; this setter is the seam.
        this.userSources = sources;
    }

    public getAstrometry(): { id: string, astrometry: Astrometry }[] {
        return this.sources.map((source) => {
            return {id: source.id, astrometry: source.astrometry, photometries: source.photometries};
        })
    }

    // in kparsec not parsec
    getDistance(full: boolean = false): (number)[] {
        const data = (full || this.cluster_sources == null) ? this.sources : this.cluster_sources;
        return data.filter(
            (source) => {
                return source.fsr !== null && source.fsr.distance !== null;
            }
        ).map((source) => {
            return parseFloat((source.fsr!.distance).toFixed(2));
        }).sort((a, b) => {
            return a - b;
        });
    }

    getPmra(full: boolean = false): number[] {
        const data = (full || this.cluster_sources == null) ? this.sources : this.cluster_sources;
        return data.filter(
            (source) => {
                return source.fsr !== null && source.fsr.pm_ra !== null;
            }
        ).map((source) => {
            return parseFloat((source.fsr!.pm_ra).toFixed(2));
        }).sort((a, b) => {
            return a - b;
        });
    }

    getPmdec(full: boolean = false): number[] {
        const data = (full || this.cluster_sources == null) ? this.sources : this.cluster_sources;
        return data.filter(
            (source) => {
                return source.fsr !== null && source.fsr.pm_dec !== null;
            }
        ).map((source) => {
            return parseFloat((source.fsr!.pm_dec).toFixed(2));
        }).sort((a, b) => {
            return a - b;
        });
    }

    get2DpmChartData(): { cluster: number[][], field: number[][] } {
        if (this.cluster_sources == null || this.field_sources == null)
            return {cluster: [], field: []};
        const cluster = this.cluster_sources.filter(
            (source) => {
                return source.fsr !== null && source.fsr.pm_ra !== null && source.fsr.pm_dec !== null;
            }
        ).map((source) => {
            return [source.fsr!.pm_ra, source.fsr!.pm_dec];
        });
        const field = this.field_sources.filter((source) => {
            return source.fsr !== null && source.fsr.pm_ra !== null && source.fsr.pm_dec !== null;
        }).map((source) => {
            return [source.fsr!.pm_ra, source.fsr!.pm_dec];
        });
        return {cluster: cluster, field: field};
    }

    getRa(full: boolean = false): number[] {
        const data = (full || this.cluster_sources == null) ? this.sources : this.cluster_sources;
        return data.filter(
            (source) => {
                return source.astrometry !== null && source.astrometry.ra !== null;
            }
        ).map((source) => {
            return parseFloat((source.astrometry!.ra).toFixed(2));
        }).sort((a, b) => {
            return a - b;
        });
    }

    getClusterRa(): number | null {
        const array = this.getRa();
        return array.length === 0 ? null : array[Math.floor(array.length / 2)];
    }

    getDec(full: boolean = false): number[] {
        const data = (full || this.cluster_sources == null) ? this.sources : this.cluster_sources;
        return data.filter(
            (source) => {
                return source.astrometry !== null && source.astrometry.dec !== null;
            }
        ).map((source) => {
            return parseFloat((source.astrometry!.dec).toFixed(2));
        }).sort((a, b) => {
            return a - b;
        });
    }

    getClusterDec(): number | null {
        const array = this.getDec();
        return array.length === 0 ? null : array[Math.floor(array.length / 2)];
    }

    getCluster(): ClusterMWSC | null {
        return this.cluster;
    }

    setCluster(cluster: ClusterMWSC) {
        // EXTRACTED: was `private setCluster` which also called
        //            this.storageService.setCluster(cluster). In astromancer it
        //            was fed from the /cluster/catalog and /cluster/fsr
        //            responses (`resp['cluster']`); made public here since the
        //            network layer is gone.
        this.cluster = cluster;
    }

    getStarCounts(): StarCounts | null {
        return this.starCounts;
    }

    setStarCounts(starCounts: StarCounts | null) {
        // EXTRACTED: was `private setStarCounts` + storageService persistence.
        //            Fed from `resp['star_counts']` of /cluster/catalog.
        this.starCounts = starCounts;
    }

    getInterfaceStarCounts() {
        const starCounts: any = {};
        if (this.getUserPhotometry() !== null) {
            // EXTRACTED: was this.storageService.getFsrParams().
            const userSources = updateClusterFieldSources(this.getUserPhotometry()!,
                this.fsrParams);
            starCounts['user'] = {
                field_stars: userSources.not_fsr.length,
                cluster_stars: userSources.fsr.length,
                unused_stars: 0,
            }
        }
        if (this.starCounts !== null && this.cluster !== null) {
            starCounts['GAIA'] = getStarCountsByFilter(
                this.cluster_sources!, this.field_sources!, GAIA_FILTERS,
                this.fsrParams, this.starCounts.GAIA, this.cluster.num_total_stars);
            starCounts['APASS'] = getStarCountsByFilter(
                this.cluster_sources!, this.field_sources!, APASS_FILTERS,
                this.fsrParams, this.starCounts.APASS, this.cluster.num_APASS_stars);
            starCounts['TWO_MASS'] = getStarCountsByFilter(
                this.cluster_sources!, this.field_sources!, TWO_MASS_FILTERS,
                this.fsrParams, this.starCounts.TWO_MASS, this.cluster.num_TWO_MASS_stars);
            starCounts['WISE'] = getStarCountsByFilter(
                this.cluster_sources!, this.field_sources!, WISE_FILTERS,
                this.fsrParams, this.starCounts.WISE, this.cluster.num_WISE_stars);
        }
        return starCounts;
    }

    public computeGalacticCoordinates(): { l: number, b: number } {
        if (this.cluster !== null) {
            const {l, b} = equatorial2Galactic(this.getClusterRa()!, this.getClusterDec()!);
            this.galacticLongitude = l;
            this.galacticLatitude = b;
        }
        return {l: this.galacticLongitude!, b: this.galacticLatitude!};
    }

    public getGalacticLongitude(): number | null {
        return this.galacticLongitude;
    }

    public getGalacticLatitude(): number | null {
        return this.galacticLatitude;
    }

    private generateFilterList(): FILTER[] {
        let filter_list: FILTER[] = [];
        this.sources.forEach((source) => {
            source.photometries.forEach((photometry: any) => {
                if (!filter_list.includes(photometry.filter)) {
                    filter_list.push(photometry.filter);
                }
            });
        });
        filter_list.sort((a, b) => {
            return filterWavelength[a] - filterWavelength[b];
        })
        return filter_list;
    }

}
