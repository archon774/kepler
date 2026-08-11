"""Plate-solve validation and write-back: ``algorithms/wcs/wcs.py``.

The solve itself needs astrometry.net index files covering the field scale, or a
local UCAC catalog — neither of which this repository carries, and neither of
which the fixture frames' ~10 arcmin fields are served by the commonly installed
wide-field index set. So ``solve_wcs`` is exercised only behind the
``solver_data`` marker, and everything around it is tested directly:

* **parity and the CD matrix** — the ``has_cd()`` / ``PC * CDELT`` fork, checked
  against every real frame including the five that use ``PC``;
* **solution acceptance** — the parity and pointing checks that decide whether a
  candidate solution is written into the header at all;
* **header write-back** — which keywords are cleared, which survive;
* **``_clear_wcs_solution_fields``**, whose attribute-name mismatch is a
  documented parity quirk (``algorithms/wcs/EXTRACTION.md`` §5.2) and is
  asserted here so it cannot be "tidied up" by accident.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from algorithms.wcs.state import ProcessingRun, WcsSolution, now
from algorithms.wcs.wcs import (
    WCS_REGEX,
    _accept_solution,
    _angular_sep_deg,
    _clear_wcs_solution_fields,
    _parse_dec_deg,
    _parse_ra_hours,
    _solve_request_parity_from_expected,
    _wcs_det,
    _wcs_matrix,
    _wcs_parity,
    _write_wcs_to_header,
    build_wcs_for_processing_run,
)

from .conftest import ALL_FRAMES

WCS_FRAMES = [f for f in ALL_FRAMES if f != "m15_globular_open_000.fits"]
PC_FRAMES = [
    "nsv2849_star_v_000.fits", "m90_galaxy_r_000.fits",
    "ngc3628_galaxy_v_001.fits", "ngc3628_galaxy_v_002.fits",
    "ngc7293_pn_halpha_000.fits",
]
NEGATIVE_PARITY_FRAMES = [
    "m31_galaxy_v_000.fits", "m31_galaxy_r_000.fits", "ngc7048_pn_r_000.fits",
]


# ---------------------------------------------------------------------------
# The CD matrix and parity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", WCS_FRAMES)
def test_effective_cd_matrix_is_recovered_for_every_real_frame(frame_header, frame):
    matrix = _wcs_matrix(WCS(frame_header(frame)))
    assert matrix is not None, frame
    assert matrix.shape == (2, 2)
    assert np.all(np.isfinite(matrix))
    assert abs(np.linalg.det(matrix)) > 0


@pytest.mark.parametrize("frame", PC_FRAMES)
def test_pc_plus_cdelt_headers_take_the_fallback_branch(frame_header, frame):
    """Five frames write ``PC`` + ``CDELT`` instead of ``CD``.

    ``_wcs_matrix`` asks ``has_cd()`` first and only then multiplies
    ``get_pc()`` by ``diag(cdelt)``. Those frames are the only thing exercising
    the second branch — without them a regression that returned ``None`` for
    PC-form headers would pass every other test in this file.
    """
    header = frame_header(frame)
    assert "CD1_1" not in header
    assert "PC1_1" in header

    wcs = WCS(header)
    matrix = _wcs_matrix(wcs)
    assert matrix is not None

    expected = np.array([[header["PC1_1"], header["PC1_2"]],
                         [header["PC2_1"], header["PC2_2"]]]) * header["CDELT1"]
    assert matrix == pytest.approx(expected, rel=1e-9)


def test_cd_headers_take_the_has_cd_branch(frame_header):
    header = frame_header("ngc3628")
    matrix = _wcs_matrix(WCS(header))
    expected = np.array([[header["CD1_1"], header["CD1_2"]],
                         [header["CD2_1"], header["CD2_2"]]])
    assert matrix == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("frame", NEGATIVE_PARITY_FRAMES)
def test_negative_parity_is_detected(frame_header, frame):
    """Three real frames have ``det(CD) < 0`` — a mirrored detector.

    Parity is the cheapest check the solver has for "this solution is a
    reflection of the truth", so a frame set with only one handedness would let
    a sign error through unnoticed.
    """
    wcs = WCS(frame_header(frame))
    assert _wcs_det(wcs) < 0
    assert _wcs_parity(wcs) is False


@pytest.mark.parametrize(
    "frame", [f for f in WCS_FRAMES if f not in NEGATIVE_PARITY_FRAMES]
)
def test_positive_parity_is_detected(frame_header, frame):
    assert _wcs_parity(WCS(frame_header(frame))) is True


def test_parity_is_indeterminate_for_a_degenerate_matrix():
    """A zero determinant returns ``None``, not ``False``.

    The distinction matters at the call site: ``_accept_solution`` skips the
    parity check when parity is unknown, but would *reject* on ``False``.
    """
    wcs = WCS(naxis=2)
    wcs.wcs.cd = np.zeros((2, 2))
    assert _wcs_det(wcs) is None
    assert _wcs_parity(wcs) is None


def test_matrix_extraction_degrades_to_none_rather_than_raising():
    class Broken:
        @property
        def wcs(self):
            raise RuntimeError("no wcs here")

    assert _wcs_matrix(Broken()) is None
    assert _wcs_det(Broken()) is None
    assert _wcs_parity(Broken()) is None


def test_solve_request_parity_inverts_the_expected_determinant_sign():
    """astrometry.net's convention is the opposite of the output determinant.

    ``PARITY_NORMAL`` (request ``parity=True``) produces ``det < 0``. Callers
    here work in terms of the expected WCS determinant, so the flag is inverted
    on the way in. Getting this backwards makes the solver search the wrong
    handedness and simply fail to solve — a silent failure, not an error.
    """
    assert _solve_request_parity_from_expected(True) is False
    assert _solve_request_parity_from_expected(False) is True
    assert _solve_request_parity_from_expected(None) is None


# ---------------------------------------------------------------------------
# Angular separation
# ---------------------------------------------------------------------------

def test_angular_separation_of_identical_positions_is_zero():
    assert _angular_sep_deg(180.0, 10.0, 180.0, 10.0) == pytest.approx(0.0, abs=1e-12)


def test_angular_separation_along_a_meridian_is_the_dec_difference():
    assert _angular_sep_deg(180.0, 10.0, 180.0, 11.0) == pytest.approx(1.0, abs=1e-9)


def test_angular_separation_shrinks_with_cos_dec_along_a_parallel():
    """One degree of RA is less than one degree of arc away from the equator."""
    at_equator = _angular_sep_deg(180.0, 0.0, 181.0, 0.0)
    at_sixty = _angular_sep_deg(180.0, 60.0, 181.0, 60.0)

    assert at_equator == pytest.approx(1.0, abs=1e-9)
    assert at_sixty == pytest.approx(0.5, abs=1e-3)


def test_angular_separation_handles_the_ra_seam():
    assert _angular_sep_deg(359.5, 0.0, 0.5, 0.0) == pytest.approx(1.0, abs=1e-9)


def test_angular_separation_of_antipodes_is_180():
    assert _angular_sep_deg(0.0, 90.0, 0.0, -90.0) == pytest.approx(180.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Solution acceptance
# ---------------------------------------------------------------------------

def _accept(wcs, **kw):
    args = dict(
        expected_parity=None, ra_hint_deg=None, dec_hint_deg=None,
        width=1056, height=1027, max_sep_deg=1.0,
    )
    args.update(kw)
    return _accept_solution(wcs, **args)


def test_a_solution_with_no_hints_is_accepted(frame_header):
    accepted, reason = _accept(WCS(frame_header("ngc3628")))
    assert accepted is True
    assert reason is None


def test_a_parity_mismatch_is_rejected_with_a_reason(frame_header):
    """Reason strings surface in logs; they are the operator's only diagnostic."""
    wcs = WCS(frame_header("ngc3628"))
    assert _wcs_parity(wcs) is True

    accepted, reason = _accept(wcs, expected_parity=False)
    assert accepted is False
    assert "parity mismatch" in reason
    assert "expected False" in reason and "got True" in reason


def test_a_matching_parity_is_accepted(frame_header):
    wcs = WCS(frame_header("ngc3628"))
    assert _accept(wcs, expected_parity=True)[0] is True


def test_parity_is_not_checked_when_the_solution_is_degenerate():
    """Unknown parity must not be treated as a mismatch."""
    wcs = WCS(naxis=2)
    wcs.wcs.crval = [180.0, 10.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.cd = np.zeros((2, 2))

    assert _accept(wcs, expected_parity=True)[0] is True


def test_a_solution_pointing_at_the_hint_is_accepted(frame_header):
    """The frame's own centre, used as its own hint."""
    header = frame_header("ngc3628")
    wcs = WCS(header)
    width, height = header["NAXIS1"], header["NAXIS2"]
    centre = wcs.all_pix2world((width - 1) / 2, (height - 1) / 2, 0)

    accepted, reason = _accept(
        wcs, ra_hint_deg=float(centre[0]) % 360, dec_hint_deg=float(centre[1]),
        width=width, height=height, max_sep_deg=0.01,
    )
    assert accepted is True, reason


def test_a_solution_far_from_the_hint_is_rejected(frame_header):
    """The check that catches a solve landing on the wrong field entirely."""
    header = frame_header("ngc3628")
    wcs = WCS(header)
    accepted, reason = _accept(
        wcs, ra_hint_deg=(header["CRVAL1"] + 30) % 360, dec_hint_deg=header["CRVAL2"],
        width=header["NAXIS1"], height=header["NAXIS2"], max_sep_deg=1.0,
    )
    assert accepted is False
    assert "from hint" in reason
    assert "max 1.000" in reason


def test_the_pointing_check_needs_both_hint_coordinates(frame_header):
    """A half-specified hint is ignored rather than half-applied."""
    header = frame_header("ngc3628")
    wcs = WCS(header)
    assert _accept(wcs, ra_hint_deg=0.0, dec_hint_deg=None)[0] is True
    assert _accept(wcs, ra_hint_deg=None, dec_hint_deg=0.0)[0] is True


def test_acceptance_measures_from_the_image_centre_not_from_crpix(frame_header):
    """The check uses ``((w-1)/2, (h-1)/2)``, not the reference pixel.

    On these frames CRPIX sits a few hundred pixels off centre, so measuring
    from the wrong point shifts the comparison by an appreciable fraction of the
    field — enough to flip a marginal accept/reject.
    """
    header = frame_header("nsv2849")
    wcs = WCS(header)
    width, height = header["NAXIS1"], header["NAXIS2"]

    centre = wcs.all_pix2world((width - 1) / 2, (height - 1) / 2, 0)
    crpix_offset = math.hypot(
        header["CRPIX1"] - (width - 1) / 2, header["CRPIX2"] - (height - 1) / 2
    )
    assert crpix_offset > 50, "fixture should have an off-centre CRPIX"

    tight = 1e-4
    assert _accept(
        wcs, ra_hint_deg=float(centre[0]) % 360, dec_hint_deg=float(centre[1]),
        width=width, height=height, max_sep_deg=tight,
    )[0] is True
    # The CRVAL position is measurably different from the frame centre.
    assert _accept(
        wcs, ra_hint_deg=header["CRVAL1"] % 360, dec_hint_deg=header["CRVAL2"],
        width=width, height=height, max_sep_deg=tight,
    )[0] is False


# ---------------------------------------------------------------------------
# Header write-back
# ---------------------------------------------------------------------------

def test_wcs_regex_matches_the_keywords_a_rewrite_must_clear():
    for key in ("WCSAXES", "CRVAL1", "CRPIX2", "CD1_1", "PC2_2", "CDELT1",
                "CTYPE1", "CUNIT1", "CROTA2", "A_ORDER", "A_1_1", "B_2_0",
                "RADESYS", "LONPOLE", "LATPOLE"):
        assert WCS_REGEX.match(key), key


def test_wcs_regex_leaves_unrelated_keywords_alone():
    for key in ("EXPTIME", "FILTER", "TELESCOP", "GAIN", "OBJECT", "DATE-OBS",
                "NAXIS1", "SECPIX", "XPIXSZ", "FOCALLEN"):
        assert not WCS_REGEX.match(key), key


def test_equinox_and_radecsys_survive_a_rewrite(frame_header_copy, frame_header):
    """GAP: the clear-list covers ``RADESYS`` but not ``EQUINOX``/``RADECSYS``.

    A rewrite deletes every keyword ``WCS_REGEX`` matches. ``RADESYS`` matches;
    its legacy spelling ``RADECSYS`` and the ``EQUINOX`` keyword do not. So a
    header that declared, say, ``EQUINOX = 1950.0`` keeps it after being
    resolved to an ICRS solution, and any later reader that consults
    ``EQUINOX`` — ``header_utils._frame_from_header`` does, when ``RADESYS`` is
    absent — would interpret the new solution in the old frame. That is a ~0.6
    degree error between B1950 and ICRS.

    Latent in this fixture set: all 36 frames carrying a frame keyword use
    ``RADESYS = ICRS``, and none carries ``EQUINOX``, so nothing stale can
    survive today. Recorded rather than fixed, since widening the regex changes
    which keywords a solve destroys.
    """
    assert WCS_REGEX.match("RADESYS")
    assert not WCS_REGEX.match("EQUINOX")
    assert not WCS_REGEX.match("RADECSYS")

    header = frame_header_copy("ngc3628")
    header["EQUINOX"] = 1950.0
    header["RADECSYS"] = "FK4"

    _write_wcs_to_header(header, WCS(frame_header("carina")))

    assert header["EQUINOX"] == 1950.0
    assert header["RADECSYS"] == "FK4"


def test_no_fixture_frame_carries_a_stale_frame_keyword(frame_header):
    """Bound the exposure of the gap above."""
    for frame in ALL_FRAMES:
        header = frame_header(frame)
        assert "EQUINOX" not in header, frame
        assert "RADECSYS" not in header, frame
        if "RADESYS" in header:
            assert header["RADESYS"] == "ICRS", frame


def test_write_back_replaces_stale_wcs_keywords(frame_header_copy, frame_header):
    """A rewrite must not leave the old solution's keywords behind.

    Mixing CD terms from one solution with CRVAL from another produces a WCS
    that is syntactically valid and astrometrically nonsense. The NGC 3628
    header uses ``CD``; the replacement is written by ``to_header(relax=True)``
    as ``PC`` + ``CDELT``, so this also checks the old ``CD*`` keywords are gone
    rather than sitting alongside the new ``PC*`` ones.
    """
    header = frame_header_copy("ngc3628")
    replacement = WCS(frame_header("carina"))
    assert "CD1_1" in header

    _write_wcs_to_header(header, replacement)

    assert header["CRVAL1"] == pytest.approx(replacement.wcs.crval[0], abs=1e-9)
    assert header["CRVAL2"] == pytest.approx(replacement.wcs.crval[1], abs=1e-9)
    assert "CD1_1" not in header
    assert "PC1_1" in header


def test_write_back_is_astrometrically_faithful_but_not_bit_exact(
    frame_header_copy, frame_header
):
    """``to_header(relax=True)`` refactors ``CD`` into ``PC`` x ``CDELT``.

    That decomposition is not exact in float: the recovered matrix differs from
    the original in the fifth significant figure (~5e-5 relative). Across a
    1056-pixel frame at 0.6 arcsec/pixel that is a few hundredths of an arcsec —
    far below the ~1 arcsec matching tolerances downstream, but not zero.

    Pinned as an equivalence in *sky position*, which is what actually matters,
    with the matrix-level drift bounded so a real regression still shows up.
    """
    header = frame_header_copy("ngc3628")
    replacement = WCS(frame_header("carina"))
    _write_wcs_to_header(header, replacement)
    written = WCS(header)

    original_matrix = _wcs_matrix(replacement)
    written_matrix = _wcs_matrix(written)
    assert written_matrix == pytest.approx(original_matrix, rel=1e-4)
    assert written_matrix != pytest.approx(original_matrix, rel=1e-12)

    # Sky positions agree to well under a tenth of an arcsecond at the corners.
    for x, y in ((0, 0), (1055, 0), (0, 1026), (1055, 1026)):
        a = replacement.all_pix2world(x, y, 0)
        b = written.all_pix2world(x, y, 0)
        sep_arcsec = _angular_sep_deg(
            float(a[0]) % 360, float(a[1]), float(b[0]) % 360, float(b[1])
        ) * 3600
        assert sep_arcsec < 0.1, f"({x},{y}): {sep_arcsec:.4f} arcsec"


def test_write_back_preserves_non_wcs_keywords(frame_header_copy, frame_header):
    header = frame_header_copy("ngc3628")
    before = {k: header[k] for k in ("EXPTIME", "FILTER", "TELESCOP", "GAIN", "OBJECT")}

    _write_wcs_to_header(header, WCS(frame_header("carina")))

    for key, value in before.items():
        assert header[key] == value


def test_write_back_preserves_observation_time_keywords(frame_header_copy, frame_header):
    """DATE-OBS matches the WCS regex, so it is explicitly saved and restored.

    Losing it would break proper-motion correction and every downstream epoch
    calculation — and it would do so silently, because a missing DATE-OBS just
    means "no epoch" rather than an error.
    """
    header = frame_header_copy("ngc3628")
    original = header["DATE-OBS"]

    _write_wcs_to_header(header, WCS(frame_header("carina")))
    assert header["DATE-OBS"] == original


def test_write_back_adds_a_history_record(frame_header_copy, frame_header):
    header = frame_header_copy("ngc3628")
    _write_wcs_to_header(header, WCS(frame_header("carina")))
    assert any("WCS calibration applied" in str(h) for h in header["HISTORY"])


def test_write_back_records_solution_diagnostics_in_history(frame_header_copy, frame_header):
    """Index name and match counts go into HISTORY for later forensics."""
    class Solution:
        index_name = "index-4107.fits"
        n_field = 42
        n_match = 16

    header = frame_header_copy("ngc3628")
    _write_wcs_to_header(header, WCS(frame_header("carina")), solution=Solution())

    history = " ".join(str(h) for h in header["HISTORY"])
    assert "index=index-4107.fits" in history
    assert "n_field=42" in history
    assert "n_match=16" in history


def test_write_back_omits_absent_solution_fields(frame_header_copy, frame_header):
    class Sparse:
        index_name = None
        n_field = None
        n_match = 7

    header = frame_header_copy("ngc3628")
    _write_wcs_to_header(header, WCS(frame_header("carina")), solution=Sparse())

    history = " ".join(str(h) for h in header["HISTORY"])
    assert "n_match=7" in history
    assert "index=" not in history
    assert "n_field=" not in history


def test_written_header_round_trips_through_a_fits_file(tmp_path, frame_header_copy, frame_header):
    """The rewrite must survive serialisation, not just live in memory."""
    header = frame_header_copy("ngc3628")
    replacement = WCS(frame_header("carina"))
    _write_wcs_to_header(header, replacement)

    path = tmp_path / "written.fits"
    fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.float32), header=header).writeto(path)

    reread = WCS(fits.getheader(path))
    assert _wcs_matrix(reread) == pytest.approx(_wcs_matrix(replacement), rel=1e-4)
    assert reread.wcs.crval == pytest.approx(replacement.wcs.crval, abs=1e-9)


# ---------------------------------------------------------------------------
# The documented _clear_wcs_solution_fields quirk
# ---------------------------------------------------------------------------

def test_clearing_resets_the_fields_whose_names_actually_match():
    solution = WcsSolution(
        found_solution=1, crpix1=1.0, crpix2=2.0, crval1=3.0, crval2=4.0,
        cd11=5.0, cd12=6.0, cd21=7.0, cd22=8.0, date_solved=now(),
    )
    _clear_wcs_solution_fields(solution)

    assert solution.found_solution == 0
    for attr in ("crpix1", "crpix2", "crval1", "crval2",
                 "cd11", "cd12", "cd21", "cd22", "date_solved"):
        assert getattr(solution, attr) is None, attr


def test_clearing_silently_misses_four_mapped_columns():
    """PRESERVED QUIRK — ``algorithms/wcs/EXTRACTION.md`` §5.2.

    ``_clear_wcs_solution_fields`` clears the names ``ra``, ``dec``,
    ``pixel_scale`` and ``rotation``. The solve writes ``ra_deg``, ``dec_deg``,
    ``pixel_scale_arcsec_per_px`` and ``rotation_deg``. On a SQLAlchemy instance
    ``setattr`` of an unmapped name silently creates a plain attribute, so
    upstream those four clears are no-ops and the real columns keep their
    previous values after a *failed* solve — stale astrometry presented as
    current.

    ``WcsSolution`` is a plain, non-``slots`` dataclass specifically so this
    reproduces rather than raising ``AttributeError``. Adding ``slots=True``
    would turn a silent no-op into a crash, which is why that is called out in
    CLAUDE.md as something not to "fix".
    """
    solution = WcsSolution(
        found_solution=1,
        ra_deg=180.0, dec_deg=10.0,
        pixel_scale_arcsec_per_px=0.61, rotation_deg=2.2,
    )
    _clear_wcs_solution_fields(solution)

    # The stale values survive, exactly as upstream.
    assert solution.ra_deg == 180.0
    assert solution.dec_deg == 10.0
    assert solution.pixel_scale_arcsec_per_px == 0.61
    assert solution.rotation_deg == 2.2

    # ...and four junk attributes are created instead.
    for orphan in ("ra", "dec", "pixel_scale", "rotation"):
        assert getattr(solution, orphan) is None
        assert orphan not in WcsSolution.__dataclass_fields__


def test_wcs_solution_is_not_a_slots_dataclass():
    """Guard the mechanism, not just the symptom.

    ``slots=True`` would make the four unmapped clears raise instead of being
    silent, changing behaviour on every failed solve.
    """
    assert not hasattr(WcsSolution, "__slots__")
    solution = WcsSolution()
    solution.some_name_not_declared_anywhere = 1  # must not raise


# ---------------------------------------------------------------------------
# WCS construction for a processing run
# ---------------------------------------------------------------------------

def test_processing_run_wcs_comes_from_the_header_when_present(frame_header):
    run = ProcessingRun()
    wcs = build_wcs_for_processing_run(run, frame_header("ngc3628"))
    assert wcs is not None
    assert wcs.has_celestial


def test_processing_run_wcs_is_none_for_an_unsolved_header(frame_header):
    run = ProcessingRun()
    assert build_wcs_for_processing_run(run, frame_header("m15_open")) is None


# ---------------------------------------------------------------------------
# FITS keyword parsing
# ---------------------------------------------------------------------------

def test_ra_above_24_is_read_as_degrees():
    """The documented heuristic: values over 24 cannot be hours."""
    assert _parse_ra_hours(180.0) == pytest.approx(12.0)
    assert _parse_ra_hours(12.0) == pytest.approx(12.0)


def test_ra_and_dec_parse_sexagesimal_strings():
    assert _parse_ra_hours("06:00:00") == pytest.approx(6.0, abs=1e-9)
    assert _parse_dec_deg("+30:00:00") == pytest.approx(30.0, abs=1e-9)
    assert _parse_dec_deg("-30:00:00") == pytest.approx(-30.0, abs=1e-9)


def test_unparseable_keywords_return_none():
    assert _parse_ra_hours(None) is None
    assert _parse_dec_deg(None) is None
    assert _parse_ra_hours("not a coordinate") is None
    assert _parse_dec_deg("not a coordinate") is None


# ---------------------------------------------------------------------------
# The solve itself — opt-in
# ---------------------------------------------------------------------------

@pytest.mark.solver_data
def test_blind_solve_recovers_the_known_plate_solution(frame_image, anet_available, tmp_path):
    """End-to-end plate solve, checked against the frame's own recorded WCS.

    Skipped unless a usable astrometry.net install is present *and* its index
    files cover this field scale. The fixture frames are ~10 arcmin across,
    which needs the 4200-series (or 4107 and below) indexes; the commonly
    installed 4107-4119 set starts at 22 arcmin and will not solve them.

    Both backends degrade to "unavailable" rather than failing, so without the
    data this returns no solution instead of raising — which is why the skip is
    explicit rather than relying on an exception.
    """
    if not anet_available:
        pytest.skip("solve-field not on PATH")

    from algorithms.wcs.wcs import solve_wcs

    data, header = frame_image("ngc3628")
    expected = WCS(header)

    stripped = header.copy()
    for key in list(stripped.keys()):
        if WCS_REGEX.match(key):
            del stripped[key]

    run = ProcessingRun()
    solved, _ = solve_wcs(run, stripped, np.array(data), str(tmp_path))
    if solved is None:
        pytest.skip("no solution — index files likely do not cover this field scale")

    centre_expected = expected.all_pix2world(528, 513, 0)
    centre_solved = solved.all_pix2world(528, 513, 0)
    sep = _angular_sep_deg(
        float(centre_expected[0]) % 360, float(centre_expected[1]),
        float(centre_solved[0]) % 360, float(centre_solved[1]),
    )
    assert sep < 0.01
    assert _wcs_parity(solved) == _wcs_parity(expected)
