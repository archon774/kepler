"""FITS header interpretation: ``algorithms/wcs/header_utils.py``.

These are the functions that turn a telescope's header into the two hints the
plate solver needs — a pixel scale and a rough pointing. Both are exercised
against all 39 real frames, which is the point: the failure modes here are
vendor-specific header spellings, not algorithms. Five telescopes are
represented, including one that writes RA/Dec with **comma decimal separators**
(`'00:42:44,3'`).

One preserved oddity gets its own test: ``estimate_pixel_scale_arcsec_per_pix``
documents a three-step preference order but has steps 1 and 3 commented out
upstream, so only direct keywords are consulted. That is verbatim from
``skynet .../runners/utils.py:301`` and is recorded here rather than repaired.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.wcs import WCS

from algorithms.wcs.header_utils import (
    _arcsec_from_direct_keywords,
    _arcsec_from_optics,
    _arcsec_from_wcs,
    _binning_from_header,
    _first_present,
    _frame_from_header,
    _get_any,
    _parse_ra_dec_values,
    estimate_pixel_scale_arcsec_per_pix,
    guess_icrs_radec_from_header,
)

from .conftest import ALL_FRAMES

WCS_FRAMES = [f for f in ALL_FRAMES if f != "m15_globular_open_000.fits"]

#: Frames carrying a real FOCALLEN, and the value.
FOCAL_LENGTH_FRAMES = {
    "ngc5286_globular_v_000.fits": 4565.0,
    "ngc5128_galaxy_v_000.fits": 4565.0,
    "ngc3628_galaxy_v_002.fits": 4565.0,
    "ngc1982_nebula_r_000.fits": 2011.0,
    "ngc5946_galaxy_r_000.fits": 2011.0,
}


# ---------------------------------------------------------------------------
# Pixel scale
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_pixel_scale_is_recovered_for_every_real_frame(frame_header, frame):
    """All 39 frames carry SECPIX, so all 39 resolve — including the WCS-less one.

    Sub-arcsecond sampling across the board: these are 0.4-0.8 arcsec/pixel
    imagers. A value outside that band means a unit slipped.
    """
    scale = estimate_pixel_scale_arcsec_per_pix(frame_header(frame))
    assert scale is not None, frame
    assert 0.3 < scale < 1.0, f"{frame}: {scale} arcsec/pixel"


def test_pixel_scale_comes_from_secpix_not_from_the_wcs(frame_header):
    """PRESERVED STATE: only step 2 of the documented three actually runs.

    The docstring lists WCS first, direct keywords second, optics third — but
    steps 1 and 3 are commented out in the source, verbatim from upstream
    (``skynet .../runners/utils.py:301``). So a header with a perfectly good CD
    matrix and no SECPIX returns ``None``.

    Recorded, not fixed. Two consequences a caller should know: the returned
    scale is whatever the *camera* claimed rather than what the plate solution
    implies, and a header without a direct keyword yields no hint at all even
    when one is derivable.
    """
    header = frame_header("ngc3628")

    direct = _arcsec_from_direct_keywords(header, 1, 1)
    assert direct is not None
    assert estimate_pixel_scale_arcsec_per_pix(header) == pytest.approx(direct[2])
    assert estimate_pixel_scale_arcsec_per_pix(header) == pytest.approx(header["SECPIX"])

    # The WCS path would also have answered, and with a slightly different value.
    from_wcs = _arcsec_from_wcs(header)
    assert from_wcs is not None
    assert from_wcs[2] != pytest.approx(direct[2], abs=1e-9)


def test_a_header_with_a_wcs_but_no_direct_keyword_returns_none(frame_header_copy):
    """The concrete cost of the disabled WCS branch."""
    header = frame_header_copy("ngc3628")
    for key in ("SECPIX", "PIXSCALE", "SECPIXEL", "PIXSCALE1", "SECPIX1",
                "CDELT1A", "PIXSCALE2", "SECPIX2", "CDELT2A"):
        header.pop(key, None)

    assert _arcsec_from_wcs(header) is not None      # derivable...
    assert estimate_pixel_scale_arcsec_per_pix(header) is None   # ...but not returned


@pytest.mark.parametrize("frame", WCS_FRAMES)
def test_wcs_derived_scale_agrees_with_the_header_keyword(frame_header, frame):
    """SECPIX and the plate solution should agree to a few percent.

    They come from different places — the camera's own metadata versus the
    astrometric fit — so exact agreement is not expected, but a large
    disagreement would mean one of the two paths is misreading the header.
    """
    header = frame_header(frame)
    from_wcs = _arcsec_from_wcs(header)
    assert from_wcs is not None, frame
    assert from_wcs[2] == pytest.approx(header["SECPIX"], rel=0.05), frame


def test_wcs_scale_handles_a_pc_plus_cdelt_header(frame_header):
    """NSV 2849 writes ``PC`` + ``CDELT``, not ``CD``.

    ``proj_plane_pixel_scales`` handles both, but the manual fallback below it
    reads ``CD*`` first and ``CDELT*`` only after. This frame is the one that
    would expose a regression in that ordering.
    """
    header = frame_header("nsv2849")
    assert "CD1_1" not in header
    assert "PC1_1" in header

    scales = _arcsec_from_wcs(header)
    assert scales is not None
    assert scales[2] == pytest.approx(header["SECPIX"], rel=0.05)


def test_wcs_scale_handles_a_ninety_degree_rotation(frame_header):
    """Carina's scale lives off-diagonal; a CD1_1-only reader would see ~zero."""
    header = frame_header("carina")
    assert abs(header["CD1_1"]) * 3600 < 0.05

    scales = _arcsec_from_wcs(header)
    assert scales[2] == pytest.approx(header["SECPIX"], rel=0.05)


# ---------------------------------------------------------------------------
# The optics path (live only if someone re-enables step 3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame,focal_mm", sorted(FOCAL_LENGTH_FRAMES.items()))
def test_optics_formula_matches_the_header_scale_where_focal_length_exists(
    frame_header, frame, focal_mm
):
    """``206.265 * pixel_um * bin / focal_mm``, checked on the five real cases.

    Unreachable from ``estimate_pixel_scale_arcsec_per_pix`` today, but it is
    live code and the only path that works for a header with neither a WCS nor a
    scale keyword. These frames make it testable with real optics rather than
    invented numbers.
    """
    header = frame_header(frame)
    assert header["FOCALLEN"] == pytest.approx(focal_mm)

    scales = _arcsec_from_optics(header, 1, 1)
    assert scales is not None
    assert scales[2] == pytest.approx(header["SECPIX"], rel=0.05), frame


def test_optics_formula_uses_the_published_constant(frame_header):
    header = frame_header("ngc5286")
    expected = 206.264806 * header["XPIXSZ"] / header["FOCALLEN"]
    assert _arcsec_from_optics(header, 1, 1)[0] == pytest.approx(expected, rel=1e-12)


def test_optics_scale_is_multiplied_by_binning():
    """Binned pixels subtend proportionally more sky."""
    header = {"XPIXSZ": 13.0, "YPIXSZ": 13.0, "FOCALLEN": 4565.0}
    unbinned = _arcsec_from_optics(header, 1, 1)
    binned = _arcsec_from_optics(header, 2, 2)
    assert binned[2] == pytest.approx(unbinned[2] * 2, rel=1e-12)


def test_optics_returns_none_without_a_focal_length(frame_header):
    """Most frames record FOCALLEN as 0, which is falsy and disables the path."""
    header = frame_header("ngc3628")
    assert header["FOCALLEN"] == 0.0
    assert _arcsec_from_optics(header, 1, 1) is None


# ---------------------------------------------------------------------------
# Binning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_binning_is_read_from_every_real_frame(frame_header, frame):
    xb, yb = _binning_from_header(frame_header(frame))
    assert xb >= 1 and yb >= 1


@pytest.mark.parametrize(
    "header,expected",
    [
        ({}, (1, 1)),
        ({"XBINNING": 2, "YBINNING": 2}, (2, 2)),
        ({"XBIN": 3, "YBIN": 4}, (3, 4)),
        ({"CCDXBIN": 2, "CCDYBIN": 2}, (2, 2)),
        ({"BINX": 2, "BINY": 2}, (2, 2)),
        # A combined string keyword overrides the per-axis ones.
        ({"XBINNING": 1, "BINNING": "2 2"}, (2, 2)),
        ({"BINNING": "3x3"}, (3, 3)),
        ({"BINNING": "2X2"}, (2, 2)),
        # Junk degrades to unbinned rather than raising.
        ({"XBINNING": "nonsense"}, (1, 1)),
        ({"BINNING": "not-a-binning"}, (1, 1)),
        ({"XBINNING": 0}, (1, 1)),
        ({"XBINNING": -2}, (1, 1)),
    ],
)
def test_binning_keyword_variants(header, expected):
    assert _binning_from_header(header) == expected


def test_get_any_returns_the_first_present_key():
    header = {"B": 2, "C": 3}
    assert _get_any(header, ["A", "B", "C"]) == 2
    assert _get_any(header, ["A"], default="fallback") == "fallback"


# ---------------------------------------------------------------------------
# Pointing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_pointing_is_recovered_for_every_real_frame(frame_header, frame):
    ra, dec = guess_icrs_radec_from_header(frame_header(frame))
    assert ra is not None and dec is not None, frame
    assert 0.0 <= ra < 360.0
    assert -90.0 <= dec <= 90.0


@pytest.mark.parametrize("frame", WCS_FRAMES)
def test_pointing_agrees_with_the_plate_solution(frame_header, frame):
    """Header pointing versus WCS centre: within half a degree.

    Two independent numbers — where the telescope thought it was, and where the
    solve says it was. Agreement to pointing accuracy confirms both the
    sexagesimal parsing and the frame handling.
    """
    header = frame_header(frame)
    ra, dec = guess_icrs_radec_from_header(header)

    wcs = WCS(header)
    centre = wcs.all_pix2world((header["NAXIS1"] - 1) / 2, (header["NAXIS2"] - 1) / 2, 0)
    ra_wcs, dec_wcs = float(centre[0]) % 360, float(centre[1])

    sep = np.hypot((ra - ra_wcs) * np.cos(np.deg2rad(dec)), dec - dec_wcs)
    assert sep < 0.5, f"{frame}: {sep:.3f} deg between header and WCS pointing"


def test_crval_is_preferred_when_the_header_has_a_celestial_ctype(frame_header):
    """Step 1: a solved header's own reference point beats any pointing keyword."""
    header = frame_header("ngc3628")
    ra, dec = guess_icrs_radec_from_header(header)

    assert ra == pytest.approx(header["CRVAL1"] % 360, abs=1e-9)
    assert dec == pytest.approx(header["CRVAL2"], abs=1e-9)


def test_pointing_keywords_are_used_when_there_is_no_wcs(frame_header):
    """The M15 Open frame falls through to its RA/DEC strings."""
    header = frame_header("m15_open")
    assert "CRVAL1" not in header

    ra, dec = guess_icrs_radec_from_header(header)
    # RA '21:29:58.3' -> 21h29m58.3s -> 322.49 deg
    assert ra == pytest.approx(322.49, abs=0.01)
    assert dec == pytest.approx(12.167, abs=0.01)


def test_comma_decimal_separators_raise_and_are_not_caught(frame_header):
    """LATENT DEFECT: OAUJ-CDK500 writes ``'00:42:44,3'`` and parsing raises.

    Three frames in the fixture set — both M31 exposures and NGC 7048 — use a
    comma as the decimal separator, a European locale convention. astropy's
    ``Angle`` rejects it with ``ValueError: Invalid character at col 8``, and
    ``_parse_ra_dec_values`` normalises only the unicode minus sign, not the
    comma.

    Today this is harmless *only* because all three frames are already plate
    solved: ``guess_icrs_radec_from_header`` reads ``CRVAL`` at step 1 and never
    reaches the pointing keywords. An unsolved frame from the same telescope —
    exactly the case the solver hint exists for — would raise instead of
    returning a hint, and the exception is not caught.

    Recorded, not fixed, per the extraction contract. If a maintainer decides to
    handle it, the fix belongs in ``_norm`` alongside the existing unicode-minus
    replacement, and this test should then be inverted.
    """
    header = frame_header("m31")
    assert "," in str(header["RA"])

    with pytest.raises(ValueError, match="Invalid character"):
        _parse_ra_dec_values(header["RA"], header["DEC"])

    # Solved, so CRVAL answers first and the comma strings are never touched.
    ra, dec = guess_icrs_radec_from_header(header)
    assert ra == pytest.approx(header["CRVAL1"] % 360, abs=1e-9)

    # Strip the plate solution and the failure surfaces, uncaught.
    unsolved = header.copy()
    for key in ("CRVAL1", "CRVAL2", "CTYPE1", "CTYPE2"):
        unsolved.pop(key, None)
    with pytest.raises(ValueError, match="Invalid character"):
        guess_icrs_radec_from_header(unsolved)


def test_only_the_three_known_frames_use_comma_separators(frame_header):
    """Bound the exposure: if a fourth appears, this fails and prompts a look."""
    affected = {
        frame for frame in ALL_FRAMES
        if any("," in str(frame_header(frame).get(key, ""))
               for key in ("RA", "DEC", "OBJCTRA", "OBJCTDEC"))
    }
    assert affected == {
        "m31_galaxy_r_000.fits",
        "m31_galaxy_v_000.fits",
        "ngc7048_pn_r_000.fits",
    }
    # All three are solved, which is why the defect stays latent.
    for frame in affected:
        assert "CRVAL1" in frame_header(frame)


def test_sexagesimal_ra_is_read_as_hours_and_dec_as_degrees():
    """The unit asymmetry: RA strings are hourangle, Dec strings are degrees.

    Reading RA as degrees instead would place every field 15x closer to RA=0 —
    a wrong-but-plausible pointing that the solver then fails to confirm.
    """
    ra, dec = _parse_ra_dec_values("06:00:00", "+30:00:00")
    assert ra == pytest.approx(90.0, abs=1e-9)
    assert dec == pytest.approx(30.0, abs=1e-9)


def test_unicode_minus_is_normalised():
    ra, dec = _parse_ra_dec_values("06:00:00", "−30:00:00")
    assert dec == pytest.approx(-30.0, abs=1e-9)


def test_numeric_ra_under_24_is_treated_as_hours():
    """The documented heuristic, and the boundary it turns on."""
    assert _parse_ra_dec_values(6.0, 30.0)[0] == pytest.approx(90.0)
    assert _parse_ra_dec_values(24.0, 30.0)[0] == pytest.approx(360.0)
    # Above 24 it is taken as degrees already.
    assert _parse_ra_dec_values(25.0, 30.0)[0] == pytest.approx(25.0)
    assert _parse_ra_dec_values(180.0, 30.0)[0] == pytest.approx(180.0)


def test_numeric_ra_between_0_and_24_degrees_is_misread_as_hours():
    """KNOWN AMBIGUITY: a genuine RA of 10 degrees cannot be expressed numerically.

    The heuristic reads any numeric RA at or below 24 as hours, so a header
    meaning 10 degrees gets 150. There is no way to distinguish the two from the
    number alone, which is why real headers use sexagesimal strings — every
    frame in the fixture set does. Pinned so the ambiguity is documented rather
    than rediscovered.
    """
    assert _parse_ra_dec_values(10.0, 0.0)[0] == pytest.approx(150.0)


def test_unparseable_values_return_none_rather_than_raising():
    assert _parse_ra_dec_values(None, None) == (None, None)
    assert _parse_ra_dec_values(object(), object()) == (None, None)


def test_first_present_requires_both_keys_of_a_pair():
    header = {"OBJCTRA": "1", "DEC": "2"}
    assert _first_present(header, [("OBJCTRA", "OBJCTDEC"), ("RA", "DEC")]) == (None, None)

    header["OBJCTDEC"] = "3"
    assert _first_present(header, [("OBJCTRA", "OBJCTDEC"), ("RA", "DEC")]) == (
        "OBJCTRA", "OBJCTDEC"
    )


# ---------------------------------------------------------------------------
# Coordinate frames
# ---------------------------------------------------------------------------

def test_explicit_icrs_is_honoured():
    from astropy.coordinates import ICRS

    assert isinstance(_frame_from_header({"RADESYS": "ICRS"}), ICRS)


def test_fk5_and_fk4_are_selected_by_equinox():
    """The 1980 cut: J-equinoxes go to FK5, B-equinoxes to FK4."""
    from astropy.coordinates import FK4, FK5

    assert isinstance(_frame_from_header({"EQUINOX": 2000.0}), FK5)
    assert isinstance(_frame_from_header({"EQUINOX": 1950.0}), FK4)
    assert isinstance(_frame_from_header({"RADESYS": "FK5"}), FK5)
    assert isinstance(_frame_from_header({"RADESYS": "FK4"}), FK4)


def test_radecsys_is_accepted_as_a_legacy_alias():
    from astropy.coordinates import ICRS

    assert isinstance(_frame_from_header({"RADECSYS": "ICRS"}), ICRS)


def test_frame_defaults_to_icrs_when_nothing_is_declared():
    from astropy.coordinates import ICRS

    assert isinstance(_frame_from_header({}), ICRS)


@pytest.mark.parametrize("frame", ALL_FRAMES)
def test_frame_resolution_never_raises_on_a_real_header(frame_header, frame):
    assert _frame_from_header(frame_header(frame)) is not None
