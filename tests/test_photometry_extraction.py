"""SEP source extraction: ``algorithms/photometry/source_extraction.py``.

Run against the real frames, because the things that break here are things
synthetic Gaussians do not have: big-endian pixel data, headers with orphaned
SIP coefficients, frames with no WCS at all, and negative-parity plate
solutions.

The numeric baselines below are **recorded behaviour for these specific
frames**, not physics. They exist so that a change in the extraction settings,
the background mesh, or the SEP version shows up as a diff rather than as a
quietly different source list. Each says so in its failure message.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.wcs import WCS

from algorithms.photometry.schemas import (
    SourceExtractionData,
    SourceExtractionSettings,
)
from algorithms.photometry.source_extraction import (
    SIGMA_TO_FWHM,
    _crop_data,
    _strip_orphan_sip,
    build_wcs_from_header,
    get_source_radec,
    get_source_xy,
    run_source_extraction,
)

from .conftest import ALL_FRAMES

#: Recorded detection counts under default settings. Regenerate deliberately.
EXPECTED_SOURCE_COUNTS = {
    "ngc3628_galaxy_v_000.fits": 35,
    "ngc5128_galaxy_b_001.fits": 124,
    "m15_globular_open_000.fits": 154,
    "m31_galaxy_v_000.fits": 193,
}

BASELINE_NOTE = (
    "recorded baseline for this frame under default SourceExtractionSettings; "
    "if the frame, the settings, or the SEP version changed, re-record it "
    "deliberately rather than widening the tolerance"
)


def _extract(frame_image, name, **settings):
    data, header = frame_image(name)
    return run_source_extraction(
        np.array(data), header, SourceExtractionSettings(**settings), file_id=1
    )


# ---------------------------------------------------------------------------
# Extraction over real frames
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.parametrize("frame,expected", sorted(EXPECTED_SOURCE_COUNTS.items()))
def test_detection_count_is_stable_for_a_given_frame(frame_image, frame, expected):
    sources, _, _ = _extract(frame_image, frame)
    assert len(sources) == expected, f"{frame}: {BASELINE_NOTE}"


@pytest.mark.slow
def test_extraction_is_deterministic(frame_image):
    """Same input, same output — down to the last float.

    Nothing in the path is stochastic, but SEP works on a buffer Kepler
    prepares, so a bug that left the buffer partly modified would show up as run
    to run drift rather than as an error.
    """
    first, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits")
    second, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits")

    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert (a.x, a.y, a.flux, a.fwhm_x, a.fwhm_y) == (b.x, b.y, b.flux, b.fwhm_x, b.fwhm_y)


@pytest.mark.slow
def test_extraction_does_not_mutate_the_input_image(frame_image):
    """The caller's array must survive: FITS data is often reused downstream.

    SEP needs a native-endian contiguous buffer and these frames are big-endian
    on disk, so a conversion happens somewhere. It must not be an in-place one.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    before = working.copy()

    run_source_extraction(working, header, SourceExtractionSettings(), file_id=1)
    assert np.array_equal(working, before)


@pytest.mark.slow
def test_big_endian_fits_data_is_accepted(frame_path):
    """FITS is big-endian; ``sep`` requires native byte order.

    Reading a frame the obvious way hands extraction a ``>f4`` array. If the
    conversion were dropped this would raise a byte-order error rather than
    return anything wrong — which is why it is worth one explicit test.
    """
    from astropy.io import fits

    with fits.open(frame_path("ngc3628")) as hdul:
        raw = hdul[0].data
        header = hdul[0].header.copy()
        assert raw.dtype.byteorder == ">", "fixture should be big-endian on disk"
        sources, _, _ = run_source_extraction(
            raw, header, SourceExtractionSettings(), file_id=1
        )
    assert sources


@pytest.mark.slow
@pytest.mark.parametrize("frame", sorted(EXPECTED_SOURCE_COUNTS))
def test_extracted_sources_are_physically_plausible(frame_image, frame):
    """Every detection lands on the image with a positive flux and a real FWHM.

    The settings filter on ``min_fwhm=0.8`` / ``max_fwhm=50`` /
    ``max_ellipticity=3``, so anything outside those got through a filter that
    was supposed to catch it.
    """
    data, _ = frame_image(frame)
    height, width = data.shape
    sources, _, _ = _extract(frame_image, frame)

    for source in sources:
        assert 0 <= source.x < width
        assert 0 <= source.y < height
        assert source.flux > 0
        assert 0.8 <= source.fwhm_x / SIGMA_TO_FWHM * SIGMA_TO_FWHM
        assert source.fwhm_x > 0 and source.fwhm_y > 0
        assert source.fwhm_x / max(source.fwhm_y, 1e-9) <= 3.0 * SIGMA_TO_FWHM


@pytest.mark.slow
def test_background_and_rms_maps_match_the_image_shape(frame_image):
    data, _ = frame_image("ngc3628")
    _, background, rms = _extract(frame_image, "ngc3628_galaxy_v_000.fits")

    assert background.shape == data.shape
    assert rms.shape == data.shape
    assert np.all(np.isfinite(background))
    assert np.all(rms >= 0)


@pytest.mark.slow
def test_sky_coordinates_are_attached_when_the_header_has_a_wcs(frame_image):
    sources, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits")

    assert all(s.ra_hours is not None and s.dec_degs is not None for s in sources)
    assert all(0 <= s.ra_hours < 24 for s in sources)
    assert all(-90 <= s.dec_degs <= 90 for s in sources)


@pytest.mark.slow
def test_extraction_still_works_with_no_wcs_at_all(frame_image):
    """The M15 Open frame has no WCS keywords; extraction must degrade, not fail.

    Sources come back with pixel positions and no sky coordinates. That is the
    documented degradation path — the same frame's Lum sibling has a WCS, so the
    pair isolates this from every other difference.
    """
    data, header = frame_image("m15_open")
    assert build_wcs_from_header(header) is None

    sources, _, _ = _extract(frame_image, "m15_globular_open_000.fits")
    assert sources
    assert all(s.ra_hours is None and s.dec_degs is None for s in sources)
    assert all(s.x is not None and s.y is not None for s in sources)


@pytest.mark.slow
def test_header_metadata_is_stamped_onto_every_source(frame_image):
    """Filter, telescope, exposure and epoch travel with the detections."""
    sources, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits")
    _, header = frame_image("ngc3628")

    for source in sources:
        assert source.filter == header["FILTER"]
        assert source.telescope == header["TELESCOP"]
        assert source.exp_length == pytest.approx(header["EXPTIME"])
        assert source.file_id == 1
        assert source.time is not None


@pytest.mark.slow
def test_limit_keeps_the_brightest_sources(frame_image):
    """``limit`` sorts by flux and keeps the top N, not the first N found."""
    unlimited, _, _ = _extract(frame_image, "m31_galaxy_v_000.fits")
    limited, _, _ = _extract(frame_image, "m31_galaxy_v_000.fits", limit=10)

    assert len(limited) == 10
    brightest = sorted((s.flux for s in unlimited), reverse=True)[:10]
    assert sorted((s.flux for s in limited), reverse=True) == pytest.approx(brightest)


@pytest.mark.slow
def test_a_higher_threshold_finds_fewer_sources(frame_image):
    low, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits", threshold=2.5)
    high, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits", threshold=10.0)
    assert len(high) < len(low)


@pytest.mark.slow
def test_row_cropping_offsets_positions_back_into_full_frame_coordinates(frame_image):
    """A crop must not shift the reported positions.

    ``_crop_data`` returns the offset and extraction adds it back, so a source
    found in a sub-window reports the same x/y it would have in the full frame.
    Without that, catalog matching against a cropped run would be silently off
    by the crop origin.

    Only a row crop is exercised, because a column crop currently raises — see
    ``test_column_cropping_is_a_preserved_upstream_defect``.
    """
    data, _ = frame_image("m31")
    height, width = data.shape
    y0 = height // 4

    full, _, _ = _extract(frame_image, "m31_galaxy_v_000.fits")
    cropped, _, _ = _extract(
        frame_image, "m31_galaxy_v_000.fits", y=y0 + 1, height=height // 2,
    )
    assert cropped

    # Every detection lies inside the requested window in full-frame
    # coordinates — only true if the offset was added back.
    for source in cropped:
        assert y0 <= source.y <= y0 + height // 2

    # And positions agree with the full-frame run for sources found in both.
    full_by_pos = {(round(s.x, 1), round(s.y, 1)) for s in full}
    matched = sum((round(s.x, 1), round(s.y, 1)) in full_by_pos for s in cropped)
    assert matched > len(cropped) // 2


@pytest.mark.slow
def test_column_cropping_is_a_preserved_upstream_defect(frame_image):
    """PRESERVED DEFECT: any crop that narrows the rows raises in ``sep``.

    ``_crop_data`` returns ``data[y0:y0+h, x0:x0+w]``, a numpy *view*. Slicing
    rows alone leaves it C-contiguous, but slicing columns does not, and
    ``sep.Background`` rejects a non-contiguous buffer with
    ``ValueError: array is not C-contiguous``. So every source extraction with
    an ``x`` offset or a ``width`` narrower than the frame fails outright.

    This is upstream's code verbatim — ``skynet .../source_extraction.py:115``
    has the same ``return data[y0:y0+h, x0:x0+w]`` with no
    ``np.ascontiguousarray``. Notably ``photometry.py`` *does* carry
    ``_ensure_native_contiguous`` and calls it before its own ``sep`` entry
    points, so the guard exists in the sibling module and was simply never
    applied here.

    Recorded, not fixed: the extraction contract says preserve known bugs. The
    one-line fix, if a maintainer decides to diverge, is to wrap the return in
    ``np.ascontiguousarray``. This test then fails and should be deleted.
    """
    data, _ = frame_image("m31")
    _, width = data.shape

    # A row-only crop is contiguous and works.
    row_cropped, _, _ = _crop_data(
        np.array(data), SourceExtractionSettings(y=200, height=400)
    )
    assert row_cropped.flags["C_CONTIGUOUS"]

    # A column crop is not, and extraction raises.
    column_cropped, _, _ = _crop_data(
        np.array(data), SourceExtractionSettings(x=200, width=400)
    )
    assert not column_cropped.flags["C_CONTIGUOUS"]

    with pytest.raises(ValueError, match="array is not C-contiguous"):
        _extract(frame_image, "m31_galaxy_v_000.fits", x=200, width=400)

    with pytest.raises(ValueError, match="array is not C-contiguous"):
        _extract(
            frame_image, "m31_galaxy_v_000.fits",
            x=200, y=200, width=400, height=400,
        )


def test_full_width_crop_stays_contiguous_and_is_the_supported_path():
    """Passing ``width`` equal to the frame width is fine — it is still a row crop."""
    data = np.zeros((100, 80), dtype=np.float32)
    cropped, ofs_x, ofs_y = _crop_data(
        data, SourceExtractionSettings(y=21, height=40, width=80)
    )
    assert cropped.flags["C_CONTIGUOUS"]
    assert (ofs_x, ofs_y) == (0, 20)


# ---------------------------------------------------------------------------
# Crop-region validation
# ---------------------------------------------------------------------------

def test_crop_defaults_return_the_original_array_object():
    """No crop requested means no copy — the fast path returns ``data`` itself."""
    data = np.zeros((20, 30), dtype=np.float32)
    cropped, ofs_x, ofs_y = _crop_data(data, SourceExtractionSettings())
    assert cropped is data
    assert (ofs_x, ofs_y) == (0, 0)


def test_crop_coordinates_are_one_based():
    """``x``/``y`` default to 1 and are converted to 0-based internally.

    FITS convention, and getting it wrong shifts every position by one pixel —
    small enough to look like a centroiding difference rather than an off-by-one.
    """
    data = np.arange(600, dtype=np.float32).reshape(20, 30)
    cropped, ofs_x, ofs_y = _crop_data(
        data, SourceExtractionSettings(x=1, y=1, width=5, height=5)
    )
    assert (ofs_x, ofs_y) == (0, 0)
    assert np.array_equal(cropped, data[0:5, 0:5])

    cropped, ofs_x, ofs_y = _crop_data(
        data, SourceExtractionSettings(x=3, y=2, width=4, height=4)
    )
    assert (ofs_x, ofs_y) == (2, 1)
    assert np.array_equal(cropped, data[1:5, 2:6])


def test_crop_rejects_a_non_2d_image():
    with pytest.raises(ValueError, match="expects a 2D image array"):
        _crop_data(np.zeros((2, 3, 4)), SourceExtractionSettings())


@pytest.mark.parametrize(
    "settings,message",
    [
        (dict(x=0), "X must be within image bounds"),
        (dict(x=31), "X must be within image bounds"),
        (dict(y=0), "Y must be within image bounds"),
        (dict(y=21), "Y must be within image bounds"),
        (dict(width=40), "width must be positive and within bounds"),
        (dict(height=40), "height must be positive and within bounds"),
        (dict(x=20, width=20), "width must be positive and within bounds"),
    ],
)
def test_crop_rejects_out_of_bounds_regions(settings, message):
    data = np.zeros((20, 30), dtype=np.float32)
    with pytest.raises(ValueError, match=message):
        _crop_data(data, SourceExtractionSettings(**settings))


# ---------------------------------------------------------------------------
# WCS construction from real headers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", [f for f in ALL_FRAMES if f != "m15_globular_open_000.fits"])
def test_every_frame_with_wcs_keywords_builds_a_celestial_wcs(frame_header, frame):
    assert build_wcs_from_header(frame_header(frame)) is not None


def test_a_header_with_no_wcs_returns_none(frame_header):
    assert build_wcs_from_header(frame_header("m15_open")) is None


def test_build_wcs_never_mutates_the_callers_header(frame_header_copy):
    """It works on a copy — callers reuse the header for the write-back step."""
    header = frame_header_copy("ngc3628")
    before = dict(header)
    build_wcs_from_header(header)
    assert dict(header) == before


def test_crval1_is_wrapped_into_zero_to_360(frame_header_copy):
    header = frame_header_copy("ngc3628")
    original = header["CRVAL1"]
    header["CRVAL1"] = original + 360.0

    wcs = build_wcs_from_header(header)
    assert wcs.wcs.crval[0] == pytest.approx(original % 360, abs=1e-9)


def test_orphan_sip_coefficients_are_dropped(frame_header_copy):
    """SIP without a ``-SIP`` CTYPE is inconsistent; apply it and positions shift.

    Some upstream reductions leave ``A_*``/``B_*`` behind after rewriting CTYPE.
    astropy would apply them anyway (with a warning). Kepler drops them, because
    it builds header WCS objects only for linear pixel<->sky conversion.
    """
    header = frame_header_copy("ngc3628")
    assert not str(header["CTYPE1"]).upper().endswith("-SIP")

    header["A_ORDER"] = 2
    header["A_1_1"] = 1e-5
    header["B_ORDER"] = 2
    header["B_1_1"] = -1e-5

    _strip_orphan_sip(header)
    assert "A_ORDER" not in header
    assert "A_1_1" not in header
    assert "B_ORDER" not in header
    assert "B_1_1" not in header


def test_consistent_sip_headers_are_left_alone(frame_header_copy):
    """A real distortion solution must never be stripped."""
    header = frame_header_copy("ngc3628")
    header["CTYPE1"] = "RA---TAN-SIP"
    header["CTYPE2"] = "DEC--TAN-SIP"
    header["A_ORDER"] = 2
    header["A_1_1"] = 1e-5

    _strip_orphan_sip(header)
    assert header["A_ORDER"] == 2
    assert header["A_1_1"] == 1e-5


def test_sip_free_headers_are_left_alone(frame_header_copy):
    header = frame_header_copy("ngc3628")
    before = dict(header)
    _strip_orphan_sip(header)
    assert dict(header) == before


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------

def _wcs_for(frame_header, name="ngc3628"):
    return build_wcs_from_header(frame_header(name))


def test_source_xy_round_trips_through_a_real_wcs(frame_header):
    """Sky -> pixel -> sky must return the original position."""
    wcs = _wcs_for(frame_header)
    ra_deg, dec_deg = wcs.all_pix2world(500.0, 400.0, 1)

    source = SourceExtractionData(
        ra_hours=float(ra_deg) / 15.0, dec_degs=float(dec_deg)
    )
    x, y = get_source_xy(source, None, wcs)
    assert x == pytest.approx(500.0, abs=1e-6)
    assert y == pytest.approx(400.0, abs=1e-6)

    back = SourceExtractionData(x=float(x), y=float(y))
    ra_hours, dec_degs = get_source_radec(back, None, wcs)
    assert ra_hours == pytest.approx(float(ra_deg) % 360 / 15.0, abs=1e-9)
    assert dec_degs == pytest.approx(float(dec_deg), abs=1e-9)


def test_source_xy_prefers_sky_coordinates_over_stored_pixels(frame_header):
    """When both are present the sky position wins — it is the durable one."""
    wcs = _wcs_for(frame_header)
    ra_deg, dec_deg = wcs.all_pix2world(500.0, 400.0, 1)

    source = SourceExtractionData(
        ra_hours=float(ra_deg) / 15.0, dec_degs=float(dec_deg), x=1.0, y=1.0
    )
    x, y = get_source_xy(source, None, wcs)
    assert x == pytest.approx(500.0, abs=1e-6)


def test_source_xy_falls_back_to_stored_pixels_without_a_wcs():
    source = SourceExtractionData(x=12.5, y=34.5, ra_hours=1.0, dec_degs=2.0)
    assert get_source_xy(source, None, None) == (12.5, 34.5)


def test_source_xy_returns_none_when_it_has_nothing_to_work_with():
    assert get_source_xy(SourceExtractionData(), None, None) == (None, None)


def test_sky_proper_motion_moves_the_source_along_its_position_angle(frame_header):
    """Proper motion is applied in sky coordinates before projecting to pixels.

    ``pm_sky`` is per second, and the RA component is divided by cos(dec) — the
    standard correction. A source with position angle 0 must move north only.
    """
    wcs = _wcs_for(frame_header)
    ra_deg, dec_deg = wcs.all_pix2world(500.0, 400.0, 1)
    epoch = datetime(2026, 4, 8, tzinfo=timezone.utc)
    pm_epoch = epoch - timedelta(days=365)

    # 1 degree per year, due north.
    per_second = 1.0 / (365 * 24 * 3600)
    source = SourceExtractionData(
        ra_hours=float(ra_deg) / 15.0, dec_degs=float(dec_deg),
        pm_sky=per_second, pm_pos_angle_sky=0.0, pm_epoch=pm_epoch,
    )
    x, y = get_source_xy(source, epoch, wcs)

    moved_ra, moved_dec = wcs.all_pix2world(float(x), float(y), 1)
    assert float(moved_dec) - float(dec_deg) == pytest.approx(1.0, abs=1e-3)
    assert float(moved_ra) == pytest.approx(float(ra_deg), abs=1e-3)


def test_pixel_proper_motion_is_used_when_there_is_no_wcs():
    """``pm_pixel``/``pm_pos_angle_pixel`` is the no-WCS path.

    Position angle 90 deg moves purely in +y, matching ``cos``/``sin`` on x/y.
    """
    epoch = datetime(2026, 4, 8, tzinfo=timezone.utc)
    source = SourceExtractionData(
        x=100.0, y=200.0, pm_pixel=1.0, pm_pos_angle_pixel=90.0,
        pm_epoch=epoch - timedelta(seconds=10),
    )
    x, y = get_source_xy(source, epoch, None)
    assert x == pytest.approx(100.0, abs=1e-9)
    assert y == pytest.approx(210.0, abs=1e-9)


def test_proper_motion_is_ignored_without_an_epoch():
    source = SourceExtractionData(
        x=100.0, y=200.0, pm_pixel=1.0, pm_pos_angle_pixel=90.0,
        pm_epoch=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    assert get_source_xy(source, None, None) == (100.0, 200.0)


def test_source_radec_returns_hours_wrapped_into_zero_to_24(frame_header):
    """RA is reported in *hours*, modulo 360 degrees first.

    Two conversions in one line, and both are easy to lose: a source just west
    of RA=0 must come back near 23.99, not near -0.01.
    """
    wcs = _wcs_for(frame_header)
    source = SourceExtractionData(x=500.0, y=400.0)
    ra_hours, dec_degs = get_source_radec(source, None, wcs)

    assert 0 <= ra_hours < 24
    ra_deg, _ = wcs.all_pix2world(500.0, 400.0, 1)
    assert ra_hours == pytest.approx(float(ra_deg) % 360 / 15.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

def test_sigma_to_fwhm_constant():
    """``2*sqrt(2*ln 2)``. SEP reports Gaussian sigma; Kepler reports FWHM."""
    assert SIGMA_TO_FWHM == pytest.approx(2.3548200450309493, abs=1e-12)
    assert SIGMA_TO_FWHM == pytest.approx(2 * math.sqrt(2 * math.log(2)), abs=0)


@pytest.mark.slow
def test_reported_fwhm_is_the_sep_axis_scaled_by_the_constant(frame_image):
    """``from_numpy_row`` multiplies the ``a``/``b`` axes by SIGMA_TO_FWHM.

    Reporting raw sigma as FWHM would under-report seeing by a factor of 2.35
    and quietly change which sources pass the ``min_fwhm``/``max_fwhm`` filters.
    """
    sources, _, _ = _extract(frame_image, "ngc3628_galaxy_v_000.fits")
    for source in sources:
        assert source.fwhm_x >= source.fwhm_y  # SEP's a >= b
        # A stellar profile at ~0.6 arcsec/pixel: sigma of order 1 pixel, so
        # FWHM should land in a few-pixel range, not a sub-pixel one.
        assert 0.5 < source.fwhm_x < 50.0
