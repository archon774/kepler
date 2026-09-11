"""Local Girardi-grid contract for the former Astromancer isochrone endpoint."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from algorithms.hrdiagram_py import isochrones, local_grid
from tools import config
from tools import hr_diagram


def test_operator_grid_setting_has_no_bundled_default():
    assert config.ISOCHRONE_DIR_ENV == "KEPLER_ISOCHRONE_DIR"
    assert config.ISOCHRONE_DIR is None


def _track() -> np.ndarray:
    rows = np.zeros((2, 23), dtype=float)
    rows[:, 0] = 8.60
    rows[:, 1] = -0.05
    rows[:, 2:7] = [[10, 11, 12, 13, 14], [20, 21, 22, 23, 24]]
    rows[:, 7:12] = [[30, 31, 32, 33, 34], [40, 41, 42, 43, 44]]
    rows[:, 12:15] = [[50, 51, 52], [60, 61, 62]]
    rows[:, 15:19] = [[70, 71, 72, 73], [80, 81, 82, 83]]
    rows[:, 19:22] = [[90, 91, 92], [100, 101, 102]]
    rows[:, 22] = -0.05
    return rows


def test_exact_girardi_track_returns_browser_colour_magnitude_shape(tmp_path):
    np.save(tmp_path / "Girardi_8.60_-0.05.npy", _track())

    response = local_grid.load_isochrone(
        tmp_path, age=8.60, metallicity=-0.05,
        blue_filter="BP", red_filter="RP", lum_filter="G",
    )

    assert response.path == tmp_path / "Girardi_8.60_-0.05.npy"
    assert response.data == [[-1.0, 90.0], [-1.0, 100.0]]
    assert response.i_skip == 0


def test_missing_exact_track_is_an_actionable_error(tmp_path):
    with pytest.raises(local_grid.GridUnavailableError, match="Girardi_8.60_0.00.npy"):
        local_grid.load_isochrone(
            tmp_path, age=8.60, metallicity=0.0,
            blue_filter="BP", red_filter="RP", lum_filter="G",
        )


def test_rejects_unknown_filter_and_wrong_shape(tmp_path):
    np.save(tmp_path / "Girardi_8.60_0.00.npy", np.zeros((2, 22)))

    with pytest.raises(local_grid.GridUnavailableError, match="23 columns"):
        local_grid.load_isochrone(
            tmp_path, age=8.60, metallicity=0.0,
            blue_filter="BP", red_filter="RP", lum_filter="G",
        )

    np.save(tmp_path / "Girardi_8.60_0.00.npy", _track())
    with pytest.raises(local_grid.GridUnavailableError, match="unsupported filter"):
        local_grid.load_isochrone(
            tmp_path, age=8.60, metallicity=0.0,
            blue_filter="X", red_filter="RP", lum_filter="G",
        )


def test_load_tracks_preserves_exact_age_and_all_supported_filter_columns(tmp_path):
    np.save(tmp_path / "Girardi_8.60_-0.05.npy", _track())
    np.save(tmp_path / "Girardi_8.65_-0.05.npy", _track() + np.array([0.05, 0, *([0] * 21)]))

    grid = local_grid.load_tracks(tmp_path, ages=[8.60, 8.65], metallicity=-0.05)

    assert list(grid[["logAge", "MH", "G", "BP", "RP"]].iloc[0]) == [8.60, -0.05, 90.0, 91.0, 92.0]
    assert set(grid["logAge"]) == {8.60, 8.65}


def test_fit_uses_configured_local_grid_without_a_parsec_request(tmp_path, monkeypatch):
    track = _track()
    track[:, 19:22] = [[10.0, 11.0, 9.0], [8.0, 9.0, 7.0]]
    np.save(tmp_path / "Girardi_8.60_0.00.npy", track)
    members = pd.DataFrame({
        "BP": [21.0, 19.0], "RP": [19.0, 17.0], "G": [20.0, 18.0],
        "BP_err": [0.01, 0.01], "RP_err": [0.01, 0.01], "G_err": [0.01, 0.01],
    })
    monkeypatch.setattr(isochrones.requests, "post", lambda *args, **kwargs: pytest.fail("network request"))
    report = isochrones.fit_and_compare(
        members, {"log_age": 8.60, "distance_kpc": 1.0, "ebv": 0.0, "age_myr": 400.0}, "local",
        members_csv_path=tmp_path / "members.csv", out_png=tmp_path / "fit.png",
        grid_dir=tmp_path, logage_half_width=0.0, max_error=1.0,
    )

    assert report["isochrone_path"] == str(tmp_path)
    assert (tmp_path / "fit.png").is_file()


def test_hr_tool_reads_operator_grid_from_config(tmp_path, monkeypatch):
    track = _track()
    track[:, 19:22] = [[10.0, 11.0, 9.0], [8.0, 9.0, 7.0]]
    np.save(tmp_path / "Girardi_8.60_0.00.npy", track)
    members_path = tmp_path / "members.csv"
    pd.DataFrame({
        "BP": [21.0, 19.0], "RP": [19.0, 17.0], "G": [20.0, 18.0],
        "BP_err": [0.01, 0.01], "RP_err": [0.01, 0.01], "G_err": [0.01, 0.01],
    }).to_csv(members_path, index=False)
    monkeypatch.setattr(config, "ISOCHRONE_DIR", tmp_path)
    monkeypatch.setattr(hr_diagram, "_fetch_literature_params", lambda _: {"log_age": 8.60, "distance_kpc": 1.0, "ebv": 0.0, "age_myr": 400.0})
    monkeypatch.setattr(hr_diagram, "_output_path", lambda stem, suffix: tmp_path / f"{stem}{suffix}")

    result = hr_diagram.fit_and_compare_hr_diagram(str(members_path), "local", max_error=1.0, logage_half_width=0.0)

    assert result.status == "ok"
    assert result.preview[0]["isochrone_path"] == str(tmp_path)
