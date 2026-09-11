"""Read the operator-installed Girardi grid used by Astromancer's HR client.

The former browser called ``GET /cluster/isochrone`` with an exact log-age,
metallicity, and three filters.  Its server returned colour/magnitude pairs.
This module is the local, network-free equivalent; configuration belongs one
layer up in :mod:`tools.config`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["GridUnavailableError", "LegacyIsochrone", "load_isochrone", "load_tracks"]


# PORTED: filter names accepted by Astromancer's
# src/app/tools/cluster/cluster.util.ts::FILTER.  Positions are the fixed
# column layout of its Girardi ``.npy`` model arrays.
_FILTER_COLUMNS = {
    "U": 2, "B": 3, "V": 4, "R": 5, "I": 6,
    "uprime": 7, "gprime": 8, "rprime": 9, "iprime": 10, "zprime": 11,
    "J": 12, "H": 13, "K": 14,
    "W1": 15, "W2": 16, "W3": 17, "W4": 18,
    "G": 19, "BP": 20, "RP": 21,
}


class GridUnavailableError(RuntimeError):
    """The configured local model cannot satisfy an isochrone request."""


@dataclass(frozen=True)
class LegacyIsochrone:
    """The former backend response plus the exact local source file."""

    data: list[list[float]]
    i_skip: int
    path: Path


def _track_path(grid_dir: Path, age: float, metallicity: float) -> Path:
    return grid_dir / f"Girardi_{age:.2f}_{metallicity:.2f}.npy"


def _column(filter_name: str) -> int:
    try:
        return _FILTER_COLUMNS[filter_name]
    except KeyError:
        raise GridUnavailableError(
            f"unsupported filter {filter_name!r}; supported filters are "
            f"{sorted(_FILTER_COLUMNS)}"
        ) from None


def load_isochrone(
    grid_dir: str | Path,
    *,
    age: float,
    metallicity: float,
    blue_filter: str,
    red_filter: str,
    lum_filter: str,
) -> LegacyIsochrone:
    """Return one exact local Girardi track in Astromancer response shape.

    No age/metallicity interpolation or nearest-track fallback occurs. The
    source arrays do not carry Astromancer's server-side discontinuity metadata,
    so ``i_skip`` is zero (no inserted plot break).
    """

    directory = Path(grid_dir).expanduser()
    if not directory.is_dir():
        raise GridUnavailableError(
            f"Girardi grid directory {directory} is unavailable; set "
            "KEPLER_ISOCHRONE_DIR to an unpacked grid directory"
        )

    blue_column = _column(blue_filter)
    red_column = _column(red_filter)
    lum_column = _column(lum_filter)
    path = _track_path(directory, age, metallicity)
    if not path.is_file():
        raise GridUnavailableError(
            f"required exact Girardi track {path.name} is missing from {directory}"
        )
    try:
        track = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise GridUnavailableError(f"could not read Girardi track {path}: {exc}") from exc
    if track.ndim != 2 or track.shape[1] != 23 or not np.issubdtype(track.dtype, np.number):
        raise GridUnavailableError(
            f"Girardi track {path} must be a numeric two-dimensional array with 23 columns"
        )

    return LegacyIsochrone(
        data=[
            [float(row[blue_column] - row[red_column]), float(row[lum_column])]
            for row in track
        ],
        i_skip=0,
        path=path,
    )


def load_tracks(
    grid_dir: str | Path,
    *,
    ages: list[float],
    metallicity: float,
) -> pd.DataFrame:
    """Load exact-age tracks into the named columns used by ``hrfit``.

    This keeps age selection explicit for the fitter while preserving each
    source row's order inside an individual legacy track.
    """

    directory = Path(grid_dir).expanduser()
    if not directory.is_dir():
        raise GridUnavailableError(
            f"Girardi grid directory {directory} is unavailable; set "
            "KEPLER_ISOCHRONE_DIR to an unpacked grid directory"
        )

    columns = ["logAge", "MH", *list(_FILTER_COLUMNS), "MH_repeat"]
    frames: list[pd.DataFrame] = []
    for age in ages:
        path = _track_path(directory, age, metallicity)
        if not path.is_file():
            raise GridUnavailableError(
                f"required exact Girardi track {path.name} is missing from {directory}"
            )
        try:
            track = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise GridUnavailableError(f"could not read Girardi track {path}: {exc}") from exc
        if track.ndim != 2 or track.shape[1] != 23 or not np.issubdtype(track.dtype, np.number):
            raise GridUnavailableError(
                f"Girardi track {path} must be a numeric two-dimensional array with 23 columns"
            )
        frames.append(pd.DataFrame(track, columns=columns))
    return pd.concat(frames, ignore_index=True)
