"""Parity checks for the non-browser Astromancer HR helpers."""

from __future__ import annotations

import math

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
    assert math.isnan(legacy.get_default_bin([1.0, 1.0, 1.0]))


def test_plot_transform_preserves_off_by_one_break_and_strict_error_cut():
    raw = [{"id": "a", "x": 1.0, "y": 10.0, "max_mag_error": 0.1}, {"id": "b", "x": 2.0, "y": 11.0, "max_mag_error": 0.2}]

    points, ids = legacy.get_plot_data(raw, "CM", {"blue": "BP", "red": "RP", "lum": "G"}, {"distance": 1.0, "reddening": 0.0}, 0.2)
    assert points == [[1.0, 10.0]] and ids == ["a"]
    assert legacy.apply_isochrone_transform({"data": [[1, 2], [3, 4], [5, 6]], "iSkip": 1}, "HR", {"blue": "BP", "red": "RP", "lum": "G"}, {"distance": 1.0, "reddening": 0.0}) == [[None, None], [3, 4], [5, 6]]
    assert legacy.compute_plot_delta(
        {"blue": "gprime", "red": "iprime", "lum": "rprime"},
        {"distance": 1.0, "reddening": 0.2},
    ) == pytest.approx({"x": -0.3396268972771528, "y": -10.54009866066234})


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


def test_fsr_merge_and_catalog_star_counts_preserve_legacy_tallies():
    sources = [
        {"id": "2", "photometries": [{"filter": "G"}], "fsr": None},
        {"id": "10", "photometries": [{"filter": "BP"}], "fsr": None},
    ]

    updated = legacy.append_fsr_results(sources, [
        {"id": "10", "pm_ra": 1.0, "pm_dec": 2.0, "distance": 3.0},
        {"id": "2", "pm_ra": 4.0, "pm_dec": 5.0, "distance": 6.0},
    ])
    counts = legacy.get_star_counts_by_filter(
        updated[:1], updated[1:], ["G"], {},
        {"cluster_stars": 8, "field_stars": 4, "unused_stars": 0}, 5,
    )

    assert updated[0]["fsr"] == {"pm_ra": 4.0, "pm_dec": 5.0, "distance": 6.0}
    assert updated[1]["fsr"] == {"pm_ra": 1.0, "pm_dec": 2.0, "distance": 3.0}
    assert counts == {"cluster_stars": 1, "field_stars": 4, "unused_stars": 0}


def test_angles_and_result_derivations_preserve_legacy_units_and_percentiles():
    assert legacy.rad(180.0) == pytest.approx(3.141592653589793)
    assert legacy.deg(3.141592653589793) == pytest.approx(180.0)
    assert legacy.d2_hms(30.5) == [2, 2, 0.0]
    assert legacy.d2_dms(-1.5) == [1, 30, 0.0]
    assert legacy.haversine(0.0, 0.0, 0.0, 1.0) == pytest.approx(1.0)

    members = [
        {"astrometry": {"ra": 0.0, "dec": 0.0}, "fsr": {"pm_ra": 1.0, "pm_dec": 0.0}},
        {"astrometry": {"ra": 1.0, "dec": 0.0}, "fsr": {"pm_ra": 2.0, "pm_dec": 0.0}},
        {"astrometry": {"ra": {"bad": "shape"}, "dec": 0.0}, "fsr": None},
    ]
    # The original median picks floor(n / 2), and its dispersion slice is
    # upper-exclusive; this fixture makes both choices observable.
    assert legacy.get_half_light_radius(members[:2], 0.0, 0.0) == pytest.approx(1.0)
    assert legacy.get_pmra([1.0, 2.0, 3.0]) == 2.0
    assert legacy.get_pmdec([1.0, 2.0, 3.0]) == 2.0
    assert legacy.get_velocity_dispersion(members[:2], 0.0, 0.0) == pytest.approx(1.5)
    assert legacy.get_physical_radius(1.0, 1.0) == pytest.approx(56.9252, rel=1e-4)
    assert legacy.log_age_to_myr(6.0) == 1.0


def test_standard_range_and_distance_reset_keep_legacy_formulae():
    view_range = legacy.get_standard_view_range({"blue": "BP", "red": "RP", "lum": "G"})
    assert view_range["x"] == pytest.approx({"min": -0.7575, "max": 2.0175})
    assert view_range["y"] == pytest.approx({"min": -13.08375, "max": 11.16625})
    assert legacy.reset_distance({"distance": {"min": 0.111, "max": 0.222}}) == 0.17
    assert legacy.reset_distance({"distance": None}) == 0.1


def test_galactic_mass_and_summary_derivations_preserve_result_stage_values():
    galactic_center = legacy.equatorial_to_galactic(266.4051, -28.936175)
    assert galactic_center == pytest.approx({"l": 0.0012579619862264737, "b": -0.0001457301529737966})
    assert legacy.get_mass(1.0, 1.0, 1.0) == pytest.approx(16018.999484122987)

    sources = [
        {"astrometry": {"ra": 0.0, "dec": 0.0}, "fsr": {"pm_ra": 1.0, "pm_dec": 0.0}},
        {"astrometry": {"ra": 1.0, "dec": 0.0}, "fsr": {"pm_ra": 2.0, "pm_dec": 0.0}},
    ]
    summary = legacy.compute_cluster_summary(
        sources, 0.0, 0.0, [1.0, 2.0], [0.0, 0.0],
        {"distance": 1.0, "reddening": 0.1}, {"age": 8.0, "metallicity": -0.1},
    )

    assert summary == pytest.approx({
        "numberOfStars": 2,
        "angularRadius": 1.0,
        "ra": 0.0,
        "dec": 0.0,
        "l": 96.33857264298052,
        "b": -60.18841116963577,
        "physicalRadius": 56.92640582325447,
        "pmra": 2.0,
        "pmdec": 0.0,
        "velocityDispersion": 0.5,
        "mass": 227976.0163789223,
        "distance": 1.0,
        "age": 8.0,
        "metallicity": -0.1,
        "reddening": 0.1,
    })


def test_catalog_data_shaping_preserves_filter_order_and_fsr_projections():
    sources = [
        {
            "id": "a", "astrometry": {"ra": 10.004, "dec": -1.995},
            "fsr": {"distance": 1.234, "pm_ra": 2.345, "pm_dec": -3.456},
            "photometries": [
                {"filter": "G", "mag": 10.0, "mag_error": 0.1},
                {"filter": "BP", "mag": 11.0, "mag_error": 0.2},
                {"filter": "not-a-filter", "mag": 12.0, "mag_error": 0.1},
                {"filter": "RP", "mag": float("nan"), "mag_error": 0.1},
            ],
        },
        {
            "id": "b", "astrometry": {"ra": 3.0, "dec": 4.0}, "fsr": None,
            "photometries": [{"filter": "RP", "mag": 9.0, "mag_error": 0.1}],
        },
    ]

    normalized, filters = legacy.normalize_sources(sources)

    assert [point["filter"] for point in normalized[0]["photometries"]] == ["BP", "G"]
    assert filters == ["BP", "G"]
    assert legacy.get_fsr_values(normalized, "distance") == [1.23]
    assert legacy.get_fsr_values(normalized, "pm_ra") == [2.35]
    assert legacy.get_fsr_values(normalized, "pm_dec") == [-3.46]
    assert legacy.get_astrometry_values(normalized, "ra") == [10.0]
    assert legacy.get_astrometry_values(normalized, "dec") == [-2.0]
    assert legacy.get_cluster_coordinate(normalized, "ra") == 10.0
    assert legacy.get_2d_pm_chart_data(normalized, []) == {"cluster": [[2.345, -3.456]], "field": []}


def test_interface_star_counts_assemble_catalog_and_user_partitions():
    cluster_sources = [{"photometries": [{"filter": "G"}]}]
    field_sources = [{"photometries": [{"filter": "BP"}]}]
    result = legacy.get_interface_star_counts(
        cluster_sources, field_sources,
        {"GAIA": {"field_stars": 2}, "APASS": {"field_stars": 0}, "TWO_MASS": {"field_stars": 0}, "WISE": {"field_stars": 0}},
        {"num_total_stars": 4, "num_APASS_stars": 0, "num_TWO_MASS_stars": 0, "num_WISE_stars": 0},
        {"fsr": [{"id": "member"}], "not_fsr": [{"id": "field"}]},
    )

    assert result == {
        "user": {"cluster_stars": 1, "field_stars": 1, "unused_stars": 0},
        "GAIA": {"cluster_stars": 1, "field_stars": 3, "unused_stars": 0},
        "APASS": {"cluster_stars": 0, "field_stars": 0, "unused_stars": 0},
        "TWO_MASS": {"cluster_stars": 0, "field_stars": 0, "unused_stars": 0},
        "WISE": {"cluster_stars": 0, "field_stars": 0, "unused_stars": 0},
    }


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
