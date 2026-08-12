"""algorithms.radio.spectral_fitting - flux vs. frequency model fitting.

Radio (and more generally non-thermal) source spectra are conventionally
described as a power law in flux density vs. frequency, ``S_nu ~ nu **
spectral_index`` -- a straight line in log-log space. A synchrotron source is
typically optically thin at radio frequencies, giving a *negative* spectral
index (flux declining with frequency, roughly -0.5 to -1.0); a flatter or
positive index suggests self-absorption or a thermal (free-free) component.

Every model here is fit against the *same* target, ``log10(flux)`` -- so
their R^2 values are directly comparable. (An earlier draft of this fit
compared R^2 across models fit to different targets -- raw flux, log flux,
flux vs. log frequency -- which produces R^2 values that are not
commensurable; "highest R^2 wins" was comparing unlike quantities. Kept as a
recorded lesson, not a defect being preserved -- there is no upstream to
match here.)
"""

from __future__ import annotations

import warnings

import numpy as np

__all__ = [
    "fit_power_law",
    "fit_log_parabola",
    "evaluate_power_law",
    "evaluate_log_parabola",
    "analyze_spectrum",
]

#: Minimum R^2 improvement the log-parabola (3 free parameters) must show over
#: the power law (2 free parameters) before curvature is reported as real
#: rather than the extra parameter fitting noise.
_CURVATURE_R2_MARGIN = 0.02


def _valid_mask(freq_hz: np.ndarray, flux: np.ndarray) -> np.ndarray:
    return np.isfinite(freq_hz) & np.isfinite(flux) & (freq_hz > 0) & (flux > 0)


def fit_power_law(freq_hz, flux, flux_err=None) -> dict:
    """Fit ``S_nu = amplitude * nu ** spectral_index`` via log-log OLS.

    ``flux_err``, if given, inverse-variance-weights the fit (propagated into
    log space: sigma_log10(flux) = flux_err / (flux * ln(10))). Points with
    non-finite or non-positive frequency/flux (or error) are dropped silently
    -- a log fit cannot use them and radio catalogs commonly carry upper
    limits or masked values that fail this check.
    """
    freq_hz = np.asarray(freq_hz, dtype=float)
    flux = np.asarray(flux, dtype=float)
    mask = _valid_mask(freq_hz, flux)

    weights = None
    if flux_err is not None:
        flux_err = np.asarray(flux_err, dtype=float)
        mask &= np.isfinite(flux_err) & (flux_err > 0)

    if mask.sum() < 2:
        raise ValueError("fit_power_law needs at least 2 valid (frequency, flux) points")

    x = np.log10(freq_hz[mask])
    y = np.log10(flux[mask])
    if flux_err is not None:
        sigma_y = flux_err[mask] / (flux[mask] * np.log(10.0))
        weights = 1.0 / sigma_y

    # cov=True needs strictly more points than free parameters (here, >2) to
    # scale a covariance matrix at all -- fit_power_law's own floor is 2, so
    # the minimal case falls back to an uncertainty-free fit rather than
    # raising. A near-singular fit can also return a non-finite covariance;
    # both are reported as "not available," never as 0 or inf.
    slope_error = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            (slope, intercept), cov = np.polyfit(x, y, 1, w=weights, cov=True)
        if np.all(np.isfinite(cov)):
            slope_error = float(np.sqrt(cov[0, 0]))
    except (ValueError, np.linalg.LinAlgError):
        slope, intercept = np.polyfit(x, y, 1, w=weights)

    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    return {
        "spectral_index": float(slope),
        "spectral_index_error": slope_error,
        "amplitude": float(10.0 ** intercept),
        "r_squared": float(r_squared),
        "n_points": int(mask.sum()),
    }


def evaluate_power_law(freq_hz, amplitude: float, spectral_index: float) -> np.ndarray:
    """``S_nu`` predicted by a `fit_power_law` result at arbitrary frequencies."""
    return amplitude * np.power(np.asarray(freq_hz, dtype=float), spectral_index)


def fit_log_parabola(freq_hz, flux) -> dict | None:
    """Fit ``log10(S_nu) = curvature*x**2 + spectral_index_at_ref*x + log_amplitude``,
    ``x = log10(nu)`` -- a quadratic in log-log space, for spectral turnover
    (self-absorption at low frequencies, or a high-frequency cutoff).

    Returns ``None`` with fewer than 4 valid points: a 3-parameter fit to 3
    points is exact (R^2 = 1 by construction) and reports nothing about
    curvature being real.
    """
    freq_hz = np.asarray(freq_hz, dtype=float)
    flux = np.asarray(flux, dtype=float)
    mask = _valid_mask(freq_hz, flux)
    if mask.sum() < 4:
        return None

    x = np.log10(freq_hz[mask])
    y = np.log10(flux[mask])

    # Same "not available" fallback as fit_power_law -- the 4-point floor
    # above is exactly enough for cov=True (order=2 needs n>2), but a
    # near-singular fit can still return a non-finite covariance.
    spectral_index_at_ref_error = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            (curvature, spectral_index_at_ref, log_amplitude), cov = np.polyfit(x, y, 2, cov=True)
        if np.all(np.isfinite(cov)):
            spectral_index_at_ref_error = float(np.sqrt(cov[1, 1]))
    except (ValueError, np.linalg.LinAlgError):
        curvature, spectral_index_at_ref, log_amplitude = np.polyfit(x, y, 2)

    y_pred = curvature * x**2 + spectral_index_at_ref * x + log_amplitude
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    return {
        "curvature": float(curvature),
        "spectral_index_at_ref": float(spectral_index_at_ref),
        "spectral_index_at_ref_error": spectral_index_at_ref_error,
        "log_amplitude": float(log_amplitude),
        "r_squared": float(r_squared),
        "n_points": int(mask.sum()),
    }


def evaluate_log_parabola(freq_hz, curvature: float, spectral_index_at_ref: float,
                          log_amplitude: float) -> np.ndarray:
    """``S_nu`` predicted by a `fit_log_parabola` result at arbitrary frequencies."""
    x = np.log10(np.asarray(freq_hz, dtype=float))
    return 10.0 ** (curvature * x**2 + spectral_index_at_ref * x + log_amplitude)


def analyze_spectrum(freq_hz, flux, flux_err=None,
                     curvature_r2_margin: float = _CURVATURE_R2_MARGIN) -> dict:
    """Fit both models and report which one the data actually supports.

    The log-parabola only wins when it both exists (>=4 points) and clears
    ``curvature_r2_margin`` over the power law -- otherwise the extra
    parameter is presumed to be fitting noise, and the power law (with its
    directly meaningful ``spectral_index``) is reported.
    """
    power_law = fit_power_law(freq_hz, flux, flux_err)
    log_parabola = fit_log_parabola(freq_hz, flux)

    best_model = "power_law"
    if log_parabola is not None and (log_parabola["r_squared"] - power_law["r_squared"]) > curvature_r2_margin:
        best_model = "log_parabola"

    return {
        "best_model": best_model,
        "spectral_index": power_law["spectral_index"],
        "spectral_index_error": power_law["spectral_index_error"],
        "power_law": power_law,
        "log_parabola": log_parabola,
    }
