"""Exposure-time calculators: ``algorithms/skylib_lite/photometry/exposure.py``.

Not on the calibration path — these size an exposure before it is taken, rather
than measure one after. They are covered because they are live algorithm code
with published physics behind them, and because upstream carries a regression
guard here that is worth keeping: the point-source well-depth calculation must
size a source by its **brightest pixel**, not by its aperture-summed flux.

Adapted from ``skynet packages/py/skylib/tests/test_exposure.py``, extended with
the dust-extinction and blackbody helpers that suite does not cover.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import erf

from algorithms.skylib_lite.photometry.exposure import (
    dust_extinction,
    exptime_for_mag_and_counts,
    exptime_for_mag_and_snr,
    flux15_for_exptime_mag_and_snr,
    mag_for_exptime_and_snr,
    planck_law,
    planck_law_normalized,
    snr_for_mag_and_exptime,
)

#: Representative reference-instrument parameters (broadband, dark site).
SNR_PARAMS = dict(read_noise=5.0, sky=21.0, dark=0.02, flux15=1748.0,
                  pixsize=0.6, seeing=2.0)
COUNT_PARAMS = dict(sky=21.0, dark=0.02, flux15=1748.0, pixsize=0.6, seeing=2.0)


def _peak_fraction(seeing, pixsize):
    """Fraction of a Gaussian PSF's flux landing in the central pixel."""
    sigma = seeing / 2.3548
    return erf(pixsize / (2 * np.sqrt(2) * sigma)) ** 2


# ---------------------------------------------------------------------------
# SNR round-trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mag,snr", [(19.0, 20.0), (15.0, 100.0), (21.0, 5.0)])
def test_point_source_snr_round_trip(mag, snr):
    """The two calculators must be exact inverses of one another.

    ``exptime_for_mag_and_snr`` and ``snr_for_mag_and_exptime`` solve the same
    noise equation in opposite directions; a disagreement means one of them has
    a term the other does not.
    """
    t = exptime_for_mag_and_snr(point_source=True, mag=mag, snr=snr, **SNR_PARAMS)
    assert snr_for_mag_and_exptime(
        point_source=True, mag=mag, texp=t, **SNR_PARAMS
    ) == pytest.approx(snr, abs=1e-6)


@pytest.mark.parametrize("mag,snr", [(21.0, 10.0), (18.0, 50.0)])
def test_extended_source_snr_round_trip(mag, snr):
    t = exptime_for_mag_and_snr(point_source=False, mag=mag, snr=snr, **SNR_PARAMS)
    assert snr_for_mag_and_exptime(
        point_source=False, mag=mag, texp=t, **SNR_PARAMS
    ) == pytest.approx(snr, abs=1e-6)


def test_magnitude_inversion_is_close_but_not_exact():
    """``mag_for_exptime_and_snr`` is an *approximate* inverse, not an exact one.

    Unlike the exptime/SNR pair above, which round-trips to 1e-6, solving for
    magnitude recovers ~19.07 from an exposure computed for 19.0 — a 0.07 mag
    gap. The two solve the noise equation under slightly different aperture
    assumptions.

    Pinned so the discrepancy is a known quantity rather than a surprise: it is
    fine for planning an exposure, and not fine as a calibration round trip.
    """
    t = exptime_for_mag_and_snr(point_source=True, mag=19.0, snr=20.0, **SNR_PARAMS)
    recovered = mag_for_exptime_and_snr(
        point_source=True, texp=t, snr=20.0, **SNR_PARAMS
    )
    assert recovered == pytest.approx(19.0, abs=0.1)
    assert recovered != pytest.approx(19.0, abs=1e-3)


def test_magnitude_inversion_is_monotonic_in_exposure_time():
    """A longer exposure reaches a fainter magnitude at the same SNR."""
    mags = [
        mag_for_exptime_and_snr(point_source=True, texp=t, snr=20.0, **SNR_PARAMS)
        for t in (10.0, 60.0, 300.0, 900.0)
    ]
    assert all(b > a for a, b in zip(mags, mags[1:]))


def test_reference_flux_inversion_is_the_right_order_of_magnitude():
    """``flux15_for_exptime_mag_and_snr`` calibrates an instrument's zero point.

    Same approximation as above: it recovers ~1570 from a scenario built with
    1748, about 10% low. Useful for a first calibration estimate, not for a
    closed round trip.
    """
    t = exptime_for_mag_and_snr(point_source=True, mag=19.0, snr=20.0, **SNR_PARAMS)
    params = {k: v for k, v in SNR_PARAMS.items() if k != "flux15"}
    recovered = flux15_for_exptime_mag_and_snr(
        point_source=True, texp=t, mag=19.0, snr=20.0, **params
    )
    assert recovered == pytest.approx(SNR_PARAMS["flux15"], rel=0.2)


def test_reference_flux_inversion_is_monotonic():
    """A brighter reference flux means the same SNR arrives sooner."""
    params = {k: v for k, v in SNR_PARAMS.items() if k != "flux15"}
    fluxes = [
        flux15_for_exptime_mag_and_snr(
            point_source=True, texp=t, mag=19.0, snr=20.0, **params
        )
        for t in (900.0, 300.0, 60.0)
    ]
    assert all(b > a for a, b in zip(fluxes, fluxes[1:]))


def test_a_longer_exposure_gives_a_better_signal_to_noise():
    snrs = [
        snr_for_mag_and_exptime(point_source=True, mag=19.0, texp=t, **SNR_PARAMS)
        for t in (10.0, 60.0, 300.0, 900.0)
    ]
    assert all(b > a for a, b in zip(snrs, snrs[1:]))


def test_a_fainter_source_needs_a_longer_exposure():
    times = [
        exptime_for_mag_and_snr(point_source=True, mag=m, snr=20.0, **SNR_PARAMS)
        for m in (15.0, 17.0, 19.0, 21.0)
    ]
    assert all(b > a for a, b in zip(times, times[1:]))


def test_a_brighter_sky_costs_exposure_time():
    """Sky brightness is in magnitudes per square arcsec — larger is darker."""
    dark_site = exptime_for_mag_and_snr(
        point_source=True, mag=19.0, snr=20.0, **{**SNR_PARAMS, "sky": 22.0}
    )
    bright_site = exptime_for_mag_and_snr(
        point_source=True, mag=19.0, snr=20.0, **{**SNR_PARAMS, "sky": 18.0}
    )
    assert bright_site > dark_site


# ---------------------------------------------------------------------------
# Well depth — the regression guard
# ---------------------------------------------------------------------------

def test_well_depth_exposure_fills_the_peak_pixel():
    """``target_counts`` is a per-pixel quantity, such as full-well capacity.

    So the exposure must put that many electrons in the *brightest* pixel —
    source peak plus background — not in the aperture sum.
    """
    target = 25000.0
    t = exptime_for_mag_and_counts(
        point_source=True, mag=12.0, target_counts=target, **COUNT_PARAMS
    )

    background = COUNT_PARAMS["dark"] + COUNT_PARAMS["flux15"] * COUNT_PARAMS["pixsize"] ** 2 * 10 ** (
        -0.4 * (COUNT_PARAMS["sky"] - 15)
    )
    peak_rate = (
        COUNT_PARAMS["flux15"] * 10 ** (-0.4 * (12.0 - 15))
        * _peak_fraction(COUNT_PARAMS["seeing"], COUNT_PARAMS["pixsize"])
        + background
    )
    assert peak_rate * t == pytest.approx(target, rel=1e-3)


def test_well_depth_exposure_is_not_aperture_summed():
    """Regression guard, carried over from upstream's own suite.

    The bug this replaced under-exposed the peak pixel by the PSF concentration
    factor — about 12x at this sampling — because it sized the source by its
    aperture-summed flux. If this fails, the calculation has reverted.
    """
    target = 25000.0
    t_peak = exptime_for_mag_and_counts(
        point_source=True, mag=12.0, target_counts=target, **COUNT_PARAMS
    )

    seeing, pixsize = COUNT_PARAMS["seeing"], COUNT_PARAMS["pixsize"]
    rad = (2 * seeing) / 2 / pixsize
    background = COUNT_PARAMS["dark"] + COUNT_PARAMS["flux15"] * pixsize ** 2 * 10 ** (
        -0.4 * (COUNT_PARAMS["sky"] - 15)
    )
    counts_ap = COUNT_PARAMS["flux15"] * 10 ** (-0.4 * (12.0 - 15)) * (
        1 - np.exp(-0.5 * (rad / seeing * 2.35 * pixsize) ** 2)
    )
    t_aperture = target / (counts_ap + background * np.pi * rad ** 2)

    assert t_peak > 5 * t_aperture


def test_a_brighter_source_fills_the_well_faster():
    target = 25000.0
    times = [
        exptime_for_mag_and_counts(
            point_source=True, mag=m, target_counts=target, **COUNT_PARAMS
        )
        for m in (8.0, 10.0, 12.0, 14.0)
    ]
    assert all(b > a for a, b in zip(times, times[1:]))


def test_an_extended_source_well_depth_calculation_also_runs():
    target = 25000.0
    t = exptime_for_mag_and_counts(
        point_source=False, mag=18.0, target_counts=target, **COUNT_PARAMS
    )
    assert t > 0 and math.isfinite(t)


def test_better_seeing_concentrates_the_psf_and_shortens_the_exposure():
    """A tighter PSF puts more light in the peak pixel, so the well fills sooner."""
    sharp = exptime_for_mag_and_counts(
        point_source=True, mag=12.0, target_counts=25000.0,
        **{**COUNT_PARAMS, "seeing": 1.0},
    )
    soft = exptime_for_mag_and_counts(
        point_source=True, mag=12.0, target_counts=25000.0,
        **{**COUNT_PARAMS, "seeing": 4.0},
    )
    assert sharp < soft


# ---------------------------------------------------------------------------
# Blackbody and extinction helpers
# ---------------------------------------------------------------------------

def test_planck_law_peak_follows_wiens_displacement():
    """The peak wavelength must scale as ``1/T``.

    Wien's law: ``lambda_max * T = 2.898e-3 m*K``. Checking the peak's *shift*
    rather than an absolute value keeps this independent of the unit convention
    the function happens to use.
    """
    wavelengths = np.linspace(100e-9, 3000e-9, 4000)

    peaks = {}
    for temperature in (3000.0, 6000.0):
        values = np.array([planck_law(w, temperature) for w in wavelengths])
        peaks[temperature] = wavelengths[int(np.argmax(values))]

    assert peaks[6000.0] < peaks[3000.0]
    assert peaks[3000.0] / peaks[6000.0] == pytest.approx(2.0, rel=0.05)


def test_a_hotter_blackbody_is_brighter_at_every_wavelength():
    for wavelength in (400e-9, 550e-9, 700e-9):
        assert planck_law(wavelength, 8000.0) > planck_law(wavelength, 4000.0)


def test_normalized_planck_law_peaks_at_one():
    values = [
        planck_law_normalized(w, 5800.0) for w in np.linspace(100e-9, 3000e-9, 2000)
    ]
    assert max(values) == pytest.approx(1.0, rel=1e-3)
    assert all(0.0 <= v <= 1.0 + 1e-9 for v in values)


def test_zero_extinction_when_there_is_no_dust():
    assert dust_extinction(550.0, av=0.0) == pytest.approx(0.0, abs=1e-12)


def test_extinction_grows_with_the_dust_column():
    values = [dust_extinction(550.0, av=av) for av in (0.5, 1.0, 2.0)]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_extinction_is_stronger_in_the_blue():
    """Interstellar dust reddens: extinction falls with wavelength.

    This is the sign convention the whole helper exists to encode — getting it
    backwards would de-redden a source instead.
    """
    # Wavelengths in NANOMETRES here — ``planck_law`` above takes metres, so the
    # two neighbouring helpers disagree on units. B, V and K band centres.
    blue = dust_extinction(440.0, av=1.0)
    visual = dust_extinction(550.0, av=1.0)
    infrared = dust_extinction(2200.0, av=1.0)

    assert blue > visual > infrared


def test_extinction_at_v_is_approximately_av():
    """By definition ``A_V`` is the extinction at 550 nm."""
    assert dust_extinction(550.0, av=1.0) == pytest.approx(1.0, rel=0.1)


def test_a_flatter_extinction_law_reddens_less():
    """``rv`` is the total-to-selective ratio; 3.1 is the diffuse-ISM standard."""
    standard = dust_extinction(440.0, av=1.0, rv=3.1)
    flat = dust_extinction(440.0, av=1.0, rv=5.0)
    assert flat < standard
