#!/usr/bin/env python
"""Claude photometry plotting tool using this repo's photometry pipeline.

This script loads a FITS image, runs source extraction and photometry using the
repository's `algorithms.photometry` modules, saves a plot, and optionally
summarizes the results with Claude.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import requests
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Generated plots default to the user's Downloads folder rather than next to the
# source FITS file — bundled test_data targets live inside the repo tree, and
# this repo's convention is to never write generated artifacts there (see
# CLAUDE.md: "Do not commit downloaded FITS products, generated plots, ...").
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"

from algorithms.photometry.photometry import PhotometrySettings, run_photometry
from algorithms.photometry.schemas import SourceExtractionSettings
from algorithms.photometry.source_extraction import build_wcs_from_header, perform_source_extraction


@dataclass
class ZeroPointResolution:
    """The zero point actually applied, and whether it was independently verified.

    ``verified`` is True only for the field-calibration path, where this tool
    itself cross-matched detected sources against a reference catalog and can
    report solve diagnostics. A CLI override or a header-embedded value is
    "provided" but not something this tool verified, so magnitudes derived from
    them must not be described as calibrated.
    """

    value: float | None
    source: str  # "cli" | "header" | "field-cal" | "none"
    verified: bool
    diagnostics: dict[str, float | int] | None = None
    # The per-star calibration sources fed into the field-cal solve (each an
    # `algorithms.photometry.schemas.PhotometryData` with `.mag`, `.ref_mag`,
    # and `.catalog_name`). Populated only for the field-cal path -- this is
    # what `plot_zero_point_solution` needs to draw the fit and mark outliers;
    # nothing else in this tool reads it.
    calibration_sources: list[object] | None = None


def resolve_zero_point_mag(fits_path: Path, header: object) -> float | None:
    """Return a photometric zero point from the FITS header when available."""
    if hasattr(header, "get"):
        for key in ("PHOT_M0", "PHOTZP", "ZEROPOINT", "ZP"):
            value = header.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def compute_field_cal_zero_point(
    header: object,
    data: "np.ndarray",
    catalogs: Sequence[str] | None = None,
) -> tuple[float | None, dict[str, float | int] | None, str | None, object | None]:
    """Solve for a real photometric zero point via ``fieldcal.perform_field_calibration``.

    Queries a reference catalog (over the network, via ``query.runner.query_catalogs``)
    for stars in the field, cross-matches them against detected sources, and solves
    for the zero point. Returns ``(zero_point_mag, diagnostics, error_message,
    field_cal_result)`` — on success ``error_message`` is ``None``, ``diagnostics``
    carries the solve's own verification evidence (zero-point error, rejection
    rate, number of calibration stars used), and ``field_cal_result`` is the raw
    ``algorithms.fieldcal.schemas.FieldCalResult`` (its ``phot_results`` is the
    per-star data ``plot_zero_point_solution`` needs); on any failure
    ``zero_point_mag``, ``diagnostics``, and ``field_cal_result`` are all
    ``None`` and ``error_message`` explains why, so callers can fall back to
    instrumental magnitudes instead of crashing the whole run.
    """
    # Imported lazily: `fieldcal`/`catalogs`/`query` pull in the (optional) network
    # stack only when field calibration is actually attempted.
    from algorithms.catalogs import CATALOGS
    from algorithms.fieldcal import deps as fieldcal_deps
    from algorithms.fieldcal.field_cal import perform_field_calibration
    from algorithms.fieldcal.schemas import PhotometricCalibrationSettings
    from algorithms.photometry.source_extraction import get_source_radec, run_source_extraction
    from algorithms.query.selection import select_catalogs_for_filter

    # Wire the seams `fieldcal` cut when it was extracted from Skynet (see
    # docs/extraction.md §4.3) to this repo's own photometry/WCS implementations.
    # `deps.query_catalogs` already defaults to `query.runner.query_catalogs`, so it
    # needs no wiring here.
    fieldcal_deps.run_photometry = run_photometry
    fieldcal_deps.run_source_extraction = run_source_extraction
    fieldcal_deps.get_source_radec = get_source_radec
    # EXTRACTED: was `build_wcs_from_header(header) or build_wcs_from_processing_run_solution(...)`;
    # the DB-backed fallback was dropped upstream of fieldcal (see deps.py), so a
    # header-only implementation is exactly what field calibration depends on here.
    fieldcal_deps.build_wcs_for_processing_run = lambda _processing_run, hdr: build_wcs_from_header(hdr)

    wcs = build_wcs_from_header(header)
    if wcs is None:
        return None, None, "image header has no celestial WCS; cannot query a reference catalog", None

    image_filter = header.get("FILTER") if hasattr(header, "get") else None
    selected_catalogs = list(catalogs) if catalogs else select_catalogs_for_filter(
        list(CATALOGS), image_filter
    )
    if not selected_catalogs:
        return None, None, f"no calibration catalog supports filter {image_filter!r}", None

    field_cal_settings = PhotometricCalibrationSettings(catalogs=selected_catalogs)
    extraction_settings = SourceExtractionSettings()
    photometry_settings = PhotometrySettings(mode="aperture", a=5.0, a_in_px=8.0, a_out_px=12.0)

    try:
        outcome = perform_field_calibration(
            ProcessingRun(),
            header,
            data,
            field_cal_settings=field_cal_settings,
            photometry_settings=photometry_settings,
            extraction_settings=extraction_settings,
        )
    except Exception as exc:  # network failures, no catalog matches, etc.
        return None, None, f"field calibration failed: {exc}", None

    if outcome is None:
        return None, None, "field calibration returned no solution", None
    zero_point_mag, result = outcome
    if zero_point_mag is None or not np.isfinite(zero_point_mag):
        return None, None, "field calibration did not converge on a finite zero point", None

    diagnostics = {
        "zero_point_error_mag": result.zero_point_error_mag,
        "zero_point_slop": result.zero_point_slop,
        "rejection_percent": result.rej_percent,
        "num_calibration_stars": len(result.phot_results),
        "catalogs_queried": ", ".join(selected_catalogs),
    }
    return float(zero_point_mag), diagnostics, None, result


def resolve_fits_path(query: str | Path) -> Path:
    """Resolve a FITS path from an explicit path, a relative path, or a bundled target name."""
    query_path = Path(str(query))
    search_roots = [Path.cwd(), ROOT, ROOT / "test_data" / "optical"]

    if query_path.is_absolute():
        if query_path.exists():
            return query_path.resolve()
        raise FileNotFoundError(
            f"FITS file '{query_path}' was not found locally."
        )

    candidates = [
        query_path,
        *[root / query_path for root in search_roots],
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    search_root = ROOT / "test_data" / "optical"
    if search_root.exists():
        name = query_path.name.lower()
        stem = query_path.stem.lower()
        fits_matches = [
            path
            for path in search_root.rglob("*.fits")
            if path.is_file() and (path.name.lower() == name or path.stem.lower() == stem)
        ]
        if len(fits_matches) == 1:
            return fits_matches[0].resolve()
        if len(fits_matches) > 1:
            matches_text = ", ".join(str(path.relative_to(ROOT)) for path in fits_matches[:8])
            raise FileNotFoundError(
                f"FITS target '{query}' matched multiple local files: {matches_text}."
            )

    raise FileNotFoundError(
        f"FITS file '{query}' was not found locally. Searched current directory, repo root, and {search_root}."
    )


def list_bundled_targets() -> dict[str, list[str]]:
    """Return the FITS target stems bundled under test_data/optical, by category.

    This tool has no live archive query behind it — a target name resolves only
    if it ships in test_data/optical. This is the discovery step for what's
    actually on hand, so a user isn't left guessing or hitting a bare
    FileNotFoundError for a target that was never bundled.

    test_data/optical is a flat directory (see test_data/README.md), so the
    category isn't a subdirectory name — it's derived from each file's stem,
    which follows a `<object>_<category>_<filter>_<seq>` naming convention
    (e.g. ``ngc1846_cluster_r_000``, ``m104_galaxy_v_000``).
    """
    search_root = ROOT / "test_data" / "optical"
    targets: dict[str, list[str]] = {}
    if not search_root.exists():
        return targets
    for path in sorted(search_root.glob("*.fits")):
        if not path.is_file():
            continue
        parts = path.stem.split("_")
        category = parts[1] if len(parts) > 1 else "uncategorized"
        targets.setdefault(category, []).append(path.stem)
    return targets


def select_zero_point_mag(
    explicit_zero_point_mag: float | None,
    header: object,
    data: "np.ndarray | None" = None,
    *,
    use_field_cal: bool = False,
    catalogs: Sequence[str] | None = None,
) -> ZeroPointResolution:
    """Choose the effective zero point and report where it came from.

    Preference order: an explicit CLI override, then a zero point already stamped
    into the FITS header, then (if requested) a live field-calibration solve
    against a reference catalog. Only the field-calibration path is marked
    ``verified`` — it is the only one where this tool itself checked the zero
    point against catalog data rather than trusting a supplied number.
    """
    if explicit_zero_point_mag is not None:
        return ZeroPointResolution(explicit_zero_point_mag, "cli", verified=False)

    header_zero_point = resolve_zero_point_mag(Path("<header>"), header)
    if header_zero_point is not None:
        return ZeroPointResolution(header_zero_point, "header", verified=False)

    if use_field_cal and data is not None:
        zero_point_mag, diagnostics, error, field_cal_result = compute_field_cal_zero_point(
            header, data, catalogs=catalogs
        )
        if zero_point_mag is not None:
            return ZeroPointResolution(
                zero_point_mag,
                "field-cal",
                verified=True,
                diagnostics=diagnostics,
                calibration_sources=field_cal_result.phot_results if field_cal_result else None,
            )
        print(f"Field calibration could not solve a zero point: {error}", file=sys.stderr)

    return ZeroPointResolution(None, "none", verified=False)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run photometry on a FITS file using the repo's photometry pipeline, "
            "save a plot, and optionally summarize results with Claude."
        )
    )
    parser.add_argument(
        "fits_path",
        nargs="?",
        default=None,
        help="Path to the FITS file to analyze, or a target name such as ngc1846_cluster_r_000. "
        "Omit when using --list-targets.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path for the photometry plot. Defaults to "
        f"{DEFAULT_OUTPUT_DIR / '<fitsname>_photometry.png'}",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-5",
        help="Claude model name to use for the API call.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Maximum token budget for the Claude summary request.",
    )
    parser.add_argument(
        "--zero-point",
        type=float,
        default=None,
        help="Optional photometric zero point to apply to the output magnitudes. "
        "Overrides both the FITS header and field calibration.",
    )
    parser.add_argument(
        "--no-field-cal",
        action="store_true",
        help="Skip the live field-calibration zero-point solve (no catalog query over "
        "the network); fall back to the FITS header or instrumental magnitudes only.",
    )
    parser.add_argument(
        "--catalogs",
        nargs="+",
        default=None,
        metavar="CATALOG",
        help="Reference catalogs to query for field calibration (e.g. APASS PanSTARRS). "
        "Defaults to catalogs that support the image's FILTER keyword.",
    )
    parser.add_argument(
        "--no-zp-plot",
        action="store_true",
        help="Skip saving the zero-point calibration diagnostic plot (fit line, "
        "residuals, kept/rejected calibration stars) even when a verified "
        "field-calibration solve is available.",
    )
    parser.add_argument(
        "--zp-plot-output",
        type=Path,
        default=None,
        help="Output PNG path for the zero-point calibration plot. Defaults to "
        "'<output>_zeropoint.png' next to the main photometry plot.",
    )
    parser.add_argument(
        "--no-claude",
        action="store_true",
        help="Skip the Claude API call and only generate the photometry plot.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only resolve the requested FITS file and report whether it exists locally.",
    )
    parser.add_argument(
        "--list-targets",
        action="store_true",
        help="List the FITS targets bundled under test_data/optical, grouped by "
        "category, and exit. There is no live archive query behind this tool — a "
        "target only resolves if it's in this list.",
    )
    return parser.parse_args()


class ProcessingRun:
    observation_asset_id = None


def load_fits_image(fits_path: Path) -> tuple[np.ndarray, object]:
    with fits.open(fits_path) as hdulist:
        header = hdulist[0].header
        data = hdulist[0].data

    if data is None:
        raise ValueError(f"FITS file '{fits_path}' contains no image data")
    if data.ndim != 2:
        raise ValueError(f"Only 2D FITS images are supported, got shape {data.shape}")
    return np.asarray(data, dtype=np.float64), header


def compute_photometry(
    fits_path: Path,
    zero_point_mag: float | None = None,
    *,
    use_field_cal: bool = True,
    catalogs: Sequence[str] | None = None,
) -> tuple[np.ndarray, list[object], ZeroPointResolution]:
    data, header = load_fits_image(fits_path)
    zero_point = select_zero_point_mag(
        zero_point_mag, header, data, use_field_cal=use_field_cal, catalogs=catalogs
    )
    effective_zero_point_mag = zero_point.value
    extraction_settings = SourceExtractionSettings()
    sources, background, background_rms = perform_source_extraction(
        ProcessingRun(),
        header,
        data,
        settings=extraction_settings,
    )

    photometry_settings = PhotometrySettings(
        mode="aperture",
        a=5.0,
        a_in_px=8.0,
        a_out_px=12.0,
        zero_point_mag=effective_zero_point_mag if effective_zero_point_mag is not None else 0.0,
    )

    results = run_photometry(
        data=data,
        header=header,
        sources=sources,
        settings=photometry_settings,
        background=background,
        background_rms=background_rms,
    )
    return data, results, zero_point


def plot_photometry(
    data: np.ndarray,
    results: Sequence[object],
    output_path: Path,
    magnitude_label: str = "instrumental magnitude",
) -> None:
    valid_results = [
        r for r in results
        if r.x is not None and r.y is not None and r.mag is not None
    ]
    if not valid_results:
        raise ValueError("No valid photometry results available for plotting")

    x = np.array([float(r.x) for r in valid_results], dtype=float)
    y = np.array([float(r.y) for r in valid_results], dtype=float)
    mag = np.array([float(r.mag) for r in valid_results], dtype=float)
    flux = np.array([float(r.flux) for r in valid_results], dtype=float)

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    img = axes[0].imshow(
        data,
        origin="lower",
        cmap="gray",
        vmin=np.nanpercentile(data, 2),
        vmax=np.nanpercentile(data, 98),
        interpolation="nearest",
    )
    fig.colorbar(img, ax=axes[0], label="counts")
    scatter = axes[0].scatter(
        x,
        y,
        c=mag,
        cmap="viridis_r",
        s=30,
        edgecolors="white",
        linewidths=0.5,
        alpha=0.9,
    )
    axes[0].set_title("FITS image with photometry sources")
    axes[0].set_xlabel("x")
    axes[0].set_ylabel("y")
    fig.colorbar(scatter, ax=axes[0], label=magnitude_label)

    bright_idx = np.argsort(mag)[: min(8, len(mag))]
    if len(bright_idx) > 0:
        axes[0].scatter(
            x[bright_idx],
            y[bright_idx],
            c="red",
            s=70,
            edgecolors="white",
            linewidths=0.8,
            alpha=0.95,
        )
        for idx, label in enumerate(bright_idx, start=1):
            axes[0].text(
                x[label],
                y[label],
                str(idx),
                color="white",
                fontsize=8,
                ha="center",
                va="center",
                bbox={"boxstyle": "round,pad=0.2", "facecolor": "black", "alpha": 0.55},
            )

    axes[1].hist(mag, bins=25, color="steelblue", edgecolor="black", alpha=0.9)
    axes[1].set_title(f"{magnitude_label} histogram")
    axes[1].set_xlabel(magnitude_label)
    axes[1].set_ylabel("number of sources")
    axes[1].grid(True, alpha=0.3)

    axes[2].scatter(mag, flux, c=flux, cmap="plasma", edgecolors="k", alpha=0.8)
    axes[2].invert_xaxis()
    axes[2].set_title("Photometry results")
    axes[2].set_xlabel(magnitude_label)
    axes[2].set_ylabel("flux")
    axes[2].grid(True, alpha=0.3)

    fig.suptitle(
        f"Detected {len(valid_results)} sources | median mag {np.median(mag):.3f} | median flux {np.median(flux):.1f}",
        y=0.98,
    )
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _replicate_zero_point_rejection(sources: Sequence[object]) -> np.ndarray:
    """Recover which calibration sources the zero-point solve's Chauvenet loop kept.

    ``algorithms.fieldcal.solution.calc_solution`` is a byte-preserved
    extraction from Skynet (see CLAUDE.md, "The extraction contract") and its
    public return is aggregate-only -- zero point, its error, scatter, limiting
    magnitude, and an overall rejection percentage. It never reports *which*
    sources survived, so there is nothing to read off for per-star plotting.

    Rather than change that extracted function's signature, this mirrors its
    iterative weighted-mean-plus-Chauvenet-rejection loop line for line (down
    to reusing its private `_sigma_eq` helper), adding only index bookkeeping
    to track which sources survive each round. Keep this in sync by hand if
    `calc_solution` ever changes.

    Returns a boolean array the same length as ``sources``, True where the
    source survived to the final solution.
    """
    from math import sqrt

    from scipy.optimize import brenth

    from algorithms.fieldcal.solution import _sigma_eq
    from algorithms.skylib_lite.util.stats import chauvenet

    n_total = len(sources)
    kept = np.ones(n_total, dtype=bool)
    if n_total == 0:
        return kept

    mag_arr, mag_error_arr, ref_mag_arr, ref_mag_error_arr = np.transpose([
        (
            source.mag,
            getattr(source, "mag_error", None) or 0,
            source.ref_mag,
            getattr(source, "ref_mag_error", None) or 0,
        )
        for source in sources
    ])
    orig_idx = np.arange(n_total)

    if mag_error_arr.any():
        good = mag_error_arr > 0
        mag_error_arr, ref_mag_error_arr = mag_error_arr[good], ref_mag_error_arr[good]
        ref_mag_arr = ref_mag_arr[good]
        orig_idx = orig_idx[good]
        b = ref_mag_arr - mag_arr[good]
    else:
        b = ref_mag_arr - mag_arr

    sigmas2 = mag_error_arr**2 + ref_mag_error_arr**2
    no_errors = not sigmas2.any()
    if no_errors:
        sigmas2 = 0
    sigma2 = 0
    weights = None

    while True:
        for _ in range(100):
            if no_errors:
                m0 = b.mean()
            else:
                m0 = (b / (sigmas2 + sigma2)).sum() / (1 / (sigmas2 + sigma2)).sum()

            prev_sigma2 = sigma2
            sigma2 = ((b - m0) ** 2).sum() / len(b)
            left, right = 0.9 * sigma2, 1.1 * sigma2
            for __ in range(100):
                if _sigma_eq(left, sigmas2, b, m0) * _sigma_eq(right, sigmas2, b, m0) < 0:
                    break
                left *= 0.9
                right *= 1.1
            try:
                sigma2 = brenth(_sigma_eq, left, right, (sigmas2, b, m0))
            except Exception:
                pass

            if len(b) < 2 or abs(sigma2 - prev_sigma2) < 1e-8:
                break

        if no_errors:
            denom = len(b) - 1
            sigma_override = sqrt(((b - m0) ** 2).sum() / denom) if denom > 0 else float("inf")
            rejected = chauvenet(b, mean_override=m0, sigma_override=sigma_override, max_iter=1)[0]
        else:
            weights = 1 / (sigmas2 + sigma2)
            sum_weights = weights.sum()
            sigma_override = sqrt(
                (weights * (b - m0) ** 2).sum() / (sum_weights - (weights**2).sum() / sum_weights)
            )
            rejected = chauvenet(b, mean_override=m0, sigma_override=sigma_override, max_iter=1)[0]

        if not rejected.any():
            break

        good = ~rejected
        b = b[good]
        orig_idx = orig_idx[good]
        if weights is not None:
            weights = weights[good]
        if not no_errors:
            sigmas2 = sigmas2[good]

    kept[:] = False
    kept[orig_idx] = True
    return kept


def plot_zero_point_solution(
    zero_point: ZeroPointResolution,
    output_path: Path,
) -> Path | None:
    """Save a zero-point calibration diagnostic plot.

    Two panels, both built from the calibration sources the field-cal solve
    actually used (``zero_point.calibration_sources``):

    - left: instrumental magnitude vs. catalog reference magnitude, with the
      solved zero-point line (``ref_mag = mag + zero_point``) overlaid. This
      is the interpolation the solve fit -- a fixed unit slope offset by the
      zero point, not a free two-parameter regression (see
      ``algorithms/fieldcal/solution.py::calc_solution``).
    - right: each star's residual from that fit (``ref_mag - mag -
      zero_point``) vs. instrumental magnitude, with the solved scatter
      (+/-1 sigma) shaded.

    In both panels, stars the solve's Chauvenet-rejection loop kept are blue;
    stars it rejected as outliers are red crosses (see
    ``_replicate_zero_point_rejection`` for how "rejected" is recovered, since
    ``calc_solution`` itself reports only an aggregate rejection percentage).

    Returns ``None`` (after a stderr message) if ``zero_point`` was not a
    verified field-cal solve, or carries fewer than 2 usable calibration
    sources -- there is nothing meaningful to plot from an unverified
    zero point (CLI override / FITS header) or an empty solve.
    """
    if not zero_point.verified or not zero_point.calibration_sources:
        print(
            "No field-calibration solve to plot a zero point for "
            f"(zero point source: {zero_point.source}).",
            file=sys.stderr,
        )
        return None

    sources = [
        s for s in zero_point.calibration_sources
        if s.mag is not None and s.ref_mag is not None
    ]
    if len(sources) < 2:
        print(
            "Fewer than 2 calibration sources with both an instrumental and "
            "reference magnitude; skipping the zero-point plot.",
            file=sys.stderr,
        )
        return None

    mag = np.array([float(s.mag) for s in sources])
    ref_mag = np.array([float(s.ref_mag) for s in sources])
    catalog_names = [getattr(s, "catalog_name", None) or "unknown" for s in sources]
    m0 = float(zero_point.value)
    diagnostics = zero_point.diagnostics or {}
    m0_error = diagnostics.get("zero_point_error_mag")
    sigma = diagnostics.get("zero_point_slop")

    kept = _replicate_zero_point_rejection(sources)
    resid = ref_mag - mag - m0

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    axes[0].scatter(
        mag[kept], ref_mag[kept],
        c="steelblue", s=35, edgecolors="k", linewidths=0.4, alpha=0.85,
        label=f"good fit ({int(kept.sum())})",
    )
    if (~kept).any():
        axes[0].scatter(
            mag[~kept], ref_mag[~kept],
            c="crimson", s=55, marker="x", linewidths=1.6,
            label=f"rejected outlier ({int((~kept).sum())})",
        )
    mag_range = np.array([mag.min(), mag.max()])
    axes[0].plot(
        mag_range, mag_range + m0,
        color="black", linestyle="--", linewidth=1.2,
        label=f"fit: ref_mag = mag + {m0:.3f}",
    )
    axes[0].set_xlabel("instrumental magnitude")
    axes[0].set_ylabel("catalog reference magnitude")
    axes[0].set_title("Zero-point interpolation")
    axes[0].legend(loc="best", fontsize=8)
    axes[0].grid(True, alpha=0.3)

    axes[1].axhline(0.0, color="black", linewidth=1.0)
    if sigma:
        axes[1].axhspan(-sigma, sigma, color="gray", alpha=0.15, label=f"±1σ ({sigma:.3f} mag)")
    axes[1].scatter(
        mag[kept], resid[kept],
        c="steelblue", s=35, edgecolors="k", linewidths=0.4, alpha=0.85,
        label="good fit",
    )
    if (~kept).any():
        axes[1].scatter(
            mag[~kept], resid[~kept],
            c="crimson", s=55, marker="x", linewidths=1.6,
            label="rejected outlier",
        )
    axes[1].set_xlabel("instrumental magnitude")
    axes[1].set_ylabel("residual (ref_mag − mag − zero_point)")
    axes[1].set_title("Zero-point residuals")
    axes[1].legend(loc="best", fontsize=8)
    axes[1].grid(True, alpha=0.3)

    catalog_counts = Counter(catalog_names)
    catalog_summary = ", ".join(
        f"{name} ({count})" for name, count in sorted(catalog_counts.items(), key=lambda kv: -kv[1])
    )
    title = f"zero point = {m0:.4f}"
    if m0_error is not None:
        title += f" ± {m0_error:.4f}"
    title += (
        f" mag  |  {len(sources)} calibration stars "
        f"({int(kept.sum())} kept, {int((~kept).sum())} rejected)  |  catalogs: {catalog_summary}"
    )
    fig.suptitle(title, fontsize=10, y=0.99)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def magnitude_label_for(zero_point: ZeroPointResolution) -> str:
    """Label magnitudes accurately: 'calibrated' only when independently verified."""
    if zero_point.value is None:
        return "instrumental magnitude"
    if zero_point.verified:
        return "calibrated magnitude"
    return "magnitude (unverified zero point applied)"


def compute_magnitude_stats(results: Sequence[object]) -> dict[str, float | int]:
    """Robust magnitude statistics over the complete result set.

    Uses the median and median absolute deviation (MAD) rather than the mean and
    standard deviation, so a handful of bad measurements can't distort the scale
    used to judge everything else. Always computed from every source with a
    valid magnitude — never a subsample — so any later "unusual" call is
    grounded in the full population.
    """
    mags = np.array([float(r.mag) for r in results if r.mag is not None], dtype=float)
    if mags.size == 0:
        return {"count": 0}
    median_mag = float(np.median(mags))
    mad = float(np.median(np.abs(mags - median_mag)))
    # 1.4826 scales MAD to be a consistent estimator of sigma for normal data.
    robust_sigma = mad * 1.4826 if mad > 0 else float(np.std(mags))
    return {
        "count": int(mags.size),
        "median_mag": median_mag,
        "robust_sigma_mag": robust_sigma,
        "min_mag": float(np.min(mags)),
        "max_mag": float(np.max(mags)),
    }


def find_magnitude_outliers(
    results: Sequence[object],
    stats: dict[str, float | int],
    n_sigma: float = 3.0,
) -> list[object]:
    """Sources more than ``n_sigma`` robust-sigma from the full-dataset median.

    Deliberately measured against ``stats`` (computed over every source) rather
    than any sample, and returns nothing if the dataset is too small or has no
    measurable scatter to compare against.
    """
    count = stats.get("count", 0)
    sigma = stats.get("robust_sigma_mag")
    if count < 5 or not sigma:
        return []
    median_mag = stats["median_mag"]
    outliers = [
        r for r in results
        if r.mag is not None and abs(float(r.mag) - median_mag) > n_sigma * sigma
    ]
    return sorted(outliers, key=lambda r: float(r.mag))


def calibration_quality_verdict(diagnostics: dict[str, float | int] | None) -> str:
    """Deterministic calibration-quality label from zero-point error and star count.

    Thresholds are a fixed, documented judgment call rather than another CLI
    knob, to keep this cheap: <0.02 mag error with >=20 stars is "GOOD",
    <0.05 mag with >=10 stars is "ACCEPTABLE", anything looser is "MARGINAL".
    """
    if not diagnostics:
        return "UNAVAILABLE (no verified calibration was performed)"
    error = diagnostics.get("zero_point_error_mag")
    stars = diagnostics.get("num_calibration_stars") or 0
    if error is not None and error < 0.02 and stars >= 20:
        return "GOOD"
    if error is not None and error < 0.05 and stars >= 10:
        return "ACCEPTABLE"
    return "MARGINAL (treat calibrated magnitudes with caution)"


def describe_extreme_source(result: object, label: str, snr_floor: float = 5.0) -> str:
    """One-line description of a brightest/faintest source with a grounded QA warning.

    The warning is only raised when an actual measured value crosses a
    threshold (sat_pixels>0, or flux/flux_error below snr_floor) -- never a
    blanket disclaimer.
    """
    line = f"{label}: mag={result.mag:.3f} flux={result.flux:.1f} at (x={result.x:.1f}, y={result.y:.1f})"
    if result.sat_pixels is not None and result.sat_pixels > 0:
        line += f" -- sat_pixels={result.sat_pixels}, inspect for saturation"
    elif result.flux is not None and result.flux_error:
        snr = result.flux / result.flux_error
        if snr < snr_floor:
            line += f" -- SNR={snr:.1f} (below {snr_floor:.0f}), inspect for low signal-to-noise"
    return line


def build_claude_prompt(
    fits_path: Path,
    results: Sequence[object],
    zero_point: ZeroPointResolution,
) -> str:
    stats = compute_magnitude_stats(results)
    outliers = find_magnitude_outliers(results, stats)

    if zero_point.value is None:
        mag_basis = (
            "Instrumental magnitudes only (mag = -2.5*log10(flux)). No photometric "
            "zero point was available, so these are NOT on a standard magnitude "
            "scale and cannot be compared to catalog or literature magnitudes."
        )
    elif zero_point.verified:
        diag = zero_point.diagnostics or {}
        mag_basis = (
            f"Calibrated magnitudes: a zero point of {zero_point.value:.4f} was solved "
            f"by this tool cross-matching detected sources against reference catalog(s) "
            f"({diag.get('catalogs_queried', 'unknown')}). Solve diagnostics: "
            f"zero-point error={diag.get('zero_point_error_mag')} mag, "
            f"{diag.get('num_calibration_stars')} calibration stars used, "
            f"{diag.get('rejection_percent')}% rejected during the solve."
        )
    else:
        origin = "a manual --zero-point override" if zero_point.source == "cli" else "the FITS header"
        mag_basis = (
            f"A zero point of {zero_point.value:.4f} was applied from {origin}, but this "
            "tool did not independently verify it against a catalog. Do not describe "
            "these magnitudes as 'calibrated' — describe them as magnitudes with an "
            "unverified zero point applied."
        )

    lines = [
        "You are summarizing the output of an automated aperture-photometry pipeline. "
        "Follow these rules strictly:",
        "1. State only what is directly supported by the numbers given below. Do not "
        "infer physical properties — temperature, spectral type, distance, mass, "
        "luminosity, physical size, or similar — that cannot be established from "
        "pixel position, flux, and magnitude alone.",
        "2. Distinguish three kinds of statements and label them accordingly: "
        "measured facts (position, flux, magnitude as reported), mathematical "
        "consequences (values derived from those measurements by a stated formula, "
        "e.g. a magnitude from flux and a zero point), and hypotheses (anything else, "
        "e.g. a source being noteworthy or unusual for the target type). Never "
        "present a hypothesis as an established fact.",
        f"3. {mag_basis}",
        "4. Do not identify any source as a cluster member, foreground/background "
        "star, or otherwise associate it with a specific population. This pipeline "
        "performs no proper-motion, radial-velocity, or density-based membership "
        "analysis, so there is no membership evidence available.",
        "5. When discussing unusually bright or faint sources, use only the "
        "full-dataset statistics and outlier list below — computed from all "
        f"{stats.get('count', 0)} sources with valid photometry, not a sample.",
        "",
        f"FITS file: {fits_path.name}",
        f"Total sources with valid photometry: {len(results)}",
    ]

    if zero_point.verified:
        lines.append(f"Calibration quality (computed, not your judgment): {calibration_quality_verdict(zero_point.diagnostics)}.")

    if stats.get("count", 0) > 0:
        lines.append(
            f"Full-dataset magnitude statistics: median={stats['median_mag']:.3f}, "
            f"robust scatter (MAD-based sigma)={stats['robust_sigma_mag']:.3f}, "
            f"min={stats['min_mag']:.3f}, max={stats['max_mag']:.3f}."
        )
        valid_mag_results = [r for r in results if r.mag is not None]
        brightest = min(valid_mag_results, key=lambda r: r.mag)
        faintest = max(valid_mag_results, key=lambda r: r.mag)
        lines.append(describe_extreme_source(brightest, "Brightest detected source"))
        lines.append(describe_extreme_source(faintest, "Faintest detected source"))
    else:
        lines.append("No sources have a valid magnitude; no statistics are available.")

    if outliers:
        lines.append(
            f"Sources more than 3 robust-sigma from the full-dataset median magnitude "
            f"({len(outliers)} of {stats.get('count', 0)}):"
        )
        for result in outliers[:20]:
            lines.append(
                f"  x={result.x:.2f}, y={result.y:.2f}, mag={result.mag:.3f}, flux={result.flux:.1f}"
            )
        if len(outliers) > 20:
            lines.append(f"  ... and {len(outliers) - 20} more.")
    else:
        lines.append("No sources exceed 3 robust-sigma from the full-dataset median magnitude.")

    lines.append(
        "Summarize these results using only the statistics and outliers listed above."
    )
    return "\n".join(lines)


def call_claude_haiku(prompt: str, model: str, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Please set ANTHROPIC_API_KEY in your environment to call Claude.")

    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()
    return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")


def summarize_results(results: Sequence[object], magnitude_label: str) -> str:
    mags = [float(r.mag) for r in results if r.mag is not None]
    fluxes = [float(r.flux) for r in results if r.flux is not None]
    if not mags or not fluxes:
        return "No numeric photometry statistics available."
    return (
        f"Photometry summary: {len(results)} sources, "
        f"median {magnitude_label} {np.median(mags):.3f}, "
        f"median flux {np.median(fluxes):.1f}."
    )


def main() -> int:
    args = parse_args()

    if args.list_targets:
        targets = list_bundled_targets()
        if not targets:
            print("No bundled FITS targets found under test_data/optical.", file=sys.stderr)
            return 1
        total = sum(len(stems) for stems in targets.values())
        print(f"{total} bundled FITS targets under test_data/optical:")
        for category, stems in targets.items():
            print(f"\n{category} ({len(stems)}):")
            for stem in stems:
                print(f"  {stem}")
        return 0

    if args.fits_path is None:
        print(
            "Missing FITS target. Pass a path or target name, or use --list-targets "
            "to see what's bundled under test_data/optical.",
            file=sys.stderr,
        )
        return 1

    try:
        fits_path = resolve_fits_path(args.fits_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.check_only:
        print(f"FOUND {fits_path}")
        return 0

    output_path = args.output or DEFAULT_OUTPUT_DIR / f"{fits_path.stem}_photometry.png"
    print(f"Loading FITS image from: {fits_path}")
    data, results, zero_point = compute_photometry(
        fits_path,
        zero_point_mag=args.zero_point,
        use_field_cal=not args.no_field_cal,
        catalogs=args.catalogs,
    )
    print(f"Detected {len(results)} sources.")

    magnitude_label = magnitude_label_for(zero_point)
    zero_point_source_text = {
        "cli": "the --zero-point override (unverified)",
        "header": "the FITS header (unverified)",
        "field-cal": "a live field-calibration catalog solve (verified)",
        "none": None,
    }[zero_point.source]
    if zero_point_source_text is not None:
        print(f"Photometric zero point resolved from: {zero_point_source_text}")
        if zero_point.verified and zero_point.diagnostics:
            diag = zero_point.diagnostics
            print(
                f"  zero-point error={diag.get('zero_point_error_mag')} mag, "
                f"{diag.get('num_calibration_stars')} calibration stars, "
                f"{diag.get('rejection_percent')}% rejected, "
                f"catalogs={diag.get('catalogs_queried')}"
            )
            print(f"  Calibration quality: {calibration_quality_verdict(diag)}")
    else:
        print(
            "No photometric zero point was available; magnitudes will be reported as instrumental only.",
            file=sys.stderr,
        )

    valid_mag_results = [r for r in results if r.mag is not None]
    if valid_mag_results:
        brightest = min(valid_mag_results, key=lambda r: r.mag)
        faintest = max(valid_mag_results, key=lambda r: r.mag)
        print(describe_extreme_source(brightest, "Brightest source"))
        print(describe_extreme_source(faintest, "Faintest source"))

    print(f"Saving photometry plot to: {output_path}")
    plot_photometry(data, results, output_path, magnitude_label=magnitude_label)
    print(summarize_results(results, magnitude_label))
    print(f"For a visual check, see the saved plot: {output_path}")

    if not args.no_zp_plot:
        zp_output_path = args.zp_plot_output or output_path.with_name(f"{output_path.stem}_zeropoint.png")
        zp_plot_saved = plot_zero_point_solution(zero_point, zp_output_path)
        if zp_plot_saved is not None:
            print(f"Saved zero-point calibration plot to: {zp_plot_saved}")

    if not args.no_claude:
        try:
            prompt = build_claude_prompt(fits_path, results, zero_point)
            print(f"Calling Claude model {args.model} for a summary...")
            summary = call_claude_haiku(prompt, args.model, args.max_tokens)
            print("\nClaude summary:\n" + summary)
        except Exception as exc:
            print(f"Claude API call failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

