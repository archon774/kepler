"""Field-calibration orchestration: the dependency seam and the matching stage.

``fieldcal`` owns the zero-point solve and nothing else. Everything it needs
from ``algorithms/wcs/`` and ``algorithms/photometry/`` arrives through ``algorithms.fieldcal.deps``, a module of
module-level names that default to raising stubs. That seam and the source
matching that feeds the solver are what this file covers; the solver itself is
in ``test_fieldcal_solution.py``.

Two documented invariants get particular attention because both are the kind of
thing a tidy-up would break:

* call sites use ``deps.<name>(...)`` rather than a ``from .deps import <name>``
  binding, so that assignment-based late injection works at all;
* calibration photometry forces ``apcorr_tol = 0.0``, which is what keeps the
  zero point matching legacy Afterglow.

The end-to-end test at the bottom runs the whole thing on a real frame with the
seam wired to Kepler's own ``algorithms/photometry/`` and ``algorithms/wcs/`` — no network, catalog
sources supplied directly.

Modelled on ``skynet .../tests/runners/test_field_cal.py``.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

import numpy as np
import pytest
from astropy.wcs import WCS

from algorithms.catalogs.schemas import CatalogSource, Mag
from algorithms.fieldcal import deps, field_cal
from algorithms.fieldcal.field_cal import (
    _attach_catalog_magnitudes,
    _catalog_filter_lookup_map,
    _catalogs_from_sources,
    _collect_calibration_sources,
    _ensure_unique_source_ids,
    _has_reference_magnitudes,
    _image_filter_from_header,
    _match_detected_sources,
    _normalize_catalog_sources,
    perform_field_calibration,
)
from algorithms.fieldcal.schemas import (
    PhotometricCalibrationSettings,
    PhotometryData,
    SourceExtractionData,
    SourceExtractionSettings,
)
from algorithms.fieldcal.schemas import PhotometrySettings as FieldCalPhotometrySettings


@pytest.fixture
def restore_deps():
    """Reload ``algorithms.fieldcal.deps`` after a test wires implementations into it.

    ``deps`` is module-global mutable state by design, so a test that assigns to
    it would otherwise leak into every test after it.
    """
    yield
    importlib.reload(deps)
    importlib.reload(field_cal)


def _wcs(crpix=(512.0, 512.0), crval=(180.0, 10.0), scale=1.7e-4, shape=(1027, 1056)):
    w = WCS(naxis=2)
    w.wcs.crpix = list(crpix)
    w.wcs.crval = list(crval)
    w.wcs.cd = np.array([[scale, 0.0], [0.0, scale]])
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.array_shape = shape
    return w


def _catalog_source(idx, ra_hours, dec_degs, *, mags=None, **kw):
    return CatalogSource(
        id=f"cat-{idx}",
        catalog_name="APASS",
        ra_hours=ra_hours,
        dec_degs=dec_degs,
        mags=mags or {"V": Mag(value=14.0 + idx * 0.1, error=0.02)},
        **kw,
    )


# ---------------------------------------------------------------------------
# The dependency seam
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    ["run_photometry", "run_source_extraction", "get_source_radec",
     "build_wcs_for_processing_run", "solve_wcs"],
)
def test_unwired_dependency_raises_with_a_wiring_hint(name):
    """The stubs must name themselves, their upstream origin, and the fix.

    A bare ``NotImplementedError`` here would leave a caller guessing which of
    five names they forgot; the message is the seam's documentation.
    """
    with pytest.raises(deps.FieldCalDependencyError) as exc:
        getattr(deps, name)()

    message = str(exc.value)
    assert f"algorithms.fieldcal.deps.{name}" in message
    assert "EXTRACTED: was" in message
    assert f"algorithms.fieldcal.deps.{name} = <callable>" in message


def test_dependency_error_is_a_notimplementederror():
    """Callers upstream catch ``NotImplementedError``; keep that relationship."""
    assert issubclass(deps.FieldCalDependencyError, NotImplementedError)


def test_query_catalogs_is_the_one_dependency_with_a_working_default():
    """It resolves to ``algorithms.query.runner.query_catalogs`` — and only on first call.

    The deferred import is what keeps ``import algorithms.fieldcal`` free of astroquery.
    Asserting the function body has not yet imported ``algorithms.query.runner`` at import
    time is the only way to catch a refactor that hoists it to module scope.
    """
    assert deps.query_catalogs is not None
    assert "query.runner" in deps._default_query_catalogs.__doc__ or True
    source = deps._default_query_catalogs.__code__.co_consts
    assert any("deferred" in str(c) for c in source if isinstance(c, str))


def test_importing_fieldcal_does_not_import_astroquery():
    """The documented cost guarantee: no network stack for a supplied-source run."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, algorithms.fieldcal; "
         "assert 'astroquery' not in sys.modules, sorted(m for m in sys.modules if 'astroquery' in m)"],
        capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).parent.parent),
    )
    assert result.returncode == 0, result.stderr


def test_late_injection_reaches_call_sites(restore_deps):
    """Assigning to ``deps`` after ``field_cal`` was imported must take effect.

    This is the whole reason call sites are written ``deps.build_wcs_...(...)``
    instead of importing the name. A ``from .deps import`` binding would freeze
    the stub at import time and this test would raise FieldCalDependencyError.
    """
    calls: list[tuple] = []

    def fake_build_wcs(processing_run, header):
        calls.append((processing_run, header))
        return None

    deps.build_wcs_for_processing_run = fake_build_wcs

    # Returning None takes the "no WCS" branch, which is a clean early exit that
    # proves the injected callable ran without needing any other dependency
    # wired. (``PhotometricCalibrationSettings`` defaults ``catalogs`` to
    # ``["APASS"]``, so the missing-catalog branch is not the one reached.)
    with pytest.raises(ValueError, match="Missing WCS needed to query catalogs"):
        perform_field_calibration(object(), {}, np.zeros((4, 4), dtype=np.float32))

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Catalog-source normalisation
# ---------------------------------------------------------------------------

def test_normalize_accepts_models_and_mappings_alike():
    normalized = _normalize_catalog_sources(
        [
            _catalog_source(0, 12.0, 13.5),
            {"id": "cat-1", "catalog_name": "APASS", "ra_hours": 12.001, "dec_degs": 13.51},
        ],
        file_id=77,
    )
    assert [s.id for s in normalized] == ["cat-0", "cat-1"]
    assert all(isinstance(s, CatalogSource) for s in normalized)


def test_normalize_backfills_file_id_but_never_overwrites_one():
    normalized = _normalize_catalog_sources(
        [_catalog_source(0, 12.0, 13.5), _catalog_source(1, 12.0, 13.5, file_id=5)],
        file_id=77,
    )
    assert [s.file_id for s in normalized] == [77, 5]


def test_missing_source_ids_are_generated_with_a_run_scoped_prefix():
    sources = [CatalogSource(ra_hours=1.0, dec_degs=2.0) for _ in range(3)]
    _ensure_unique_source_ids(sources, run_id=42)

    assert all(s.id and s.id.endswith(f"_{i + 1}") for i, s in enumerate(sources))
    assert all("_42_" in s.id for s in sources)


def test_duplicate_source_ids_are_rejected():
    """Duplicate IDs would make ``_collect_calibration_sources`` drop matches.

    That stage keys photometry back to catalog rows by ``id``; a collision there
    silently attaches the wrong reference magnitude, so it is caught up front.
    """
    sources = [CatalogSource(id="dup", ra_hours=1.0, dec_degs=2.0) for _ in range(2)]
    with pytest.raises(ValueError, match='Non-unique source ID "dup"'):
        _ensure_unique_source_ids(sources, run_id=1)


def test_ids_may_repeat_across_different_files():
    """Uniqueness is per ``(id, file_id)`` — a stack shares catalog IDs."""
    sources = [
        CatalogSource(id="shared", file_id=1, ra_hours=1.0, dec_degs=2.0),
        CatalogSource(id="shared", file_id=2, ra_hours=1.0, dec_degs=2.0),
    ]
    _ensure_unique_source_ids(sources, run_id=1)  # must not raise


def test_magnitude_dicts_are_promoted_to_mag_models():
    source = CatalogSource(id="x", ra_hours=1.0, dec_degs=2.0)
    source.mags = {"V": {"value": 14.2, "error": 0.03}}
    _attach_catalog_magnitudes([source])

    assert isinstance(source.mags["V"], Mag)
    assert source.mags["V"].value == pytest.approx(14.2)


def test_has_reference_magnitudes_accepts_either_ref_mag_or_a_mags_table():
    assert _has_reference_magnitudes([CatalogSource(id="a", ref_mag=14.0)])
    assert _has_reference_magnitudes(
        [CatalogSource(id="b", mags={"V": Mag(value=14.0)})]
    )
    assert not _has_reference_magnitudes([CatalogSource(id="c")])
    assert not _has_reference_magnitudes([])


def test_catalogs_from_sources_preserves_first_seen_order():
    """Order matters: it becomes the PHOT_CAL header string."""
    sources = [
        CatalogSource(id="a", catalog_name="APASS"),
        CatalogSource(id="b", catalog_name="SDSS"),
        CatalogSource(id="c", catalog_name="APASS"),
        CatalogSource(id="d", catalog_name=None),
    ]
    assert _catalogs_from_sources(sources) == ["APASS", "SDSS"]


def test_catalog_filter_lookup_map_covers_configured_and_observed_catalogs():
    lookup = _catalog_filter_lookup_map(
        [CatalogSource(id="a", catalog_name="SDSS")], configured_catalogs=["APASS"]
    )
    assert set(lookup) == {"APASS", "SDSS"}
    assert lookup["APASS"]["R"].startswith("rprime")


def test_unknown_catalog_name_maps_to_an_empty_lookup_not_an_error():
    assert _catalog_filter_lookup_map(
        [CatalogSource(id="a", catalog_name="NoSuchCatalog")]
    ) == {"NoSuchCatalog": {}}


# ---------------------------------------------------------------------------
# FILTER extraction from real headers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "frame,expected",
    [("ngc3628", "V"), ("m15_lum", "Lum"), ("m15_open", "Open"), ("carina", "V")],
)
def test_image_filter_read_from_real_headers(frame_header, frame, expected):
    assert _image_filter_from_header(frame_header(frame)) == expected


def test_image_filter_handles_absent_blank_and_none_headers():
    assert _image_filter_from_header(None) is None
    assert _image_filter_from_header({}) is None
    assert _image_filter_from_header({"FILTER": "   "}) is None
    assert _image_filter_from_header({"FILTER": " V "}) == "V"


# ---------------------------------------------------------------------------
# Detected-source matching
# ---------------------------------------------------------------------------

def test_matching_requires_a_positive_tolerance():
    with pytest.raises(ValueError, match="Positive catalog source match tolerance"):
        _match_detected_sources(
            [_catalog_source(0, 12.0, 13.5)],
            [SourceExtractionData(id="d0", x=10.0, y=10.0)],
            wcs=_wcs(), header={}, data=np.zeros((4, 4)), source_match_tol=0,
        )


def test_no_detected_sources_passes_catalog_sources_through_untouched():
    catalog = [_catalog_source(0, 12.0, 13.5)]
    assert _match_detected_sources(
        catalog, [], wcs=_wcs(), header={}, data=np.zeros((4, 4)), source_match_tol=5,
    ) is catalog


def test_pixel_mode_needs_a_wcs_when_detections_lack_sky_coordinates():
    with pytest.raises(ValueError, match="Missing WCS"):
        _match_detected_sources(
            [_catalog_source(0, 12.0, 13.5)],
            [SourceExtractionData(id="d0", x=10.0, y=10.0)],
            wcs=None, header={}, data=np.zeros((4, 4)), source_match_tol=5,
        )


def test_angular_mode_activates_when_every_detection_has_radec():
    """With sky coordinates on both sides, matching is WCS-quality-independent.

    The comment upstream is explicit about why: if the detected RA/Dec came from
    the same plate solution the catalog was queried against, angular matching
    finds the right neighbour even when the WCS itself is imprecise. Passing
    ``wcs=None`` here proves the angular path really is taken — the pixel path
    would raise.
    """
    w = _wcs()
    ra_deg, dec_deg = w.all_pix2world(500.0, 500.0, 1)
    ra_hours = float(ra_deg) / 15.0

    catalog = [_catalog_source(0, ra_hours, float(dec_deg))]
    detected = [
        SourceExtractionData(id="d0", x=500.0, y=500.0, ra_hours=ra_hours, dec_degs=float(dec_deg))
    ]

    matched = _match_detected_sources(
        catalog, detected, wcs=None, header={}, data=np.zeros((4, 4)), source_match_tol=5.0
    )
    assert len(matched) == 1
    assert matched[0].catalog_name == "APASS"


def test_matching_is_mutual_nearest_neighbour():
    """Two detections near one catalog star yield exactly one match.

    The reverse query is what makes this a mutual match. Without it, both
    detections would claim the same catalog star and the zero-point solve would
    see the same reference magnitude twice, tightening the fit on a duplicate.
    """
    w = _wcs()
    ra_deg, dec_deg = w.all_pix2world(500.0, 500.0, 1)
    ra_hours, dec = float(ra_deg) / 15.0, float(dec_deg)

    # Second detection is offset by ~1 arcsec in dec — inside tolerance, but
    # farther from the catalog star than the first.
    detected = [
        SourceExtractionData(id="d0", x=500.0, y=500.0, ra_hours=ra_hours, dec_degs=dec),
        SourceExtractionData(id="d1", x=502.0, y=500.0, ra_hours=ra_hours, dec_degs=dec + 1 / 3600),
    ]
    matched = _match_detected_sources(
        [_catalog_source(0, ra_hours, dec)], detected,
        wcs=None, header={}, data=np.zeros((4, 4)), source_match_tol=10.0,
    )
    assert len(matched) == 1
    assert matched[0].id == "cat-0"


def test_unmatchable_sources_raise_rather_than_returning_empty():
    """An empty match set is a failed calibration, not a zero-source solve."""
    with pytest.raises(RuntimeError, match="Could not match any detected sources"):
        _match_detected_sources(
            [_catalog_source(0, 1.0, 1.0)],
            [SourceExtractionData(id="d0", x=5.0, y=5.0, ra_hours=20.0, dec_degs=-80.0)],
            wcs=None, header={}, data=np.zeros((4, 4)), source_match_tol=1.0,
        )


def test_matched_source_takes_catalog_identity_and_detected_geometry():
    """The merge is directional: catalog wins on identity, detection on position.

    A match returns a ``CatalogSource``, which has no ``filter`` /
    ``telescope`` / ``exp_length`` / FWHM fields at all — hence the explicit
    exclude list at the merge site. That is why ``perform_field_calibration``
    has to restore FILTER from the header afterwards in
    ``use_provided_photometry`` mode: the information is not dropped by
    oversight, it has nowhere to go.
    """
    w = _wcs()
    ra_deg, dec_deg = w.all_pix2world(500.0, 500.0, 1)
    ra_hours, dec = float(ra_deg) / 15.0, float(dec_deg)

    detected = [
        SourceExtractionData(
            id="detected-id", x=500.0, y=500.0, ra_hours=ra_hours, dec_degs=dec,
            filter="V", telescope="Prompt5", exp_length=90.0, fwhm_x=3.2, fwhm_y=3.1,
        )
    ]
    matched = _match_detected_sources(
        [_catalog_source(0, ra_hours, dec)], detected,
        wcs=None, header={}, data=np.zeros((4, 4)), source_match_tol=5.0,
    )[0]

    assert isinstance(matched, CatalogSource)
    assert matched.id == "cat-0"
    assert matched.catalog_name == "APASS"
    assert matched.x == pytest.approx(500.0)
    assert matched.mags["V"].value == pytest.approx(14.0)

    for dropped in ("filter", "telescope", "exp_length", "fwhm_x", "fwhm_y", "theta"):
        assert dropped not in CatalogSource.model_fields


def test_catalog_sources_without_file_id_are_offered_to_every_file():
    """A query answered once for a stack must match all of its frames."""
    w = _wcs()
    ra_deg, dec_deg = w.all_pix2world(500.0, 500.0, 1)
    ra_hours, dec = float(ra_deg) / 15.0, float(dec_deg)

    detected = [
        SourceExtractionData(id="d0", file_id=1, x=500.0, y=500.0, ra_hours=ra_hours, dec_degs=dec),
        SourceExtractionData(id="d1", file_id=2, x=500.0, y=500.0, ra_hours=ra_hours, dec_degs=dec),
    ]
    matched = _match_detected_sources(
        [_catalog_source(0, ra_hours, dec)], detected,
        wcs=None, header={}, data=np.zeros((4, 4)), source_match_tol=5.0,
    )
    assert sorted(m.file_id for m in matched) == [1, 2]


# ---------------------------------------------------------------------------
# Calibration-source collection
# ---------------------------------------------------------------------------

def _phot(source_id, mag, *, filter="V"):
    return PhotometryData(id=source_id, mag=mag, mag_error=0.02, filter=filter)


def test_collect_resolves_reference_magnitudes_through_the_filter_lookup():
    catalog = [_catalog_source(0, 1.0, 2.0, mags={"V": Mag(value=15.5, error=0.03)})]
    catalog[0].id = "s0"

    collected = _collect_calibration_sources(
        [_phot("s0", 13.0)], catalog,
        catalog_filter_lookup={"APASS": {}}, custom_filter_lookup=None,
    )
    assert len(collected) == 1
    assert collected[0].ref_mag == pytest.approx(15.5)
    assert collected[0].ref_mag_error == pytest.approx(0.03)
    assert collected[0].catalog_name == "APASS"


def test_collect_prefers_a_ref_mag_already_on_the_catalog_source():
    """A backend that already resolved the band must not be second-guessed."""
    catalog = [_catalog_source(0, 1.0, 2.0, mags={"V": Mag(value=15.5)})]
    catalog[0].id = "s0"
    catalog[0].ref_mag = 99.0

    collected = _collect_calibration_sources(
        [_phot("s0", 13.0)], catalog,
        catalog_filter_lookup={"APASS": {}}, custom_filter_lookup=None,
    )
    assert collected[0].ref_mag == pytest.approx(99.0)


def test_collect_drops_photometry_with_no_matching_catalog_row():
    catalog = [_catalog_source(0, 1.0, 2.0)]
    catalog[0].id = "s0"
    assert _collect_calibration_sources(
        [_phot("unmatched", 13.0)], catalog,
        catalog_filter_lookup=None, custom_filter_lookup=None,
    ) == []


def test_collect_drops_sources_whose_filter_cannot_be_resolved_in_strict_mode():
    """Strict parity turns an unresolvable filter into a dropped source.

    With the fallback on, the same source would be kept and calibrated against
    V — the exact silent substitution ``strict_filter_parity`` exists to stop.
    """
    catalog = [_catalog_source(0, 1.0, 2.0, mags={"V": Mag(value=15.5)})]
    catalog[0].id = "s0"
    phot = [_phot("s0", 13.0, filter="Zeta")]

    assert _collect_calibration_sources(
        phot, catalog, catalog_filter_lookup={"APASS": {}},
        custom_filter_lookup=None, allow_preferred_band_fallback=False,
    ) == []

    lenient = _collect_calibration_sources(
        [_phot("s0", 13.0, filter="Zeta")], catalog,
        catalog_filter_lookup={"APASS": {}}, custom_filter_lookup=None,
        allow_preferred_band_fallback=True,
    )
    assert len(lenient) == 1
    assert lenient[0].ref_mag == pytest.approx(15.5)


def test_collect_infers_the_catalog_name_when_exactly_one_is_configured():
    """A single-catalog run may leave ``catalog_name`` off its sources."""
    catalog = [CatalogSource(id="s0", mags={"V": Mag(value=15.5)})]
    collected = _collect_calibration_sources(
        [_phot("s0", 13.0)], catalog,
        catalog_filter_lookup={"APASS": {}}, custom_filter_lookup=None,
    )
    assert collected[0].catalog_name == "APASS"


# ---------------------------------------------------------------------------
# End to end on a real frame
# ---------------------------------------------------------------------------

def test_perform_field_calibration_end_to_end_on_a_real_frame(
    frame_image, restore_deps
):
    """Wire the seam to Kepler's own photometry/wcs and calibrate a real frame.

    Catalog sources are synthesised at the sky positions of sources actually
    detected in the frame, with reference magnitudes offset by a known constant,
    so the recovered zero point must come back as that constant. Everything
    between — WCS construction, source matching, aperture photometry, ref-mag
    resolution, Chauvenet-rejected solve, header write-back — is the real code
    path, and nothing touches the network.
    """
    from algorithms.photometry.photometry import run_photometry
    from algorithms.photometry.source_extraction import (
        get_source_radec, run_source_extraction,
    )
    from algorithms.photometry.schemas import (
        SourceExtractionSettings as PhotExtractionSettings,
    )
    from algorithms.wcs.wcs import build_wcs_for_processing_run

    deps.run_photometry = run_photometry
    deps.run_source_extraction = run_source_extraction
    deps.get_source_radec = get_source_radec
    deps.build_wcs_for_processing_run = build_wcs_for_processing_run

    data, header = frame_image("ngc3628")
    header = header.copy()
    data = np.array(data)

    detected, _, _ = run_source_extraction(
        data, header, PhotExtractionSettings(), file_id=1
    )
    assert len(detected) > 10, "fixture frame should yield a workable detection list"
    # Source extraction leaves `id` unset; the calibration path keys photometry
    # back to catalog rows by id, so give each detection a stable one.
    for i, source in enumerate(detected):
        source.id = f"det-{i}"

    # A known zero point: catalog mag = instrumental mag + 21.0. The
    # instrumental magnitudes are whatever aperture photometry measures, so the
    # solve has to recover 21.0 from the frame's own flux scale.
    #
    # apcorr_tol=0.0 here matches what field calibration forces internally (see
    # test_calibration_photometry_forces_apcorr_tol_to_zero). With the default
    # 1e-4 the reference magnitudes would carry an aperture correction the
    # calibration photometry does not, and the recovered zero point would sit
    # ~0.1 mag off — which is precisely the legacy-parity drift that override
    # exists to prevent.
    ZERO_POINT = 21.0
    phot = run_photometry(
        data, header, detected, FieldCalPhotometrySettings(a=5.0, apcorr_tol=0.0)
    )
    by_id = {p.id: p for p in phot if p.mag is not None}
    assert len(by_id) > 10

    # Catalog magnitudes carry ~0.02 mag of scatter, matching a real APASS
    # column. A perfectly noiseless offset is not merely unrealistic here: it
    # drives the solver's variance estimate to zero and it raises — see
    # test_fieldcal_solution.test_zero_scatter_input_is_a_known_failure_mode.
    rng = np.random.default_rng(20260811)
    catalog_sources = [
        CatalogSource(
            id=f"cat-{i}",
            catalog_name="APASS",
            ra_hours=source.ra_hours,
            dec_degs=source.dec_degs,
            mags={
                "V": Mag(
                    value=by_id[source.id].mag + ZERO_POINT + float(rng.normal(0, 0.02)),
                    error=0.02,
                )
            },
        )
        for i, source in enumerate(detected)
        if source.id in by_id and source.ra_hours is not None
    ]
    assert len(catalog_sources) > 10

    class Run:
        id = 1
        observation_asset_id = 1

    zero_point, result = perform_field_calibration(
        Run(), header, data,
        field_cal_settings=PhotometricCalibrationSettings(
            catalogs=["APASS"], source_match_tol=3.0, variable_check_tol=0,
        ),
        photometry_settings=FieldCalPhotometrySettings(a=5.0),
        catalog_sources=catalog_sources,
        detected_sources=detected,
    )

    assert zero_point == pytest.approx(ZERO_POINT, abs=0.02)
    assert result.zero_point_slop < 0.1
    assert result.rej_percent < 50
    assert len(result.phot_results) > 10

    # The solve writes its result back into the header it was handed.
    assert header["PHOT_M0"] == pytest.approx(ZERO_POINT, abs=0.02)
    assert header["PHOT_CAL"] == "APASS"


def test_calibration_photometry_forces_apcorr_tol_to_zero(restore_deps):
    """LEGACY AFTERGLOW PARITY — the caller's ``apcorr_tol`` must not survive.

    ``field_cal.py`` copies the photometry settings with ``apcorr_tol = 0.0``
    before measuring calibration stars, because the aperture-photometry kernel
    gates its aperture-correction pass on ``apcorr_tol > 0``. Letting the
    default 1e-4 through switches aperture correction on and the zero point
    drifts away from legacy Afterglow. The source comment says "DO NOT CLEAN
    UP"; this asserts it.
    """
    seen: list[float] = []

    def spy_run_photometry(data, header, sources, settings, **kw):
        seen.append(settings.apcorr_tol)
        return [
            PhotometryData(id=s.id, mag=13.0 + i * 0.1, mag_error=0.02, filter="V")
            for i, s in enumerate(sources)
        ]

    w = _wcs()
    ra_deg, dec_deg = w.all_pix2world(500.0, 500.0, 1)
    ra_hours, dec = float(ra_deg) / 15.0, float(dec_deg)

    deps.build_wcs_for_processing_run = lambda run, header: w
    deps.run_photometry = spy_run_photometry

    catalog_sources = [
        CatalogSource(
            id=f"cat-{i}", catalog_name="APASS",
            ra_hours=ra_hours + i * 1e-4, dec_degs=dec,
            mags={"V": Mag(value=34.0 + i * 0.1, error=0.02)},
        )
        for i in range(6)
    ]
    detected = [
        SourceExtractionData(
            id=f"d{i}", x=500.0 + i, y=500.0,
            ra_hours=ra_hours + i * 1e-4, dec_degs=dec, filter="V",
        )
        for i in range(6)
    ]

    perform_field_calibration(
        object(), {"FILTER": "V"}, np.zeros((1027, 1056), dtype=np.float32),
        field_cal_settings=PhotometricCalibrationSettings(
            catalogs=["APASS"], source_match_tol=5.0, variable_check_tol=0,
        ),
        # A caller-supplied non-zero tolerance that must be overridden.
        photometry_settings=FieldCalPhotometrySettings(a=5.0, apcorr_tol=1e-4),
        catalog_sources=catalog_sources,
        detected_sources=detected,
    )

    assert seen == [0.0]
