"""Read the operator-installed Girardi grid used by Astromancer's HR client.

The former browser called ``GET /cluster/isochrone`` with an exact log-age,
metallicity, and three filters.  Its server returned colour/magnitude pairs.
This module is the local, network-free equivalent; configuration belongs one
layer up in :mod:`tools.config`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tools import config

__all__ = ["GridUnavailableError", "load_isochrone", "load_tracks"]


# The supplied tracks are about 100 KiB. These caps keep a malformed
# operator-installed ``.npy`` file from exhausting the tool process.
MAX_TRACK_BYTES = 8 * 1024 * 1024
MAX_TRACK_ROWS = 100_000


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


def _configured_directory() -> Path:
    if config.ISOCHRONE_DIR is None:
        raise GridUnavailableError(
            "Girardi grid directory is unavailable; set KEPLER_ISOCHRONE_DIR "
            "to an unpacked grid directory"
        )
    directory = config.ISOCHRONE_DIR
    if not directory.is_dir():
        raise GridUnavailableError(
            "Girardi grid directory is unavailable; set KEPLER_ISOCHRONE_DIR "
            "to an unpacked grid directory"
        )
    return directory


def _track_path(grid_dir: Path, age: float, metallicity: float) -> Path:
    return grid_dir / f"Girardi_{age:.2f}_{metallicity:.2f}.npy"


def _load_track(directory: Path, age: float, metallicity: float) -> np.ndarray:
    path = _track_path(directory, age, metallicity)
    if not path.is_file():
        raise GridUnavailableError(f"required exact Girardi track {path.name} is missing")
    try:
        if path.stat().st_size > MAX_TRACK_BYTES:
            raise GridUnavailableError(
                f"Girardi track {path.name} exceeds the maximum size of {MAX_TRACK_BYTES} bytes"
            )
        track = np.load(path, allow_pickle=False, mmap_mode="r")
    except (OSError, ValueError) as exc:
        raise GridUnavailableError(f"could not read Girardi track {path.name}: {exc}") from exc
    if (
        track.ndim != 2
        or track.shape[1] != 23
        or track.shape[0] > MAX_TRACK_ROWS
        or not np.issubdtype(track.dtype, np.number)
    ):
        raise GridUnavailableError(
            f"Girardi track {path.name} must be a numeric two-dimensional array with 23 columns "
            f"and at most {MAX_TRACK_ROWS} rows"
        )
    return track


def _column(filter_name: str) -> int:
    try:
        return _FILTER_COLUMNS[filter_name]
    except KeyError:
        raise GridUnavailableError(
            f"unsupported filter {filter_name!r}; supported filters are "
            f"{sorted(_FILTER_COLUMNS)}"
        ) from None


def load_isochrone(
    *,
    age: float,
    metallicity: float,
    blue_filter: str,
    red_filter: str,
    lum_filter: str,
) -> dict[str, list[list[float]] | int]:
    """Return one exact local Girardi track in Astromancer response shape.

    No age/metallicity interpolation or nearest-track fallback occurs. The
    source arrays do not carry Astromancer's server-side discontinuity metadata,
    so ``iSkip`` is zero (no inserted plot break).
    """

    blue_column = _column(blue_filter)
    red_column = _column(red_filter)
    lum_column = _column(lum_filter)
    track = _load_track(_configured_directory(), age, metallicity)

    return {
        "data": [
            [float(row[blue_column] - row[red_column]), float(row[lum_column])]
            for row in track
        ],
        "iSkip": 0,
    }


def load_tracks(
    *,
    ages: list[float],
    metallicity: float,
) -> pd.DataFrame:
    """Load exact-age tracks into the named columns used by ``hrfit``.

    This keeps age selection explicit for the fitter while preserving each
    source row's order inside an individual legacy track.
    """

    columns = ["logAge", "MH", *list(_FILTER_COLUMNS), "MH_repeat"]
    frames: list[pd.DataFrame] = []
    directory = _configured_directory()
    for age in ages:
        track = _load_track(directory, age, metallicity)
        frames.append(pd.DataFrame(track, columns=columns))
    return pd.concat(frames, ignore_index=True)
