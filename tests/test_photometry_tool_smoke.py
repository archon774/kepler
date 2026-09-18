from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import tools.photometry_pipeline as photometry_pipeline
from tools.photometry_pipeline import (
    PhotometrySettings,
    ZeroPointResolution,
    _add_mentor_sidebar,
    _replicate_zero_point_rejection,
    compute_photometry,
    list_bundled_targets,
    magnitude_label_for,
    plot_zero_point_solution,
    render_credits_card,
    resolve_fits_path,
    resolve_zero_point_mag,
    summarize_results,
)


class DummyHeader(dict):
    pass


class DummyCalSource:
    """Stands in for `algorithms.photometry.schemas.PhotometryData` in the
    zero-point solve test below -- only the four attributes `calc_solution`
    (and its mirror, `_replicate_zero_point_rejection`) actually reads."""

    def __init__(self, mag, ref_mag, mag_error=0.0, ref_mag_error=0.0, catalog_name="TEST"):
        self.mag = mag
        self.ref_mag = ref_mag
        self.mag_error = mag_error
        self.ref_mag_error = ref_mag_error
        self.catalog_name = catalog_name


def test_resolve_zero_point_mag_from_header() -> None:
    header = DummyHeader({"PHOT_M0": 17.2})
    assert resolve_zero_point_mag(Path("dummy.fits"), header) == 17.2


def test_resolve_zero_point_mag_returns_none_when_missing() -> None:
    header = DummyHeader({"FILTER": "R"})
    assert resolve_zero_point_mag(Path("dummy.fits"), header) is None


def test_summarize_results_uses_supplied_magnitude_label() -> None:
    results = [
        SimpleNamespace(mag=12.5, flux=100.0),
        SimpleNamespace(mag=13.0, flux=200.0),
    ]

    summary = summarize_results(results, "calibrated magnitude")

    assert "median calibrated magnitude" in summary


def test_resolve_fits_path_accepts_repo_test_subject_name() -> None:
    resolved = resolve_fits_path("ngc1846_cluster_r_000")

    assert resolved.is_file()
    assert resolved.name == "ngc1846_cluster_r_000.fits"


def test_list_bundled_targets_groups_repo_test_subjects() -> None:
    targets = list_bundled_targets()

    assert "cluster" in targets
    assert "ngc1846_cluster_r_000" in targets["cluster"]


def test_magnitude_label_distinguishes_unverified_zero_points() -> None:
    zero_point = SimpleNamespace(value=17.2, verified=False)

    assert magnitude_label_for(zero_point) == "magnitude (unverified zero point applied)"


def test_pipeline_keeps_the_default_output_directory_constant() -> None:
    assert photometry_pipeline.DEFAULT_OUTPUT_DIR == Path.home() / "Downloads"


def test_replicate_zero_point_rejection_flags_planted_outlier() -> None:
    # A clean zero_point=20 relation with small, fixed (non-zero, so the
    # solve's variance step doesn't divide by zero on a perfect line) per-star
    # scatter, plus one star whose ref_mag is 5 mag off the rest.
    zero_point = 20.0
    good_mags = [-10.0, -9.5, -9.0, -8.5, -8.0, -7.5, -7.0, -6.5, -6.0, -5.5]
    jitter = [0.01, -0.02, 0.015, -0.01, 0.02, -0.015, 0.01, -0.02, 0.015, -0.01]
    sources = [
        DummyCalSource(mag=m, ref_mag=m + zero_point + j)
        for m, j in zip(good_mags, jitter)
    ]
    sources.append(DummyCalSource(mag=-9.2, ref_mag=-9.2 + zero_point + 5.0))

    kept = _replicate_zero_point_rejection(sources)

    assert len(kept) == len(sources)
    assert kept[:-1].all()
    assert not kept[-1]


def test_plot_zero_point_solution_skips_unverified_zero_point() -> None:
    # A CLI override or header value was never checked against a catalog, so
    # there is no per-star calibration data to plot.
    zero_point = ZeroPointResolution(value=20.0, source="header", verified=False)
    assert plot_zero_point_solution(zero_point, Path("unused.png")) is None


def test_compute_photometry_disables_apcorr_for_field_cal_zero_point() -> None:
    # field_cal.py solves its zero point with apcorr_tol=0 (aperture correction
    # off -- see docs/extraction.md's apcorr_tol note and field_cal.py's own
    # "LEGACY AFTERGLOW PARITY -- DO NOT CLEAN UP" comment). Applying that zero
    # point to a final pass using the class default (apcorr_tol=1e-4, aperture
    # correction on) would silently bias every reported magnitude by the
    # frame's own aperture-correction constant -- confirmed live on bundled
    # frames to be as large as ~0.25 mag, far bigger than a typical zero-point
    # solve's own reported uncertainty. Mocked rather than run against a real
    # catalog: this checks the settings compute_photometry actually builds,
    # not the network-dependent solve itself.
    fits_path = resolve_fits_path("nsv2849_star_v_000")
    fake_zero_point = ZeroPointResolution(value=20.0, source="field-cal", verified=True, diagnostics={})
    captured = {}
    real_run_photometry = photometry_pipeline.run_photometry

    def spy(*args, **kwargs):
        captured["apcorr_tol"] = kwargs["settings"].apcorr_tol
        return real_run_photometry(*args, **kwargs)

    with (
        patch.object(photometry_pipeline, "select_zero_point_mag", return_value=fake_zero_point),
        patch.object(photometry_pipeline, "run_photometry", side_effect=spy),
    ):
        compute_photometry(fits_path, use_field_cal=True)

    assert captured["apcorr_tol"] == 0.0


def test_compute_photometry_keeps_default_apcorr_for_non_field_cal_zero_point() -> None:
    # A CLI override or header value was never solved against a catalog in the
    # first place, so there's no apcorr_tol=0 scale to match -- the default
    # (aperture correction on) is correct here, unchanged from before the fix.
    fits_path = resolve_fits_path("nsv2849_star_v_000")
    fake_zero_point = ZeroPointResolution(value=20.0, source="header", verified=False)
    captured = {}
    real_run_photometry = photometry_pipeline.run_photometry

    def spy(*args, **kwargs):
        captured["apcorr_tol"] = kwargs["settings"].apcorr_tol
        return real_run_photometry(*args, **kwargs)

    with (
        patch.object(photometry_pipeline, "select_zero_point_mag", return_value=fake_zero_point),
        patch.object(photometry_pipeline, "run_photometry", side_effect=spy),
    ):
        compute_photometry(fits_path, use_field_cal=False)

    assert captured["apcorr_tol"] == PhotometrySettings().apcorr_tol


def test_render_credits_card_skips_image_when_photo_missing() -> None:
    # The mentor's photo isn't bundled with the repo -- this is an easter
    # egg, not something worth crashing over when the asset isn't there.
    result = render_credits_card(Path("unused.png"), asset_path=Path("does_not_exist.jpg"))
    assert result is None


def test_add_mentor_sidebar_skips_silently_when_asset_missing() -> None:
    # docs/assets/salad.png is untracked by design (same as the credits-card
    # photo) -- a fresh clone won't have it, so this must add nothing rather
    # than raise.
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        _add_mentor_sidebar(fig, asset_path=Path("does_not_exist.jpg"))
        assert len(fig.axes) == 1
    finally:
        plt.close(fig)
