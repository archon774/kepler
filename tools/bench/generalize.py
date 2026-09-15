"""Would this correctness hold on tool-use questions the model was never asked?

The per-task matrix says what happened. This module answers the separate,
harder question: a model passed 13 of our 16 questions -- what should we expect
on the seventeenth, which nobody has written yet?

**Why not a binomial interval over the sessions.** That treats 48 sessions as
48 independent draws from one urn. They are not: they are 16 questions asked
three times each, and the three repeats of one question tell you almost nothing
new about a *different* question. Worse, the binomial model has only one
parameter, so it cannot represent the thing that actually decides
generalisation -- how much the questions differ from each other. A model that
passes every easy task and fails every hard one, and a model that passes 80% of
every task, can post the same total and have completely different prospects on
a question nobody has asked.

**The model here.** Two levels, which is what the design has:

    p_t  ~  Beta(alpha, beta)        each question has its own difficulty
    y_t  ~  Binomial(m, p_t)         repeats within a question

Fitted by maximum likelihood over the per-task counts. It yields two answers to
two different questions, and conflating them is the mistake this module exists
to prevent:

``expected_rate``
    The mean of the fitted Beta -- the pass rate to expect *on average* over
    many new questions. Its interval narrows as more tasks are added, because
    it is an estimate of a population mean.

``predictive_interval``
    Where a *single* new question's pass rate is likely to fall. This does
    **not** narrow with more tasks. It is bounded below by however much the
    questions genuinely differ from one another, and for a model with uneven
    tool-use ability it is very wide no matter how much you measure. It is the
    honest answer to "will it handle the next thing I ask".

``heterogeneity``
    ``1 / (alpha + beta + 1)``: 0 when every question is equally hard for this
    model, approaching 1 when questions are all-or-nothing. It is the number
    that says how much the total can be trusted to travel.

**Measured coverage, because a nominal level is a claim and not a result.**
Simulated against corpora drawn from known populations at this suite's shape
(16 tasks, 3 repeats), nominal 95%:

===========================  ==========  ============
task population              ``E[p]``    predictive
===========================  ==========  ============
mostly-passes (Beta 8,2)         94.0%         94.5%
varied (Beta 2,2)                94.5%         89.5%
uniform (Beta 1,1)               93.5%         88.5%
all-or-nothing (Beta .5,.5)      91.0%         89.0%
homogeneous (Beta 50,50)         98.5%        100.0%
===========================  ==========  ============

The expected-rate interval holds its level. **The predictive interval runs
about six points light on heterogeneous corpora** -- a 95% label delivering
roughly 89%. That is characteristic of a Bayesian credible interval read as a
frequentist one rather than a defect, but the label would mislead, so the
measurement is published beside it and pinned by a test.

Calibrating the level away was tried and rejected: the shortfall is
population-dependent (94.5% against 88.5% at the same nominal level), so the
constant that would fix it depends on the very thing being estimated. A
calibration that needs the answer is not a calibration. Three earlier
estimators -- plug-in Beta quantiles, bootstrap refit, and Wilson over
sessions -- were discarded on the same kind of evidence; this one is kept with
its shortfall stated rather than hidden.

**What it still assumes**, and this is not a statistical question: that the 16
tasks are exchangeable with the questions a reader cares about. They are
hand-picked probes of documented failure modes, deliberately concentrated on
places models are known to fail. A model's rate on *that* population is not its
rate on a uniform sample of everyday tool calls, and no amount of arithmetic
here converts one into the other. Section 7.1.9 of ``docs/working/benchmark.md``
is where that judgement belongs.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "TaskCount",
    "Generalization",
    "fit",
    "MIN_TASKS",
]

#: Below this the fit is not attempted. Two questions cannot distinguish "these
#: tasks differ" from "this model is inconsistent", which is the entire
#: quantity being estimated.
MIN_TASKS = 4

#: Concentration bounds. kappa -> infinity is the binomial limit (all questions
#: equally hard) and kappa -> 0 is the all-or-nothing limit; both are attained
#: by degenerate data, and an unbounded optimiser walks off to infinity there.
_KAPPA_MIN = 1e-3
_KAPPA_MAX = 1e6


@dataclass(frozen=True)
class TaskCount:
    """One task's record: how many repeats passed, out of how many run."""

    task_id: str
    passed: int
    repeats: int


@dataclass(frozen=True)
class Generalization:
    """What the fit says about questions that were never asked."""

    tasks: int
    sessions: int
    observed_rate: float
    #: Beta parameters of the fitted question-difficulty distribution.
    alpha: float
    beta: float
    #: Expected pass rate on a new question, and its confidence interval.
    expected_rate: float
    expected_interval: tuple[float, float]
    #: Where one new question's own pass rate is likely to fall.
    predictive_interval: tuple[float, float]
    #: 0 = every question equally hard; ->1 = all-or-nothing questions.
    heterogeneity: float
    #: Ratio of observed to binomial variance across tasks. 1.0 means the
    #: questions were interchangeable; large means they were not.
    overdispersion: float
    #: Set when the data cannot support a fit and the result is a bound.
    degenerate: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "sessions": self.sessions,
            "observed_rate": self.observed_rate,
            "alpha": self.alpha,
            "beta": self.beta,
            "expected_rate": self.expected_rate,
            "expected_interval": list(self.expected_interval),
            "predictive_interval": list(self.predictive_interval),
            "heterogeneity": self.heterogeneity,
            "overdispersion": self.overdispersion,
            "degenerate": self.degenerate,
            "notes": list(self.notes),
        }


#: Posterior grid. Two parameters, so a grid is both feasible and preferable to
#: sampling: it is deterministic, it cannot fail to converge, and it degrades
#: gracefully on the degenerate corpora (every task passed, every task failed)
#: that break an optimiser and destabilise a bootstrap refit.
_MU_POINTS = 160
_KAPPA_POINTS = 96


def _posterior(counts: Sequence[TaskCount]):
    """Posterior over ``(mu, kappa)`` on a grid, and the grid itself.

    ``mu`` is the mean difficulty across questions and ``kappa`` the
    concentration; ``alpha = mu*kappa``, ``beta = (1-mu)*kappa``.

    Priors: uniform on ``mu``, and flat in ``log kappa`` -- scale-free, which is
    the right ignorance for a concentration that could plausibly be 0.5 or 500.
    Neither prior pulls the answer toward a conclusion; they keep the degenerate
    corners finite.
    """

    import numpy as np
    from scipy.special import betaln

    mu = np.linspace(1e-3, 1 - 1e-3, _MU_POINTS)
    kappa = np.exp(np.linspace(math.log(0.05), math.log(2000.0), _KAPPA_POINTS))
    alpha = mu[:, None] * kappa[None, :]
    beta = (1.0 - mu)[:, None] * kappa[None, :]

    loglik = np.zeros_like(alpha)
    for count in counts:
        loglik += betaln(
            count.passed + alpha, count.repeats - count.passed + beta
        ) - betaln(alpha, beta)

    loglik -= loglik.max()
    post = np.exp(loglik)
    post /= post.sum()
    return mu, kappa, alpha, beta, post


def _credible(values, weights, low: float = 0.025, high: float = 0.975):
    """Equal-tailed credible interval from a weighted 1-D marginal."""

    import numpy as np

    order = np.argsort(values)
    values, weights = np.asarray(values)[order], np.asarray(weights)[order]
    cdf = np.cumsum(weights)
    cdf /= cdf[-1]
    return (
        float(np.interp(low, cdf, values)),
        float(np.interp(high, cdf, values)),
    )


def _predictive(alpha, beta, post) -> tuple[float, float]:
    """Where one *new* question's pass rate is likely to fall.

    The posterior predictive: a mixture of ``Beta(alpha, beta)`` over the whole
    posterior, not the single best-fitting Beta. That distinction is the
    difference between a 95% claim that holds and one that does not -- plugging
    in the fitted parameters as though sixteen tasks had pinned them down
    measured 69%-87% coverage against a nominal 95%.

    It carries both sources of spread: how much questions genuinely differ, and
    how little sixteen of them establish about that.
    """

    import numpy as np
    from scipy.special import betainc

    grid = np.linspace(0.0, 1.0, 257)
    flat_a, flat_b, flat_w = alpha.ravel(), beta.ravel(), post.ravel()
    # Prune hard. The posterior is concentrated and its tail costs time without
    # moving a 2.5% quantile; 1e-6 of the peak keeps five significant figures
    # of the mixture weight.
    keep = flat_w > flat_w.max() * 1e-6
    flat_a, flat_b, flat_w = flat_a[keep], flat_b[keep], flat_w[keep]
    flat_w = flat_w / flat_w.sum()

    # One vectorised pass over (grid x posterior) rather than a Python loop.
    cdf = betainc(
        flat_a[None, :], flat_b[None, :], grid[:, None]
    ) @ flat_w
    return (
        float(np.interp(0.025, cdf, grid)),
        float(np.interp(0.975, cdf, grid)),
    )


def _moment_estimate(counts: Sequence[TaskCount]) -> tuple[float, float]:
    """Method of moments on the per-task proportions -- reported as a summary
    of the observed spread, never as the estimate the intervals come from."""

    props = [c.passed / c.repeats for c in counts]
    mean = sum(props) / len(props)
    if mean <= 0.0 or mean >= 1.0 or len(props) < 2:
        return mean, 0.0
    variance = sum((p - mean) ** 2 for p in props) / (len(props) - 1)
    room = mean * (1.0 - mean)
    if variance <= 0.0 or variance >= room:
        return mean, _KAPPA_MAX if variance <= 0.0 else _KAPPA_MIN
    return mean, min(_KAPPA_MAX, max(_KAPPA_MIN, room / variance - 1.0))


def fit(
    counts: Sequence[TaskCount],
    *,
    bootstrap_draws: int = 0,
    seed: int = 20260914,
) -> Generalization | None:
    """Fit the two-level model. ``None`` when there are too few tasks.

    ``bootstrap_draws`` and ``seed`` are accepted and ignored: the estimator is
    a deterministic posterior grid, so two runs over the same corpus give the
    same interval. They remain in the signature because a caller should not
    have to know which estimator is in use to ask the question.
    """

    import numpy as np

    counts = [c for c in counts if c.repeats > 0]
    if len(counts) < MIN_TASKS:
        return None

    sessions = sum(c.repeats for c in counts)
    passed = sum(c.passed for c in counts)
    observed = passed / sessions
    props = [c.passed / c.repeats for c in counts]
    mean_prop = sum(props) / len(props)

    notes: list[str] = []
    degenerate: str | None = None
    if all(p == 1.0 for p in props):
        degenerate = "every task passed every repeat"
        notes.append(
            "No failure was seen, so nothing here separates a model that "
            "always succeeds from one whose failure rate is simply below what "
            "this many questions can resolve. The lower bound is the result; "
            "the upper bound is an artefact of the corpus size."
        )
    elif all(p == 0.0 for p in props):
        degenerate = "no task passed any repeat"

    mu, kappa, alpha, beta, post = _posterior(counts)

    # Marginal over mu: the expected pass rate on a new question.
    mu_weights = post.sum(axis=1)
    expected = float((mu * mu_weights).sum() / mu_weights.sum())
    expected_interval = _credible(mu, mu_weights)
    predictive = _predictive(alpha, beta, post)

    # Heterogeneity, posterior mean of 1/(kappa+1): 0 when every question is
    # equally hard for this model, approaching 1 when they are all-or-nothing.
    kappa_weights = post.sum(axis=0)
    heterogeneity = float(
        ((1.0 / (kappa + 1.0)) * kappa_weights).sum() / kappa_weights.sum()
    )

    m = sessions / len(counts)
    binomial_var = mean_prop * (1.0 - mean_prop) / m if 0 < mean_prop < 1 else 0.0
    observed_var = (
        sum((p - mean_prop) ** 2 for p in props) / (len(props) - 1)
        if len(props) > 1
        else 0.0
    )
    overdispersion = observed_var / binomial_var if binomial_var > 0 else 1.0
    if overdispersion > 1.5:
        notes.append(
            f"Questions vary {overdispersion:.1f}x more than one common rate "
            "would produce, so the headline total travels poorly: it is an "
            "average over unlike questions."
        )

    _, kappa_moment = _moment_estimate(counts)

    return Generalization(
        tasks=len(counts),
        sessions=sessions,
        observed_rate=observed,
        alpha=float((alpha * post).sum()),
        beta=float((beta * post).sum()),
        expected_rate=expected,
        expected_interval=expected_interval,
        predictive_interval=predictive,
        heterogeneity=heterogeneity,
        overdispersion=overdispersion,
        degenerate=degenerate,
        notes=tuple(notes),
    )
