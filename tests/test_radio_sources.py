"""algorithms/radio + tools/radio_sources.py -- fitting math, matching, and
the plot_field_sed / identify_radio_sources / analyze_source_spectrum tools.

No network access by default -- VizieR/NED-backed paths are covered by
synthetic-data unit tests here and were confirmed live manually (see
docs/extraction.md).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from algorithms.radio import spectral_fitting
from algorithms.radio.matching import guess_radec_columns, match_sources_to_catalog
from tools.models import ToolResult
from tools.radio_sources import analyze_source_spectrum, identify_radio_sources


# ---------------------------------------------------------------------------
# algorithms.radio.spectral_fitting
# ---------------------------------------------------------------------------
def test_fit_power_law_recovers_injected_spectral_index():
    freq = np.logspace(7, 10, 12)
    true_index, true_amplitude = -0.75, 100.0
    flux = true_amplitude * freq**true_index

    result = spectral_fitting.fit_power_law(freq, flux)

    assert result["spectral_index"] == pytest.approx(true_index, abs=1e-6)
    assert result["amplitude"] == pytest.approx(true_amplitude, rel=1e-6)
    assert result["r_squared"] > 0.999


def test_fit_power_law_needs_at_least_two_points():
    with pytest.raises(ValueError):
        spectral_fitting.fit_power_law([1e9], [1.0])


def test_fit_power_law_reports_a_finite_spectral_index_error_with_enough_points():
    freq = np.logspace(7, 10, 12)
    flux = 100.0 * freq**-0.75

    result = spectral_fitting.fit_power_law(freq, flux)

    assert result["spectral_index_error"] is not None
    assert np.isfinite(result["spectral_index_error"])
    assert result["spectral_index_error"] >= 0.0


def test_fit_power_law_reports_no_uncertainty_for_the_minimal_two_point_case():
    # cov=True needs strictly more points than free parameters (2 here) to
    # scale a covariance matrix -- the 2-point floor must not raise or
    # fabricate a value, it must say "not available."
    result = spectral_fitting.fit_power_law([1e8, 1e9], [10.0, 1.0])

    assert result["spectral_index_error"] is None


def test_fit_log_parabola_returns_none_below_four_points():
    freq = np.logspace(8, 9, 3)
    flux = 10.0 * freq**-0.7
    assert spectral_fitting.fit_log_parabola(freq, flux) is None


def test_analyze_spectrum_prefers_power_law_for_a_clean_power_law():
    freq = np.logspace(7, 10, 12)
    flux = 50.0 * freq**-0.7
    result = spectral_fitting.analyze_spectrum(freq, flux)
    assert result["best_model"] == "power_law"
    assert result["spectral_index"] == pytest.approx(-0.7, abs=1e-6)


def test_analyze_spectrum_detects_real_curvature():
    # A low-frequency turnover (self-absorption): a clean power law with a
    # multiplicative suppression below ~500 MHz -- this should show up as a
    # materially better log-parabola fit, not just noise.
    freq = np.logspace(7, 10, 14)
    flux = 50.0 * freq**-0.7 * (1.0 - np.exp(-(freq / 5e8)))
    result = spectral_fitting.analyze_spectrum(freq, flux)
    assert result["best_model"] == "log_parabola"
    assert result["log_parabola"]["r_squared"] > result["power_law"]["r_squared"]


# ---------------------------------------------------------------------------
# algorithms.radio.matching
# ---------------------------------------------------------------------------
def test_guess_radec_columns_tries_known_conventions_in_order():
    table = pd.DataFrame({"RAJ2000": [10.0], "DEJ2000": [-30.0], "Sp": [1.2]})
    assert guess_radec_columns(table) == ("RAJ2000", "DEJ2000")

    table2 = pd.DataFrame({"ra": [10.0], "dec": [-30.0]})
    assert guess_radec_columns(table2) == ("ra", "dec")

    table3 = pd.DataFrame({"Flux": [1.0], "Name": ["x"]})
    assert guess_radec_columns(table3) is None


def test_match_sources_to_catalog_finds_nearby_and_skips_far():
    catalog = pd.DataFrame(
        {"RAJ2000": [10.001, 20.5], "DEJ2000": [-30.0005, 40.0], "Name": ["A", "B"]}
    )
    sources = pd.DataFrame({"ra_deg": [10.0, 20.0, 100.0], "dec_deg": [-30.0, 40.0, 0.0]})

    matches = match_sources_to_catalog(sources, catalog, radius_arcsec=10.0)

    assert len(matches) == 1
    assert matches[0]["source_index"] == 0
    assert matches[0]["catalog_row"]["Name"] == "A"
    assert matches[0]["separation_arcsec"] < 10.0


def test_match_sources_to_catalog_handles_sexagesimal_columns():
    # Confirmed live: some VizieR tables carry sexagesimal strings under the
    # same RA/DEC column names decimal-degree tables use.
    catalog = pd.DataFrame({"RA": ["00 40 00.0"], "DEC": ["+41 00 00"]})
    sources = pd.DataFrame({"ra_deg": [10.0], "dec_deg": [41.0]})

    # Not a real match (RA 00 40 00.0 = 10 deg, matches!) -- check it doesn't crash.
    matches = match_sources_to_catalog(sources, catalog, radius_arcsec=30.0)
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# tools.radio_sources -- offline paths
# ---------------------------------------------------------------------------
def test_analyze_source_spectrum_with_explicit_arrays(tmp_path: Path):
    freq = np.logspace(7, 10, 10).tolist()
    flux = (50.0 * np.logspace(7, 10, 10) ** -0.7).tolist()

    result = analyze_source_spectrum(
        name="synthetic", frequencies_hz=freq, fluxes_jy=flux, output_dir=tmp_path
    )

    assert result.status == "ok"
    fit = result.preview[0]
    assert fit["source_name"] == "synthetic"
    assert fit["spectral_index"] == pytest.approx(-0.7, abs=1e-3)
    assert len(result.artifacts) == 1
    assert Path(result.artifacts[0].path).exists()


def test_analyze_source_spectrum_with_csv(tmp_path: Path):
    freq = np.logspace(7, 10, 10)
    flux = 50.0 * freq**-0.7
    csv_path = tmp_path / "spectrum.csv"
    pd.DataFrame({"frequency": freq, "flux": flux}).to_csv(csv_path, index=False)

    result = analyze_source_spectrum(csv_path=str(csv_path), output_dir=tmp_path)

    assert result.status == "ok"
    assert result.preview[0]["spectral_index"] == pytest.approx(-0.7, abs=1e-3)


def test_analyze_source_spectrum_requires_some_input():
    result = analyze_source_spectrum()
    assert result.status == "error"


def _write_synthetic_fits(
    path: Path, with_wcs: bool = True, with_source: bool = True,
    size: int = 100, pixel_scale_arcsec: float = 2.0, n_sources: int = 1,
) -> None:
    rng = np.random.default_rng(0)
    data = rng.normal(0, 0.01, (size, size)).astype(np.float32)
    if with_source:
        yy, xx = np.mgrid[0:size, 0:size]
        # Spread sources across the frame (not all at the centre) so a wide,
        # coarse-pixel frame actually produces a wide angular footprint.
        centres = np.linspace(size * 0.1, size * 0.9, n_sources)
        for c in centres:
            data += 5.0 * np.exp(-(((xx - c) ** 2 + (yy - c) ** 2) / (2 * 3.0**2)))

    header = None
    if with_wcs:
        w = WCS(naxis=2)
        w.wcs.crpix = [size / 2, size / 2]
        w.wcs.cdelt = [-pixel_scale_arcsec / 3600.0, pixel_scale_arcsec / 3600.0]
        w.wcs.crval = [180.0, 0.0]
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        header = w.to_header()
    fits.writeto(path, data, header=header, overwrite=True)


def test_identify_radio_sources_reports_error_without_wcs(tmp_path: Path):
    fits_path = tmp_path / "no_wcs.fits"
    _write_synthetic_fits(fits_path, with_wcs=False)

    result = identify_radio_sources(str(fits_path))

    assert result.status == "error"
    assert "WCS" in result.errors[0].message


def test_identify_radio_sources_reports_not_found_with_no_sources(tmp_path: Path):
    fits_path = tmp_path / "empty.fits"
    _write_synthetic_fits(fits_path, with_wcs=True, with_source=False)

    result = identify_radio_sources(str(fits_path), threshold=8.0)

    assert result.status == "not_found"


def test_identify_radio_sources_scales_the_default_cross_match_radius_with_pixel_scale(tmp_path: Path):
    """Confirmed live against a real GreenBank 20m map (~122"/pixel): the old
    fixed 15" default is smaller than one pixel there, so it could never
    match anything regardless of whether a real catalogued source was right
    there. The default must scale with the frame's own pixel scale."""
    fine_path = tmp_path / "fine.fits"
    _write_synthetic_fits(fine_path, pixel_scale_arcsec=2.0)
    coarse_path = tmp_path / "coarse.fits"
    _write_synthetic_fits(coarse_path, pixel_scale_arcsec=120.0)

    with patch("tools.radio_sources.search_vizier", return_value=ToolResult(status="not_found")):
        fine_result = identify_radio_sources(str(fine_path))
        coarse_result = identify_radio_sources(str(coarse_path))

    fine_radius = float(
        fine_result.warnings[-1].message.split("within ")[-1].rstrip('"')
    )
    coarse_radius = float(
        coarse_result.warnings[-1].message.split("within ")[-1].rstrip('"')
    )
    assert fine_radius == pytest.approx(15.0)  # the 15" floor wins at a fine pixel scale
    assert coarse_radius == pytest.approx(1.5 * 120.0)  # the pixel-scale term wins once coarse


def test_identify_radio_sources_caps_a_wide_field_and_warns(tmp_path: Path):
    """Confirmed live: a real GreenBank 20m scan's detected sources spanned
    ~20-24 degrees, computing a ~14-degree field_footprint radius that turned
    into an effectively whole-sky VizieR query with no practical runtime.
    Must cap the request and say so, not hang."""
    fits_path = tmp_path / "wide.fits"
    _write_synthetic_fits(fits_path, size=600, pixel_scale_arcsec=120.0, n_sources=3)

    captured: dict = {}

    def fake_search_vizier(**kwargs):
        captured.update(kwargs)
        return ToolResult(status="not_found")

    with patch("tools.radio_sources.search_vizier", side_effect=fake_search_vizier):
        result = identify_radio_sources(str(fits_path), max_field_radius_arcmin=60.0)

    assert captured["radius_arcmin"] == pytest.approx(60.0)
    assert [w.code for w in result.warnings].count("field_radius_capped") == 1


def test_identify_radio_sources_field_cap_can_be_disabled(tmp_path: Path):
    fits_path = tmp_path / "wide2.fits"
    _write_synthetic_fits(fits_path, size=600, pixel_scale_arcsec=120.0, n_sources=3)

    captured: dict = {}

    def fake_search_vizier(**kwargs):
        captured.update(kwargs)
        return ToolResult(status="not_found")

    with patch("tools.radio_sources.search_vizier", side_effect=fake_search_vizier):
        result = identify_radio_sources(str(fits_path), max_field_radius_arcmin=None)

    assert captured["radius_arcmin"] > 60.0
    assert "field_radius_capped" not in [w.code for w in result.warnings]


def test_registry_exposes_radio_tools():
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    names = {"plot_field_sed", "identify_radio_sources", "analyze_source_spectrum"}
    assert names.issubset(TOOL_FUNCTIONS)
    schema_names = {s["name"] for s in TOOL_SCHEMAS}
    assert names.issubset(schema_names)
