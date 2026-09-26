"""Error-weighted variable-star Lomb--Scargle computation.

# PORTED: git-history:algorithms/periodogram/core/lomb-scargle.ts::lombScargleWithError
# PORTED: git-history:algorithms/periodogram/variable/variable-periodogram.compute.ts
"""

from __future__ import annotations

from math import atan2, cos, exp, inf, log, nan, pi, sin
from typing import Sequence

from algorithms.variable_star.lightcurve import VariableDataRow, differential_data


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _variance(values: Sequence[float]) -> float:
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _error_mean(values: Sequence[float], errors: Sequence[float]) -> float:
    weights = [1 / error**2 for error in errors]
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def _error_dot(left: Sequence[float], errors: Sequence[float], right: Sequence[float]) -> float:
    weights = [1 / error**2 for error in errors]
    products = [a * b for a, b in zip(left, right, strict=True)]
    return sum(value * weight for value, weight in zip(products, weights, strict=True)) / sum(weights)


def _ieee_divide(numerator: float, denominator: float) -> float:
    """Match JavaScript number division where Python would raise on zero."""
    if denominator != 0:
        return numerator / denominator
    if numerator == 0:
        return nan
    return inf if numerator > 0 else -inf


def lomb_scargle_with_error(
    times: Sequence[float],
    values: Sequence[float],
    errors: Sequence[float],
    start: float,
    stop: float,
    steps: int = 1000,
) -> list[tuple[float, float]]:
    """Return the exact error-weighted, logarithmic-period spectrum.

    The length mismatch behavior is made explicit as ``ValueError`` at the
    Python boundary; valid inputs retain the TypeScript arithmetic unchanged.
    """
    if len(times) != len(values):
        raise ValueError("Dimension mismatch between time array and value array.")
    step = (stop - start) / steps
    residue_mean = _error_mean(values, errors)
    residues = [value - residue_mean for value in values]
    two_variance = 2 * _variance(values)
    result: list[tuple[float, float]] = []
    x_value = start
    index = 0
    while x_value < stop:
        period = exp(log(start) + (log(stop) - log(start)) * index / steps)
        omega = 2 * pi / period
        two_omega_times = [2 * omega * value for value in times]
        tau = atan2(sum(sin(value) for value in two_omega_times), sum(cos(value) for value in two_omega_times)) / (2 * omega)
        shifted = [omega * (value - tau) for value in times]
        cos_values = [cos(value) for value in shifted]
        sin_values = [sin(value) for value in shifted]
        power = _ieee_divide(
            _ieee_divide(
                _error_dot(residues, errors, cos_values) ** 2,
                sum(value * value for value in cos_values),
            )
            + _ieee_divide(
                _error_dot(residues, errors, sin_values) ** 2,
                sum(value * value for value in sin_values),
            ),
            two_variance,
        )
        result.append((period, power))
        x_value += step
        index += 1
    return result


def variable_periodogram(
    rows: Sequence[VariableDataRow],
    variable_star: str,
    reference_star_magnitude: float,
    start: float,
    stop: float,
) -> list[tuple[float, float]]:
    """Compute the variable tool's fixed-2,000-sample periodogram."""
    data = differential_data(rows, variable_star, reference_star_magnitude)
    errors = [
        row.error_mse
        for row in rows
        if row.jd is not None
        and row.source1 is not None
        and row.source2 is not None
        and row.error_mse is not None
    ]
    return lomb_scargle_with_error(
        [row[0] for row in data], [row[1] for row in data], errors, start, stop, 2000
    )
