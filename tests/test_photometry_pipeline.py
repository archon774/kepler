"""Aperture photometry: ``algorithms/photometry/photometry.py``.

Measures flux and instrumental magnitude at given positions on a real frame.
The tests split into three concerns:

* **argument validation** — aperture mode needs a positive ``a``; adaptive mode
  with no FWHM needs a centroiding radius. Both raise rather than silently
  measuring something meaningless;
* **magnitude arithmetic** — the exposure-time normalisation and
  ``zero_point_mag`` offset. A sign or a missing ``texp`` divide moves every
  magnitude in the frame by a constant, which is exactly the kind of error a
  zero-point solve absorbs without complaint;
* **source bookkeeping** — which rows survive, and what identity they keep.

Baselines marked "recorded" are behaviour pins for the specific fixture frame,
not physical constants.

Modelled on ``skynet .../tests/runners/test_photometry.py``.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from algorithms.photometry.photometry import (
    _apply_wcs_to_source,
    _ensure_native_contiguous,
    _row_to_mapping,
    run_photometry,
)
from algorithms.photometry.schemas import (
    PhotometrySettings,
    SourceExtractionData,
    SourceExtractionSettings,
)
from algorithms.photometry.source_extraction import (
    build_wcs_from_header,
    run_source_extraction,
)

BASELINE_NOTE = (
    "recorded baseline for this frame; re-record deliberately rather than "
    "widening the tolerance"
)


@pytest.fixture(scope="module")
def measured(request):
    """``(data, header, detections, photometry)`` for the workhorse frame."""
    frame_image = request.getfixturevalue("frame_image")
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    results = run_photometry(working, header, detections, PhotometrySettings(a=5.0))
    return working, header, detections, results


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def test_empty_source_list_returns_empty_without_touching_the_image():
    assert run_photometry(None, None, [], PhotometrySettings(a=5.0)) == []


def test_aperture_mode_requires_an_aperture_size(frame_image):
    data, header = frame_image("ngc3628")
    sources = [SourceExtractionData(x=100.0, y=100.0)]

    with pytest.raises(ValueError, match="Missing aperture radius"):
        run_photometry(np.array(data), header, sources, PhotometrySettings(a=None))


@pytest.mark.parametrize("a", [0.0, -1.0])
def test_aperture_size_must_be_positive(frame_image, a):
    data, header = frame_image("ngc3628")
    sources = [SourceExtractionData(x=100.0, y=100.0)]

    with pytest.raises(ValueError, match="must be positive"):
        run_photometry(np.array(data), header, sources, PhotometrySettings(a=a))


def test_unknown_mode_is_rejected(frame_image):
    data, header = frame_image("ngc3628")
    sources = [SourceExtractionData(x=100.0, y=100.0)]

    with pytest.raises(ValueError, match='mode must be "aperture" or "auto"'):
        run_photometry(
            np.array(data), header, sources, PhotometrySettings(mode="psf", a=5.0)
        )


def test_adaptive_mode_without_fwhm_or_centroid_radius_raises(frame_image):
    """Adaptive apertures are sized from the source FWHM.

    With neither a measured FWHM nor a centroiding radius to derive one, there
    is nothing to size the aperture from, so it raises instead of defaulting to
    an arbitrary value.
    """
    data, header = frame_image("ngc3628")
    sources = [SourceExtractionData(x=100.0, y=100.0)]  # no fwhm_x/fwhm_y

    with pytest.raises(ValueError, match="Centroiding radius must be provided"):
        run_photometry(
            np.array(data), header, sources,
            PhotometrySettings(mode="auto", a=2.5, centroid_radius=0.0),
        )


def test_all_sources_outside_the_image_raises(frame_image):
    data, header = frame_image("ngc3628")
    height, width = data.shape
    sources = [SourceExtractionData(x=width + 50.0, y=height + 50.0)]

    with pytest.raises(ValueError, match="All sources are outside image boundaries"):
        run_photometry(np.array(data), header, sources, PhotometrySettings(a=5.0))


# ---------------------------------------------------------------------------
# Measurement on a real frame
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_photometry_measures_every_detection(measured):
    _, _, detections, results = measured
    assert len(results) == len(detections) == 35, BASELINE_NOTE
    assert all(r.mag is not None for r in results)
    assert all(r.flux is not None and r.flux > 0 for r in results)


@pytest.mark.slow
def test_measurements_are_deterministic(frame_image):
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    first = run_photometry(working, header, detections, PhotometrySettings(a=5.0))
    second = run_photometry(working, header, detections, PhotometrySettings(a=5.0))

    assert [r.mag for r in first] == [r.mag for r in second]
    assert [r.flux for r in first] == [r.flux for r in second]


@pytest.mark.slow
def test_instrumental_magnitudes_are_negative_with_a_zero_zero_point(measured):
    """``mag = -2.5*log10(flux/texp)`` with ``zero_point_mag = 0``.

    Fluxes here are thousands of counts over a ~90 s exposure, so the raw
    instrumental magnitude is negative. A positive value would mean the exposure
    normalisation or the sign was lost.
    """
    _, _, _, results = measured
    assert all(r.mag < 0 for r in results)
    assert min(r.mag for r in results) > -20
    assert max(r.mag for r in results) < 0


@pytest.mark.slow
def test_magnitude_follows_the_flux_and_exposure_relation(frame_image):
    """``mag = -2.5*log10(flux/texp)`` exactly — with aperture correction off.

    This is the one arithmetic relation the whole zero point rests on, and both
    quantities come back on the same object, so it needs no baseline.

    It must be checked with ``apcorr_tol = 0``, which is also what field
    calibration uses. See the next test for why.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    results = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, apcorr_tol=0.0)
    )
    texp = float(header["EXPTIME"])

    for result in results:
        expected = -2.5 * math.log10(result.flux / texp)
        assert result.mag == pytest.approx(expected, abs=1e-9), result.id


@pytest.mark.slow
def test_aperture_correction_adjusts_the_magnitude_but_not_the_reported_flux(frame_image):
    """A trap worth pinning: with correction on, ``mag`` and ``flux`` disagree.

    The aperture-correction pass adjusts the magnitude to account for light
    outside the aperture, but the ``flux`` column keeps the raw aperture sum. So
    with the default ``apcorr_tol = 1e-4``, recomputing ``-2.5*log10(flux/texp)``
    does *not* reproduce ``mag`` — on this frame the two differ by ~0.11 mag.

    Anything that recomputes magnitudes from the reported flux has to disable
    aperture correction first, which is one more reason field calibration forces
    ``apcorr_tol = 0``.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    texp = float(header["EXPTIME"])

    corrected = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, apcorr_tol=1e-4)
    )
    uncorrected = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, apcorr_tol=0.0)
    )

    for c, u in zip(corrected, uncorrected):
        # Same measured flux...
        assert c.flux == pytest.approx(u.flux, abs=0)
        # ...but the corrected magnitude no longer matches it.
        naive = -2.5 * math.log10(c.flux / texp)
        assert u.mag == pytest.approx(naive, abs=1e-9)

    deltas = [c.mag - u.mag for c, u in zip(corrected, uncorrected)]
    assert any(abs(d) > 0.01 for d in deltas)


@pytest.mark.slow
def test_zero_point_mag_shifts_every_magnitude_by_a_constant(frame_image):
    """``zero_point_mag`` is a pure additive offset — Afterglow passes 20 here."""
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )

    base = run_photometry(working, header, detections, PhotometrySettings(a=5.0))
    offset = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, zero_point_mag=20.0)
    )

    assert len(base) == len(offset)
    for b, o in zip(base, offset):
        assert o.mag - b.mag == pytest.approx(20.0, abs=1e-9)
        assert o.flux == pytest.approx(b.flux, abs=0)
        assert o.mag_error == pytest.approx(b.mag_error, abs=0)


@pytest.mark.slow
def test_growing_the_aperture_collects_more_flux_in_aggregate(measured, frame_image):
    """Typical flux rises with aperture size — but only in aggregate.

    Per source it is *not* monotonic, and that is expected rather than a bug:
    the background estimate comes from an annulus that scales with the aperture,
    so for a faint or blended source the extra subtracted background can
    outweigh the extra collected light. On this frame source 0 is brighter at
    a=5 than at a=7.

    The population median is the honest claim, and it is the one that would
    break if the aperture size stopped being applied at all.
    """
    data, header, detections, _ = measured

    medians = []
    for a in (3.0, 5.0, 7.0):
        results = run_photometry(
            np.array(data), header, detections,
            PhotometrySettings(a=a, apcorr_tol=0.0),
        )
        medians.append(float(np.median([r.flux for r in results])))

    assert medians[0] < medians[1] < medians[2], medians


@pytest.mark.slow
def test_aperture_geometry_is_reported_back(measured):
    """The measured aperture travels with the result, for reproducibility."""
    _, _, _, results = measured
    for result in results:
        assert result.aper_a == pytest.approx(5.0)
        assert result.aper_b == pytest.approx(5.0)


@pytest.mark.slow
def test_aperture_correction_changes_the_magnitudes(frame_image):
    """``apcorr_tol > 0`` enables the aperture-correction pass.

    Field calibration force-disables this (``apcorr_tol = 0.0``) for legacy
    Afterglow parity. The two settings must therefore produce *different*
    magnitudes — if they did not, that override would be a no-op and the parity
    comment would be describing nothing.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )

    corrected = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, apcorr_tol=1e-4)
    )
    uncorrected = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, apcorr_tol=0.0)
    )

    deltas = [c.mag - u.mag for c, u in zip(corrected, uncorrected)]
    assert any(abs(d) > 1e-6 for d in deltas), (
        "aperture correction had no effect; field calibration's apcorr_tol=0 "
        "override would then be meaningless"
    )
    # The correction is a real but modest brightening, not a wholesale rescale.
    assert all(abs(d) < 1.0 for d in deltas)


@pytest.mark.slow
def test_photometry_works_on_a_frame_with_no_wcs(frame_image):
    """The M15 Open frame: pixel positions only, and that is enough.

    Photometry needs pixel coordinates, not sky ones. Results come back with no
    RA/Dec, which is what makes a subsequent catalog match impossible — but the
    measurement itself must still succeed.
    """
    data, header = frame_image("m15_open")
    assert build_wcs_from_header(header) is None

    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    results = run_photometry(working, header, detections, PhotometrySettings(a=5.0))

    assert results
    assert all(r.mag is not None for r in results)
    assert all(r.ra_hours is None for r in results)


@pytest.mark.slow
def test_out_of_bounds_sources_are_dropped_not_measured(frame_image):
    """A source off the detector is skipped; the rest are still measured."""
    data, header = frame_image("ngc3628")
    height, width = data.shape
    working = np.array(data)

    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    padded = list(detections) + [
        SourceExtractionData(x=-10.0, y=10.0),
        SourceExtractionData(x=float(width + 10), y=10.0),
        SourceExtractionData(x=10.0, y=float(height + 10)),
    ]

    results = run_photometry(working, header, padded, PhotometrySettings(a=5.0))
    assert len(results) == len(detections)


@pytest.mark.slow
def test_source_identity_survives_measurement(frame_image):
    """Photometry results carry the detection's ``id`` through.

    Field calibration keys photometry back to catalog rows by ``id``; losing it
    here makes every match fail silently.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    for i, source in enumerate(detections):
        source.id = f"det-{i}"

    results = run_photometry(working, header, detections, PhotometrySettings(a=5.0))
    assert {r.id for r in results} == {f"det-{i}" for i in range(len(detections))}


@pytest.mark.slow
def test_header_metadata_is_restamped_onto_results(measured):
    _, header, _, results = measured
    for result in results:
        assert result.filter == header["FILTER"]
        assert result.telescope == header["TELESCOP"]
        assert result.exp_length == pytest.approx(header["EXPTIME"])


@pytest.mark.slow
def test_gain_is_read_from_the_header_when_not_supplied(frame_image):
    """A supplied ``gain`` of exactly 1 is treated as "unset", not as a value.

    ``run_photometry`` falls back to the header when ``settings.gain`` is
    ``None`` *or* ``1``. That second condition is easy to miss and means a
    caller genuinely wanting unit gain cannot ask for it — pinned because it
    changes the reported flux errors.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )
    assert header["GAIN"] != 1

    from_header = run_photometry(working, header, detections, PhotometrySettings(a=5.0))
    gain_one = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, gain=1)
    )
    explicit = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, gain=4.0)
    )

    # gain=1 behaves identically to unset.
    assert [r.mag_error for r in gain_one] == [r.mag_error for r in from_header]
    # A genuinely different gain changes the uncertainties.
    assert [r.mag_error for r in explicit] != [r.mag_error for r in from_header]


@pytest.mark.slow
def test_centroiding_moves_positions_and_is_off_by_default(frame_image):
    """``centroid_radius`` defaults to 0, which disables the refinement pass."""
    data, header = frame_image("ngc3628")
    working = np.array(data)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )

    assert PhotometrySettings(a=5.0).centroid_radius == 0.0

    plain = run_photometry(working, header, detections, PhotometrySettings(a=5.0))
    centroided = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, centroid_radius=5.0)
    )

    assert [round(r.x, 6) for r in plain] == [round(s.x, 6) for s in detections]
    moved = sum(
        abs(c.x - p.x) > 1e-6 or abs(c.y - p.y) > 1e-6
        for c, p in zip(centroided, plain)
    )
    assert moved > 0


@pytest.mark.slow
def test_reported_radec_reflects_the_measured_pixel_position(frame_image):
    """LEGACY PARITY: RA/Dec is recomputed *after* centroiding, not carried over.

    ``run_photometry`` builds the result from the row (which holds the
    centroided x/y) and only then applies the WCS. Carrying the detection's
    original RA/Dec across instead would leave sky and pixel positions
    describing different points.
    """
    data, header = frame_image("ngc3628")
    working = np.array(data)
    wcs = build_wcs_from_header(header)
    detections, _, _ = run_source_extraction(
        working, header, SourceExtractionSettings(), file_id=1
    )

    results = run_photometry(
        working, header, detections, PhotometrySettings(a=5.0, centroid_radius=5.0)
    )
    for result in results:
        ra_deg, dec_deg = wcs.all_pix2world(result.x, result.y, 1)
        assert result.ra_hours == pytest.approx(float(ra_deg) % 360 / 15.0, abs=1e-12)
        assert result.dec_degs == pytest.approx(float(dec_deg), abs=1e-12)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def test_ensure_native_contiguous_fixes_byte_order_and_layout():
    """``sep`` needs both; FITS gives neither for a sliced big-endian array."""
    big_endian = np.arange(12, dtype=">f4").reshape(3, 4)
    assert big_endian.dtype.byteorder == ">"

    fixed = _ensure_native_contiguous(big_endian)
    assert fixed.dtype.byteorder in ("=", "|")
    assert fixed.flags["C_CONTIGUOUS"]
    assert np.array_equal(fixed, big_endian)

    sliced = np.arange(12, dtype=np.float32).reshape(3, 4)[:, 1:3]
    assert not sliced.flags["C_CONTIGUOUS"]
    assert _ensure_native_contiguous(sliced).flags["C_CONTIGUOUS"]


def test_ensure_native_contiguous_leaves_a_good_array_alone():
    native = np.ascontiguousarray(np.arange(12, dtype=np.float32))
    assert np.array_equal(_ensure_native_contiguous(native), native)


def test_row_to_mapping_exposes_structured_fields_by_name():
    row = np.zeros(1, [("x", float), ("y", float), ("flux", float)])[0]
    row["x"], row["y"], row["flux"] = 1.5, 2.5, 100.0
    assert _row_to_mapping(row) == {"x": 1.5, "y": 2.5, "flux": 100.0}


def test_apply_wcs_is_a_no_op_without_a_wcs():
    source = SourceExtractionData(x=10.0, y=20.0)
    assert _apply_wcs_to_source(source, None) is source


def test_apply_wcs_stamps_sky_coordinates(frame_header):
    wcs = build_wcs_from_header(frame_header("ngc3628"))
    source = SourceExtractionData(x=500.0, y=400.0)

    updated = _apply_wcs_to_source(source, wcs)
    assert updated.ra_hours is not None and updated.dec_degs is not None
    assert 0 <= updated.ra_hours < 24

    ra_deg, dec_deg = wcs.all_pix2world(500.0, 400.0, 1)
    assert updated.ra_hours == pytest.approx(float(ra_deg) % 360 / 15.0, abs=1e-12)
    assert updated.dec_degs == pytest.approx(float(dec_deg), abs=1e-12)
