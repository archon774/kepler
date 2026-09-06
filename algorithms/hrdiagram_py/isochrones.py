"""algorithms.hrdiagram_py.isochrones - PARSEC isochrone fetch, fit, and comparison.

The one network call this package still makes directly: stev.oapd.inaf.it's
PARSEC CMD service has no existing Kepler tool wrapping it (unlike Gaia/VizieR
cluster-parameter lookups, which route through ``tools.vizier.search_vizier``
one layer up -- see ``matching.py`` and ``literature.py``), so there is
nothing to reuse here.

Output paths (the members CSV ``hrfit`` reads back, and the HR-diagram PNG)
are always caller-supplied, not computed here -- callers in ``tools/`` decide
where results land (``artifacts/hrdiagram/``, matching every other tool's
``subdir=`` convention); this package stays ignorant of that layout.
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

from algorithms.hrdiagram_py import hrfit

__all__ = [
    "PARSEC_PHOTSYS",
    "fetch_parsec_isochrone_grid",
    "fit_and_compare",
]

logger = logging.getLogger(__name__)

#: PARSEC isochrone download cache -- a reference-data cache, not a per-call
#: result artifact, so it stays outside the artifacts/ convention (see
#: .gitignore's isochrone_cache/ entry).
CACHE_DIR = Path("isochrone_cache")

# name -> PARSEC CMD "photsys_file" value, and the isochrone-file column names it
# produces. Only Gaia systems are wired up because match_sources_to_gaia() is the
# only photometry source this package fetches automatically.
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
# PARSEC isochrone fetch (stev.oapd.inaf.it/cmd)
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
    # Confirmed live 2026-08-12: the completed-job page emits this link with an
    # UNQUOTED href (`href=../tmp/output....dat.gz>`), not `href="...">` --
    # requiring a quote here made every fetch fail with "no download link".
    link = re.search(r'href=[\'"]?(\.\./tmp/output[^\'">\s]+\.dat\.gz)[\'"]?', resp.text)
    if not link:
        raise RuntimeError(
            "PARSEC CMD service did not return an isochrone download link. It may be "
            "down, or the requested age/metallicity is outside its grid. Response "
            f"excerpt: {resp.text[-500:]!r}"
        )
    # Confirmed live 2026-08-12: the relative link is one directory level
    # shallower than `post_url` (the form's own POST target) implies -- it
    # must resolve against `base` (the original GET URL) or the request 404s.
    data_url = requests.compat.urljoin(base, link.group(1))

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
# Fit distance/reddening/age, compare to literature, plot
# ---------------------------------------------------------------------------
def fit_and_compare(
    members: pd.DataFrame,
    literature: Mapping[str, Any],
    cluster_name: str,
    *,
    members_csv_path: str | Path,
    out_png: str | Path,
    blue: str = "BP",
    red: str = "RP",
    lum: str = "G",
    max_error: float = 0.1,
    logage_half_width: float = 0.3,
    dlage: float = 0.05,
    mh: float = 0.0,
    iso_path: str | Path | None = None,
    photsys: str = "gaiaEDR3",
) -> dict[str, Any]:
    """Fit distance/E(B-V)/age to `members` against a PARSEC isochrone grid
    centred on the literature age, and compare the fit to the literature.

    `mh` is the isochrone grid's metallicity ([M/H], solar=0.0). The literature
    source used here (Cantat-Gaudin & Anders 2020) does not publish per-cluster
    metallicity, so this defaults to solar; override it if you have a better
    estimate for the target cluster.

    ``members_csv_path`` and ``out_png`` are always caller-supplied -- this
    function does not choose where its outputs live.
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

    members_csv_path = Path(members_csv_path)
    members_csv_path.parent.mkdir(parents=True, exist_ok=True)
    members.to_csv(members_csv_path, index=False)

    iso_all = hrfit.load_isochrone(iso_path)
    logages = sorted(np.unique(iso_all["logAge"].values))

    result = hrfit.fit_cluster(
        members_csv_path, iso_path, blue, red, lum,
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
        # hrfit.fit_distance_reddening uses Nelder-Mead (derivative-free), which
        # gives a point estimate and no covariance/Hessian -- there is no
        # formal parameter uncertainty to report here, ever, for any cluster.
        # Do not infer a precision from reduced_cost; it is a fit-quality
        # score, not related to parameter uncertainty in distance/ebv/age.
        "parameter_uncertainty": None,
    }
    comparison = {
        "distance_pct_diff": 100.0 * (fitted["distance_kpc"] - literature["distance_kpc"]) / literature["distance_kpc"],
        "ebv_diff": fitted["ebv"] - literature["ebv"],
        "age_pct_diff": 100.0 * (fitted["age_myr"] - literature["age_myr"]) / literature["age_myr"],
    }

    df = hrfit.load_photometry(members_csv_path, blue, red, lum, max_error=max_error)
    colour, mag = hrfit.to_absolute_cmd(df, blue, red, lum, fitted["distance_kpc"], fitted["ebv"])
    iso_sel = hrfit.select_isochrone(iso_all, fitted["log_age"])
    iso_colour, iso_mag = hrfit.isochrone_cmd(iso_sel, iso_cols["blue"], iso_cols["red"], iso_cols["lum"])

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
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
        "members_csv_path": str(members_csv_path),
    }
