"""Parity checks for the non-browser Astromancer HR helpers."""

from __future__ import annotations

import pytest

from algorithms.hrdiagram_py import legacy


SOURCES = [
    {"id": "1", "photometries": [{"filter": "BP", "mag": 12.0, "mag_error": 0.1}, {"filter": "RP", "mag": 11.0, "mag_error": 0.2}], "astrometry": {"ra": 0.0, "dec": 0.0}, "fsr": None},
    {"id": "2", "photometries": [{"filter": "W1", "mag": 10.0, "mag_error": 0.1}, {"filter": "W2", "mag": 9.5, "mag_error": 0.1}], "astrometry": {"ra": 0.0, "dec": 0.0}, "fsr": None},
]


def test_cmd_prefers_bp_rp_even_when_another_pair_is_available():
    result = legacy.get_cmd_data(SOURCES, ["BP", "RP", "W1", "W2"])

    assert result == {"data": [[1.0, 11.0]], "blue_filter": "BP", "red_filter": "RP"}


def test_histogram_preserves_empty_fallback_and_sorted_percentile_indices():
    assert legacy.get_default_bin([]) == 10
    assert legacy.get_histogram_extremes([0, 1, 2, 3, 4], []) == {"min": -999, "max": 999}
    assert legacy.get_histogram_extremes(list(range(100)), [1]) == {"min": 1, "max": 99}


def test_plot_transform_preserves_off_by_one_break_and_strict_error_cut():
    raw = [{"id": "a", "x": 1.0, "y": 10.0, "max_mag_error": 0.1}, {"id": "b", "x": 2.0, "y": 11.0, "max_mag_error": 0.2}]

    points, ids = legacy.get_plot_data(raw, "CM", {"blue": "BP", "red": "RP", "lum": "G"}, {"distance": 1.0, "reddening": 0.0}, 0.2)
    assert points == [[1.0, 10.0]] and ids == ["a"]
    assert legacy.apply_isochrone_transform({"data": [[1, 2], [3, 4], [5, 6]], "iSkip": 1}, "HR", {"blue": "BP", "red": "RP", "lum": "G"}, {"distance": 1.0, "reddening": 0.0}) == [[None, None], [3, 4], [5, 6]]


def test_mwsc_distributions_keep_original_clip_and_unit_rules():
    clusters = [
        {"age": 9.0, "distance": 1000, "metallicity": 0.0, "e_bv": 0.2, "num_cluster_stars": 10},
        {"age": None, "distance": -1, "metallicity": 0.8, "e_bv": 1.1, "num_cluster_stars": 0},
    ]

    assert legacy.get_mwsc_age_distribution(clusters) == []
    assert legacy.get_mwsc_distance_distribution(clusters) == [1.0]
    assert legacy.get_mwsc_metallicity_distribution(clusters) == [0.0]
    assert legacy.get_mwsc_reddening_distribution(clusters) == [0.2]
    assert legacy.get_mwsc_star_count_distribution(clusters) == [10]


def test_source_serialization_and_elliptical_field_star_partition_preserve_legacy_rules():
    serialized = legacy.source_serialization([{
        "id": "a", "photometries": [{"filter": "G", "mag": 10.0, "mag_err": 0.2}],
        "astrometry": {"ra": 1.0, "dec": 2.0}, "fsr": {"pm_ra": 3.0, "pm_dec": 4.0, "distance": 5.0},
    }])
    assert serialized["filters"] == ["G"]
    assert serialized["sources"][0]["photometries"] == [{"filter": "G", "mag": 10.0, "mag_error": 0.2}]
    partitions = legacy.update_cluster_field_sources(
        serialized["sources"],
        {"distance": {"min": 4.0, "max": 6.0}, "pm_ra": {"min": 2.0, "max": 4.0}, "pm_dec": {"min": 3.0, "max": 5.0}},
    )
    assert partitions == {"fsr": serialized["sources"], "not_fsr": []}


def test_derived_galaxy_offsets_and_filter_validation_follow_legacy_values():
    assert legacy.is_valid_filter_selection({"blue": "BP", "red": "RP", "lum": "G"}) is True
    assert legacy.is_valid_filter_selection({"blue": "BP", "red": "BP", "lum": "G"}) is False
    assert legacy.galaxy_face_on_offset(90.0, 0.0, 2.0) == pytest.approx({"delta_x": 64.0, "delta_y": 0.0})
    assert legacy.galaxy_edge_on_offset(180.0, 90.0, 100.0)["delta_y"] == 500


def test_raw_plot_points_include_worst_error_and_data_range_only_pads_two_dimensional_spans():
    raw = legacy.generate_raw_data(SOURCES, {"blue": "BP", "red": "RP", "lum": "RP"})
    assert raw == [{"id": "1", "x": 1.0, "y": 11.0, "max_mag_error": 0.2}]
    assert legacy.get_data_range([[1.0, 2.0], [3.0, 4.0]]) == {"x": {"min": 0.8, "max": 3.2}, "y": {"min": 1.8, "max": 4.2}}
    assert legacy.get_data_range([[1.0, 2.0], [1.0, 4.0]]) == {"x": {"min": 1.0, "max": 1.0}, "y": {"min": 2.0, "max": 4.0}}
