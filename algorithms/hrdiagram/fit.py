"""Fit distance/E(B-V)/age against an isochrone, compare to literature, plot.

Ties together hrfit.py (the fit math), isochrones.py (MIST/PARSEC grids), and
whatever the caller resolved from literature.py -- the real domain logic for
HR-diagram fitting lives here. Callers (tools.hr_diagram) own where
output files go; the functions here take explicit csv_path/out_png_path
arguments rather than choosing their own artifact directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from algorithms.hrdiagram import hrfit
from algorithms.hrdiagram.isochrones import (
    PARSEC_PHOTSYS,
    SPOTS_FSPOTS,
    fetch_mist_isochrone,
    fetch_parsec_isochrone_grid,
    fetch_spots_isochrone,
    mist_iso_cols,
    spots_iso_cols,
)


def _age_grid_for_isochrone(
    iso_all_logages: np.ndarray, literature: Mapping[str, Any], logage_half_width: float,
) -> list[float]:
    """Which ages (drawn from those actually present in one isochrone file) to
    scan a fit over, given the literature's log_age and whether it's a
    fabricated default (see the age_is_literature_default note below)."""
    if literature.get("age_is_literature_default"):
        # Harris doesn't publish per-cluster ages for globulars, so this "literature"
        # age was never a real measurement -- and a giant-branch-only CMD (no main-
        # sequence turnoff reached) barely constrains age on its own anyway. Letting
        # the optimizer scan age here just chases noise to the grid boundary (observed:
        # real NGC 1851 data converging to the oldest age MIST has, 10.3 = ~20 Gyr,
        # older than the universe) while barely moving the cost. Fix it at the default
        # instead, so distance/E(B-V) -- which the data *does* constrain -- aren't
        # dragged along for the ride.
        nearest = iso_all_logages[np.argmin(np.abs(iso_all_logages - literature["log_age"]))]
        return [float(nearest)]
    # hrfit.fit_cluster() stores each trial's `la` as-is (never through float()),
    # so cast here -- otherwise it's a numpy scalar that json.dumps(default=str)
    # would silently turn into a string in the agent's tool results.
    age_mask = np.abs(iso_all_logages - literature["log_age"]) <= logage_half_width
    logages = [float(a) for a in sorted(np.unique(iso_all_logages[age_mask]))]
    if not logages:
        logages = [float(a) for a in sorted(np.unique(iso_all_logages))]
    return logages


def _fit_against_isochrone(
    csv_path: Path, iso_path: Path, iso_cols: dict[str, str],
    blue: str, red: str, lum: str,
    literature: Mapping[str, Any], max_error: float, logage_half_width: float,
) -> dict[str, Any]:
    """Run hrfit.fit_cluster() against one isochrone file, scanning whichever
    ages _age_grid_for_isochrone picks. Shared by the single-file sources
    (mist, parsec) and, looped once per starspot covering fraction, by spots.
    """
    iso_all = hrfit.load_isochrone(iso_path)
    logages = _age_grid_for_isochrone(iso_all["logAge"].values, literature, logage_half_width)
    return hrfit.fit_cluster(
        csv_path, iso_path, blue, red, lum,
        iso_cols["blue"], iso_cols["red"], iso_cols["lum"],
        logages=logages, max_error=max_error,
        x0=(literature["distance_kpc"], literature["ebv"]),
    )


def fit_and_compare(
    members: pd.DataFrame,
    literature: Mapping[str, Any],
    cluster_name: str,
    csv_path: str | Path,
    out_png_path: str | Path,
    blue: str = "BP",
    red: str = "RP",
    lum: str = "G",
    max_error: float = 0.1,
    logage_half_width: float = 0.3,
    dlage: float = 0.05,
    mh: float | None = None,
    iso_path: str | Path | None = None,
    isochrone_source: str = "mist",
    photsys: str = "gaiaEDR3",
    pre_dereddened_ebv: float = 0.0,
) -> dict[str, Any]:
    """Fit distance/E(B-V)/age to `members` against an isochrone grid centred
    on the literature age, and compare the fit to the literature.

    `csv_path` / `out_png_path` are where the (re-saved) members table and the
    plot get written -- the caller decides the location (see
    tools.hr_diagram, which uses tools.config.artifact_directory()).

    `isochrone_source` picks where the isochrone grid comes from:
      - "mist" (default): the MIST v1.2 grid, downloaded whole and cached
        locally (see isochrones.fetch_mist_isochrone) -- a one-time ~150MB
        download, then every call is a local file read.
      - "parsec": stev.oapd.inaf.it's CMD web form, fetched per age-window
        request (see isochrones.fetch_parsec_isochrone_grid). Kept as a
        fallback/cross-check; that service has been observed to rate-limit or
        reset connections under repeated automated use, which "mist" avoids by
        not depending on a live per-request service at all.
      - "spots": the Somers, Pinsonneault & Cao (2019) SPOTS grid of
        pre-main-sequence isochrones with a starspot covering-fraction axis
        (Fspot in {0, 17, 34, 51, 68, 85}%, see isochrones.fetch_spots_isochrone).
        Use this for young clusters where standard spot-free models like
        MIST/PARSEC systematically mismatch active, spotted pre-main-sequence
        stars. Fspot isn't known ahead of time -- it's scanned the same way
        age is, and the winning value is reported in fitted["fspot"] as a fit
        result, not a literature-sourced property. The grid is single (solar)
        metallicity only, so `mh` has no effect for this source.

    `mh` is the isochrone grid's metallicity ([M/H], solar=0.0). If left as
    None (the default), it's read from `literature["feh"]` when present
    (globular clusters, via Harris) and falls back to solar otherwise (open
    clusters -- Cantat-Gaudin & Anders 2020 doesn't publish per-cluster
    metallicity). Pass an explicit value to override either way.

    `pre_dereddened_ebv`: set this if `members`' blue/red/lum magnitudes have
    already had some E(B-V) removed upstream (e.g. baked into a photometric
    calibration step before this file was produced) -- the fit itself is
    unaffected, since it always solves for whatever *residual* colour excess
    remains in the magnitudes it's actually given, but leaving this at 0.0
    when it shouldn't be means the reported `fitted["ebv"]` understates the
    true total reddening and the literature comparison is apples-to-oranges
    (literature E(B-V) is always a total, foreground value). The plot's CMD
    shift uses the residual (correct for the as-given magnitudes);
    `fitted["ebv"]` and the comparison use the total (residual +
    pre_dereddened_ebv), comparable to literature.
    """
    if mh is None:
        # .get("feh", 0.0) is not enough: a dict built from
        # ClusterLiteratureParams.model_dump() always has a "feh" key (None for
        # open clusters, since it's a declared model field), so the key is
        # never actually *absent* the way a plain hand-built dict's would be --
        # only ever None -- and .get()'s default only fires on absence.
        feh = literature.get("feh")
        mh = feh if feh is not None else 0.0

    if isochrone_source == "parsec" and {blue, red, lum} - {"G", "BP", "RP"}:
        raise ValueError(
            f"isochrone_source='parsec' only has Gaia bands wired up (PARSEC_PHOTSYS), but "
            f"blue={blue!r} red={red!r} lum={lum!r} was requested. Use isochrone_source='mist' "
            "or 'spots' instead (MIST_FILTER_MAP / SPOTS_FILTER_MAP cover a wider set of "
            "filters), or pass iso_path pointing at a PARSEC table you fetched with a "
            "matching photsys."
        )

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    members.to_csv(csv_path, index=False)

    fitted_fspot: float | None = None

    if iso_path is None:
        if isochrone_source == "mist":
            iso_path = fetch_mist_isochrone(mh=mh)
            iso_cols = mist_iso_cols(blue, red, lum)
            result = _fit_against_isochrone(
                csv_path, iso_path, iso_cols, blue, red, lum,
                literature, max_error, logage_half_width,
            )
        elif isochrone_source == "parsec":
            iso_path = fetch_parsec_isochrone_grid(
                literature["log_age"],
                logage_half_width=logage_half_width,
                dlage=dlage,
                mh=mh,
                photsys=photsys,
            )
            iso_cols = PARSEC_PHOTSYS[photsys]
            result = _fit_against_isochrone(
                csv_path, iso_path, iso_cols, blue, red, lum,
                literature, max_error, logage_half_width,
            )
        elif isochrone_source == "spots":
            # Fspot isn't known ahead of time the way age at least has a
            # literature-derived starting point -- scan every covering
            # fraction the grid offers (one isochrone file each) and keep
            # whichever gives the best (age-scanned) fit.
            best_result = None
            best_fspot = None
            best_iso_path = None
            best_iso_cols = None
            for fspot in SPOTS_FSPOTS:
                candidate_iso_path = fetch_spots_isochrone(fspot)
                candidate_iso_cols = spots_iso_cols(blue, red, lum)
                candidate_result = _fit_against_isochrone(
                    csv_path, candidate_iso_path, candidate_iso_cols, blue, red, lum,
                    literature, max_error, logage_half_width,
                )
                if (
                    best_result is None
                    or candidate_result["best"]["reduced_cost"] < best_result["best"]["reduced_cost"]
                ):
                    best_result = candidate_result
                    best_fspot = fspot
                    best_iso_path = candidate_iso_path
                    best_iso_cols = candidate_iso_cols
            result = best_result
            fitted_fspot = best_fspot
            iso_path = best_iso_path
            iso_cols = best_iso_cols
        else:
            raise ValueError(
                f"Unknown isochrone_source {isochrone_source!r}; use 'mist', 'parsec', or 'spots'"
            )
    else:
        if isochrone_source == "mist":
            iso_cols = mist_iso_cols(blue, red, lum)
        elif isochrone_source == "spots":
            iso_cols = spots_iso_cols(blue, red, lum)
        else:
            iso_cols = PARSEC_PHOTSYS[photsys]
        result = _fit_against_isochrone(
            csv_path, iso_path, iso_cols, blue, red, lum,
            literature, max_error, logage_half_width,
        )

    best = result["best"]

    fitted = {
        "distance_kpc": best["distance_kpc"],
        "ebv_residual": best["ebv"],
        "ebv": best["ebv"] + pre_dereddened_ebv,
        "pre_dereddened_ebv": pre_dereddened_ebv,
        "log_age": best["logage"],
        "age_myr": 10.0 ** best["logage"] / 1.0e6,
        "fspot": fitted_fspot,
        "n_stars_fitted": result["n_stars"],
        "reduced_cost": best["reduced_cost"],
    }
    comparison = {
        "distance_pct_diff": 100.0 * (fitted["distance_kpc"] - literature["distance_kpc"]) / literature["distance_kpc"],
        "ebv_diff": fitted["ebv"] - literature["ebv"],
        "age_pct_diff": 100.0 * (fitted["age_myr"] - literature["age_myr"]) / literature["age_myr"],
    }

    df = hrfit.load_photometry(csv_path, blue, red, lum, max_error=max_error)
    # members' magnitudes already have pre_dereddened_ebv removed, so only the
    # residual belongs in this shift -- fitted["ebv"] (the total) would double-count it.
    colour, mag = hrfit.to_absolute_cmd(df, blue, red, lum, fitted["distance_kpc"], fitted["ebv_residual"])
    iso_all = hrfit.load_isochrone(iso_path)
    iso_sel = hrfit.select_isochrone(iso_all, fitted["log_age"])
    iso_colour, iso_mag = hrfit.isochrone_cmd(iso_sel, iso_cols["blue"], iso_cols["red"], iso_cols["lum"])

    out_png_path = Path(out_png_path)
    out_png_path.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    title_lines = [
        cluster_name,
        f"fit: d={fitted['distance_kpc']:.2f} kpc, E(B-V)={fitted['ebv']:.3f}, age={fitted['age_myr']:.0f} Myr",
        f"lit: d={literature['distance_kpc']:.2f} kpc, E(B-V)={literature['ebv']:.3f}, age={literature['age_myr']:.0f} Myr",
    ]
    if pre_dereddened_ebv:
        title_lines.insert(
            2,
            f"(fit E(B-V) = {fitted['ebv_residual']:.3f} residual + {pre_dereddened_ebv:.3f} pre-applied)",
        )
    ax = hrfit.plot_cmd(
        colour, mag, iso_colour, iso_mag,
        xlabel=f"({blue} - {red})$_0$", ylabel=f"M$_{{{lum}}}$",
        title="\n".join(title_lines),
    )
    ax.set_title(ax.get_title(), fontsize=9)
    ax.figure.tight_layout()
    ax.figure.savefig(out_png_path, dpi=130)

    return {
        "cluster": cluster_name,
        "fitted": fitted,
        "literature": dict(literature),
        "comparison": comparison,
        "png_path": str(out_png_path),
        "isochrone_path": str(iso_path),
        "members_csv_path": str(csv_path),
    }


def plot_observed_cmd(
    df: pd.DataFrame,
    blue: str,
    red: str,
    lum: str,
    csv_path: str | Path,
    out_png_path: str | Path,
    max_error: float | None = None,
    err_suffix: str = "_err",
    title: str | None = None,
) -> dict[str, Any]:
    """Plot an observed colour-magnitude diagram (blue - red vs lum), with no
    distance-modulus or reddening correction applied -- apparent magnitudes as
    measured, not the absolute-magnitude HR diagram fit_and_compare() produces.

    Use this when there's no literature distance/E(B-V) to shift by (e.g. the
    cluster isn't in literature.get_literature_cluster_params()'s catalogs at
    all) and a fitted comparison isn't the goal, just the diagram itself. If
    the cluster *is* resolvable, fit_and_compare() (via
    tools.hr_diagram.run_hr_diagram_pipeline_from_photometry) gives a
    real absolute-magnitude HR diagram with an isochrone fit instead.
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    clean = hrfit.load_photometry(csv_path, blue, red, lum, err_suffix=err_suffix, max_error=max_error)
    colour = clean[blue].values - clean[red].values
    mag = clean[lum].values

    out_png_path = Path(out_png_path)
    out_png_path.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    ax = hrfit.plot_cmd(
        colour, mag,
        xlabel=f"{blue} - {red}", ylabel=lum,
        title=title or f"Observed CMD (n={len(clean)})",
        frame_on_data=True,
    )
    ax.figure.tight_layout()
    ax.figure.savefig(out_png_path, dpi=130)

    return {"n_stars": len(clean), "n_input": len(df), "png_path": str(out_png_path)}
