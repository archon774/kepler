"""Multi-band, densified-isochrone cluster fitting.

hrfit._weighted_cost() (frozen, untouched) matches each star to its nearest
point on the isochrone using exactly two dimensions -- one colour, one
magnitude -- against the isochrone's raw tabulated rows. That throws away
every other band a crossmatched member actually has (a Gaia-crossmatched
member CSV carries G/BP/RP alongside whatever the original photometry was,
e.g. B/V/R/I) and it can only ever be as fine-grained as the isochrone file's
own row spacing.

This module generalizes both: build_candidate_points() densifies the main-
sequence portion of a (phase-filtered) isochrone by linear interpolation in
mass -- smoother matching than the raw discrete rows PARSEC/MIST/SPOTS
tabulate -- while leaving the giant-branch/horizontal-branch rows as-is
(post-main-sequence evolution happens at ~one mass per age, so there is no
mass axis to interpolate against there; see algorithms.hrdiagram.phases).
multiband_cost() then matches each star to its nearest candidate point using
every band both the star and that point actually have, not just one colour.

Extinction and the distance-modulus transform are hrfit.get_extinction() /
hrfit.distance_modulus() applied per band -- the same CCM89 law hrfit.py
already uses, evaluated at each band's own effective wavelength (already
tabulated in hrfit.FILTER_WAVELENGTH), so no new extinction dependency.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from algorithms.hrdiagram import hrfit
from algorithms.hrdiagram.phases import PHASE_COL, PHASE_GROUPS, filter_excluded_phases

MASS_COL_CANDIDATES = ("initial_mass", "Mass", "mass", "Mini", "M_ini")


def _find_mass_col(iso: pd.DataFrame) -> str | None:
    for col in MASS_COL_CANDIDATES:
        if col in iso.columns:
            return col
    return None


def _densify_group(
    group: pd.DataFrame, mass_col: str | None, band_cols: Mapping[str, str], n_dense: int,
) -> dict[str, np.ndarray]:
    """Linearly interpolate each band over `n_dense` evenly spaced mass points
    spanning the group's own mass range. Each band uses its own finite subset
    of (mass, value) pairs, so one band's gaps (e.g. a SPOTS colour outside
    its calibrated range, replaced with NaN -- see isochrones.fetch_spots_isochrone)
    don't block densifying the others. Falls back to the group's raw rows,
    undensified, when there's no usable mass axis (constant/near-constant
    mass, as in a giant-branch or horizontal-branch group -- see
    algorithms.hrdiagram.phases) or too few points to interpolate.
    """
    out: dict[str, np.ndarray] = {}
    mass = group[mass_col].values.astype(float) if mass_col else None
    can_densify = (
        mass is not None
        and np.isfinite(mass).sum() >= 2
        and np.unique(mass[np.isfinite(mass)]).size >= 2
    )
    if not can_densify:
        for band, col in band_cols.items():
            if col in group.columns:
                out[band] = group[col].values.astype(float)
        return out

    finite_mass = np.isfinite(mass)
    mass_grid = np.linspace(mass[finite_mass].min(), mass[finite_mass].max(), n_dense)
    for band, col in band_cols.items():
        if col not in group.columns:
            continue
        values = group[col].values.astype(float)
        valid = finite_mass & np.isfinite(values)
        if valid.sum() < 2:
            continue
        order = np.argsort(mass[valid])
        out[band] = np.interp(mass_grid, mass[valid][order], values[valid][order])
    return out


def build_candidate_points(
    iso: pd.DataFrame, band_cols: Mapping[str, str], phase_col: str = PHASE_COL, n_dense: int = 200,
) -> dict[str, np.ndarray]:
    """Per-band arrays of candidate isochrone points to match cluster members
    against -- densified within the main sequence, raw tabulated rows for any
    other phase group present (see module docstring). All arrays returned are
    independently sized per band (each band densifies over its own valid mass
    range), which multiband_cost() handles band-by-band, not point-by-point.
    """
    iso = filter_excluded_phases(iso, phase_col)
    mass_col = _find_mass_col(iso)

    if phase_col not in iso.columns:
        groups = [iso]
    else:
        phase_values = iso[phase_col].values
        groups = []
        for _name, values in PHASE_GROUPS:
            mask = np.isin(phase_values, list(values))
            if mask.any():
                groups.append(iso[mask])

    per_band_arrays: dict[str, list[np.ndarray]] = {band: [] for band in band_cols}
    for group in groups:
        densified = _densify_group(group, mass_col, band_cols, n_dense)
        for band, arr in densified.items():
            per_band_arrays[band].append(arr)

    return {band: np.concatenate(arrs) for band, arrs in per_band_arrays.items() if arrs}


def load_photometry_multiband(
    path: str | Path, band_cols: Mapping[str, str], err_suffix: str = "_err",
    max_error: float | None = None, min_bands: int = 2,
) -> pd.DataFrame:
    """Like hrfit.load_photometry(), but keeps a star as long as it has at
    least `min_bands` usable bands (finite magnitude, finite positive error at
    or under max_error) among band_cols, rather than requiring three specific
    named columns -- a member CSV can carry more bands than any one fit needs
    (e.g. B/V/R/I plus Gaia G/BP/RP from crossmatch_gaia), and every one of
    them is a real constraint on that star's fit.
    """
    df = pd.read_csv(path)
    available = {band: col for band, col in band_cols.items() if col_present(df, band, err_suffix)}
    if not available:
        raise KeyError(
            f"{path!r} has none of the expected magnitude/error column pairs for bands "
            f"{sorted(band_cols)}. Have: {list(df.columns)}"
        )

    usable_count = np.zeros(len(df), dtype=int)
    for band in available:
        mag = df[band].values
        err = df[band + err_suffix].values
        ok = np.isfinite(mag) & np.isfinite(err) & (err > 0)
        if max_error is not None:
            ok &= err <= max_error
        usable_count += ok.astype(int)

    return df[usable_count >= min_bands].reset_index(drop=True)


def col_present(df: pd.DataFrame, band: str, err_suffix: str) -> bool:
    return band in df.columns and (band + err_suffix) in df.columns


def observed_bands_absolute(
    df: pd.DataFrame, band_cols: Mapping[str, str], distance_kpc: float, ebv: float,
    err_suffix: str, rv: float,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    mu = hrfit.distance_modulus(distance_kpc)
    obs_by_band: dict[str, np.ndarray] = {}
    err_by_band: dict[str, np.ndarray] = {}
    for band in band_cols:
        if not col_present(df, band, err_suffix):
            continue
        extinction = hrfit.get_extinction(band, ebv, rv)
        obs_by_band[band] = df[band].values.astype(float) - extinction - mu
        err_by_band[band] = df[band + err_suffix].values.astype(float)
    return obs_by_band, err_by_band


def multiband_cost(
    obs_by_band: Mapping[str, np.ndarray], err_by_band: Mapping[str, np.ndarray],
    model_by_band: Mapping[str, np.ndarray],
) -> float:
    """Sum over stars of each star's minimum chi2 to any candidate isochrone
    point, using every band both the star and that candidate point have
    finite values for -- the multi-band generalization of
    hrfit._weighted_cost()'s single-colour nearest-point search."""
    bands = [b for b in obs_by_band if b in model_by_band]
    if not bands:
        return 1e12

    n_stars = len(next(iter(obs_by_band.values())))
    n_cand = len(next(iter(model_by_band.values())))
    total_sq = np.zeros((n_stars, n_cand))
    total_n = np.zeros((n_stars, n_cand))

    for band in bands:
        obs = obs_by_band[band][:, None]
        err = err_by_band[band][:, None]
        model = model_by_band[band][None, :]
        valid = np.isfinite(obs) & np.isfinite(err) & (err > 0) & np.isfinite(model)
        diff_sq = np.where(valid, ((obs - model) / np.where(err > 0, err, 1.0)) ** 2, 0.0)
        total_sq += diff_sq
        total_n += valid

    per_pair_cost = np.where(total_n > 0, total_sq, np.inf)
    best_cost_per_star = per_pair_cost.min(axis=1)
    # A star with no usable candidate anywhere (no band overlap at all with the
    # isochrone -- shouldn't normally happen) gets a large fixed penalty rather
    # than an inf that would swallow the whole trial's cost.
    best_cost_per_star = np.where(np.isfinite(best_cost_per_star), best_cost_per_star, 1e6)
    return float(best_cost_per_star.sum())


def fit_distance_reddening_multiband(
    df: pd.DataFrame, band_cols: Mapping[str, str], candidate_points: Mapping[str, np.ndarray],
    x0: tuple[float, float] = (1.0, 0.1), err_suffix: str = "_err",
    d_bounds: tuple[float, float] = (0.05, 100.0), ebv_bounds: tuple[float, float] = (0.0, 3.1),
    rv: float = 3.1,
) -> dict[str, Any]:
    """Optimize distance (kpc) and E(B-V) against the multi-band cost --
    mirrors hrfit.fit_distance_reddening()'s signature/return shape."""
    from scipy.optimize import minimize

    def cost(p: np.ndarray) -> float:
        d, ebv = p
        if not (d_bounds[0] <= d <= d_bounds[1]) or not (ebv_bounds[0] <= ebv <= ebv_bounds[1]):
            return 1e12
        obs_by_band, err_by_band = observed_bands_absolute(df, band_cols, d, ebv, err_suffix, rv)
        return multiband_cost(obs_by_band, err_by_band, candidate_points)

    res = minimize(cost, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 2000})
    d, ebv = res.x
    return {
        "distance_kpc": float(d), "ebv": float(ebv), "cost": float(res.fun),
        "reduced_cost": float(res.fun / max(len(df), 1)), "success": bool(res.success),
    }


def fit_cluster_multiband(
    csv_path: str | Path, iso_path: str | Path, band_cols: Mapping[str, str], logages: list[float],
    mh: float | None = None, max_error: float | None = None, err_suffix: str = "_err",
    x0: tuple[float, float] = (1.0, 0.1), rv: float = 3.1, phase_col: str = PHASE_COL,
    n_dense: int = 200, min_bands: int = 2,
) -> dict[str, Any]:
    """Scan logages, fit distance & E(B-V) for each against the multi-band
    cost, return best + ranked trials -- mirrors hrfit.fit_cluster()'s return
    shape ({"best", "trials", "n_stars"}) so callers don't need to branch."""
    df = load_photometry_multiband(csv_path, band_cols, err_suffix, max_error, min_bands)
    iso_all = hrfit.load_isochrone(iso_path)

    trials = []
    for la in logages:
        iso_sel = hrfit.select_isochrone(iso_all, la, mh)
        candidate_points = build_candidate_points(iso_sel, band_cols, phase_col, n_dense)
        fit = fit_distance_reddening_multiband(df, band_cols, candidate_points, x0=x0, err_suffix=err_suffix, rv=rv)
        fit["logage"] = la
        trials.append(fit)
    trials.sort(key=lambda t: t["cost"])
    return {"best": trials[0], "trials": trials, "n_stars": len(df)}
