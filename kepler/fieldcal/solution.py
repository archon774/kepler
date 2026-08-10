"""Zero-point solution: weighted mean magnitude offset with Chauvenet rejection.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/utils.py
lines 468-603 (``_sigma_eq``, ``calc_solution``), copied verbatim.

``skynet_db/runners/utils.py`` is a 907-line grab-bag (S3 download helpers,
FITS product writers, VizieR cache pruning, header parsing, WCS box helpers,
DB session plumbing).  Only the zero-point solver lives here; the reference
magnitude resolver from the same file lives in ``ref_mag.py``.
"""
from __future__ import annotations

import logging

import numpy as np
from numpy import transpose

# EXTRACTED: was `from skylib.util.stats import chauvenet` (installed skylib
# package) — now the shared vendored copy under kepler.skylib_lite.
# ``chauvenet`` is the outlier-rejection kernel of this solver; it is
# numba-jitted and numba is a hard runtime dependency, not an optional
# accelerator.
from kepler.skylib_lite.util.stats import chauvenet

from .schemas import PhotometryData

__all__ = ["calc_solution"]

logger = logging.getLogger(__name__)


# util.py (keep/ensure these exist)
def _sigma_eq(sigma2, sigmas2, b, m0):
    w = 1.0 / (sigmas2 + sigma2)
    return (((b - m0) ** 2 * w - 1) * w).sum()

def calc_solution(sources: list[PhotometryData]):
    from math import sqrt
    from scipy.optimize import brenth

    if not sources:
        return np.nan, np.nan, np.nan, np.nan, 100.0

    mags, mag_errors, ref_mags, ref_mag_errors = transpose([
        (
            source.mag,
            getattr(source, "mag_error", None) or 0,
            source.ref_mag,
            getattr(source, "ref_mag_error", None) or 0,
        )
        for source in sources
    ])

    logger.debug("calc_solution: starting with %d sources", len(sources))
    if mag_errors.any():
        good = mag_errors > 0
        mags = mags[good]
        mag_errors = mag_errors[good]
        ref_mags = ref_mags[good]
        ref_mag_errors = ref_mag_errors[good]
        snr = 1 / (10 ** (mag_errors / 2.5) - 1)
        logger.debug("calc_solution: kept %d sources after mag_error>0 filter", len(mags))
    else:
        snr = None

    b = ref_mags - mags
    sigmas2 = mag_errors**2 + ref_mag_errors**2
    no_errors = not sigmas2.any()
    if no_errors:
        sigmas2 = 0
    sigma2 = 0
    weights = None

    iteration = 0
    while True:
        for _ in range(100):
            if no_errors:
                m0 = b.mean()
            else:
                m0 = (b / (sigmas2 + sigma2)).sum() / (1 / (sigmas2 + sigma2)).sum()

            prev_sigma2 = sigma2
            sigma2 = ((b - m0) ** 2).sum() / len(b)
            left, right = 0.9 * sigma2, 1.1 * sigma2
            for __ in range(100):
                if _sigma_eq(left, sigmas2, b, m0) * _sigma_eq(right, sigmas2, b, m0) < 0:
                    break
                left *= 0.9
                right *= 1.1
            try:
                sigma2 = brenth(_sigma_eq, left, right, (sigmas2, b, m0))
            except Exception:
                pass

            if len(b) < 2 or abs(sigma2 - prev_sigma2) < 1e-8:
                break

        if no_errors:
            denom = len(b) - 1
            sigma_override = sqrt(((b - m0) ** 2).sum() / denom) if denom > 0 else float("inf")
            rejected = chauvenet(
                b, mean_override=m0, sigma_override=sigma_override, max_iter=1
            )[0]
        else:
            weights = 1 / (sigmas2 + sigma2)
            sum_weights = weights.sum()
            sigma_override = sqrt(
                (weights * (b - m0) ** 2).sum() / (sum_weights - (weights**2).sum() / sum_weights)
            )
            rejected = chauvenet(
                b, mean_override=m0, sigma_override=sigma_override, max_iter=1
            )[0]
        iteration += 1
        logger.debug(
            "calc_solution: iteration=%d rejected=%d remaining=%d",
            iteration,
            int(rejected.sum()),
            int((~rejected).sum()),
        )
        if not rejected.any():
            break

        good = ~rejected
        mags = mags[good]
        if snr is not None:
            snr = snr[good]
        b = b[good]
        if weights is not None:
            weights = weights[good]
        if not no_errors:
            sigmas2 = sigmas2[good]

    n = len(b)
    if n > 1:
        if weights is None:
            m0_error = sqrt(((b - m0) ** 2).sum() / n / (n - 1))
        else:
            sum_weights = weights.sum()
            mean_weight = sum_weights / n
            d1 = weights * b - mean_weight * m0
            d2 = weights - mean_weight
            m0_error = sqrt(
                n
                / (n - 1)
                / sum_weights**2
                * ((d1**2).sum() - 2 * m0 * (d1 * d2).sum() + m0**2 * (d2**2).sum())
            )
    else:
        m0_error = np.nan

    limmag = np.nan
    if snr is not None:
        limmag_a, limmag_b = np.polyfit(mags + m0, np.log10(snr), 1)
        if limmag_a:
            limmag = (np.log10(5) - limmag_b) / limmag_a

    if n:
        resid = b - m0
        logger.debug(
            "calc_solution: residual stats n=%d min=%s max=%s median=%s",
            n,
            float(np.min(resid)),
            float(np.max(resid)),
            float(np.median(resid)),
        )

    return m0, m0_error, sqrt(sigma2), limmag, (1 - len(b) / len(sources)) * 100
