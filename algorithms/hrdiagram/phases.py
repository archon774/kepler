"""Evolutionary-phase handling for MIST isochrones.

MIST's UBVRIplus tables carry a `phase` column using FSPS's coding: PMS=-1,
MS=0, SGB+RGB=2, CHeB=3 (core He burning -- the horizontal branch), EAGB=4,
TPAGB=5, post-AGB=6, WR=9. hrfit.isochrone_cmd() (frozen, untouched) has no
idea any of this exists -- it just extracts colour/magnitude arrays in the
file's native row order and, at most, breaks the plotted line at one caller-
supplied index. For an old, globular-cluster-age isochrone that native order
runs MS -> turnoff -> RGB -> (a real, physical jump at the He flash) -> HB ->
AGB -> ..., so drawing every phase as one connected polyline draws a straight
line across that jump and through the short, sparse, rarely-populated-by-real-
data AGB/post-AGB/WR tail -- the "janky cutoff" after the main sequence.

This module does two things with that `phase` column where hrfit.py can't:
  1. filter_excluded_phases() drops AGB/post-AGB/WR rows before fitting or
     plotting -- short-lived, sparsely sampled, and essentially never where a
     real cluster member lands.
  2. isochrone_cmd_with_breaks() extracts the same colour/magnitude arrays as
     hrfit.isochrone_cmd(), but inserts a NaN break at every remaining phase-
     group transition (MS+turnoff -> giant branch -> horizontal branch) so the
     plotted line doesn't connect points that aren't really continuous.

Isochrone sources without a `phase` column (SPOTS, PARSEC) pass through both
functions unchanged -- there is nothing to group.

One real limitation this does NOT fix, and can't: a single isochrone track
represents one deterministic amount of RGB mass loss, so it traces exactly one
point through the horizontal branch's temperature range at each moment, not
the horizontal *spread* of colours real HB stars show (that spread comes from
star-to-star scatter in RGB mass loss, which needs a synthetic-HB population
model -- a Monte Carlo over a mass-loss distribution -- to reproduce; a single
isochrone line fundamentally cannot). Keeping HB points in the fit (unlike the
excluded AGB/post-AGB/WR phases) still lets real HB members find their nearest
point on that one track; it does not make the track itself a full HB model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PHASE_COL = "phase"

# FSPS phase codes, grouped for plotting/fitting purposes.
PHASE_MS = frozenset({-1.0, 0.0})       # PMS, MS
PHASE_GIANT = frozenset({2.0})          # SGB + RGB
PHASE_HB = frozenset({3.0})             # CHeB (horizontal branch)
PHASE_EXCLUDED = frozenset({4.0, 5.0, 6.0, 9.0})  # EAGB, TPAGB, post-AGB, WR

PHASE_GROUPS: tuple[tuple[str, frozenset[float]], ...] = (
    ("ms", PHASE_MS),
    ("giant", PHASE_GIANT),
    ("hb", PHASE_HB),
)


def filter_excluded_phases(iso: pd.DataFrame, phase_col: str = PHASE_COL) -> pd.DataFrame:
    """Drop AGB/post-AGB/WR rows if `iso` has a phase column; no-op otherwise."""
    if phase_col not in iso.columns:
        return iso
    return iso[~iso[phase_col].isin(PHASE_EXCLUDED)].reset_index(drop=True)


def _phase_group_ids(phase_values: np.ndarray) -> np.ndarray:
    """Map each phase value to its group's index in PHASE_GROUPS (or -1 for an
    unrecognized value, so it still gets its own break rather than silently
    joining a neighbouring group)."""
    group_id = np.full(phase_values.shape, -1, dtype=int)
    for i, (_name, values) in enumerate(PHASE_GROUPS):
        group_id[np.isin(phase_values, list(values))] = i
    return group_id


def isochrone_cmd_with_breaks(
    iso: pd.DataFrame, blue_col: str, red_col: str, lum_col: str, phase_col: str = PHASE_COL,
) -> tuple[np.ndarray, np.ndarray]:
    """Like hrfit.isochrone_cmd(), but breaks the line at every phase-group
    transition instead of drawing one continuous polyline through physically
    disjoint segments (see module docstring). Row order is preserved -- callers
    should pass a phase-filtered, natively-ordered isochrone selection."""
    colour = iso[blue_col].values - iso[red_col].values
    mag = iso[lum_col].values.astype(float)

    if phase_col not in iso.columns or len(iso) == 0:
        return colour, mag

    group_id = _phase_group_ids(iso[phase_col].values)
    break_before = np.where(np.diff(group_id) != 0)[0] + 1
    if len(break_before) == 0:
        return colour, mag

    colour = np.insert(colour, break_before, np.nan)
    mag = np.insert(mag, break_before, np.nan)
    return colour, mag
