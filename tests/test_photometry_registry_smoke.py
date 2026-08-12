from __future__ import annotations

from pathlib import Path

from tools.photometry import list_photometry_targets, run_photometry_on_target


def test_list_photometry_targets_includes_known_bundled_stem() -> None:
    library = list_photometry_targets()

    assert library.total_count > 0
    assert "ngc1846_cluster_r_000" in library.categories.get("cluster", [])


def test_run_photometry_on_target_reports_missing_target_as_error() -> None:
    result = run_photometry_on_target("does-not-exist-target")

    assert result.file.exists is False
    assert len(result.errors) == 1
    assert result.errors[0].code == "target_not_found"
    assert result.artifacts == []


def test_run_photometry_on_target_no_field_cal_is_fast_and_local(tmp_path: Path) -> None:
    # use_field_cal=False keeps this test offline and deterministic -- the
    # network field-cal path is exercised manually, not in the default
    # no-network test suite.
    result = run_photometry_on_target(
        "ngc1846_cluster_r_000", use_field_cal=False, output_dir=tmp_path
    )

    assert result.source_count > 0
    assert result.zero_point_source == "none"
    assert result.zero_point is None
    assert len(result.artifacts) == 1
    assert Path(result.artifacts[0].path).exists()
