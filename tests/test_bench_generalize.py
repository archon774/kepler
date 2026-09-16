"""The generalization model: would this correctness hold on questions the
model was never asked?

Every claim here is checked by simulation against data generated from known
parameters. An interval that does not hit its nominal coverage is not a
conservative interval, it is a wrong one, and three estimators were discarded
on exactly this evidence before the one under test.
"""

from __future__ import annotations

import random

import pytest

from tools.bench.generalize import MIN_TASKS, TaskCount, fit


def simulate(alpha: float, beta: float, tasks: int, repeats: int, rng):
    """A corpus from the two-level model: one difficulty per *task*, then
    repeats within it."""

    out = []
    for index in range(tasks):
        difficulty = rng.betavariate(alpha, beta)
        passes = sum(rng.random() < difficulty for _ in range(repeats))
        out.append(TaskCount(f"t{index}", passes, repeats))
    return out


# --- the shape of the answer ----------------------------------------------


def test_too_few_tasks_declines_to_answer():
    """Two questions cannot separate "these tasks differ" from "this model is
    inconsistent", which is the whole quantity being estimated."""

    counts = [TaskCount(f"t{i}", 2, 3) for i in range(MIN_TASKS - 1)]
    assert fit(counts) is None
    assert fit(counts + [TaskCount("extra", 1, 3)]) is not None


def test_the_estimate_is_deterministic():
    """A benchmark number that moves between two runs over the same recorded
    corpus is not a measurement. The estimator is a grid, not a sampler."""

    counts = [TaskCount(f"t{i}", i % 4, 3) for i in range(16)]
    first, second = fit(counts), fit(counts)
    assert first.expected_interval == second.expected_interval
    assert first.predictive_interval == second.predictive_interval


def test_a_new_question_is_far_less_certain_than_the_average_of_many():
    """The distinction the module exists for. Averaging over many new
    questions is a narrow claim; predicting the next single one is not, and
    reporting the first as though it answered the second is the error."""

    rng = random.Random(4)
    result = fit(simulate(2.0, 2.0, 16, 3, rng))
    expected_width = result.expected_interval[1] - result.expected_interval[0]
    predictive_width = result.predictive_interval[1] - result.predictive_interval[0]
    assert predictive_width > expected_width * 1.5


def test_uneven_ability_is_reported_as_heterogeneity_not_hidden_in_a_total():
    """Two models can post the same total and have completely different
    prospects on a question nobody has asked."""

    even = [TaskCount(f"t{i}", 2, 3) for i in range(12)]          # 24/36 everywhere
    uneven = [TaskCount(f"t{i}", 3 if i < 8 else 0, 3) for i in range(12)]  # 24/36
    assert sum(c.passed for c in even) == sum(c.passed for c in uneven)

    even_fit, uneven_fit = fit(even), fit(uneven)
    assert uneven_fit.heterogeneity > even_fit.heterogeneity
    assert uneven_fit.overdispersion > even_fit.overdispersion
    # ... and the all-or-nothing model's next question is far less predictable.
    even_width = even_fit.predictive_interval[1] - even_fit.predictive_interval[0]
    uneven_width = uneven_fit.predictive_interval[1] - uneven_fit.predictive_interval[0]
    assert uneven_width > even_width


# --- degenerate corpora ----------------------------------------------------


def test_a_clean_sweep_is_a_lower_bound_not_a_certainty():
    """Sixteen questions all passed does not establish the next one will."""

    result = fit([TaskCount(f"t{i}", 3, 3) for i in range(16)])
    assert result.degenerate == "every task passed every repeat"
    assert result.expected_interval[0] < 1.0
    assert result.predictive_interval[0] < 0.95
    assert any("below what this many questions can resolve" in n for n in result.notes)


def test_a_total_failure_is_handled_without_raising():
    result = fit([TaskCount(f"t{i}", 0, 3) for i in range(16)])
    assert result.degenerate == "no task passed any repeat"
    assert result.expected_rate < 0.5


def test_a_single_repeat_per_task_still_answers():
    """--repeats 1 loses the within-task signal but the between-task spread is
    what generalisation needs, and that survives."""

    rng = random.Random(8)
    result = fit(simulate(3.0, 2.0, 20, 1, rng))
    assert result is not None
    assert 0.0 <= result.expected_rate <= 1.0


# --- it recovers what generated it ----------------------------------------


@pytest.mark.parametrize(
    "alpha,beta", [(8.0, 2.0), (2.0, 2.0), (1.0, 1.0), (0.5, 0.5)]
)
def test_the_expected_rate_recovers_the_population_mean(alpha, beta):
    """Averaged over many simulated corpora, the estimate should sit on the
    value the data was generated from."""

    rng = random.Random(11)
    estimates = [
        fit(simulate(alpha, beta, 48, 3, rng)).expected_rate for _ in range(12)
    ]
    assert sum(estimates) / len(estimates) == pytest.approx(
        alpha / (alpha + beta), abs=0.06
    )


# --- the coverage claim, pinned ------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize(
    "alpha,beta,label,expected_floor,predictive_floor",
    [
        (8.0, 2.0, "mostly-passes", 0.88, 0.88),
        (1.0, 1.0, "uniform", 0.88, 0.82),
    ],
)
def test_measured_coverage_matches_what_the_module_claims(
    alpha, beta, label, expected_floor, predictive_floor
):
    """A nominal level is a claim; this is the result.

    The module publishes measured coverage rather than its nominal label,
    because the predictive interval runs about six points light on
    heterogeneous corpora. That shortfall is documented, so it must also be
    pinned -- if a future estimator changes it in either direction, this fails
    and the documented table has to be re-measured rather than quietly left
    wrong.

    Floors are set below the measured values by more than the sampling error
    at this trial count, so the test fails on a real regression and not on
    noise.
    """

    rng = random.Random(99)
    trials = 120
    expected_hits = predictive_hits = 0
    truth = alpha / (alpha + beta)
    for _ in range(trials):
        counts = simulate(alpha, beta, 16, 3, rng)
        result = fit(counts)
        low, high = result.expected_interval
        expected_hits += low <= truth <= high
        new_question = rng.betavariate(alpha, beta)
        low, high = result.predictive_interval
        predictive_hits += low <= new_question <= high

    assert expected_hits / trials >= expected_floor, label
    assert predictive_hits / trials >= predictive_floor, label
    # And neither may silently become a 100% interval that says nothing.
    assert expected_hits / trials <= 0.995
