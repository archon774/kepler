"""Isochrone grids: MIST (default, whole-grid download + cache), PARSEC
(per-request web form, fallback), and SPOTS (starspot-inflated pre-main-
sequence models, for young clusters where standard isochrones systematically
mismatch active, spotted stars).

All three write into isochrone_cache_dir() (below) -- a shared, persistent,
user-level cache distinct from a run's own output artifacts
(tools.config.artifact_directory): the MIST grid especially is a ~150MB
one-time download meant to be reused across every run and every project on
the machine, not per-run output. Deliberately not imported from
tools.config: algorithms/ doesn't depend on tools/ (see algorithms/wcs/config.py
for the same pattern -- a small algorithm-local, environment-backed setting,
not a shared tools.config import).
"""
from __future__ import annotations

import logging
import os
import re
import warnings
from pathlib import Path

import numpy as np
import requests

from algorithms.hrdiagram import hrfit
from algorithms.hrdiagram.phases import filter_excluded_phases

logger = logging.getLogger(__name__)

ISOCHRONE_CACHE_DIR_ENV = "KEPLER_ISOCHRONE_CACHE_DIR"


def isochrone_cache_dir(directory: str | Path | None = None) -> Path:
    """Resolve the shared, persistent isochrone-grid cache directory."""
    if directory is not None:
        return Path(directory).expanduser().resolve()
    configured = os.environ.get(ISOCHRONE_CACHE_DIR_ENV)
    if not configured:
        return (Path.home() / ".cache" / "kepler" / "isochrones").resolve()
    return Path(configured).expanduser().resolve()

# name -> PARSEC CMD "photsys_file" value, and the isochrone-file column names it
# produces. Only Gaia systems are wired up because gaia.crossmatch_gaia() is the
# only photometry source this module fetches automatically for the PARSEC path.
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

# MIST v1.2 synthetic-photometry isochrone grid (Choi et al. 2016; Dotter 2016),
# UBVRIplus system -- covers Johnson-Cousins (Bessell_*), 2MASS, and Gaia_*_EDR3
# passbands in one file. Unlike PARSEC_PHOTSYS above, this is not a per-request
# web form: the whole grid (all ages x all [Fe/H], one file per metallicity) is
# downloaded once and cached, then read locally from then on. See
# _ensure_mist_grid() for why this replaced PARSEC as the default.
MIST_TARBALL_URL = "https://mist.science/data/tarballs_v1.2/MIST_v1.2_vvcrit0.4_UBVRIplus.txz"
MIST_GRID_DIRNAME = "MIST_v1.2_vvcrit0.4_UBVRIplus"
MIST_FEHS = (-4.0, -3.5, -3.0, -2.5, -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5)
# Observed-band name -> MIST column name. fit.fit_and_compare() looks each of
# its blue/red/lum arguments up here, so the isochrone is always pulled from
# the same photometric system as the observed data -- e.g. fitting B/R/V
# Johnson-Cousins photometry against Gaia_BP/RP/G columns silently mismatches
# two different colour systems and produces a badly biased distance/reddening
# fit (~2x distance error observed on real NGC 1851 data before this was
# per-band).
MIST_FILTER_MAP = {
    "U": "Bessell_U", "B": "Bessell_B", "V": "Bessell_V", "R": "Bessell_R", "I": "Bessell_I",
    "J": "2MASS_J", "H": "2MASS_H", "K": "2MASS_Ks", "Ks": "2MASS_Ks",
    "G": "Gaia_G_EDR3", "BP": "Gaia_BP_EDR3", "RP": "Gaia_RP_EDR3",
    "Kp": "Kepler_Kp", "Kepler": "Kepler_Kp", "TESS": "TESS", "Hp": "Hipparcos_Hp",
}


def mist_iso_cols(blue: str, red: str, lum: str) -> dict[str, str]:
    try:
        return {"blue": MIST_FILTER_MAP[blue], "red": MIST_FILTER_MAP[red], "lum": MIST_FILTER_MAP[lum]}
    except KeyError as exc:
        raise ValueError(
            f"No MIST isochrone column known for filter {exc.args[0]!r}. Known filters: "
            f"{sorted(MIST_FILTER_MAP)}. Pass iso_path pointing at a table with your own "
            "column names if you need a filter not in this map."
        ) from exc


# ---------------------------------------------------------------------------
# PARSEC (stev.oapd.inaf.it/cmd) -- per-request web form, fallback
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
    hrfit.load_isochrone()-compatible file, caching it under
    isochrone_cache_dir().

    A single web request returns every age in [logage_center - half_width,
    logage_center + half_width] stepped by dlage, so fit.fit_and_compare() can
    scan ages without one request per age.
    """
    if photsys not in PARSEC_PHOTSYS:
        raise ValueError(f"Unknown photsys {photsys!r}; supported: {sorted(PARSEC_PHOTSYS)}")

    lo, hi = logage_center - logage_half_width, logage_center + logage_half_width
    step = dlage if logage_half_width > 0 else 0.0

    cache_path = Path(out_path) if out_path else isochrone_cache_dir() / (
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
            "requests. Retry in a bit, or pass fit.fit_and_compare(..., iso_path=...) with "
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
# MIST (mist.science) -- default; whole-grid download, then local
# ---------------------------------------------------------------------------
def _mist_feh_filename(feh: float) -> str:
    sign = "m" if feh < 0 else "p"
    return f"MIST_v1.2_feh_{sign}{abs(feh):.2f}_afe_p0.0_vvcrit0.4_UBVRIplus.iso.cmd"


def _ensure_mist_grid() -> Path:
    """Download (once) and extract the MIST v1.2 UBVRIplus grid; ~150MB total.

    fetch_parsec_isochrone_grid() scrapes a PARSEC web form per request, which
    turned out to rate-limit / reset connections under repeated use (see that
    function's retry logic). This downloads the whole precomputed grid -- every
    age, all 15 metallicities -- exactly once, so every call after the first is
    a local file read with nothing to fail.

    Not using the `isochrones` PyPI package's own MIST downloader here: its
    hardcoded bolometric-correction-table URL (waps.cfa.harvard.edu/MIST/BC_tables/
    {phot}.txz) 404s against MIST's current site layout, which reorganized
    BC_tables/ under v1/, v2/ subdirectories. The isochrone tarball URL used
    below is a different, still-live endpoint, unaffected by that.
    """
    cache_dir = isochrone_cache_dir()
    grid_dir = cache_dir / MIST_GRID_DIRNAME
    if grid_dir.exists() and any(grid_dir.glob("*.iso.cmd")):
        return grid_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    tarball_path = cache_dir / "MIST_v1.2_vvcrit0.4_UBVRIplus.txz"
    if not tarball_path.exists():
        logger.info("Downloading MIST isochrone grid (~150MB, one-time): %s", MIST_TARBALL_URL)
        with requests.get(MIST_TARBALL_URL, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            tmp_path = tarball_path.with_suffix(".txz.part")
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
            tmp_path.rename(tarball_path)

    import tarfile

    logger.info("Extracting MIST isochrone grid to %s", grid_dir)
    with tarfile.open(tarball_path, "r:xz") as tar:
        tar.extractall(cache_dir, filter="data")
    return grid_dir


def fetch_mist_isochrone(mh: float = 0.0) -> Path:
    """hrfit-compatible isochrone file (all ages, one metallicity nearest `mh`).

    The raw MIST file uses different age/metallicity column names than the
    PARSEC format hrfit.py was written against (`log10_isochrone_age_yr`,
    `[Fe/H]` instead of `logAge`, `MH`). Rather than touch hrfit.py -- it's
    meant to be a faithful, frozen reference implementation -- this writes a
    renamed copy once and caches it; hrfit.fit_cluster() re-reads iso_path
    from disk internally, so the renamed copy is what needs to exist on disk,
    not just an in-memory DataFrame.

    Also drops EAGB/TPAGB/post-AGB/WR rows here (see phases.PHASE_EXCLUDED):
    short-lived, sparsely sampled evolutionary phases that real cluster
    members essentially never populate, and that otherwise get drawn/fit as
    part of one continuous polyline through phases that aren't physically
    continuous with each other (see algorithms.hrdiagram.phases). MS, giant
    branch, and horizontal-branch (CHeB) rows are kept -- see
    phases.isochrone_cmd_with_breaks for how the plot avoids connecting those
    with a straight line across the real, physical jump at the He flash.
    """
    grid_dir = _ensure_mist_grid()
    feh = min(MIST_FEHS, key=lambda f: abs(f - mh))
    raw_path = grid_dir / _mist_feh_filename(feh)
    if not raw_path.exists():
        raise RuntimeError(f"Expected MIST isochrone file not found: {raw_path}")

    # v2: filters excluded phases (see docstring) -- distinct filename so a
    # cache written before that filter existed doesn't get silently reused.
    normalized_path = isochrone_cache_dir() / f"mist_feh{feh:+.2f}_v2_hrfit.dat"
    if not normalized_path.exists():
        df = hrfit.load_isochrone(raw_path)
        df = df.rename(columns={"log10_isochrone_age_yr": "logAge", "[Fe/H]": "MH"})
        df = filter_excluded_phases(df)
        with open(normalized_path, "w") as f:
            f.write("# " + " ".join(df.columns) + "\n")
            df.to_csv(f, sep=" ", index=False, header=False)
        logger.info("fetch_mist_isochrone: normalized feh=%.2f -> %s", feh, normalized_path)
    return normalized_path


# ---------------------------------------------------------------------------
# SPOTS (Somers, Pinsonneault & Cao 2019) -- starspot-inflated pre-main-
# sequence isochrones, for young clusters (~1 Myr - 4 Gyr) where magnetic
# starspots measurably inflate radii and cool effective temperatures. Standard
# isochrones (MIST, PARSEC) don't model this at all, which can bias fitted
# ages/distances for young, active clusters. Six files, one per starspot
# covering fraction (0%, 17%, ..., 85%); each spans the full age range, so
# unlike MIST's metallicity axis, Fspot has to be scanned like age is --
# see fit.spots_fit_and_compare (fit.py doesn't just pick a fixed Fspot the
# way it picks a fixed [Fe/H] for MIST, because there's no independent
# literature source for a cluster's spot-covering fraction the way Harris
# gives [Fe/H] for globulars).
# ---------------------------------------------------------------------------
SPOTS_CITATION = (
    "Somers, G., Pinsonneault, M. H. & Cao, L. (2019). The SPOTS Models: A "
    "Grid of Theoretical Stellar Evolution Tracks and Isochrones For Testing "
    "The Effects of Starspots on Structure and Colors (Version 1.0) "
    "[Dataset]. Zenodo. https://doi.org/10.5281/zenodo.3593339"
)
SPOTS_ZENODO_RECORD = "3593339"
SPOTS_FSPOTS = (0.0, 0.17, 0.34, 0.51, 0.68, 0.85)
# Single metallicity grid (no [Fe/H]/MH column at all) -- unlike MIST/PARSEC,
# there's no metallicity axis to pick from here; the isochrones are solar-only.
SPOTS_FILTER_MAP = {
    "B": "B_mag", "V": "V_mag", "R": "Rc_mag", "I": "Ic_mag",
    "J": "J_mag", "H": "H_mag", "K": "K_mag", "Ks": "K_mag",
    "W1": "W1_mag", "G": "G_mag", "BP": "BP_mag", "RP": "RP_mag",
}


def spots_iso_cols(blue: str, red: str, lum: str) -> dict[str, str]:
    try:
        return {"blue": SPOTS_FILTER_MAP[blue], "red": SPOTS_FILTER_MAP[red], "lum": SPOTS_FILTER_MAP[lum]}
    except KeyError as exc:
        raise ValueError(
            f"No SPOTS isochrone column known for filter {exc.args[0]!r}. Known filters: "
            f"{sorted(SPOTS_FILTER_MAP)}. Pass iso_path pointing at a table with your own "
            "column names if you need a filter not in this map."
        ) from exc


def _spots_filename(fspot: float) -> str:
    return f"f{round(fspot * 100):03d}.isoc"


def _ensure_spots_grid() -> Path:
    """Download (once) the six SPOTS isochrone files; ~2.9MB total, tiny next
    to MIST's ~150MB. Fetched individually from Zenodo's file-content API
    (stable, DOI-backed URLs; verified byte-identical to the dataset's own
    zip contents) rather than a single archive, since Zenodo serves each file
    at its own URL and there's no bundled isochrones-only zip.
    """
    grid_dir = isochrone_cache_dir() / "SPOTS_v1.0"
    if grid_dir.exists() and all((grid_dir / _spots_filename(f)).exists() for f in SPOTS_FSPOTS):
        return grid_dir

    grid_dir.mkdir(parents=True, exist_ok=True)
    for fspot in SPOTS_FSPOTS:
        filename = _spots_filename(fspot)
        dest = grid_dir / filename
        if dest.exists():
            continue
        url = f"https://zenodo.org/api/records/{SPOTS_ZENODO_RECORD}/files/{filename}/content"
        logger.info("Downloading SPOTS isochrone file (one-time): %s", url)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        tmp_path = dest.with_suffix(".isoc.part")
        tmp_path.write_bytes(resp.content)
        tmp_path.rename(dest)
    return grid_dir


def fetch_spots_isochrone(fspot: float) -> Path:
    """hrfit-compatible isochrone file (all ages, one starspot covering
    fraction nearest `fspot`).

    The raw file already uses hrfit.py's expected column name for age
    (`logAge`) and repeats its column-header comment once per age block --
    the same shape hrfit.load_isochrone() already handles for MIST/PARSEC, so
    no renaming is needed there. What does need fixing: colours outside the
    grid's calibrated range are written as the literal sentinel -99.0 (e.g. a
    very young, very low-mass star with no calibrated W1 colour yet) --
    left as-is, a -99.0 "magnitude" is bright enough to corrupt a nearest-
    isochrone-point cost search. hrfit._weighted_cost() already drops
    non-finite isochrone points (`np.isfinite(iso_colour) & np.isfinite(iso_mag)`),
    so replacing -99.0 with NaN here, once, is enough to make that existing
    guard take care of it -- written back out as the literal token "NaN" (not
    pandas' default blank field) so the whitespace-separated re-read doesn't
    lose column alignment on those rows.
    """
    grid_dir = _ensure_spots_grid()
    nearest = min(SPOTS_FSPOTS, key=lambda f: abs(f - fspot))
    raw_path = grid_dir / _spots_filename(nearest)
    if not raw_path.exists():
        raise RuntimeError(f"Expected SPOTS isochrone file not found: {raw_path}")

    normalized_path = isochrone_cache_dir() / f"spots_f{round(nearest * 100):03d}_hrfit.dat"
    if not normalized_path.exists():
        df = hrfit.load_isochrone(raw_path)
        mag_cols = [c for c in df.columns if c.endswith("_mag")]
        df[mag_cols] = df[mag_cols].replace(-99.0, np.nan)
        with open(normalized_path, "w") as f:
            f.write("# " + " ".join(df.columns) + "\n")
            df.to_csv(f, sep=" ", index=False, header=False, na_rep="NaN")
        logger.info("fetch_spots_isochrone: normalized fspot=%.2f -> %s", nearest, normalized_path)
    return normalized_path
