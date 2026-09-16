"""Vendored FITS helpers: ``algorithms/skylib_lite/util/fits.py``.

Small functions, but they sit on the hot path: ``run_source_extraction`` and
``run_photometry`` both call ``get_fits_gain`` / ``get_fits_exp_length`` /
``get_fits_time`` on every frame. A wrong exposure length shifts every
instrumental magnitude by a constant, and a wrong gain silently rescales every
uncertainty — neither raises, and a zero-point solve absorbs the first without
complaint.

Exercised against all 42 real headers, plus the specific keyword fallbacks that
no fixture frame happens to use.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from astropy.io.fits import Header

from algorithms.skylib_lite.util.fits import (
    get_fits_exp_length,
    get_fits_fov,
    get_fits_gain,
    get_fits_time,
    str_to_datetime,
)

from .conftest import ALL_FRAMES

WCS_FRAMES = [f for f in ALL_FRAMES if f != "m15_globular_open_000.fits"]


# ---------------------------------------------------------------------------
# Exposure length
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_exposure_length_is_read_from_every_real_frame(frame_header, frame):
    texp = get_fits_exp_length(frame_header(frame))
    assert texp is not None, frame
    assert 0 < texp < 3600, f"{frame}: {texp} s"


def test_exptime_is_preferred_over_exposure():
    """Both keywords exist in the wild; EXPTIME wins when they disagree."""
    assert get_fits_exp_length(Header({"EXPTIME": 60.0, "EXPOSURE": 30.0})) == 60.0


def test_exposure_is_the_documented_fallback():
    assert get_fits_exp_length(Header({"EXPOSURE": 30.0})) == 30.0


def test_a_header_with_neither_keyword_returns_none():
    assert get_fits_exp_length(Header()) is None


def test_an_unparseable_exposure_falls_through_to_the_next_keyword():
    """A junk EXPTIME must not shadow a good EXPOSURE.

    The loop ``continue``s on ``ValueError``, so a malformed first keyword is
    skipped rather than accepted or raised.
    """
    assert get_fits_exp_length(Header({"EXPTIME": "not-a-number", "EXPOSURE": 30.0})) == 30.0


# ---------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_gain_is_read_from_every_real_frame(frame_header, frame):
    gain = get_fits_gain(frame_header(frame))
    assert gain is not None, frame
    assert 0 < gain < 20, f"{frame}: {gain} e-/ADU"


def test_gain_keyword_preference_is_gain_then_egain_then_eperadu():
    """Three spellings, and the order decides which a dual-keyword header uses.

    Some SBIG headers carry both ``GAIN`` (the camera's own figure) and
    ``EGAIN`` (electrons per ADU); they are not always equal, and the choice
    scales every reported flux uncertainty.
    """
    assert get_fits_gain(Header({"GAIN": 1.2, "EGAIN": 0.78, "EPERADU": 2.0})) == 1.2
    assert get_fits_gain(Header({"EGAIN": 0.78, "EPERADU": 2.0})) == 0.78
    assert get_fits_gain(Header({"EPERADU": 2.0})) == 2.0


def test_a_header_with_no_gain_keyword_returns_none():
    assert get_fits_gain(Header()) is None


def test_an_unparseable_gain_falls_through():
    assert get_fits_gain(Header({"GAIN": "unknown", "EGAIN": 0.78})) == 0.78


# ---------------------------------------------------------------------------
# Observation time
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_observation_times_are_recovered_for_every_real_frame(frame_header, frame):
    """Start, centre and stop, all derived from DATE-OBS plus EXPTIME.

    That derivation only holds where ``DATE-END`` is absent, which was every
    frame until the three NGC 5286 B stacks arrived. They carry a real
    ``DATE-END``, and it is the end of the *whole four-exposure stack* rather
    than of the primary exposure — identical in all three files
    (``15:53:59.92``) while each ``DATE-OBS`` differs. So the recovered span is
    the stack's, from 77 s up to 12.1 hours for the frame whose primary was
    taken first, and only ``_002`` — whose primary happens to be the last
    exposure — still satisfies the single-exposure identity.

    Those three also record ``DATE-CEN``, so ``get_fits_time`` returns all
    three times as written rather than deriving any of them — and the recorded
    centre is Afterglow's own stack centre, not the arithmetic midpoint
    (``_001`` puts it at 11:12:17.939207, well off the half-way point of its
    12-hour span). Preferring recorded values is right; only the derived branch
    can claim the midpoint.
    """
    header = frame_header(frame)
    t_start, t_cen, t_stop = get_fits_time(header)

    assert t_start is not None, frame
    assert t_cen is not None and t_stop is not None
    assert t_start <= t_cen <= t_stop

    texp = get_fits_exp_length(header)
    span = (t_stop - t_start).total_seconds()

    if "DATE-END" in header:
        # A stack, every time recorded: the span has to cover the primary
        # exposure, but nothing here is derived from it.
        assert span >= texp - 1e-6, frame
    else:
        assert span == pytest.approx(texp, abs=1e-6)
        assert (t_cen - t_start).total_seconds() == pytest.approx(texp / 2, abs=1e-6)


def test_centre_and_stop_are_derived_from_start_and_exposure():
    header = Header({"DATE-OBS": "2026-04-08T03:26:45", "EXPTIME": 90.0})
    t_start, t_cen, t_stop = get_fits_time(header)

    assert t_start == datetime(2026, 4, 8, 3, 26, 45)
    assert t_cen == t_start + timedelta(seconds=45)
    assert t_stop == t_start + timedelta(seconds=90)


def test_start_is_derived_backwards_from_a_recorded_centre():
    header = Header({"DATE-CEN": "2026-04-08T03:27:30", "EXPTIME": 90.0})
    t_start, t_cen, t_stop = get_fits_time(header)

    assert t_cen == datetime(2026, 4, 8, 3, 27, 30)
    assert t_start == t_cen - timedelta(seconds=45)
    assert t_stop == t_cen + timedelta(seconds=45)


def test_start_is_derived_backwards_from_a_recorded_end():
    header = Header({"DATE-END": "2026-04-08T03:28:15", "EXPTIME": 90.0})
    t_start, t_cen, t_stop = get_fits_time(header)

    assert t_stop == datetime(2026, 4, 8, 3, 28, 15)
    assert t_start == t_stop - timedelta(seconds=90)


def test_a_separate_time_obs_keyword_is_appended_to_a_date_only_value():
    """Older headers split the timestamp across DATE-OBS and TIME-OBS.

    Only joined when DATE-OBS has no ``T`` of its own, so a full ISO timestamp
    is never corrupted by a stray TIME-OBS.
    """
    joined = get_fits_time(
        Header({"DATE-OBS": "2026-04-08", "TIME-OBS": "03:26:45", "EXPTIME": 0.0})
    )[0]
    assert joined == datetime(2026, 4, 8, 3, 26, 45)

    already_full = get_fits_time(
        Header({"DATE-OBS": "2026-04-08T01:02:03", "TIME-OBS": "03:26:45", "EXPTIME": 0.0})
    )[0]
    assert already_full == datetime(2026, 4, 8, 1, 2, 3)


def test_a_supplied_exposure_length_is_used_when_the_header_has_none():
    """The ``exp_length`` argument exists for callers holding a database value."""
    header = Header({"DATE-OBS": "2026-04-08T03:26:45"})
    _, _, t_stop_default = get_fits_time(header)
    _, _, t_stop_supplied = get_fits_time(header, exp_length=90.0)

    # With no exposure known, the default is zero — start, centre and stop coincide.
    assert t_stop_default == datetime(2026, 4, 8, 3, 26, 45)
    assert t_stop_supplied == datetime(2026, 4, 8, 3, 28, 15)


def test_a_header_with_no_time_at_all_returns_nones():
    assert get_fits_time(Header()) == (None, None, None)


def test_str_to_datetime_handles_the_common_iso_forms():
    assert str_to_datetime("2026-04-08T03:26:45") == datetime(2026, 4, 8, 3, 26, 45)
    assert str_to_datetime("2026-04-08T03:26:45.150") == datetime(
        2026, 4, 8, 3, 26, 45, 150000
    )
    assert str_to_datetime("nonsense") is None
    assert str_to_datetime("") is None


def test_fractional_seconds_in_a_real_header_are_preserved(frame_header):
    """M31 records DATE-OBS to the centisecond; truncation would lose it."""
    header = frame_header("m31")
    assert "." in str(header["DATE-OBS"])
    t_start, _, _ = get_fits_time(header)
    assert t_start.microsecond != 0


# ---------------------------------------------------------------------------
# Field of view
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", WCS_FRAMES)
def test_field_of_view_is_derived_for_every_solved_frame(frame_header, frame):
    ra, dec, radius, scale, width, height = get_fits_fov(frame_header(frame))

    assert ra is not None and dec is not None, frame
    assert 0 <= ra < 24, f"{frame}: RA {ra} h"
    assert -90 <= dec <= 90
    assert 0 < radius < 1.0, f"{frame}: radius {radius} deg"
    assert 0.3 < scale < 1.0, f"{frame}: {scale} arcsec/pixel"
    assert width > 0 and height > 0


def test_field_of_view_returns_ra_in_hours_not_degrees(frame_header):
    """The unit switch: ``get_fits_fov`` reports RA in hours, CRVAL1 is degrees.

    The position is the *image centre* projected through the WCS, not CRVAL —
    which on these frames sits a few hundred pixels off centre, so the two
    differ by a few hundredths of a degree.
    """
    from astropy.wcs import WCS

    header = frame_header("ngc3628")
    ra, dec, _, _, _, _ = get_fits_fov(header)

    wcs = WCS(header)
    centre = wcs.all_pix2world((header["NAXIS1"] - 1) / 2, (header["NAXIS2"] - 1) / 2, 0)
    assert ra == pytest.approx(float(centre[0]) % 360 / 15.0, rel=1e-9)
    assert dec == pytest.approx(float(centre[1]), rel=1e-9)

    # Close to CRVAL, but deliberately not equal to it.
    assert ra == pytest.approx(header["CRVAL1"] % 360 / 15.0, abs=0.01)
    assert dec != pytest.approx(header["CRVAL2"], abs=1e-6)


def test_field_of_view_dimensions_match_the_header(frame_header):
    header = frame_header("m31")
    *_, width, height = get_fits_fov(header)
    assert (width, height) == (header["NAXIS1"], header["NAXIS2"])


def test_field_of_view_scale_agrees_with_the_frames_own_secpix(frame_header):
    header = frame_header("ngc3628")
    _, _, _, scale, _, _ = get_fits_fov(header)
    assert scale == pytest.approx(header["SECPIX"], rel=0.05)


def test_field_of_view_falls_back_to_maxim_pointing_keywords(frame_header):
    """No WCS, so it parses OBJRA/TELRA/RA and OBJDEC/TELDEC/DEC by hand.

    The M15 Open frame has no solution. Unlike
    ``wcs.header_utils._parse_ra_dec_values``, this fallback still produces a
    position — and a radius, from SECPIX and the detector size.
    """
    header = frame_header("m15_open")
    ra, dec, radius, scale, width, height = get_fits_fov(header)

    assert ra == pytest.approx(21.4995, abs=1e-3)
    assert dec == pytest.approx(12.167, abs=1e-3)
    assert radius is not None and radius > 0
    assert scale == pytest.approx(header["SECPIX"])
    assert (width, height) == (header["NAXIS1"], header["NAXIS2"])


def test_the_maxim_fallback_handles_comma_decimal_separators():
    """This parser *does* handle the OAUJ-CDK500 comma convention.

    ``float(s.replace(',', '.'))`` — the fix that
    ``wcs.header_utils._parse_ra_dec_values`` lacks, which is why the same
    header raises there and parses here. Worth pinning as the contrast: two
    coordinate parsers in the same repository disagree about the same real
    input. See ``test_wcs_headers.py`` for the failing side.
    """
    header = Header({
        "NAXIS1": 1024, "NAXIS2": 1024,
        "RA": "00:42:44,3", "DEC": "+41:16:7,457", "SECPIX": 0.78,
    })
    ra, dec, _, _, _, _ = get_fits_fov(header)

    assert ra == pytest.approx(0.7123, abs=1e-3)
    assert dec == pytest.approx(41.2687, abs=1e-3)


@pytest.mark.parametrize("dec_string", ["-51:22:28.1", "-00:30:00.0", "-01:00:00.0"])
def test_southern_declinations_collapse_to_zero_in_the_fallback(dec_string):
    """PRESERVED DEFECT: the sign factor is ``(1 - startswith('-'))``.

    For a southern declination that evaluates to ``1 - True`` = ``0``, so the
    magnitude is multiplied by zero and the field centre is reported as sitting
    on the celestial equator. The correct factor — used in
    ``algorithms/catalogs/landolt_catalog.py``'s column mapping, which does the
    same job — is ``(1 - 2*startswith('-'))``.

    Byte-identical to ``skynet packages/py/skylib/skylib/util/fits.py``, so this
    is upstream's bug, preserved rather than introduced.

    Only reachable for an **unsolved** southern frame: a header with a WCS never
    enters this branch. Roughly half the fixture set is southern, but all of
    those are solved, so nothing in this repository trips it today.
    """
    header = Header({
        "NAXIS1": 1056, "NAXIS2": 1027,
        "RA": "21:29:58.3", "DEC": dec_string, "SECPIX": 0.59,
    })
    _, dec, _, _, _, _ = get_fits_fov(header)
    assert dec == 0.0


def test_northern_declinations_are_unaffected():
    header = Header({
        "NAXIS1": 1056, "NAXIS2": 1027,
        "RA": "21:29:58.3", "DEC": "+41:16:07.4", "SECPIX": 0.59,
    })
    _, dec, _, _, _, _ = get_fits_fov(header)
    assert dec == pytest.approx(41.2687, abs=1e-3)


def test_a_header_with_neither_a_wcs_nor_pointing_keywords_reports_dimensions_only():
    ra, dec, radius, scale, width, height = get_fits_fov(
        Header({"NAXIS1": 100, "NAXIS2": 200})
    )
    assert ra is None and dec is None and radius is None and scale is None
    assert (width, height) == (100, 200)


def test_field_of_view_radius_scales_with_the_detector(frame_header):
    """The 1600x1200 frame covers more sky than the 1056x1027 ones.

    Both are ~0.6 arcsec/pixel, so the larger detector must report a larger
    radius — a check that the radius is derived from the actual footprint rather
    than a constant.
    """
    _, _, small_radius, _, _, _ = get_fits_fov(frame_header("ngc3628"))
    _, _, large_radius, _, _, _ = get_fits_fov(frame_header("ngc1982"))
    assert large_radius > small_radius
