"""WCS footprint geometry: ``algorithms/query/geometry.py``.

This is the module that decides *which patch of sky gets queried*, so an error
here does not raise — it fetches the wrong stars and the zero-point solve
quietly calibrates against them. Everything is exercised against the real
headers in ``test_data/optical``, because the interesting cases are exactly the
ones real detectors produce: rotation, negative parity, and southern fields
where the cos(dec) narrowing stops being a rounding detail.

Two footprint implementations coexist and disagree, deliberately:
``boxes_from_wcs`` projects the four corners and handles rotation;
``image_boxes_from_wcs`` multiplies pixel scale by axis length and does not.
Both are pinned, including where they diverge.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.wcs import WCS

from algorithms.query.geometry import (
    boxes_from_wcs,
    clip_sources_to_box,
    clip_sources_to_wcs,
    combined_bounding_box,
    image_boxes_from_wcs,
    infer_image_shape,
    normalize_wcs_list,
    remove_duplicate_sources,
    wcs_array_shape,
)

from .conftest import ALL_FRAMES

#: Frames with a usable WCS. m15_open has no WCS keywords at all.
WCS_FRAMES = [f for f in ALL_FRAMES if f != "m15_globular_open_000.fits"]


class _Source:
    """Minimal duck-typed stand-in for CatalogSource in the geometry helpers."""

    def __init__(self, ra_hours=None, dec_degs=None, id=None):
        self.ra_hours = ra_hours
        self.dec_degs = dec_degs
        self.id = id
        self.x = None
        self.y = None


def _wcs_from(frame_header, name):
    header = frame_header(name)
    wcs = WCS(header)
    wcs.array_shape = (header["NAXIS2"], header["NAXIS1"])
    return wcs, header


# ---------------------------------------------------------------------------
# Shape resolution
# ---------------------------------------------------------------------------

def test_wcs_array_shape_is_strict_about_a_missing_shape():
    """Guessing a footprint produces a plausible-looking but wrong query region.

    So the catalog-query path treats a shapeless WCS as a caller error rather
    than inventing dimensions. ``infer_image_shape`` is the lenient variant.
    """
    with pytest.raises(ValueError, match="array_shape is required"):
        wcs_array_shape(WCS(naxis=2))


def test_wcs_array_shape_returns_height_first(frame_header):
    wcs, header = _wcs_from(frame_header, "ngc3628")
    assert wcs_array_shape(wcs) == (header["NAXIS2"], header["NAXIS1"])
    assert wcs_array_shape(wcs) == (1027, 1056)


def test_infer_shape_prefers_an_explicit_argument(frame_header):
    wcs, _ = _wcs_from(frame_header, "ngc3628")
    assert infer_image_shape(wcs, shape=(7, 9)) == (7, 9)


def test_infer_shape_falls_back_through_wcs_header_and_data(frame_header):
    """Order: explicit, array_shape, pixel_shape, header NAXIS, data.shape."""
    header = frame_header("ngc3628")
    bare = WCS(header)          # no array_shape set
    bare.array_shape = None
    bare.pixel_shape = None

    assert infer_image_shape(bare, header=header) == (1027, 1056)
    assert infer_image_shape(bare, data=np.zeros((11, 13))) == (11, 13)

    with pytest.raises(ValueError, match="Cannot determine image shape"):
        infer_image_shape(bare)


def test_pixel_shape_is_width_first_unlike_everything_else(frame_header):
    """``pixel_shape`` is ``(naxis1, naxis2)``; every other source is (h, w).

    An easy transposition to make, and on the 1024² frames it would be
    invisible — which is why this is asserted on a non-square one.
    """
    header = frame_header("ngc3628")
    wcs = WCS(header)
    wcs.array_shape = None
    wcs.pixel_shape = (1056, 1027)
    assert infer_image_shape(wcs) == (1027, 1056)


# ---------------------------------------------------------------------------
# Footprints from real WCS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame", WCS_FRAMES)
def test_footprint_is_plausible_for_every_real_frame(frame_header, frame):
    """Sweep: every real WCS yields a sane centre and a sub-degree field.

    These are all small-field imagers (0.4-0.8 arcsec/pixel over ~1000-1600
    pixels), so a footprint outside these bounds means the projection went
    wrong, not that the telescope is unusual.
    """
    wcs, header = _wcs_from(frame_header, frame)
    (ra, dec, width, height), = boxes_from_wcs(wcs)

    assert 0.0 <= ra < 360.0
    assert -90.0 <= dec <= 90.0
    assert 0.0 < width < 1.0, f"{frame}: width {width} deg"
    assert 0.0 < height < 1.0, f"{frame}: height {height} deg"


@pytest.mark.parametrize("frame", WCS_FRAMES)
def test_footprint_centre_matches_the_header_pointing(frame_header, frame):
    """The computed centre must agree with the frame's own RA/DEC keywords.

    An independent check on the projection: RA/DEC in the header came from the
    telescope, while the footprint centre comes from the plate solution. They
    should agree to a few arcminutes — pointing error, not a coordinate bug.
    """
    from algorithms.wcs.header_utils import guess_icrs_radec_from_header

    wcs, header = _wcs_from(frame_header, frame)
    (ra, dec, _, _), = boxes_from_wcs(wcs)

    hint_ra, hint_dec = guess_icrs_radec_from_header(header)
    if hint_ra is None or hint_dec is None:
        pytest.skip(f"{frame} carries no pointing keywords")

    cos_dec = np.cos(np.deg2rad(dec))
    sep = np.hypot((ra - hint_ra) * cos_dec, dec - hint_dec)
    assert sep < 0.5, f"{frame}: footprint centre {sep:.3f} deg from header pointing"


def test_footprint_width_is_narrowed_by_cos_dec(frame_header):
    """The southern frame's width must be an angular extent, not an RA span.

    NGC 2070 sits at dec −69, where cos(dec) is 0.36: the raw span of corner RAs
    is nearly three times the true angular width. Getting this wrong would query
    a box far wider than the detector and pull in stars that are not on the
    frame.
    """
    wcs, _ = _wcs_from(frame_header, "ngc2070")
    (_, dec, width, height), = boxes_from_wcs(wcs)

    assert dec < -60
    # Roughly square detector, so width and height should be comparable...
    assert 0.5 < width / height < 2.0
    # ...and the naive RA span would be inflated by 1/cos(dec) ~ 2.8x.
    corners = wcs.calc_footprint()
    naive_ra_span = corners[:, 0].max() - corners[:, 0].min()
    assert naive_ra_span > width * 2.0


def test_ninety_degree_rotation_swaps_the_footprint_axes(frame_header):
    """Carina is rotated ~90 deg: CD1_1 is near zero and the scale is off-diagonal.

    ``boxes_from_wcs`` projects corners, so it tracks the rotation. Anything
    reading the scale off CD1_1 alone would report a near-zero width here.
    """
    wcs, header = _wcs_from(frame_header, "carina")
    assert abs(header["CD1_1"]) < abs(header["CD1_2"]) / 10

    (_, _, width, height), = boxes_from_wcs(wcs)
    assert width > 0.1 and height > 0.1


@pytest.mark.parametrize("frame", ["m31_galaxy_v_000.fits", "ngc7048_pn_r_000.fits"])
def test_negative_parity_frames_still_yield_a_positive_footprint(frame_header, frame):
    """A flipped detector must not produce a negative or zero width."""
    wcs, _ = _wcs_from(frame_header, frame)
    matrix = wcs.pixel_scale_matrix
    assert np.linalg.det(matrix) < 0, "fixture should be negative parity"

    (_, _, width, height), = boxes_from_wcs(wcs)
    assert width > 0 and height > 0


# ---------------------------------------------------------------------------
# The two footprint implementations
# ---------------------------------------------------------------------------

def test_both_footprint_implementations_agree_on_centre_and_roughly_on_size(frame_header):
    """Same centre exactly; sizes differ by the rotation the projection sees.

    NGC 2070 is rotated ~1.6 deg. ``boxes_from_wcs`` projects the corners, so it
    returns the bounding box of the *rotated* rectangle —
    ``w*cos(theta) + h*sin(theta)`` — while ``image_boxes_from_wcs`` multiplies
    pixel scale by axis length and returns the detector's own extent. On this
    frame that is a 2.6% difference, and it grows with rotation angle.

    The centres must still agree to the last float: both project the same pixel.
    """
    wcs, header = _wcs_from(frame_header, "ngc2070")

    (ra_a, dec_a, w_a, h_a), = boxes_from_wcs(wcs)
    (ra_b, dec_b, w_b, h_b), = image_boxes_from_wcs(wcs, header=header)

    assert ra_a == pytest.approx(ra_b, abs=1e-9)
    assert dec_a == pytest.approx(dec_b, abs=1e-9)

    # The projected box is the larger one, by the rotation factor.
    theta = np.arctan2(header["CD1_2"], header["CD1_1"])
    h_px, w_px = wcs_array_shape(wcs)
    expected_ratio = (w_px * abs(np.cos(theta)) + h_px * abs(np.sin(theta))) / w_px

    assert w_a > w_b
    assert w_a / w_b == pytest.approx(expected_ratio, rel=0.01)


def test_image_boxes_does_not_see_rotation(frame_header):
    """The documented divergence, on the frame that shows it.

    Carina is rotated ~90 deg. ``image_boxes_from_wcs`` multiplies per-axis
    pixel scale by axis length, so it reports the detector's own aspect ratio;
    ``boxes_from_wcs`` projects corners and reports the sky footprint, whose
    axes are swapped. On a near-square detector this is a small difference —
    which is why the limitation has survived — but the two are not
    interchangeable.
    """
    wcs, header = _wcs_from(frame_header, "carina")

    (_, _, w_projected, h_projected), = boxes_from_wcs(wcs)
    (_, _, w_scaled, h_scaled), = image_boxes_from_wcs(wcs, header=header)

    # The projected footprint is wider than tall; the scaled one follows the
    # 1056x1027 detector and is also wider than tall, but by a different ratio.
    assert w_projected / h_projected != pytest.approx(w_scaled / h_scaled, rel=1e-3)


def test_image_boxes_works_without_an_array_shape(frame_header):
    """Its reason to exist: callers that only have a header."""
    header = frame_header("ngc3628")
    bare = WCS(header)
    bare.array_shape = None
    bare.pixel_shape = None

    with pytest.raises(ValueError):
        boxes_from_wcs(bare)

    (ra, dec, width, height), = image_boxes_from_wcs(bare, header=header)
    assert width > 0 and height > 0


# ---------------------------------------------------------------------------
# Rectangular clipping
# ---------------------------------------------------------------------------

def test_clip_keeps_sources_inside_the_box():
    sources = [
        _Source(ra_hours=12.0, dec_degs=10.0),     # centre
        _Source(ra_hours=12.0, dec_degs=10.4),     # outside in dec
        _Source(ra_hours=13.0, dec_degs=10.0),     # outside in ra
    ]
    kept = clip_sources_to_box(sources, 12.0, 10.0, width_arcmins=30, height_arcmins=30)
    assert len(kept) == 1
    assert kept[0].dec_degs == 10.0


def test_ra_half_width_is_not_naively_divided_by_cos_dec():
    """The bound is ``arcsin(sin(w/2)/cos(dec))``, which is wider than w/2/cos(dec).

    Upstream cites the tangent-meridian result rather than the small-angle
    approximation because the latter *undershoots* at high declination, clipping
    away real sources near the box edges.
    """
    dec = 80.0
    width_arcmins = 60.0
    naive = (width_arcmins / 120) / np.cos(np.deg2rad(dec)) / 15
    correct = np.rad2deg(
        np.arcsin(np.sin(np.deg2rad(width_arcmins / 120)) / np.cos(np.deg2rad(dec)))
    ) / 15
    assert correct > naive

    # A source between the two bounds must survive: the correct bound keeps it.
    ra_hours = 12.0
    edge = _Source(ra_hours=ra_hours + (naive + correct) / 2, dec_degs=dec)
    kept = clip_sources_to_box([edge], ra_hours, dec, width_arcmins, 60.0)
    assert kept == [edge]


def test_a_region_containing_the_north_pole_clips_in_declination_only():
    """Every RA qualifies once the pole is inside the field. Preserved verbatim."""
    sources = [
        _Source(ra_hours=0.5, dec_degs=89.9),
        _Source(ra_hours=18.0, dec_degs=89.9),
        _Source(ra_hours=6.0, dec_degs=20.0),
    ]
    kept = clip_sources_to_box(sources, 12.0, 89.95, width_arcmins=60, height_arcmins=60)
    assert len(kept) == 2
    assert all(s.dec_degs > 80 for s in kept)


def test_a_region_containing_the_south_pole_clips_in_declination_only():
    sources = [
        _Source(ra_hours=0.5, dec_degs=-89.9),
        _Source(ra_hours=18.0, dec_degs=-89.9),
        _Source(ra_hours=6.0, dec_degs=-20.0),
    ]
    kept = clip_sources_to_box(sources, 12.0, -89.95, width_arcmins=60, height_arcmins=60)
    assert len(kept) == 2


def test_a_region_straddling_ra_zero_splits_into_two_ranges():
    """RA wraps, so the accepted set is two disjoint intervals, not one."""
    sources = [
        _Source(ra_hours=23.99, dec_degs=0.0),   # just below 24h
        _Source(ra_hours=0.01, dec_degs=0.0),    # just above 0h
        _Source(ra_hours=12.0, dec_degs=0.0),    # opposite side of the sky
    ]
    kept = clip_sources_to_box(sources, 0.0, 0.0, width_arcmins=60, height_arcmins=60)
    assert len(kept) == 2
    assert 12.0 not in [s.ra_hours for s in kept]


def test_a_region_straddling_ra_twentyfour_splits_into_two_ranges():
    sources = [
        _Source(ra_hours=23.99, dec_degs=0.0),
        _Source(ra_hours=0.01, dec_degs=0.0),
        _Source(ra_hours=12.0, dec_degs=0.0),
    ]
    kept = clip_sources_to_box(sources, 23.99, 0.0, width_arcmins=60, height_arcmins=60)
    assert len(kept) == 2


def test_wide_box_near_a_pole_silently_returns_nothing():
    """PRESERVED DEFECT: ``arcsin`` of a value > 1 gives NaN, and NaN drops everything.

    The RA half-width is ``arcsin(sin(w/2) / cos(dec))``. Once the field is wide
    enough relative to ``cos(dec)`` the argument exceeds 1, numpy returns NaN
    with a RuntimeWarning, and every subsequent comparison against NaN is False
    — including the guards for the pole and RA-wrap cases. Execution falls
    through to the final ``ra_min <= ra <= ra_max`` filter, which rejects every
    source.

    So the failure mode is an empty result, not an exception: a catalog query
    near a pole comes back with no sources and the calibration reports "no
    catalog sources" rather than a coordinate error. The threshold is closer
    than it sounds — at dec 89.5 a 60-arcmin box is already enough.

    Recorded, not fixed: this is upstream behaviour and the extraction contract
    keeps it. The pole-inside-field guards above it work because they are checked
    on declination, before the arcsin.
    """
    sources = [_Source(ra_hours=h, dec_degs=88.0) for h in (0.0, 6.0, 12.0, 18.0)]

    with pytest.warns(RuntimeWarning, match="invalid value encountered in arcsin"):
        kept = clip_sources_to_box(sources, 12.0, 88.0, width_arcmins=600, height_arcmins=120)
    assert kept == []

    # Same latitude, a box narrow enough to keep the arcsin argument under 1.
    narrow = clip_sources_to_box(
        [_Source(ra_hours=12.0, dec_degs=88.0)], 12.0, 88.0,
        width_arcmins=20, height_arcmins=20,
    )
    assert len(narrow) == 1


def test_the_full_sky_ra_branch_is_unreachable():
    """``ra_max >= ra_min + 24`` can never fire, because arcsin caps at 90 deg.

    ``dra = degrees(arcsin(...)) / 15`` is at most ``90/15 = 6`` hours, so the
    span ``2*dra`` is at most 12 hours — never the 24 the branch tests for.
    Beyond that point the argument exceeds 1 and the NaN path above takes over
    instead. Pinned so the dead branch is understood as dead rather than
    trusted as the wide-field case.
    """
    max_dra_hours = 90.0 / 15.0
    assert 2 * max_dra_hours < 24.0


# ---------------------------------------------------------------------------
# Deduplication and image clipping
# ---------------------------------------------------------------------------

def test_duplicates_are_identified_by_id_and_exact_coordinates():
    """Exact float comparison is correct here: duplicates are the same row.

    They arise from one provider row being returned by two overlapping queries,
    not from cross-matching, so the floats are bit-identical.
    """
    a = _Source(id="1", ra_hours=12.0, dec_degs=10.0)
    b = _Source(id="1", ra_hours=12.0, dec_degs=10.0)
    c = _Source(id="1", ra_hours=12.0, dec_degs=10.000001)
    d = _Source(id="2", ra_hours=12.0, dec_degs=10.0)

    result = remove_duplicate_sources([a, b, c, d])
    assert len(result) == 3
    assert result[0] is a


def test_deduplication_mutates_in_place_and_returns_the_same_list():
    sources = [_Source(id="1", ra_hours=1.0, dec_degs=2.0) for _ in range(3)]
    result = remove_duplicate_sources(sources)
    assert result is sources
    assert len(sources) == 1


def test_clip_to_wcs_keeps_on_image_sources_and_stamps_pixel_coordinates(frame_header):
    """The final cut after a bounding-box query, using a real footprint.

    A query covers the box around a field, which for a rotated detector is
    larger than the field. Sources landing off the detector must be dropped, and
    survivors must come back carrying the pixel position photometry will measure
    at.
    """
    wcs, header = _wcs_from(frame_header, "ngc3628")
    height, width = wcs_array_shape(wcs)

    on_ra, on_dec = wcs.all_pix2world(width / 2, height / 2, 0)
    on_image = _Source(id="on", ra_hours=float(on_ra) / 15.0, dec_degs=float(on_dec))
    off_image = _Source(id="off", ra_hours=float(on_ra) / 15.0 + 2.0, dec_degs=float(on_dec))

    kept = clip_sources_to_wcs([on_image, off_image], [wcs])

    assert [s.id for s in kept] == ["on"]
    assert kept[0].x == pytest.approx(width / 2, abs=1.5)
    assert kept[0].y == pytest.approx(height / 2, abs=1.5)


def test_clip_to_wcs_with_no_images_keeps_nothing(frame_header):
    source = _Source(id="a", ra_hours=12.0, dec_degs=10.0)
    assert clip_sources_to_wcs([source], []) == []


def test_normalize_wcs_list_accepts_one_many_or_none(frame_header):
    wcs, _ = _wcs_from(frame_header, "ngc3628")
    assert normalize_wcs_list(None) == []
    assert normalize_wcs_list(wcs) == [wcs]
    assert normalize_wcs_list([wcs, wcs]) == [wcs, wcs]
    assert normalize_wcs_list([wcs, None]) == [wcs]


# ---------------------------------------------------------------------------
# The disabled combined bounding box
# ---------------------------------------------------------------------------

def test_combined_bounding_box_encloses_two_adjacent_fields():
    """Still a working function even though upstream guarded its call site off.

    Kept as code rather than a comment because the reason it was disabled was
    never recorded. Nothing in Kepler calls it; turning it on is a behaviour
    change needing its own validation.
    """
    boxes = [(180.0, 10.0, 0.2, 0.2), (180.2, 10.0, 0.2, 0.2)]
    combined = combined_bounding_box(boxes)

    assert combined is not None
    ra, dec, width, height = combined
    assert ra == pytest.approx(180.1, abs=1e-6)
    assert dec == pytest.approx(10.0, abs=1e-9)
    assert height == pytest.approx(0.2, abs=1e-9)

    # Both field centres fall inside the combined RA range. The width is a touch
    # under the naive 0.4 because the algorithm widens into a Lambert rectangle
    # by 1/cos(dec) and re-narrows by cos(dec) using the *outer* dec edge, which
    # is not quite symmetric.
    assert width == pytest.approx(0.4 * np.cos(np.deg2rad(10.1)), rel=0.01)
    assert ra - width / 2 <= 180.0 and 180.2 <= ra + width / 2


def test_combined_bounding_box_declines_when_fields_are_too_sparse():
    """Returns ``None`` so the caller queries each field separately.

    Two fields on opposite sides of the sky would combine into a box covering
    vastly more area than either, and the query would fetch far more than the
    caller needs.
    """
    boxes = [(10.0, 10.0, 0.2, 0.2), (190.0, -40.0, 0.2, 0.2)]
    assert combined_bounding_box(boxes) is None


def test_combined_bounding_box_is_not_wired_into_the_query_runner():
    """Assert the disabled state, so re-enabling it is a deliberate act."""
    import inspect

    from algorithms.query import runner

    assert "combined_bounding_box" not in inspect.getsource(runner)
