"""Variable-star period folding with upstream row and display semantics.

# PORTED: algorithms/lightcurve/variable/variable-lightcurve.algorithms.ts
# PORTED: algorithms/lightcurve/variable/variable-period-folding.algorithms.ts
"""

from __future__ import annotations

from typing import Sequence

from algorithms.variable_star.lightcurve import (
    VariableDataRow,
    differential_data,
    differential_errors,
    jd_range,
)


def _float_mod(value: float, modulus: float) -> float:
    """Mirror the TypeScript helper's deliberately strict ``>`` loop."""
    while value > modulus:
        value -= modulus
    return value


def fold_with_error(
    rows: Sequence[VariableDataRow],
    variable_star: str,
    reference_star_magnitude: float,
    *,
    period: float = -1,
    phase: float = 0.0,
    display_periods: int = 2,
) -> tuple[list[tuple[float, float]], list[tuple[float, float, float]]]:
    """Fold differential data and error bars exactly as the variable service.

    The intentionally separate filters retain the original index-alignment
    fragility when a paired row has no combined error.
    """
    if variable_star == "none":
        return [], []
    data = sorted(differential_data(rows, variable_star, reference_star_magnitude))
    errors = sorted(differential_errors(rows, variable_star, reference_star_magnitude))
    chosen_period = jd_range(rows) if period < 0 else period
    folded_data: list[tuple[float, float]] = []
    folded_errors: list[tuple[float, float, float]] = []
    if chosen_period != 0:
        min_jd = data[0][0]
        for index, (jd, magnitude) in enumerate(data):
            x = phase * chosen_period + _float_mod(jd - min_jd, chosen_period)
            if x > chosen_period:
                x -= chosen_period
            error = errors[index]
            folded_data.append((x, magnitude))
            folded_errors.append((x, error[1], error[2]))
            if display_periods == 2:
                folded_data.append((x + chosen_period, magnitude))
                folded_errors.append((x + chosen_period, error[1], error[2]))
    return (
        sorted(folded_data, key=lambda row: row[0], reverse=True),
        sorted(folded_errors, key=lambda row: row[0], reverse=True),
    )


def get_period_step(period_folding_period: float, observation_range: float) -> float:
    """Return the folding-slider step from the extracted form component."""
    value = period_folding_period**2 * 0.01 / observation_range
    return float(f"{value:.4f}") if value > 10e-6 else 10e-6
