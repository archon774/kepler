"""Vendored geometry and angles: ``algorithms/skylib_lite/util/``.

Three independent pieces:

* ``overlap.py`` — exact pixel/aperture intersection areas. This is what makes
  aperture photometry sub-pixel accurate rather than a pixel count, so the tests
  check it against closed-form areas rather than against itself.
* ``angle.py`` — spherical distance and mean position, used by catalog matching
  and variable-star rejection. RA is in *hours* here and Dec in degrees, a unit
  mix that is the easiest thing in the module to get wrong.
* ``astrometry/atlas/`` — the orientation round-trip between the blind and
  oriented solvers.

All numba-jitted, so the first run in a fresh checkout pays a compile cost once.

The ``decompose_linear`` tests are adapted from
``skynet packages/py/skylib/tests/test_decompose_linear.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from algorithms.skylib_lite.astrometry.atlas.solve.oriented import _known_cd_rad_per_pix
from algorithms.skylib_lite.astrometry.atlas.wcs.build import decompose_linear
from algorithms.skylib_lite.util.angle import airmass_for_el, angdist, average_radec
from algorithms.skylib_lite.util.overlap import (
    area_triangle,
    circoverlap,
    ellipoverlap,
    triangle_unitcircle_overlap,
)

ARCSEC_TO_RAD = np.deg2rad(1.0 / 3600.0)


# ---------------------------------------------------------------------------
# Rectangle / circle overlap
# ---------------------------------------------------------------------------

def test_a_pixel_wholly_inside_the_circle_contributes_its_full_area():
    assert circoverlap(0.0, 0.0, 1.0, 1.0, 100.0) == pytest.approx(1.0, abs=1e-12)


def test_a_pixel_wholly_outside_contributes_nothing():
    assert circoverlap(10.0, 10.0, 11.0, 11.0, 1.0) == pytest.approx(0.0, abs=1e-12)


def test_a_rectangle_enclosing_the_circle_returns_the_circle_area():
    """The bounding box of a unit circle overlaps it in exactly pi."""
    assert circoverlap(-2.0, -2.0, 2.0, 2.0, 1.0) == pytest.approx(math.pi, abs=1e-9)


def test_a_quadrant_gets_a_quarter_of_the_circle():
    assert circoverlap(0.0, 0.0, 5.0, 5.0, 2.0) == pytest.approx(math.pi, abs=1e-9)


def test_a_half_plane_cut_gets_half_the_circle():
    assert circoverlap(-5.0, 0.0, 5.0, 5.0, 1.0) == pytest.approx(math.pi / 2, abs=1e-9)


def test_overlap_area_grows_monotonically_with_radius():
    """Partial-pixel weighting must be monotone or aperture curves go non-physical."""
    areas = [circoverlap(0.0, 0.0, 1.0, 1.0, r) for r in (0.1, 0.5, 1.0, 1.5, 2.0)]
    assert all(b >= a - 1e-12 for a, b in zip(areas, areas[1:]))
    assert areas[0] < areas[-1]


def test_summed_pixel_overlaps_reconstruct_the_circle_area():
    """The property aperture photometry depends on.

    Tiling the plane and summing each pixel's overlap must recover pi*r^2 — this
    is exactly how a flux sum is weighted, so an error here shows up as a
    systematic magnitude offset rather than as a wrong-looking number.
    """
    radius = 3.7
    total = sum(
        circoverlap(float(x), float(y), float(x + 1), float(y + 1), radius)
        for x in range(-6, 6)
        for y in range(-6, 6)
    )
    assert total == pytest.approx(math.pi * radius ** 2, rel=1e-9)


def test_overlap_is_symmetric_under_reflection():
    a = circoverlap(0.3, 0.4, 1.3, 1.4, 1.0)
    b = circoverlap(-1.3, 0.4, -0.3, 1.4, 1.0)
    c = circoverlap(0.3, -1.4, 1.3, -0.4, 1.0)
    assert a == pytest.approx(b, abs=1e-12)
    assert a == pytest.approx(c, abs=1e-12)


def test_zero_radius_contributes_nothing():
    assert circoverlap(-1.0, -1.0, 1.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Rectangle / ellipse overlap
# ---------------------------------------------------------------------------

def test_a_circular_ellipse_matches_the_circle_routine():
    """``a == b`` must reduce to the circular case, whatever ``theta`` is."""
    for theta in (0.0, 0.5, 1.0, 2.0):
        assert ellipoverlap(0.0, 0.0, 1.0, 1.0, 2.0, 2.0, theta) == pytest.approx(
            circoverlap(0.0, 0.0, 1.0, 1.0, 2.0), abs=1e-9
        )


def test_a_pixel_inside_the_ellipse_contributes_its_full_area():
    assert ellipoverlap(0.1, 0.1, 0.6, 0.6, 5.0, 4.0, 0.0) == pytest.approx(0.25, abs=1e-9)


def test_a_pixel_outside_the_ellipse_contributes_nothing():
    assert ellipoverlap(10.0, 10.0, 11.0, 11.0, 2.0, 1.0, 0.0) == pytest.approx(
        0.0, abs=1e-12
    )


def test_a_small_ellipse_wholly_inside_a_pixel_returns_its_own_area():
    """Down to the crash boundary, a sub-pixel aperture is measured correctly."""
    for semi_axis in (0.5, 0.45, 0.4):
        assert ellipoverlap(-0.5, -0.5, 0.5, 0.5, semi_axis, semi_axis, 0.0) == (
            pytest.approx(math.pi * semi_axis ** 2, rel=1e-6)
        )


def test_rotating_an_ellipse_by_pi_leaves_the_overlap_unchanged():
    """A half-turn maps the ellipse onto itself."""
    args = (-1.0, -1.0, 1.0, 1.0, 3.0, 1.0)
    assert ellipoverlap(*args, 0.3) == pytest.approx(
        ellipoverlap(*args, 0.3 + math.pi), abs=1e-9
    )


def test_elongated_apertures_capture_different_pixels_by_orientation():
    """The reason ``theta`` exists — a rotated aperture weights pixels differently."""
    horizontal = ellipoverlap(2.0, -0.5, 3.0, 0.5, 4.0, 1.0, 0.0)
    vertical = ellipoverlap(2.0, -0.5, 3.0, 0.5, 4.0, 1.0, math.pi / 2)
    assert horizontal > vertical


# ---------------------------------------------------------------------------
# A preserved crash
# ---------------------------------------------------------------------------

#: Inputs that terminate the interpreter. Never call these in-process.
CRASHING_CALLS = [
    # A pixel centred on an elliptical aperture smaller than ~0.36 px.
    "ellipoverlap(-0.5, -0.5, 0.5, 0.5, 0.35, 0.35, 0.0)",
    # The same geometry at any scale: a rectangle centred on the ellipse.
    "ellipoverlap(-2.0, -2.0, 2.0, 2.0, 1.0, 1.0, 0.0)",
]


def _crashes(expression: str) -> bool:
    """Run one overlap call in a subprocess; report whether it survived."""
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "-c",
         "from algorithms.skylib_lite.util.overlap import "
         "ellipoverlap, triangle_unitcircle_overlap\n"
         f"print({expression})"],
        capture_output=True, text=True, timeout=300,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    return result.returncode != 0


@pytest.mark.slow
@pytest.mark.parametrize("expression", CRASHING_CALLS)
def test_ellipoverlap_segfaults_on_a_centred_oversized_rectangle(expression):
    """PRESERVED DEFECT: this does not raise — it kills the interpreter.

    ``ellipoverlap`` splits the rectangle into two triangles and hands each to
    ``triangle_unitcircle_overlap``. When the rectangle is *centred* on the
    ellipse and large enough relative to it, the shared diagonal passes exactly
    through the circle centre, and the recursive clipping in
    ``triangle_unitcircle_overlap`` never terminates. The result is a stack
    overflow inside numba-compiled code: a SIGSEGV, not a Python exception, so
    no ``try``/``except`` anywhere upstream can contain it.

    Byte-identical to ``skynet packages/py/skylib/skylib/util/overlap.py`` and
    it crashes there too, so this is upstream's bug, preserved by the extraction
    contract rather than introduced by it.

    **Reachability.** ``aperture_numba.py:579`` calls
    ``ellipoverlap(dx - 0.5, dy - 0.5, dx + 0.5, dy + 0.5, a*rout, b*rout, theta)``
    — a 1x1 pixel against the aperture, with ``dx``/``dy`` the offset from the
    source centre. So a source sitting on a pixel centre with an effective
    semi-axis below about 0.36 pixels crashes the process. Measured on this
    build: 0.40 is fine, 0.35 is fatal. ``run_photometry`` validates only
    ``a > 0``, so nothing stops a caller reaching it.

    Run in a subprocess because an in-process call would take pytest down with
    it. Asserted as a non-zero exit rather than a specific signal, since the
    exact code varies by platform.
    """
    assert _crashes(expression), (
        f"{expression} no longer crashes — if the recursion was fixed upstream "
        f"or vendored anew, delete this test and unskip the normal cases"
    )


@pytest.mark.slow
def test_the_crash_boundary_sits_between_0_4_and_0_35_pixels():
    """Bound the defect so a change in either direction is visible."""
    assert not _crashes("ellipoverlap(-0.5, -0.5, 0.5, 0.5, 0.40, 0.40, 0.0)")
    assert _crashes("ellipoverlap(-0.5, -0.5, 0.5, 0.5, 0.35, 0.35, 0.0)")


@pytest.mark.slow
def test_an_off_centre_pixel_is_safe_at_the_same_scale():
    """Only the centred case is fatal, which is why it survived in production.

    Real sources rarely land exactly on a pixel centre, and real apertures are
    rarely sub-pixel — the two conditions together are what make this rare
    enough to have gone unnoticed.
    """
    assert not _crashes("ellipoverlap(-0.3, -0.7, 0.7, 0.3, 0.2, 0.2, 0.0)")


# ---------------------------------------------------------------------------
# Triangle primitives
# ---------------------------------------------------------------------------

def test_triangle_area_is_the_standard_half_base_times_height():
    assert area_triangle(0.0, 0.0, 1.0, 0.0, 0.0, 1.0) == pytest.approx(0.5, abs=1e-12)
    assert area_triangle(0.0, 0.0, 4.0, 0.0, 0.0, 3.0) == pytest.approx(6.0, abs=1e-12)


def test_degenerate_triangles_have_zero_area():
    assert area_triangle(0.0, 0.0, 1.0, 1.0, 2.0, 2.0) == pytest.approx(0.0, abs=1e-12)


def test_a_triangle_inside_the_unit_circle_overlaps_entirely():
    assert triangle_unitcircle_overlap(0.0, 0.0, 0.5, 0.0, 0.0, 0.5) == pytest.approx(
        0.125, abs=1e-9
    )


def test_a_triangle_outside_the_unit_circle_overlaps_not_at_all():
    assert triangle_unitcircle_overlap(5.0, 5.0, 6.0, 5.0, 5.0, 6.0) == pytest.approx(
        0.0, abs=1e-12
    )


def test_a_triangle_containing_the_circle_returns_the_circle_area():
    """Safe as long as no edge runs through the centre — see the crash above."""
    overlap = triangle_unitcircle_overlap(-10.0, -10.0, 10.0, -10.0, 0.0, 10.0)
    assert overlap == pytest.approx(math.pi, abs=1e-9)


# ---------------------------------------------------------------------------
# Angular distance
# ---------------------------------------------------------------------------

def test_distance_between_identical_positions_is_zero():
    assert angdist(12.0, 30.0, 12.0, 30.0) == pytest.approx(0.0, abs=1e-12)


def test_ra_is_in_hours_and_dec_in_degrees():
    """The unit mix, stated outright.

    One hour of RA at the equator is 15 degrees; one degree of Dec is one
    degree. Treating RA as degrees would under-report every separation by 15x
    and make catalog matching accept almost anything.
    """
    assert angdist(0.0, 0.0, 1.0, 0.0) == pytest.approx(15.0, abs=1e-9)
    assert angdist(0.0, 0.0, 0.0, 1.0) == pytest.approx(1.0, abs=1e-9)


def test_separation_shrinks_with_cos_dec():
    """One hour of RA subtends less arc at high declination.

    The ``cos(dec)`` factor is the small-angle approximation; this is the exact
    haversine, so at a 15-degree separation the two differ by ~0.2%. Compared
    loosely on purpose — the point is the shrinkage, not the approximation.
    """
    at_equator = angdist(0.0, 0.0, 1.0, 0.0)
    at_sixty = angdist(0.0, 60.0, 1.0, 60.0)

    assert at_sixty < at_equator
    assert at_sixty == pytest.approx(at_equator * 0.5, rel=5e-3)

    # A small separation matches the approximation far more closely.
    small_equator = angdist(0.0, 0.0, 0.01, 0.0)
    small_sixty = angdist(0.0, 60.0, 0.01, 60.0)
    assert small_sixty == pytest.approx(small_equator * 0.5, rel=1e-6)


def test_distance_is_symmetric():
    assert angdist(1.0, 20.0, 5.0, -40.0) == pytest.approx(
        angdist(5.0, -40.0, 1.0, 20.0), abs=1e-12
    )


def test_distance_across_the_ra_seam_is_short():
    """23h59m to 00h01m is two minutes of RA, not 24 hours."""
    assert angdist(23.99, 0.0, 0.01, 0.0) == pytest.approx(0.3, abs=1e-6)


def test_antipodal_points_are_180_degrees_apart():
    assert angdist(0.0, 90.0, 0.0, -90.0) == pytest.approx(180.0, abs=1e-9)


def test_distance_is_vectorised():
    ra = np.array([0.0, 1.0, 2.0])
    result = angdist(ra, np.zeros(3), ra + 1.0, np.zeros(3))
    assert result.shape == (3,)
    assert np.allclose(result, 15.0)


# ---------------------------------------------------------------------------
# Mean sky position
# ---------------------------------------------------------------------------

def test_average_of_one_point_is_that_point():
    ra, dec = average_radec(np.array([[6.0, 30.0]]))
    assert ra == pytest.approx(6.0, abs=1e-9)
    assert dec == pytest.approx(30.0, abs=1e-9)


def test_average_is_computed_on_the_sphere_not_arithmetically():
    """Two points either side of RA=0 average to RA=0, not to 12h.

    The arithmetic mean of 23.9 and 0.1 is 12.0 — the far side of the sky. The
    vector mean gives 0.0, which is why this is done in Cartesian coordinates.
    """
    ra, dec = average_radec(np.array([[23.9, 0.0], [0.1, 0.0]]))
    assert ra == pytest.approx(0.0, abs=1e-6) or ra == pytest.approx(24.0, abs=1e-6)
    assert dec == pytest.approx(0.0, abs=1e-9)


def test_average_ra_is_wrapped_into_zero_to_24():
    ra, _ = average_radec(np.array([[23.0, 10.0], [23.5, 10.0]]))
    assert 0.0 <= ra < 24.0


def test_average_of_symmetric_declinations_is_the_equator():
    _, dec = average_radec(np.array([[6.0, 30.0], [6.0, -30.0]]))
    assert dec == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Airmass
# ---------------------------------------------------------------------------

def test_airmass_at_the_zenith_is_one():
    assert airmass_for_el(90.0) == pytest.approx(1.0, abs=1e-6)


def test_airmass_increases_towards_the_horizon():
    values = [airmass_for_el(el) for el in (90.0, 60.0, 30.0, 10.0)]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_airmass_at_thirty_degrees_is_about_two():
    """``1/sin(30) = 2`` to first order; Pickering (2002) refines it slightly."""
    assert airmass_for_el(30.0) == pytest.approx(2.0, rel=0.02)


# ---------------------------------------------------------------------------
# Orientation decomposition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scale_arcsec", [0.4, 0.6, 1.5, 2.0])
@pytest.mark.parametrize("rotation_deg", [-178.55, -90.0, 0.0, 1.45, 45.0, 179.0])
@pytest.mark.parametrize("parity", [1, -1])
def test_decompose_inverts_the_oriented_solvers_composition(
    scale_arcsec, rotation_deg, parity
):
    """``decompose_linear`` is the exact inverse of ``_known_cd_rad_per_pix``.

    The blind solver emits its orientation through ``decompose_linear`` so a
    bootstrap can feed the result straight back into the oriented solver's
    prior. If the round trip is not exact, that handoff silently degrades the
    prior and the oriented solve searches the wrong neighbourhood.

    Adapted from ``skynet packages/py/skylib/tests/test_decompose_linear.py``.
    """
    cd = _known_cd_rad_per_pix(scale_arcsec, rotation_deg, parity)
    scale, angle, recovered_parity = decompose_linear(cd)

    assert recovered_parity == parity
    assert scale / ARCSEC_TO_RAD == pytest.approx(scale_arcsec, rel=1e-9)

    # The angle comes back modulo 360 from atan2, so compare wrapped.
    delta = (angle - rotation_deg + 180.0) % 360.0 - 180.0
    assert delta == pytest.approx(0.0, abs=1e-7)


def test_parity_is_the_sign_of_the_determinant():
    assert decompose_linear(np.array([[1.0, 0.0], [0.0, 1.0]]))[2] == 1
    assert decompose_linear(np.array([[-1.0, 0.0], [0.0, 1.0]]))[2] == -1


def test_decomposition_matches_the_real_frames_pixel_scale(frame_header):
    """Run the decomposition against an actual plate solution.

    The synthetic round trip above proves self-consistency; this checks the
    recovered scale against what the telescope reported for the same frame.
    """
    header = frame_header("ngc3628")
    cd_deg = np.array([[header["CD1_1"], header["CD1_2"]],
                       [header["CD2_1"], header["CD2_2"]]])
    scale_rad, angle, parity = decompose_linear(np.deg2rad(cd_deg))

    assert scale_rad / ARCSEC_TO_RAD == pytest.approx(header["SECPIX"], rel=0.02)
    assert parity in (1, -1)
    assert -180.0 <= angle <= 180.0


def test_decomposition_recovers_a_ninety_degree_rotation(frame_header):
    """Carina, where the rotation is the whole point."""
    header = frame_header("carina")
    cd_deg = np.array([[header["CD1_1"], header["CD1_2"]],
                       [header["CD2_1"], header["CD2_2"]]])
    scale_rad, angle, _ = decompose_linear(np.deg2rad(cd_deg))

    assert scale_rad / ARCSEC_TO_RAD == pytest.approx(header["SECPIX"], rel=0.02)
    assert abs(abs(angle) - 90.0) < 5.0, angle
