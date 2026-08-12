"""
hr_pipeline.py - end-to-end automation: FITS frame -> HR diagram -> literature comparison.

Chains together pieces that already exist in this repo:

    photometry/pipeline/   source extraction + aperture photometry on a FITS frame
    astroquery.gaia        multi-band (G, BP, RP) photometry for the matched sources
    astroquery.vizier      published cluster parameters (age, distance, E(B-V))
    stev.oapd.inaf.it/cmd  PARSEC isochrone grids, fetched on demand
    hrfit.py                the distance/reddening fit and the CMD/HR plot

A single FITS frame is one filter, which is not enough for a colour-magnitude
diagram on its own. The bridge is Gaia: sources detected in the frame are
matched by sky position to Gaia DR3, and Gaia's own G/BP/RP magnitudes (not
the frame's instrumental magnitude) are what gets fitted. The frame therefore
answers "which stars are actually in my image", and Gaia supplies the colour.

Pipeline:
    extract_photometry_from_fits   FITS -> detected sources (x, y, ra, dec, instrumental mag)
    crossmatch_gaia                detected sources -> + Gaia G, BP, RP, parallax, pm
    get_literature_cluster_params  cluster name -> published age/distance/E(B-V) (Vizier)
    select_cluster_members         Gaia photometry -> field stars removed (parallax + PM cut)
    fetch_parsec_isochrone_grid    literature age -> a PARSEC isochrone track (or grid of ages)
    fit_and_compare                hrfit fit vs. the literature values, CMD plot
    run_hr_diagram_pipeline        the above, chained, for a single call
"""
from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import requests
from astropy.io import fits
from scipy.spatial import cKDTree

import hrfit
from kepler.photometry.pipeline.photometry import perform_photometry
from kepler.photometry.pipeline.schemas import PhotometrySettings, SourceExtractionSettings
from kepler.photometry.pipeline.source_extraction import build_wcs_from_header
from kepler.wcs.state import ProcessingRun

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "isochrone_cache"

# Vizier catalog of Gaia-DR2-based open-cluster parameters (Cantat-Gaudin & Anders
# 2020, A&A 640, A1). Chosen over WEBDA because it is queryable through astroquery
# without HTML scraping and its distance/age/extinction are on the same Gaia
# astrometric footing as the crossmatch photometry used here.
CLUSTER_CATALOG = "J/A+A/640/A1/table1"
CLUSTER_CATALOG_CITATION = "Cantat-Gaudin & Anders 2020, A&A 640, A1 (VizieR J/A+A/640/A1)"

# name -> PARSEC CMD "photsys_file" value, and the isochrone-file column names it
# produces. Only Gaia systems are wired up because crossmatch_gaia() is the only
# photometry source this module fetches automatically.
PARSEC_PHOTSYS = {
    "gaiaEDR3": {
        "photsys_file": "YBC_tab_mag_odfnew/tab_mag_gaiaEDR3.dat",
        "blue": "G_BPmag",
        "red": "G_RPmag",
        "lum": "Gmag",
    },
    "gaiaDR2": {
        "photsys_file": "YBC_tab_mag_odfnew/tab_mag_gaiaDR2.dat",
        "blue": "G_BPmag",
        "red": "G_RPmag",
        "lum": "Gmag",
    },
}


# ---------------------------------------------------------------------------
# 1. FITS -> detected sources (instrumental photometry)
# ---------------------------------------------------------------------------
def extract_photometry_from_fits(
    fits_path: str,
    hdu_index: int = 0,
    threshold: float = 2.5,
    extraction_settings: SourceExtractionSettings | None = None,
    photometry_settings: PhotometrySettings | None = None,
) -> pd.DataFrame:
    """Detect sources in a FITS frame and measure instrumental photometry.

    Requires a celestial WCS already present in the header (from plate-solved
    data). This module does not invoke the astrometry.net/ATLAS solver in
    wcs/wcs.py -- that needs local index files most setups won't have. If the
    header has no WCS, re-solve the frame first (see wcs.wcs.solve_wcs) or
    supply ra_deg/dec_deg some other way.

    Returns a DataFrame with columns: x, y, ra_deg, dec_deg, inst_mag,
    inst_mag_err, flux, filter.
    """
    with fits.open(fits_path) as hdul:
        header = hdul[hdu_index].header
        data = np.asarray(hdul[hdu_index].data, dtype=np.float64)

    if build_wcs_from_header(header) is None:
        raise ValueError(
            f"{fits_path!r} has no celestial WCS in its header. Plate-solve the "
            "frame first; this module only measures photometry, it does not solve "
            "astrometry."
        )

    extraction_settings = extraction_settings or SourceExtractionSettings(threshold=threshold)
    # "auto" (Kron-like, sized from each source's own detected FWHM) rather than
    # "aperture" (default mode, but requires an aperture radius the caller would
    # otherwise have to know in advance).
    photometry_settings = photometry_settings or PhotometrySettings(mode="auto")

    # SourceExtractionData.file_id is typed int|None (it's just a log label), so
    # derive a stable small int from the path rather than passing the path itself.
    processing_run = ProcessingRun(observation_asset_id=abs(hash(str(fits_path))) % 10**8)
    results = perform_photometry(
        processing_run,
        header,
        data,
        settings=photometry_settings,
        extraction_settings=extraction_settings,
    )

    if not results:
        raise RuntimeError(f"No sources detected/measured in {fits_path!r}")

    rows = [
        {
            "x": r.x,
            "y": r.y,
            "ra_deg": (r.ra_hours * 15.0) if r.ra_hours is not None else None,
            "dec_deg": r.dec_degs,
            "inst_mag": r.mag,
            "inst_mag_err": r.mag_error,
            "flux": r.flux,
            "filter": r.filter,
        }
        for r in results
    ]
    df = pd.DataFrame(rows).dropna(subset=["ra_deg", "dec_deg"]).reset_index(drop=True)
    logger.info("extract_photometry_from_fits: %d sources with sky coordinates", len(df))
    return df


# ---------------------------------------------------------------------------
# 2. Detected sources -> Gaia DR3 multi-band photometry
# ---------------------------------------------------------------------------
def _flat_sky_xy(ra_deg: np.ndarray, dec_deg: np.ndarray, ra0_deg: float, dec0_deg: float) -> np.ndarray:
    """Small-field flat-sky projection in arcsec, for KD-tree matching."""
    cos_dec0 = np.cos(np.deg2rad(dec0_deg))
    x = (ra_deg - ra0_deg) * cos_dec0 * 3600.0
    y = (dec_deg - dec0_deg) * 3600.0
    return np.column_stack([x, y])


def crossmatch_gaia(
    sources: pd.DataFrame,
    radius_arcsec: float = 2.0,
    mag_limit: float = 20.0,
) -> pd.DataFrame:
    """Match detected sources to Gaia DR3 by sky position and attach G/BP/RP.

    One cone query covers the frame's whole footprint (padded), then each
    detected source is matched to its nearest Gaia neighbour within
    `radius_arcsec` (mutual nearest-neighbour, same approach as
    fieldcal/field_cal.py's angular matching).
    """
    from astroquery.gaia import Gaia

    ra0 = float(sources["ra_deg"].mean())
    dec0 = float(sources["dec_deg"].mean())
    cos_dec0 = max(0.2, abs(np.cos(np.deg2rad(dec0))))
    half_diag_deg = float(
        np.hypot(
            (sources["ra_deg"].max() - sources["ra_deg"].min()) * cos_dec0,
            sources["dec_deg"].max() - sources["dec_deg"].min(),
        )
    ) / 2.0
    radius_deg = half_diag_deg + radius_arcsec / 3600.0 + 0.02  # pad for match tolerance + safety margin

    adql = f"""
        SELECT source_id, ra, dec, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag,
               phot_g_mean_flux_over_error, phot_bp_mean_flux_over_error, phot_rp_mean_flux_over_error,
               parallax, parallax_error, pmra, pmdec, pmra_error, pmdec_error
        FROM gaiadr3.gaia_source
        WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra0}, {dec0}, {radius_deg}))
          AND phot_g_mean_mag < {mag_limit}
          AND phot_bp_mean_mag IS NOT NULL AND phot_rp_mean_mag IS NOT NULL
    """
    gaia = Gaia.launch_job(adql).get_results().to_pandas()
    if gaia.empty:
        raise RuntimeError(
            f"No Gaia DR3 sources brighter than G={mag_limit} within {radius_deg * 3600:.0f}\" "
            f"of RA={ra0:.4f} Dec={dec0:.4f}"
        )

    det_xy = _flat_sky_xy(sources["ra_deg"].to_numpy(), sources["dec_deg"].to_numpy(), ra0, dec0)
    gaia_xy = _flat_sky_xy(gaia["ra"].to_numpy(), gaia["dec"].to_numpy(), ra0, dec0)
    det_tree = cKDTree(det_xy)
    gaia_tree = cKDTree(gaia_xy)

    matched_rows = []
    for i, det_pt in enumerate(det_xy):
        j = gaia_tree.query(det_pt, distance_upper_bound=radius_arcsec)[1]
        if j >= len(gaia):
            continue
        # mutual nearest-neighbour: the matched Gaia source's nearest detection must be this one
        back = det_tree.query(gaia_xy[j], distance_upper_bound=radius_arcsec)[1]
        if back != i:
            continue
        row = sources.iloc[i].to_dict()
        g = gaia.iloc[j]
        row.update(
            {
                "gaia_source_id": int(g["source_id"]),
                "G": float(g["phot_g_mean_mag"]),
                "BP": float(g["phot_bp_mean_mag"]),
                "RP": float(g["phot_rp_mean_mag"]),
                "G_err": 1.0857 / float(g["phot_g_mean_flux_over_error"]) if g["phot_g_mean_flux_over_error"] else np.nan,
                "BP_err": 1.0857 / float(g["phot_bp_mean_flux_over_error"]) if g["phot_bp_mean_flux_over_error"] else np.nan,
                "RP_err": 1.0857 / float(g["phot_rp_mean_flux_over_error"]) if g["phot_rp_mean_flux_over_error"] else np.nan,
                "parallax": float(g["parallax"]) if pd.notna(g["parallax"]) else np.nan,
                "parallax_error": float(g["parallax_error"]) if pd.notna(g["parallax_error"]) else np.nan,
                "pmra": float(g["pmra"]) if pd.notna(g["pmra"]) else np.nan,
                "pmdec": float(g["pmdec"]) if pd.notna(g["pmdec"]) else np.nan,
                "sep_arcsec": float(np.hypot(*(det_pt - gaia_xy[j]))),
            }
        )
        matched_rows.append(row)

    if not matched_rows:
        raise RuntimeError(
            f"None of the {len(sources)} detected sources matched a Gaia source within "
            f"{radius_arcsec}\". Check the frame's WCS, or widen radius_arcsec."
        )

    df = pd.DataFrame(matched_rows)
    logger.info("crossmatch_gaia: matched %d / %d detected sources", len(df), len(sources))
    return df


# ---------------------------------------------------------------------------
# 3. Cluster name -> published parameters
# ---------------------------------------------------------------------------
def resolve_cluster_name(name: str) -> str:
    """Return a Vizier-J/A+A/640/A1-style designation ("NGC_2168") for a cluster name.

    Tries the name itself first (whitespace collapsed to a single underscore),
    then falls back to SIMBAD's alias list (e.g. "M35" -> "NGC 2168") and tries
    each alias in turn.
    """
    from astroquery.vizier import Vizier
    from astroquery.simbad import Simbad

    def normalize(raw: str) -> str:
        return re.sub(r"\s+", "_", raw.strip())

    vizier = Vizier(columns=["Cluster"])
    vizier.ROW_LIMIT = 1

    candidates = [normalize(name)]
    try:
        ids = Simbad.query_objectids(name)
        if ids is not None:
            candidates += [normalize(str(row[0])) for row in ids]
    except Exception:
        logger.warning("resolve_cluster_name: SIMBAD alias lookup failed for %r", name, exc_info=True)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            result = vizier.query_constraints(catalog=CLUSTER_CATALOG, Cluster=candidate)
        except Exception:
            continue
        if result:
            return candidate

    raise ValueError(
        f"Could not find {name!r} (tried: {', '.join(sorted(seen))}) in {CLUSTER_CATALOG}. "
        "The catalog covers ~2000 nearby open clusters; if this one isn't in it, supply "
        "literature parameters manually instead of calling get_literature_cluster_params()."
    )


def get_literature_cluster_params(name: str) -> dict[str, Any]:
    """Published age / distance / reddening for a named open cluster.

    Source: Cantat-Gaudin & Anders (2020), a Gaia-DR2 based re-derivation for
    ~2000 clusters -- chosen so distance and reddening are on the same Gaia
    astrometric footing as crossmatch_gaia()'s photometry.
    """
    from astroquery.vizier import Vizier

    resolved = resolve_cluster_name(name)
    vizier = Vizier(columns=["Cluster", "RA_ICRS", "DE_ICRS", "plx", "pmRA*", "pmDE", "AgeNN", "AVNN", "DMNN", "DistPc"])
    vizier.ROW_LIMIT = 1
    result = vizier.query_constraints(catalog=CLUSTER_CATALOG, Cluster=resolved)
    if not result:
        raise ValueError(f"{resolved!r} resolved but no longer matched {CLUSTER_CATALOG}")
    row = result[0][0]

    log_age = float(row["AgeNN"])
    av = float(row["AVNN"])
    ebv = av / 3.1  # Rv=3.1, matching hrfit.get_extinction's default
    distance_pc = float(row["DistPc"])

    return {
        "cluster": name,
        "resolved_name": resolved,
        "ra_deg": float(row["RA_ICRS"]),
        "dec_deg": float(row["DE_ICRS"]),
        "parallax_mas": float(row["plx"]),
        "pmra_mas_yr": float(row["pmRA*"]),
        "pmdec_mas_yr": float(row["pmDE"]),
        "log_age": log_age,
        "age_myr": 10.0 ** log_age / 1.0e6,
        "av": av,
        "ebv": ebv,
        "distance_pc": distance_pc,
        "distance_kpc": distance_pc / 1000.0,
        "distance_modulus": float(row["DMNN"]),
        "source": CLUSTER_CATALOG_CITATION,
    }


# ---------------------------------------------------------------------------
# 4. Field-star removal (parallax + proper-motion cut)
# ---------------------------------------------------------------------------
def select_cluster_members(
    gaia_matched: pd.DataFrame,
    literature: Mapping[str, Any],
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
) -> pd.DataFrame:
    """Keep sources consistent with the cluster's parallax and proper motion.

    This is a simplified stand-in for the elliptical (pm_ra, pm_dec) region
    intersected with a distance interval that Astromancer's field-star-removal
    module uses (hrdiagram/fsr/) -- an isotropic circular cut in proper motion
    plus a parallax window, rather than a fitted ellipse. Good enough to clear
    obvious field-star contamination; adjust plx_sigma / pm_tol_mas_yr, or port
    the elliptical FSR from hrdiagram/fsr/cmd-fsr.util.ts, for tighter work.
    """
    df = gaia_matched.dropna(subset=["parallax", "parallax_error", "pmra", "pmdec"]).copy()

    plx_tol = np.maximum(plx_sigma * df["parallax_error"].to_numpy(), 0.05)
    plx_ok = np.abs(df["parallax"].to_numpy() - literature["parallax_mas"]) <= plx_tol

    pm_sep = np.hypot(
        df["pmra"].to_numpy() - literature["pmra_mas_yr"],
        df["pmdec"].to_numpy() - literature["pmdec_mas_yr"],
    )
    pm_ok = pm_sep <= pm_tol_mas_yr

    members = df[plx_ok & pm_ok].reset_index(drop=True)
    logger.info(
        "select_cluster_members: %d / %d sources kept as cluster members (plx_sigma=%s, pm_tol=%s mas/yr)",
        len(members), len(df), plx_sigma, pm_tol_mas_yr,
    )
    if members.empty:
        raise RuntimeError(
            "No sources survived the parallax/proper-motion membership cut. Widen "
            "plx_sigma / pm_tol_mas_yr, or check that get_literature_cluster_params() "
            "resolved the intended cluster."
        )
    return members


# ---------------------------------------------------------------------------
# 5. PARSEC isochrone fetch (stev.oapd.inaf.it/cmd)
# ---------------------------------------------------------------------------
def _parsec_post(url: str, form: dict[str, str], timeout: float):
    """POST the CMD form, retrying once without TLS verification.

    stev.oapd.inaf.it serves an incomplete intermediate certificate chain as of
    2026; astropy/requests reject it by default. Public, non-sensitive isochrone
    data only -- if this starts erroring elsewhere too, remove the fallback.
    """
    files = {k: (None, str(v)) for k, v in form.items()}
    try:
        return requests.post(url, files=files, timeout=timeout)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        logger.warning("PARSEC CMD service: TLS verification failed, retrying without it (%s)", url)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return requests.post(url, files=files, timeout=timeout, verify=False)


def fetch_parsec_isochrone_grid(
    logage_center: float,
    logage_half_width: float = 0.0,
    dlage: float = 0.05,
    mh: float = 0.0,
    photsys: str = "gaiaEDR3",
    out_path: str | Path | None = None,
    timeout: float = 90.0,
) -> Path:
    """Fetch a PARSEC isochrone (or a grid of ages around logage_center) as a
    hrfit.load_isochrone()-compatible file, caching it under isochrone_cache/.

    A single web request returns every age in [logage_center - half_width,
    logage_center + half_width] stepped by dlage, so fit_and_compare() can scan
    ages without one request per age.
    """
    if photsys not in PARSEC_PHOTSYS:
        raise ValueError(f"Unknown photsys {photsys!r}; supported: {sorted(PARSEC_PHOTSYS)}")

    lo, hi = logage_center - logage_half_width, logage_center + logage_half_width
    step = dlage if logage_half_width > 0 else 0.0

    cache_path = Path(out_path) if out_path else CACHE_DIR / (
        f"{photsys}_logage{lo:.2f}-{hi:.2f}_step{step:.3f}_mh{mh:+.2f}.dat"
    )
    if cache_path.exists():
        logger.info("fetch_parsec_isochrone_grid: using cached %s", cache_path)
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _fetch_parsec_isochrone_grid_impl(lo, hi, step, mh, photsys, cache_path, timeout)
    except (requests.exceptions.RequestException, RuntimeError) as exc:
        raise RuntimeError(
            f"Could not fetch a PARSEC isochrone from stev.oapd.inaf.it ({exc}). This "
            "academic service is occasionally unreachable or rate-limits repeated "
            "requests. Retry in a bit, or pass fit_and_compare(..., iso_path=...) with "
            "an isochrone table you downloaded by hand from "
            "http://stev.oapd.inaf.it/cgi-bin/cmd (hrfit.load_isochrone() expects the "
            "same PARSEC .dat format)."
        ) from exc
    logger.info(
        "fetch_parsec_isochrone_grid: fetched logAge=[%.2f, %.2f] step=%.3f mh=%.2f -> %s",
        lo, hi, step, mh, cache_path,
    )
    return cache_path


def _fetch_parsec_isochrone_grid_impl(
    lo: float, hi: float, step: float, mh: float, photsys: str, cache_path: Path, timeout: float,
) -> None:
    import gzip
    import time

    base = "https://stev.oapd.inaf.it/cgi-bin/cmd"

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            html = _get_with_fallback(base, timeout).text
            break
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(3.0 * (attempt + 1))
    else:
        raise last_exc

    form: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]*type="(hidden|text)"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html):
        form[m.group(2)] = m.group(3)
    for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"[^>]*checked', html):
        form[m.group(1)] = m.group(2)
    for m in re.finditer(r'<select[^>]*name="([^"]+)".*?</select>', html, re.S):
        sel = re.search(r'<option selected[^>]*value="([^"]*)"', m.group(0))
        if sel:
            form[m.group(1)] = sel.group(1)

    action = re.search(r'<form[^>]*action="([^"]+)"', html)
    if not action:
        raise RuntimeError("Could not find the PARSEC CMD form action; the service's page layout may have changed")
    post_url = requests.compat.urljoin(base + "/", action.group(1))

    form.update(
        {
            "isoc_isagelog": "1",
            "isoc_lagelow": f"{lo:.4f}",
            "isoc_lageupp": f"{hi:.4f}",
            "isoc_dlage": f"{step:.4f}",
            "isoc_ismetlog": "1",
            "isoc_metlow": f"{mh:.4f}",
            "isoc_metupp": f"{mh:.4f}",
            "isoc_dmet": "0.0",
            "photsys_file": PARSEC_PHOTSYS[photsys]["photsys_file"],
            "output_kind": "0",
            "output_gzip": "1",
            "submit_form": "Submit",
        }
    )

    resp = _parsec_post(post_url, form, timeout)
    link = re.search(r'href=[\'"](\.\./tmp/output[^\'"]+\.dat\.gz)[\'"]', resp.text)
    if not link:
        raise RuntimeError(
            "PARSEC CMD service did not return an isochrone download link. It may be "
            "down, or the requested age/metallicity is outside its grid. Response "
            f"excerpt: {resp.text[-500:]!r}"
        )
    data_url = requests.compat.urljoin(post_url, link.group(1))

    try:
        data_resp = requests.get(data_url, timeout=timeout)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data_resp = requests.get(data_url, timeout=timeout, verify=False)
    cache_path.write_bytes(gzip.decompress(data_resp.content))


def _get_with_fallback(url: str, timeout: float):
    try:
        return requests.get(url, timeout=timeout)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        logger.warning("PARSEC CMD service: TLS verification failed, retrying without it (%s)", url)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return requests.get(url, timeout=timeout, verify=False)


# ---------------------------------------------------------------------------
# 6. Fit distance/reddening/age, compare to literature, plot
# ---------------------------------------------------------------------------
def fit_and_compare(
    members: pd.DataFrame,
    literature: Mapping[str, Any],
    cluster_name: str,
    blue: str = "BP",
    red: str = "RP",
    lum: str = "G",
    max_error: float = 0.1,
    logage_half_width: float = 0.3,
    dlage: float = 0.05,
    mh: float = 0.0,
    iso_path: str | Path | None = None,
    photsys: str = "gaiaEDR3",
    out_png: str | Path | None = None,
) -> dict[str, Any]:
    """Fit distance/E(B-V)/age to `members` against a PARSEC isochrone grid
    centred on the literature age, and compare the fit to the literature.

    `mh` is the isochrone grid's metallicity ([M/H], solar=0.0). The literature
    source used here (Cantat-Gaudin & Anders 2020) does not publish per-cluster
    metallicity, so this defaults to solar; override it if you have a better
    estimate for the target cluster.
    """
    if iso_path is None:
        iso_path = fetch_parsec_isochrone_grid(
            literature["log_age"],
            logage_half_width=logage_half_width,
            dlage=dlage,
            mh=mh,
            photsys=photsys,
        )
    iso_cols = PARSEC_PHOTSYS[photsys]

    csv_path = CACHE_DIR / f"_members_{re.sub(r'[^A-Za-z0-9]+', '_', cluster_name)}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    members.to_csv(csv_path, index=False)

    iso_all = hrfit.load_isochrone(iso_path)
    logages = sorted(np.unique(iso_all["logAge"].values))

    result = hrfit.fit_cluster(
        csv_path, iso_path, blue, red, lum,
        iso_cols["blue"], iso_cols["red"], iso_cols["lum"],
        logages=logages, max_error=max_error,
        x0=(literature["distance_kpc"], literature["ebv"]),
    )
    best = result["best"]

    fitted = {
        "distance_kpc": best["distance_kpc"],
        "ebv": best["ebv"],
        "log_age": best["logage"],
        "age_myr": 10.0 ** best["logage"] / 1.0e6,
        "n_stars_fitted": result["n_stars"],
        "reduced_cost": best["reduced_cost"],
    }
    comparison = {
        "distance_pct_diff": 100.0 * (fitted["distance_kpc"] - literature["distance_kpc"]) / literature["distance_kpc"],
        "ebv_diff": fitted["ebv"] - literature["ebv"],
        "age_pct_diff": 100.0 * (fitted["age_myr"] - literature["age_myr"]) / literature["age_myr"],
    }

    df = hrfit.load_photometry(csv_path, blue, red, lum, max_error=max_error)
    colour, mag = hrfit.to_absolute_cmd(df, blue, red, lum, fitted["distance_kpc"], fitted["ebv"])
    iso_sel = hrfit.select_isochrone(iso_all, fitted["log_age"])
    iso_colour, iso_mag = hrfit.isochrone_cmd(iso_sel, iso_cols["blue"], iso_cols["red"], iso_cols["lum"])

    out_png = Path(out_png) if out_png else CACHE_DIR / f"_hr_{re.sub(r'[^A-Za-z0-9]+', '_', cluster_name)}.png"
    import matplotlib
    matplotlib.use("Agg")
    ax = hrfit.plot_cmd(
        colour, mag, iso_colour, iso_mag,
        xlabel=f"({blue} - {red})$_0$", ylabel=f"M$_{{{lum}}}$",
        title=f"{cluster_name}\n"
              f"fit: d={fitted['distance_kpc']:.2f} kpc, E(B-V)={fitted['ebv']:.2f}, age={fitted['age_myr']:.0f} Myr\n"
              f"lit: d={literature['distance_kpc']:.2f} kpc, E(B-V)={literature['ebv']:.2f}, age={literature['age_myr']:.0f} Myr",
    )
    ax.set_title(ax.get_title(), fontsize=10)
    ax.figure.tight_layout()
    ax.figure.savefig(out_png, dpi=130)

    return {
        "cluster": cluster_name,
        "fitted": fitted,
        "literature": dict(literature),
        "comparison": comparison,
        "png_path": str(out_png),
        "isochrone_path": str(iso_path),
        "members_csv_path": str(csv_path),
    }


# ---------------------------------------------------------------------------
# 7. Composite entry point
# ---------------------------------------------------------------------------
def run_hr_diagram_pipeline(
    fits_path: str,
    cluster_name: str,
    gaia_match_radius_arcsec: float = 2.0,
    gaia_mag_limit: float = 20.0,
    plx_sigma: float = 3.0,
    pm_tol_mas_yr: float = 1.0,
    max_error: float = 0.1,
) -> dict[str, Any]:
    """FITS frame + cluster name -> HR diagram, fitted vs. literature parameters.

    Chains extract_photometry_from_fits -> crossmatch_gaia ->
    get_literature_cluster_params -> select_cluster_members -> fit_and_compare.
    """
    detected = extract_photometry_from_fits(fits_path)
    matched = crossmatch_gaia(detected, radius_arcsec=gaia_match_radius_arcsec, mag_limit=gaia_mag_limit)
    literature = get_literature_cluster_params(cluster_name)
    members = select_cluster_members(matched, literature, plx_sigma=plx_sigma, pm_tol_mas_yr=pm_tol_mas_yr)
    report = fit_and_compare(members, literature, cluster_name, max_error=max_error)
    report["n_detected"] = len(detected)
    report["n_gaia_matched"] = len(matched)
    report["n_members"] = len(members)
    return report
