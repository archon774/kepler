"""``algorithms/hrdiagram_py/membership.py`` -- field-star removal.

No network access -- everything here is synthetic. Two things are checked:

1. ``_elliptical_pm_mask`` in isolation: the ported ellipse formula from
   Astromancer's ``updateClusterFieldSources``
   (``algorithms/hrdiagram/photometry/cluster-data.service.util.ts:101-120``),
   including its documented "correct by accident" NaN behaviour for a point
   outside the semi-major axis (``docs/extraction.md``, HR Diagram TypeScript
   defect #8).
2. ``select_cluster_members`` end to end on a synthetic clump-plus-field
   population, including the reason the port was worth doing: a fixed
   absolute proper-motion tolerance is wrong for clusters at different
   distances, because angular PM dispersion scales as 1/distance for a fixed
   physical velocity dispersion (confirmed live against real M45 vs. NGC 6124
   Gaia data before this change; see the PR plan).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from algorithms.hrdiagram_py.membership import _elliptical_pm_mask, select_cluster_members


# ---------------------------------------------------------------------------
# _elliptical_pm_mask
# ---------------------------------------------------------------------------
def test_elliptical_pm_mask_keeps_points_inside_the_ellipse():
    # center (0, 0), semi-axes a=2 (pm_ra), b=1 (pm_dec).
    pmra = np.array([0.0, 1.0])
    pmdec = np.array([0.0, 0.4])

    mask = _elliptical_pm_mask(pmra, pmdec, 0.0, 0.0, np.full(2, 2.0), np.full(2, 1.0))

    assert mask.tolist() == [True, True]


def test_elliptical_pm_mask_rejects_a_point_inside_the_bounding_box_but_outside_the_ellipse():
    # At pm_ra=1 (within the a=2 semi-axis), the ellipse's half-width in
    # pm_dec is b*sqrt(1-(1/2)**2) = sqrt(0.75) ~= 0.866 -- a circular cut
    # using the bounding box alone would have kept this point; the real
    # ellipse must not.
    mask = _elliptical_pm_mask(
        np.array([1.0]), np.array([0.9]), 0.0, 0.0, np.array([2.0]), np.array([1.0])
    )

    assert mask.tolist() == [False]


def test_elliptical_pm_mask_rejects_outside_the_semi_major_axis_via_the_preserved_nan_path():
    """PRESERVED: for |pmra - center| > a, 1 - ((pmra-center)/a)**2 is
    negative, sqrt gives NaN, and NaN bound comparisons are False in both
    numpy and the original TypeScript -- "correct by accident," per
    docs/extraction.md's HR Diagram TypeScript defect #8. This must not raise
    or warn (np.errstate suppresses the expected RuntimeWarning)."""
    with np.errstate(all="raise"):
        mask = _elliptical_pm_mask(
            np.array([5.0]), np.array([0.0]), 0.0, 0.0, np.array([2.0]), np.array([1.0])
        )

    assert mask.tolist() == [False]


def test_elliptical_pm_mask_supports_per_source_semi_axes():
    # Same (pmra, pmdec)=(1, 0.9) as the rejection case above, but this
    # source's own wider semi-axes admit it -- semi-axes vary per star here,
    # unlike upstream's single shared ellipse (a human picked one slider
    # range for the whole sample there).
    mask = _elliptical_pm_mask(
        np.array([1.0, 1.0]), np.array([0.9, 0.9]), 0.0, 0.0,
        np.array([2.0, 4.0]), np.array([1.0, 2.0]),
    )

    assert mask.tolist() == [False, True]


# ---------------------------------------------------------------------------
# select_cluster_members
# ---------------------------------------------------------------------------
def _literature(distance_kpc: float) -> dict:
    return {
        "parallax_mas": 1.0 / distance_kpc,
        "pmra_mas_yr": 20.0,
        "pmdec_mas_yr": -45.0,
        "distance_kpc": distance_kpc,
    }


def _synthetic_population(rng, distance_kpc: float, n_members: int, n_field: int, pm_scatter_mas_yr: float) -> pd.DataFrame:
    lit = _literature(distance_kpc)
    members = pd.DataFrame({
        "parallax": rng.normal(lit["parallax_mas"], 0.05, n_members),
        "parallax_error": np.full(n_members, 0.03),
        "pmra": rng.normal(lit["pmra_mas_yr"], pm_scatter_mas_yr, n_members),
        "pmdec": rng.normal(lit["pmdec_mas_yr"], pm_scatter_mas_yr, n_members),
        "pmra_error": np.full(n_members, 0.04),
        "pmdec_error": np.full(n_members, 0.03),
    })
    field = pd.DataFrame({
        "parallax": rng.uniform(0.1, 3.0, n_field),
        "parallax_error": np.full(n_field, 0.05),
        "pmra": rng.uniform(-30.0, 30.0, n_field),
        "pmdec": rng.uniform(-60.0, 20.0, n_field),
        "pmra_error": np.full(n_field, 0.05),
        "pmdec_error": np.full(n_field, 0.04),
    })
    return pd.concat([members, field], ignore_index=True)


#: Deliberately independent of select_cluster_members's own default -- these
#: tests assert a relationship the *formula* guarantees (recovery scales with
#: scatter-to-floor ratio; fraction is distance-independent at a fixed
#: ratio), not a number tied to whatever default the module ships today.
_PM_DISPERSION_KM_S = 1.0


def test_select_cluster_members_recovers_a_clump_and_rejects_scattered_field():
    rng = np.random.default_rng(0)
    distance_kpc = 0.13
    # Half of _PM_DISPERSION_KM_S's floor at this distance (~1.62 mas/yr) --
    # comfortably inside the cut, so recovery should be high.
    pm_scatter_mas_yr = 0.5 * (_PM_DISPERSION_KM_S / (4.74 * distance_kpc))
    gaia = _synthetic_population(rng, distance_kpc, n_members=40, n_field=200, pm_scatter_mas_yr=pm_scatter_mas_yr)

    members = select_cluster_members(gaia, _literature(distance_kpc), pm_dispersion_km_s=_PM_DISPERSION_KM_S)

    # Some contamination/incompleteness at the edges is expected (this is a
    # random draw, not a hand-picked clean case) -- the point is that the cut
    # is dominated by real members, not diluted by the much larger field pool.
    assert 20 <= len(members) <= 40


def test_select_cluster_members_needs_a_wider_floor_for_a_nearby_cluster():
    """The reason the port mattered in practice: a fixed absolute PM
    tolerance rejects real nearby-cluster members whose *physical* velocity
    dispersion is unremarkable, because the same dispersion subtends a larger
    angle at a smaller distance. Same relative/absolute setup, two distances,
    the same assumed dispersion -- the nearby cluster must keep a comparable
    *fraction* of its own members, not a collapsed one.
    """
    rng = np.random.default_rng(1)
    near_kpc, far_kpc = 0.13, 0.65
    # 0.6x _PM_DISPERSION_KM_S's floor at each distance -- same *relative*
    # scatter-to-floor ratio at both distances, so both should recover a
    # similar, healthy fraction if the distance-aware floor is doing its job.
    # Without it (a fixed absolute mas/yr tolerance), the near cluster's much
    # larger absolute scatter would collapse its recovery relative to the far
    # one -- that was the actual M45-vs-NGC-6124 finding.
    multiplier = 0.6
    pm_scatter_near = multiplier * _PM_DISPERSION_KM_S / (4.74 * near_kpc)
    pm_scatter_far = multiplier * _PM_DISPERSION_KM_S / (4.74 * far_kpc)

    near = _synthetic_population(rng, near_kpc, n_members=60, n_field=100, pm_scatter_mas_yr=pm_scatter_near)
    far = _synthetic_population(rng, far_kpc, n_members=60, n_field=100, pm_scatter_mas_yr=pm_scatter_far)

    near_members = select_cluster_members(near, _literature(near_kpc), pm_dispersion_km_s=_PM_DISPERSION_KM_S)
    far_members = select_cluster_members(far, _literature(far_kpc), pm_dispersion_km_s=_PM_DISPERSION_KM_S)

    near_fraction = len(near_members) / 60
    far_fraction = len(far_members) / 60
    assert near_fraction > 0.5
    assert far_fraction > 0.5
    assert abs(near_fraction - far_fraction) < 0.3


def test_select_cluster_members_raises_when_nothing_survives():
    lit = _literature(0.5)
    gaia = pd.DataFrame({
        "parallax": [5.0], "parallax_error": [0.1],
        "pmra": [100.0], "pmdec": [100.0],
        "pmra_error": [0.1], "pmdec_error": [0.1],
    })

    with pytest.raises(RuntimeError):
        select_cluster_members(gaia, lit)


def test_select_cluster_members_requires_pm_error_columns():
    lit = _literature(0.5)
    gaia = pd.DataFrame({
        "parallax": [2.0], "parallax_error": [0.1],
        "pmra": [20.0], "pmdec": [-45.0],
    })

    # A caller passing rows without pmra_error/pmdec_error gets a clear
    # KeyError naming exactly what's missing, from the dropna(subset=...) --
    # not a silent, incorrectly-sized cut.
    with pytest.raises(KeyError):
        select_cluster_members(gaia, lit)
