"""Fit HR diagrams against the operator-installed local Girardi grid.

This module does not download isochrones. Gaia/VizieR catalog lookups remain
the responsibility of :mod:`tools.hr_diagram`.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from algorithms.hrdiagram_py import hrfit, local_grid
from tools import config

__all__ = ["fit_and_compare"]

MAX_LOGAGE_HALF_WIDTH = 1.0


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
) -> dict[str, Any]:
    """Fit distance/E(B-V)/age against exact local Girardi tracks.

    ``mh`` is the track metallicity ([M/H], solar = 0.0). The configured grid
    must contain every selected exact age; the loader never interpolates,
    substitutes a nearest track, or fetches a model.
    """
    if config.ISOCHRONE_DIR is None:
        raise RuntimeError(
            "KEPLER_ISOCHRONE_DIR is not configured; install the operator Girardi "
            "grid and set it to the unpacked track directory"
        )

    center = float(literature["log_age"])
    if not math.isfinite(center):
        raise ValueError("literature log_age must be finite")
    if not math.isfinite(logage_half_width):
        raise ValueError("logage_half_width must be finite")
    if logage_half_width < 0 or logage_half_width > MAX_LOGAGE_HALF_WIDTH:
        raise ValueError(f"logage_half_width must be between 0 and {MAX_LOGAGE_HALF_WIDTH}")
    if not math.isfinite(dlage) or dlage <= 0:
        raise ValueError("dlage must be finite and greater than zero")
    if logage_half_width == 0:
        ages = [round(center, 2)]
    else:
        count = int(round((2 * logage_half_width) / dlage))
        ages = [round(center - logage_half_width + index * dlage, 2) for index in range(count + 1)]
    iso_all = local_grid.load_tracks(ages=ages, metallicity=mh)

    members_csv_path = Path(members_csv_path)
    members_csv_path.parent.mkdir(parents=True, exist_ok=True)
    members.to_csv(members_csv_path, index=False)

    logages = sorted(np.unique(iso_all["logAge"].values))
    temporary_iso_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".dat", prefix="kepler_girardi_", dir=members_csv_path.parent,
            delete=False,
        ) as handle:
            temporary_iso_path = Path(handle.name)
            handle.write("# " + " ".join(iso_all.columns) + "\n")
            iso_all.to_csv(handle, sep=" ", index=False, header=False)
        result = hrfit.fit_cluster(
            members_csv_path, temporary_iso_path, blue, red, lum, blue, red, lum,
            logages=logages, max_error=max_error,
            x0=(literature["distance_kpc"], literature["ebv"]),
        )
    finally:
        if temporary_iso_path is not None:
            temporary_iso_path.unlink(missing_ok=True)

    best = result["best"]
    fitted = {
        "distance_kpc": best["distance_kpc"],
        "ebv": best["ebv"],
        "log_age": best["logage"],
        "age_myr": 10.0 ** best["logage"] / 1.0e6,
        "n_stars_fitted": result["n_stars"],
        "reduced_cost": best["reduced_cost"],
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
    iso_colour, iso_mag = hrfit.isochrone_cmd(iso_sel, blue, red, lum)

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    ax = hrfit.plot_cmd(
        colour, mag, iso_colour, iso_mag,
        xlabel=f"({blue} - {red})$_0$", ylabel=f"M$_{{{lum}}}$",
        title=(
            f"{cluster_name}\n"
            f"fit: d={fitted['distance_kpc']:.2f} kpc, E(B-V)={fitted['ebv']:.2f}, "
            f"age={fitted['age_myr']:.0f} Myr\n"
            f"lit: d={literature['distance_kpc']:.2f} kpc, E(B-V)={literature['ebv']:.2f}, "
            f"age={literature['age_myr']:.0f} Myr"
        ),
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
        "isochrone_path": str(config.ISOCHRONE_DIR),
        "members_csv_path": str(members_csv_path),
    }
