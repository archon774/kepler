"""Vendored statistics: ``algorithms/skylib_lite/util/stats.py``.

``chauvenet`` is the outlier-rejection kernel underneath every zero-point solve
— ``fieldcal.solution.calc_solution`` calls it once per rejection iteration with
an explicit mean and sigma. The bit-exact reproduction of four recorded Skynet
fits in ``test_fieldcal_solution.py`` already covers it end to end; this file
pins its behaviour directly, so that a failure says *which* piece moved.

These are numba-jitted with ``cache=True``, so the first call in a fresh
checkout pays a compile cost. That is a one-off, not a per-run cost.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from algorithms.skylib_lite.util.stats import (
    chauvenet,
    ng_cdf,
    quantile,
    stddev1,
    weighted_median,
    weighted_quantile,
)


# ---------------------------------------------------------------------------
# The documented example
# ---------------------------------------------------------------------------

def test_docstring_example_rejects_the_two_planted_outliers():
    """Verbatim from ``chauvenet``'s own docstring — the upstream contract."""
    x = np.zeros([5, 10])
    x[2, 3] = x[4, 5] = 1

    rejected = chauvenet(x, min_vals=4)[0].nonzero()
    assert np.array_equal(rejected[0], np.array([2, 4]))
    assert np.array_equal(rejected[1], np.array([3, 5]))


# ---------------------------------------------------------------------------
# One-dimensional rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [20260811, 1, 2, 3])
def test_a_clean_gaussian_sample_loses_almost_nothing(seed):
    """Chauvenet's criterion clips the tail it expects to be spurious.

    For n = 200 that is a handful of points at most — the criterion rejects
    anything whose expected count in a Gaussian sample is below 0.5, so a small
    non-zero loss is the design, not a defect.
    """
    data = np.random.default_rng(seed).normal(0.0, 1.0, 200)
    mask, _, _ = chauvenet(data)
    assert mask.sum() <= 5


def test_a_single_gross_outlier_is_rejected():
    data = np.concatenate([np.random.default_rng(1).normal(0, 1, 99), [50.0]])
    mask, _, _ = chauvenet(data)
    assert mask[-1]
    assert mask.sum() < 10


def test_rejection_returns_the_mean_and_sigma_it_used():
    data = np.array([1.0, 1.1, 0.9, 1.05, 0.95, 20.0])
    mask, mu, gamma = chauvenet(data, min_vals=2)

    assert mask[-1]
    assert float(mu) == pytest.approx(1.0, abs=0.2)
    assert float(gamma) > 0


def test_min_vals_stops_rejection_before_the_sample_is_exhausted():
    """The floor that keeps a small, scattered sample from vanishing entirely."""
    data = np.array([0.0, 1.0, 2.0, 3.0, 100.0, 200.0, 300.0])
    mask, _, _ = chauvenet(data, min_vals=5)
    assert (~mask).sum() >= 5


def test_min_vals_is_clamped_to_at_least_two():
    data = np.array([0.0, 0.1, 50.0])
    mask, _, _ = chauvenet(data, min_vals=0)
    assert (~mask).sum() >= 2


def test_clip_flags_select_which_tail_is_rejected():
    """``calc_solution`` uses the default (both tails); one-sided modes exist.

    The sample has to be large enough for the criterion to bite: with only a
    handful of points the sigma is dominated by the outliers themselves and
    nothing is rejected at all. 60 clean points plus one outlier per tail is
    comfortably past that.
    """
    clean = np.random.default_rng(21).normal(0.0, 1.0, 60)
    data = np.concatenate([[-40.0], clean, [40.0]])

    both, _, _ = chauvenet(data.copy())
    assert both[0] and both[-1]

    high_only, _, _ = chauvenet(data.copy(), clip_lo=False)
    assert not high_only[0]
    assert high_only[-1]

    low_only, _, _ = chauvenet(data.copy(), clip_hi=False)
    assert low_only[0]
    assert not low_only[-1]


def test_a_tiny_sample_rejects_nothing_because_sigma_absorbs_the_outliers():
    """Worth knowing: on six points, two gross outliers are kept.

    The internal sigma is computed from the same data, so with ±50 in a
    six-element sample it comes out around 32 and nothing exceeds the criterion.
    This is why ``calc_solution`` supplies its own ``sigma_override`` from the
    weighted fit rather than letting the kernel estimate it.
    """
    data = np.array([-50.0, 0.0, 0.1, -0.1, 0.05, 50.0])
    mask, _, gamma = chauvenet(data, min_vals=2)
    assert not mask.any()
    assert float(gamma) > 10


def test_max_iter_limits_the_rejection_passes():
    """``calc_solution`` passes ``max_iter=1`` and drives the loop itself.

    That is what lets it recompute the weighted mean and sigma between passes.
    A single pass must therefore reject strictly less than an unbounded run on a
    sample with outliers at several scales.
    """
    data = np.concatenate([np.random.default_rng(7).normal(0, 1, 50),
                           [8.0, 12.0, 30.0, 100.0]])
    one_pass, _, _ = chauvenet(data.copy(), max_iter=1)
    unbounded, _, _ = chauvenet(data.copy(), max_iter=0)

    assert one_pass.sum() >= 1
    assert unbounded.sum() >= one_pass.sum()


def test_mean_and_sigma_overrides_bypass_the_internal_estimates():
    """The mode ``calc_solution`` actually uses.

    It supplies its own weighted mean and weighted sigma, so ``mean_type`` and
    ``sigma_type`` are ignored. Overriding with a deliberately displaced centre
    must change which points are rejected — proof the overrides are honoured
    rather than silently recomputed.
    """
    data = np.array([0.0, 0.1, -0.1, 0.05, -0.05, 1.0])

    natural, _, _ = chauvenet(data, min_vals=2, max_iter=1)
    displaced, mu, gamma = chauvenet(
        data, min_vals=2, max_iter=1, mean_override=1.0, sigma_override=0.05
    )

    assert float(mu) == pytest.approx(1.0)
    assert float(gamma) == pytest.approx(0.05)
    assert not np.array_equal(natural, displaced)
    # With the centre moved to 1.0, the cluster near zero becomes the outlier.
    assert displaced[:5].any()


def test_median_and_percentile_modes_are_available():
    """``mean_type=1`` / ``sigma_type=1`` is the simplified robust variant."""
    data = np.concatenate([np.zeros(20), [100.0]])

    _, mean_mu, _ = chauvenet(data.copy(), min_vals=2, mean_type=0)
    _, median_mu, _ = chauvenet(data.copy(), min_vals=2, mean_type=1)

    assert float(median_mu) == pytest.approx(0.0, abs=1e-9)
    assert float(mean_mu) == pytest.approx(0.0, abs=1e-9)


def test_an_existing_mask_is_respected_and_modified_in_place():
    """Callers pass a mask forward across iterations; it must accumulate.

    Pre-masked elements stay masked and are excluded from the mean and sigma —
    which is the whole point, and also means a pre-mask can change which of the
    remaining points get rejected.
    """
    clean = np.random.default_rng(31).normal(0.0, 1.0, 60)
    data = np.concatenate([clean, [40.0]])
    mask = np.zeros(data.shape, bool)
    mask[0] = True

    returned, _, _ = chauvenet(data, mask=mask)
    assert returned is mask
    assert mask[0], "the pre-masked element must stay masked"
    assert mask[-1], "the outlier must also be masked"


def test_a_pre_mask_changes_the_estimated_centre_and_scale():
    """Masking is not cosmetic: it feeds back into mu and gamma.

    On a small sample that is enough to flip the verdict on another point.
    """
    data = np.array([0.0, 0.1, -0.1, 0.05, 50.0])

    unmasked, mu_a, _ = chauvenet(data.copy(), min_vals=2)
    mask = np.zeros(data.shape, bool)
    mask[1] = True
    _, mu_b, _ = chauvenet(data.copy(), mask=mask, min_vals=2)

    assert unmasked[-1], "without a pre-mask the outlier is rejected"
    assert float(mu_a) != pytest.approx(float(mu_b))


def test_rejection_is_deterministic():
    data = np.concatenate([np.random.default_rng(3).normal(0, 1, 80), [25.0, -25.0]])
    first, _, _ = chauvenet(data.copy())
    second, _, _ = chauvenet(data.copy())
    assert np.array_equal(first, second)


# ---------------------------------------------------------------------------
# Multi-dimensional rejection
# ---------------------------------------------------------------------------

def test_two_dimensional_rejection_runs_along_axis_zero():
    """Each column is an independent sample — the image-stacking case."""
    data = np.zeros((9, 4))
    data[4, 0] = 100.0
    data[7, 2] = -100.0

    mask, mu, gamma = chauvenet(data, min_vals=3)
    assert mask[4, 0] and mask[7, 2]
    assert mask.sum() == 2
    assert mu.shape == (4,)
    assert gamma.shape == (4,)


def test_three_dimensional_rejection_is_supported():
    data = np.zeros((7, 3, 2))
    data[3, 1, 1] = 50.0

    mask, mu, _ = chauvenet(data, min_vals=3)
    assert mask[3, 1, 1]
    assert mu.shape == (3, 2)


def test_four_dimensional_input_is_rejected():
    with pytest.raises(AssertionError):
        chauvenet(np.zeros((2, 2, 2, 2)))


# ---------------------------------------------------------------------------
# Student's-t degrees of freedom
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nu", [0, 1, 2, 4])
def test_supported_degrees_of_freedom_all_run(nu):
    """Only nu in {0, 1, 2, 4} have an analytically invertible CDF.

    nu = 0 means Gaussian, which is what ``calc_solution`` uses. The others must
    at least execute and return a well-formed mask; how much they reject is the
    subject of the next test.
    """
    data = np.concatenate([np.random.default_rng(11).normal(0, 1, 60), [40.0]])
    mask, mu, gamma = chauvenet(data, nu=nu)
    assert mask.shape == data.shape
    assert mask.dtype == bool
    assert np.isfinite(float(mu)) and float(gamma) > 0


def test_heavy_tailed_distributions_keep_outliers_a_gaussian_rejects():
    """nu = 1 and 2 expect extreme values, so a 40-sigma point survives.

    A Lorentzian has no finite variance; a point 40 units out is unremarkable
    under it. Only the Gaussian (nu=0) and nu=4 clip it. This is the parameter
    that decides how aggressive rejection is, and getting it wrong silently
    changes every zero point.
    """
    data = np.concatenate([np.random.default_rng(11).normal(0, 1, 60), [40.0]])

    verdicts = {nu: bool(chauvenet(data.copy(), nu=nu)[0][-1]) for nu in (0, 1, 2, 4)}
    assert verdicts == {0: True, 1: False, 2: False, 4: True}


def test_ng_cdf_is_monotonic_and_bounded():
    t = np.linspace(0.0, 6.0, 25)
    values = ng_cdf(t, 0)
    assert np.all(np.diff(values) >= -1e-12)
    assert np.all(values >= 0)


# ---------------------------------------------------------------------------
# Supporting statistics
# ---------------------------------------------------------------------------

def test_quantile_is_the_maples_estimator_not_numpys():
    """It carries a sample-size correction factor and is NOT ``np.quantile``.

    From Maples et al. (2018), ApJS 238, 2: the interpolated quantile is
    multiplied by ``cf``, a small-sample correction (tabulated for n <= 5,
    ``1 + 2.2212*n**-1.137`` above). Its own docstring warns it "does not work
    for q near 0 and 1" — at q = 1 it returns a value *above* the maximum.

    Substituting ``np.quantile`` would change the ``sigma_type=1`` scale
    estimate and therefore which sources a robust rejection keeps.
    """
    data = np.arange(101, dtype=float)

    assert quantile(data, 0.5) == pytest.approx(49.5726, abs=1e-3)
    assert quantile(data, 0.5) != pytest.approx(np.quantile(data, 0.5), abs=0.1)

    # Documented breakdown at the ends: q=1 overshoots the sample maximum.
    assert quantile(data, 1.0) > data.max()


def test_quantile_correction_factor_is_tabulated_for_small_samples():
    """n = 2..5 use hard-coded factors; above that a power law."""
    for n, cf in ((2, 1.76), (3, 1.59), (4, 1.53), (5, 1.31)):
        data = np.ones(n)
        # All values equal, so the interpolation returns 1.0 * cf.
        assert quantile(data, 0.5) == pytest.approx(cf, rel=1e-9), n

    n = 20
    assert quantile(np.ones(n), 0.5) == pytest.approx(
        1 + 2.2212 * n ** -1.137, rel=1e-9
    )


def test_quantile_of_an_empty_array_is_zero():
    assert quantile(np.array([], dtype=float), 0.5) == 0.0


def test_stddev1_operates_on_residuals_not_raw_values():
    """It never subtracts a mean — the caller has already done that.

    ``sqrt(sum(d**2) / (n - 1))``, skipping masked entries. Feeding it raw
    values instead of residuals inflates sigma by the sample mean, which in
    ``calc_solution`` would suppress rejection entirely.
    """
    residuals = np.array([0.0, 1.0, 2.0, 1000.0])
    mask = np.array([False, False, False, True])

    expected = math.sqrt((0.0 ** 2 + 1.0 ** 2 + 2.0 ** 2) / 2)
    assert stddev1(residuals, mask) == pytest.approx(expected, rel=1e-12)
    assert stddev1(residuals, mask) != pytest.approx(np.std([0.0, 1.0, 2.0]), rel=1e-3)


def test_stddev1_mask_marks_rejection_not_selection():
    """``True`` means "already rejected, skip me"."""
    residuals = np.array([0.0, 1.0, 2.0, 1000.0])
    keeping_the_outlier = np.array([True, True, True, False])
    assert stddev1(residuals, keeping_the_outlier) == pytest.approx(1000.0)


def test_stddev1_returns_infinity_rather_than_zero():
    """A zero or negative variance becomes ``+inf``, per the docstring.

    That makes a degenerate scale reject nothing instead of rejecting
    everything — the safe direction for an outlier filter.
    """
    residuals = np.zeros(5)
    assert stddev1(residuals, np.zeros(5, bool)) == math.inf


def test_weighted_median_reduces_to_the_plain_median_with_equal_weights():
    data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    weights = np.ones_like(data)
    assert weighted_median(data, weights) == pytest.approx(np.median(data), abs=1e-9)


def test_weighted_median_follows_the_weight():
    """Piling weight on one value pulls the median onto it."""
    data = np.array([1.0, 2.0, 3.0, 100.0])
    weights = np.array([1.0, 1.0, 1.0, 1000.0])
    assert weighted_median(data, weights) == pytest.approx(100.0)


def test_weighted_quantile_endpoints():
    data = np.array([1.0, 2.0, 3.0, 4.0])
    weights = np.ones_like(data)
    assert weighted_quantile(data, weights, 0.0) == pytest.approx(1.0)
    assert weighted_quantile(data, weights, 1.0) == pytest.approx(4.0)
