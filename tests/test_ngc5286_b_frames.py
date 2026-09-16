"""The three NGC 5286 B frames behind the recorded "bad values" solves (P8).

Before this, three of the four recorded zero-point references were checked at
the ``calc_solution`` level only: the numbers were shipped but the pixels they
came from were not, so ``ngc5128_b_002`` was the sole solve that could be driven
end to end. These frames close that, and they arrive with two traps that the
tests below exist to pin.

**They are the only Git LFS objects in the tree**, and the only multi-HDU frames
in ``data/optical/``: each holds four Afterglow-aligned exposures, of which every
Kepler code path reads the primary and nothing else. A checkout without
``git lfs`` leaves a text stub wearing the frame's name, which is why
``tools.config.is_lfs_pointer`` exists and why everything here skips rather than
errors when the objects are absent.

**The older recorder measured on a different instrumental scale.** Both fixture
families normalise by exposure time, but the three NGC 5286 solves put the
instrumental zero at 20.0 where ``ngc5128_b_002`` puts it at 0.0 -- so a zero
point solved from these pixels sits a clean 20 magnitudes above the recorded
number, the same size of miss as the Afterglow base-20 trap. Nothing in
``fit_summary.json`` names that constant;
``test_recorded_instrumental_zero_is_the_declared_one`` recomputes it.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

from tools.fieldcal_reference import (
    _INSTRUMENTAL_ZERO_BY_FIELD,
    load_zeropoint_reference,
    replay_catalog_sources,
)

from .conftest import FRAMES

ROOT = Path(__file__).resolve().parents[1]
ZP_SOLUTIONS = ROOT / "data" / "fieldcal" / "zp_solutions"

#: The three recorded solves and the frame each was measured from. The pairing
#: is index-for-index, which is *not* self-evident: the analogous NGC 5128
#: mapping is not (``ngc5128_b_002`` -> ``ngc5128_galaxy_b_001.fits``), and two
#: of these three frames share a telescope, an exposure time and a target.
#: ``test_each_frame_reproduces_its_own_recorded_detections`` is what establishes it.
B_FIELDS = ("ngc5286_b_000", "ngc5286_b_001", "ngc5286_b_002")

#: Per field: the primary header's TELESCOP, and the recorded detection count.
#: The two PROMPT-MO-1 entries are why the telescope alone cannot pair them.
RECORDED = {
    "ngc5286_b_000": {"telescope": "PROMPT-MO-1", "detections": 1228},
    "ngc5286_b_001": {"telescope": "Prompt6", "detections": 949},
    "ngc5286_b_002": {"telescope": "PROMPT-MO-1", "detections": 1319},
}

#: Every recorded run was aligned onto one Prompt6 grid, so all three frames
#: carry this WCS scale regardless of the instrument that took them.
RECORDED_PIXEL_SCALE_ARCSEC = 0.39835303951780765


def _summary(field: str) -> dict:
    import json

    return json.loads((ZP_SOLUTIONS / field / "fit_summary.json").read_text())


def _rows(field: str) -> list[dict]:
    with (ZP_SOLUTIONS / field / "fit_data.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


@pytest.mark.parametrize("field", B_FIELDS)
def test_each_frame_is_the_exposure_its_solve_describes(field, frame_path):
    """Header identity: same object, band, geometry, observation and telescope.

    Necessary but not sufficient -- ``_000`` and ``_002`` are identical on every
    one of these -- so it is the cheap gate, not the pairing proof.
    """
    header = fits.getheader(frame_path(field))
    summary = _summary(field)

    assert header["OBJECT"].replace(" ", "").lower() == "ngc5286"
    assert header["FILTER"] == summary["filter"] == "B"
    assert header["NAXIS1"] == summary["image_width"]
    assert header["NAXIS2"] == summary["image_height"]
    assert header["TELESCOP"] == summary["telescope"] == RECORDED[field]["telescope"]
    # Every recorded input_fits_name is a browser-deduplicated download of the
    # one observation: "ngc_5286_12158933.fits", "... (2) (1).fits", and so on.
    assert str(header["OBSID"]) == "12158933"
    assert "12158933" in summary["input_fits_name"]


@pytest.mark.parametrize("field", B_FIELDS)
def test_the_recorded_pixel_scale_is_the_wcs_one_not_secpix(field, frame_path):
    """SECPIX disagrees with the recorded pixel scale on two of the three, and
    the recorded value is right.

    Afterglow aligned all four exposures in each file onto one Prompt6 grid, so
    the WCS scale is Prompt6's 0.3984"/px throughout while SECPIX still reports
    whichever instrument took the frame -- 0.595"/px for the two PROMPT-MO-1
    exposures. Reading SECPIX here would look like a provenance mismatch and is
    not one; this pins which keyword the reference actually came from.
    """
    header = fits.getheader(frame_path(field))
    scales = proj_plane_pixel_scales(WCS(header).celestial) * 3600.0

    assert scales[0] == pytest.approx(scales[1], rel=1e-12)
    assert scales[0] == pytest.approx(
        _summary(field)["pixel_scale_arcsec"], rel=1e-9
    )
    assert scales[0] == pytest.approx(RECORDED_PIXEL_SCALE_ARCSEC, rel=1e-9)

    if RECORDED[field]["telescope"] == "PROMPT-MO-1":
        assert header["SECPIX"] == pytest.approx(0.595, abs=0.001)


@pytest.mark.parametrize("field", B_FIELDS)
def test_each_frame_carries_four_aligned_exposures_and_we_read_the_first(
    field, frame_path
):
    """The only multi-HDU frames in the tree.

    Kepler reads the primary HDU and nothing else (``load_fits_image``,
    ``fits.getheader``), so the extra three ride along unused. Pinned because a
    helper that started iterating extensions -- reasonable-looking on every
    other frame, all of which are single-HDU -- would silently change which
    exposure the recorded solves are compared against.
    """
    with fits.open(frame_path(field)) as hdul:
        assert len(hdul) == 4
        assert len({hdu.data.shape for hdu in hdul}) == 1, "one geometry"
        # Distinct exposures, not repeats of one: the extensions are the three
        # short Prompt6 sub-exposures taken minutes apart.
        observed = [hdu.header["DATE-OBS"] for hdu in hdul]
        assert len(set(observed)) == 4
        assert len({hdu.data.tobytes() for hdu in hdul}) == 4

    # fits.getheader with no ext is the primary, which is what Kepler reads.
    assert fits.getheader(frame_path(field))["DATE-OBS"] == observed[0]


def _exposure(field: str, frame_path) -> float:
    return float(fits.getheader(frame_path(field))["EXPTIME"])


@pytest.mark.slow
@pytest.mark.parametrize("field", B_FIELDS)
def test_each_frame_reproduces_its_own_recorded_detections(field, frame_path):
    """The pairing proof, and the reason the index mapping is not assumed.

    Re-extracting sources from the right frame lands on the recorded positions
    exactly -- median nearest-neighbour separation 0.000 px, and essentially
    every recorded row matched within half a pixel. Run against either of the
    other two frames of the same field the same comparison collapses to roughly
    a third, because they are different exposures of the same cluster. The gap
    between those two numbers is what identifies the frame.
    """
    from algorithms.photometry.schemas import SourceExtractionSettings
    from algorithms.photometry.source_extraction import run_source_extraction

    with fits.open(frame_path(field)) as hdul:
        data = hdul[0].data.astype(np.float64)
        header = hdul[0].header
    detected, _, _ = run_source_extraction(
        data, header, SourceExtractionSettings()
    )
    found = np.array([[s.x, s.y] for s in detected])

    assert len(found) == pytest.approx(RECORDED[field]["detections"], abs=5)

    def matched_fraction(other: str) -> float:
        rows = _rows(other)
        recorded = np.array([[float(r["x"]), float(r["y"])] for r in rows])
        gaps = np.hypot(
            found[:, None, 0] - recorded[None, :, 0],
            found[:, None, 1] - recorded[None, :, 1],
        ).min(axis=1)
        return float((gaps < 0.5).sum()) / len(found)

    assert matched_fraction(field) > 0.99
    for other in B_FIELDS:
        if other != field:
            assert matched_fraction(other) < 0.5


@pytest.mark.parametrize("field", B_FIELDS + ("ngc5128_b_002",))
def test_recorded_instrumental_zero_is_the_declared_one(field, frame_path):
    """Recompute the constant ``_INSTRUMENTAL_ZERO_BY_FIELD`` declares.

    Every recorded row satisfies ``mag = -2.5 log10(flux / exposure) + zero``
    for one constant ``zero`` per fixture family: 20.0 for the older NGC 5286
    recorder, 0.0 for the newer NGC 5128 one. Nothing in ``fit_summary.json``
    states it, and getting it wrong is a silent 20-magnitude error in
    ``calibrate_zeropoint``'s comparison -- so it is recomputed here rather
    than trusted, and a fixture re-recorded on another scale fails loudly.
    """
    rows = _rows(field)
    if field == "ngc5128_b_002":
        exposures = [_num(r.get("exp_length")) for r in rows]
    else:
        # The older format has no exp_length column; it is one exposure per
        # file, and the frame's own header is where it was read from.
        exposure = _exposure(field, frame_path)
        exposures = [exposure] * len(rows)

    zeros = [
        _num(row["mag"]) + 2.5 * math.log10(_num(row["flux"]) / exposure)
        for row, exposure in zip(rows, exposures)
        if _num(row.get("mag")) is not None
        and _num(row.get("flux"))
        and _num(row["flux"]) > 0
        and exposure
    ]

    assert zeros, "fixture should record at least one photometered row"
    declared = _INSTRUMENTAL_ZERO_BY_FIELD[field]
    assert max(zeros) - min(zeros) < 1e-9, "one scale per fixture, not per row"
    assert zeros[0] == pytest.approx(declared, abs=1e-9)
    assert load_zeropoint_reference(field).instrumental_zero_mag == declared


@pytest.mark.parametrize("field", B_FIELDS)
def test_the_reference_now_points_at_a_bundled_frame(field, frame_path):
    """The frame is reachable from the recorded solve, with no warning left over.

    ``frame_not_bundled`` was the marker that three quarters of the recorded
    ground truth was numbers-only; its absence here is P8's exit condition.
    """
    expected = frame_path(field)  # skips when the LFS object is not fetched
    reference = load_zeropoint_reference(field)

    assert reference.frame_path is not None
    assert Path(reference.frame_path) == expected
    codes = [w.code for w in reference.warnings]
    assert "frame_not_bundled" not in codes
    assert "frame_not_checked_out" not in codes


@pytest.mark.parametrize("field", B_FIELDS)
def test_the_selected_rows_replay_reads_the_older_csv_schema(field):
    """The older ``fit_data.csv`` needs its own reader, and gets the units right.

    It names its columns ``ra``/``dec``/``ref_mag`` rather than
    ``local_catalog_*``, and its coordinates are in degrees where the newer
    format is already in hours. Returning ``[]`` -- which is what happened
    before -- made ``calibrate_zeropoint`` fail with "Missing catalog sources".
    """
    sources = replay_catalog_sources(field)
    used = [r for r in _rows(field) if r["used_for_calibration"] == "True"]

    assert len(sources) == len(used) > 0
    assert {s.catalog_name for s in sources} == {"APASS"}
    # RA in hours, not the degrees the CSV stores. NGC 5286 is at 13.77h /
    # -51.37 deg, and the rows span the ~9' frame around it -- so a CSV value
    # read as hours, or a degree value passed straight through, lands nowhere
    # near this box.
    assert all(13.76 < s.ra_hours < 13.79 for s in sources)
    assert all(-51.45 < s.dec_degs < -51.29 for s in sources)
    assert all(s.ref_mag is not None for s in sources)


@pytest.mark.slow
@pytest.mark.parametrize("field", B_FIELDS)
def test_calibration_from_pixels_matches_each_recorded_solve(field, frame_path):
    """P8's exit: all four recorded solves now run end to end from pixels.

    Extract, measure, match, resolve reference magnitudes, solve -- then compare
    on the reference's own instrumental scale. The 0.1-magnitude bound is the
    one the NGC 5128 end-to-end cases already use, and it is loose for the same
    reason: the photometry is re-measured from pixels rather than replayed, so
    this is a real solve and not a bit-exact one.
    """
    from tools.photometry import calibrate_zeropoint

    comparison = calibrate_zeropoint(
        frame_path(field),
        catalog_sources=replay_catalog_sources(field),
        compare_to=field,
    )

    assert comparison.errors == []
    assert comparison.reference.field == field
    # Measured on Kepler's scale, which is 20 magnitudes above the recorded one.
    assert comparison.zero_point == pytest.approx(
        _summary(field)["zero_point"] + 20.0, abs=0.1
    )
    assert abs(comparison.delta_vs_skynet) < 0.1


@pytest.mark.parametrize("field", B_FIELDS)
def test_the_provenance_table_agrees_with_the_pixels(field):
    """Two independent routes to the same pairing, and they agree.

    ``data/frame_provenance.json`` was built from upstream's own
    ``reorganize.py`` and predates P8; it maps each frame stem back to the
    filename it was renamed from. Those names are exactly the
    ``input_fits_name`` each recorded solve reports -- including the browser
    deduplication suffixes, ``-2 (1)`` and ``(2) (1)``. So the rename table and
    ``test_each_frame_reproduces_its_own_recorded_detections`` arrive at the
    same index-for-index mapping from completely different evidence.

    Cheap enough to run by default, unlike the extraction, which makes this the
    regression net if a frame is ever swapped for another exposure.
    """
    import json

    provenance = json.loads((ROOT / "data" / "frame_provenance.json").read_text())
    stem = Path(FRAMES[field]).stem

    assert provenance["frames"][stem] == _summary(field)["input_fits_name"]


def test_the_recorded_stem_collision_resolves_to_the_solved_exposure():
    """``frame_provenance.json`` flags one stem as ambiguous, and it is ours.

    Upstream's rename would have put two different observations on
    ``ngc5286_globular_b_000``: the 12158933 exposure the recorded solve
    describes, and an unrelated 12158952 one. They are not interchangeable --
    12158952 is a different night and a different geometry -- so this pins that
    the bundled frame is the solved one, by the identifier rather than by name.
    """
    import json

    provenance = json.loads((ROOT / "data" / "frame_provenance.json").read_text())
    collision = provenance["_collisions"]["ngc5286_globular_b_000"]

    assert len(collision) == 2
    assert provenance["frames"]["ngc5286_globular_b_000"] in collision
    # The one we kept, and the one we did not.
    assert "12158933" in provenance["frames"]["ngc5286_globular_b_000"]
    assert any("12158952" in name for name in collision)
    assert all("12158952" not in _summary(f)["input_fits_name"] for f in B_FIELDS)


def test_every_recorded_solve_has_a_frame():
    """The rollup P8 exists to make true.

    Stated over the reference loader rather than the three fields above so that
    a fifth recorded solve added without a frame fails here.
    """
    from tools.fieldcal_reference import _BUNDLED_FRAME_BY_FIELD

    assert all(frame is not None for frame in _BUNDLED_FRAME_BY_FIELD.values())
    assert set(_BUNDLED_FRAME_BY_FIELD) == set(_INSTRUMENTAL_ZERO_BY_FIELD)
    assert set(B_FIELDS) <= set(FRAMES)
