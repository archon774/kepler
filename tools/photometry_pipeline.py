"""Reusable FITS photometry and plotting pipeline for Kepler tools.

The registered ``tools.photometry`` wrapper imports this module to resolve
local FITS targets, extract sources, compute photometry, select a zero point,
and write plots. It deliberately contains no command-line entry point and no
model-provider client.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from matplotlib.patches import FancyBboxPatch, Polygon

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Retained for callers that choose an output path compatible with the retired
# standalone command-line interface. The pipeline itself never writes there.
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"

from algorithms.photometry.photometry import PhotometrySettings, run_photometry
from algorithms.photometry.schemas import SourceExtractionSettings
from algorithms.photometry.source_extraction import build_wcs_from_header, run_source_extraction


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
    from algorithms.fieldcal.field_cal import perform_field_calibration
    from algorithms.fieldcal.schemas import PhotometricCalibrationSettings
    from algorithms.query.selection import select_catalogs_for_filter

    from tools.photometry import _resolve_calibration_inputs

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
        catalog_sources, variable_sources, _ = _resolve_calibration_inputs(
            header,
            wcs,
            catalog_sources=None,
            catalogs=selected_catalogs,
            variable_check_tol=field_cal_settings.variable_check_tol,
        )
        outcome = perform_field_calibration(
            header,
            data,
            wcs=wcs,
            field_cal_settings=field_cal_settings,
            photometry_settings=photometry_settings,
            extraction_settings=extraction_settings,
            catalog_sources=catalog_sources,
            variable_sources=variable_sources,
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
    """Resolve a FITS path from an explicit path, a relative path, or a bundled target name.

    Delegates to ``tools.optical.resolve_optical_frame`` so the CLI and the
    registered tool cannot drift apart. The CLI contract is an exception on
    failure; the tool contract is a ToolError, so this translates.
    """
    from tools.optical import resolve_optical_frame

    query_path = Path(str(query))
    if query_path.is_absolute():
        if query_path.exists():
            return query_path.resolve()
        raise FileNotFoundError(f"FITS file '{query_path}' was not found locally.")

    for candidate in (query_path, ROOT / query_path):
        if candidate.exists():
            return candidate.resolve()

    result = resolve_optical_frame(str(query))
    if hasattr(result, "path"):
        return Path(result.path).resolve()
    raise FileNotFoundError(
        "; ".join(error.message for error in result.errors)
        or f"FITS file '{query}' was not found locally."
    )


def list_bundled_targets() -> dict[str, list[str]]:
    """Return the FITS target stems bundled locally, by category.

    Delegates to ``tools.optical`` for both the inventory and the category
    parse, so the CLI and the registered tools cannot drift apart. This is an
    index of filenames, not a header listing: it goes through
    ``bundled_frame_paths`` rather than ``list_optical_frames`` so it reads no
    headers and is never subject to ``KEPLER_MAX_FRAMES`` -- an index that
    advertises itself as the complete fixed set must not silently truncate.

    Scoped to the primary root on purpose. ``list_photometry_targets`` tells
    its caller this is a small fixed set of bundled frames with no archive
    behind it, so the archive download root is deliberately excluded -- a
    downloaded product has no category token to parse and a CASDA radio cube
    is not an optical photometry target. Downloaded frames stay reachable
    through ``list_optical_frames``/``resolve_optical_frame`` and by path.
    """
    from tools.optical import bundled_frame_paths, category_from_stem

    targets: dict[str, list[str]] = {}
    for path in bundled_frame_paths():
        targets.setdefault(category_from_stem(path) or "uncategorized", []).append(
            path.stem
        )
    return {category: sorted(stems) for category, stems in sorted(targets.items())}


#: Where --credits looks for the mentor's photo. Not bundled by default --
#: see docs/assets/README.md (or the tool's own message) for how to add one.
CREDITS_ASSET_PATH = ROOT / "docs" / "assets" / "danny_boi.png"

#: A second, purely decorative mentor photo -- a small corner easter egg on the
#: photometry plot itself, not the --credits card. Same as CREDITS_ASSET_PATH:
#: untracked by design, so its absence in another checkout is ordinary, not an
#: error -- _add_mentor_sidebar skips silently rather than raising.
SALAD_ASSET_PATH = ROOT / "docs" / "assets" / "salad.png"

#: Full joke text for the terminal. Deliberately fixed rather than randomized,
#: to keep --credits output (and any test of it) deterministic. No meta-
#: commentary calling out the slang as invented -- deliver it straight.
CREDITS_LINES = [
    "Dan Reichart once graded a problem set so fast that NASA called UNC to "
    "ask if he'd discovered a new form of faster-than-light causality. He "
    "said he'd get back to them after office hours.",
    "He teaches the UNC gen-ed known as \"the class that changes your life,\" "
    "which is just tenure-track phrasing for a recruitment pipeline with a "
    "syllabus and a curve nobody has ever seen the bottom of.",
    "Morehead Planetarium once tried to project the full night sky onto its "
    "dome while he was standing under it. The dome gave up halfway through "
    "and just displayed his aura instead -- no visible spectral lines, still "
    "hasn't been peer-reviewed, still brighter than Vega.",
    "He named a robotic telescope network Skynet, pointed it at galaxies "
    "billions of light-years away, and it is, to this day, not the most "
    "self-aware thing he has ever built. That title belongs to his email "
    "signature.",
    "A PROMPT telescope in Chile once tried to measure his parallax. It "
    "returned a division-by-zero error, because you cannot triangulate a "
    "baseline against a man with no opposite side.",
    "On the magnitude scale, brighter is a lower number. His number went "
    "negative so many times the IAU quietly stopped inviting him to vote on "
    "how the scale gets defined.",
    "Asked once whether he's a 6 or a 7, the universe returned both, then "
    "stopped returning numbers of any kind, permanently, out of respect.",
    "He is not measured in astronomical units. Astronomical units are "
    "measured in him, and the error bars are just everyone else's problem "
    "now.",
]

#: Short version for the rendered image card -- CREDITS_LINES is sized for a
#: terminal, not a caption under a photo.
CREDITS_CAPTION = "6-7 god. Uncalibratable. The IAU has given up."


def render_credits_card(output_path: Path, asset_path: Path = CREDITS_ASSET_PATH) -> Path | None:
    """Print the credits bit for this project's mentor, and render a photo card.

    Easter egg, not a pipeline feature -- always prints ``CREDITS_LINES`` to
    stdout. If ``asset_path`` (the mentor's photo) exists, also renders it into
    a captioned PNG at ``output_path`` and returns that path; if the photo
    hasn't been added yet, prints where to put it and returns ``None`` rather
    than failing -- this is a joke, not something worth crashing over.
    """
    print("=" * 60)
    for line in CREDITS_LINES:
        print(line)
    print("=" * 60)

    if not asset_path.exists():
        print(
            f"No photo found at {asset_path} -- skipping the image card. "
            "Save one there (mentor in a hard hat in front of a radio dish "
            "is the canon choice) to render it.",
            file=sys.stderr,
        )
        return None

    image = plt.imread(asset_path)
    fig, ax = plt.subplots(figsize=(7, 8.5))
    ax.imshow(image)
    ax.axis("off")
    ax.set_title("Dan Reichart", fontsize=18, fontweight="bold")
    fig.text(0.5, 0.03, CREDITS_CAPTION, ha="center", va="bottom", fontsize=11)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


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
    sources, background, background_rms = run_source_extraction(
        data, header, extraction_settings,
    )

    photometry_settings = PhotometrySettings(
        mode="aperture",
        a=5.0,
        a_in_px=8.0,
        a_out_px=12.0,
        zero_point_mag=effective_zero_point_mag if effective_zero_point_mag is not None else 0.0,
        # PARITY WITH THE SOLVE, NOT JUST THE UPSTREAM DEFAULT -- field_cal.py
        # forces apcorr_tol=0 (aperture correction off) for its own internal
        # photometry pass when solving `zero_point` against catalog stars (see
        # docs/extraction.md's apcorr_tol note and field_cal.py's own "LEGACY
        # AFTERGLOW PARITY -- DO NOT CLEAN UP" comment). A field-cal zero point
        # is therefore only valid on that same apcorr_tol=0 magnitude scale --
        # applying it here with the class default (apcorr_tol=1e-4, aperture
        # correction on) would silently bias every "calibrated" magnitude in
        # this run by the frame's own aperture-correction constant (confirmed
        # up to ~0.25 mag on bundled test frames -- far bigger than the
        # zero-point solve's own reported uncertainty). Only the field-cal
        # path needs this: a CLI override or header value was never solved
        # against a catalog in the first place, so there's no scale to match.
        apcorr_tol=0.0 if zero_point.source == "field-cal" else PhotometrySettings().apcorr_tol,
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


#: Fraction of figure height _add_mentor_sidebar's footer strip needs.
#: Callers reserve this via fig.tight_layout(rect=(0, MENTOR_SIDEBAR_HEIGHT,
#: 1, ...)) themselves -- see mentor_sidebar_rect below -- rather than this
#: module fighting an already-computed tight_layout with a later
#: subplots_adjust (which, with colorbars and an equal-aspect image axes
#: involved, was observed to reflow enough to clip a two-line title).
MENTOR_SIDEBAR_HEIGHT = 0.24


def mentor_sidebar_rect(asset_path: Path = SALAD_ASSET_PATH) -> tuple[float, float, float, float]:
    """The ``rect`` to pass ``fig.tight_layout()`` so its layout leaves room
    for ``_add_mentor_sidebar`` -- or the full figure, unchanged, when
    ``asset_path`` isn't present and no footer will be added.

    0.97 on top rather than 1.0 in both cases: a two-line plot title was
    observed to clip against the literal figure edge at 1.0 once colorbars
    were in the mix, regardless of the footer -- cheap, harmless headroom
    either way.
    """
    bottom = MENTOR_SIDEBAR_HEIGHT if asset_path.exists() else 0.0
    return (0.0, bottom, 1.0, 0.97)


def _add_mentor_sidebar(
    fig,
    asset_path: Path = SALAD_ASSET_PATH,
    caption: str = CREDITS_CAPTION,
) -> None:
    """Easter egg: the mentor's photo plus a speech-bubble caption, in a
    footer strip outside every plot axes on the figure -- never overlaid on
    the data itself.

    Call this only after laying out the figure's real content via
    ``fig.tight_layout(rect=mentor_sidebar_rect())`` -- that reserves the
    footer band this draws into; this function only fills it, and does not
    itself adjust any other axes' position.

    Silently does nothing if ``asset_path`` isn't present in this checkout --
    it's untracked by design (see SALAD_ASSET_PATH), so most clones won't
    have it, and that's an ordinary case, not something worth a warning on
    every photometry run.
    """
    if not asset_path.exists():
        return

    photo_ax = fig.add_axes((0.04, 0.03, 0.15, 0.17))
    photo_ax.imshow(plt.imread(asset_path))
    photo_ax.axis("off")
    for spine in photo_ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor("black")
        spine.set_linewidth(1.0)

    bubble_ax = fig.add_axes((0.205, 0.03, 0.34, 0.17))
    bubble_ax.set_xlim(0, 1)
    bubble_ax.set_ylim(0, 1)
    bubble_ax.axis("off")
    # Tail first, so the bubble body draws over the seam where it meets the
    # photo -- clip_on=False lets it reach left of this axes' own bounds,
    # into the gap toward photo_ax.
    bubble_ax.add_patch(
        Polygon(
            [(0.08, 0.62), (0.08, 0.40), (-0.12, 0.50)],
            closed=True,
            linewidth=1.1,
            edgecolor="black",
            facecolor="white",
            clip_on=False,
            zorder=1,
        )
    )
    bubble_ax.add_patch(
        FancyBboxPatch(
            (0.06, 0.12),
            0.88,
            0.76,
            boxstyle="round,pad=0.02,rounding_size=0.10",
            linewidth=1.1,
            edgecolor="black",
            facecolor="white",
            zorder=2,
        )
    )
    bubble_ax.text(
        0.5, 0.5, caption,
        ha="center", va="center", fontsize=9.5, wrap=True, zorder=3,
    )


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

    # A single panel now -- this used to be the leftmost third of a 1x3 figure
    # alongside a magnitude histogram and a mag/flux scatter, both dropped as
    # redundant with the per-source data already in the tool result. Sized and
    # scaled up (figure, markers, dpi) for its new role as the only plot,
    # rather than just stretching the old one-third-width panel.
    fig, ax = plt.subplots(figsize=(10, 8.5))
    img = ax.imshow(
        data,
        origin="lower",
        cmap="gray",
        vmin=np.nanpercentile(data, 2),
        vmax=np.nanpercentile(data, 98),
        interpolation="nearest",
    )
    fig.colorbar(img, ax=ax, label="counts", fraction=0.046, pad=0.04)
    scatter = ax.scatter(
        x,
        y,
        c=mag,
        cmap="viridis_r",
        s=40,
        edgecolors="white",
        linewidths=0.6,
        alpha=0.9,
    )
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    fig.colorbar(scatter, ax=ax, label=magnitude_label, fraction=0.046, pad=0.08)

    bright_idx = np.argsort(mag)[: min(8, len(mag))]
    if len(bright_idx) > 0:
        ax.scatter(
            x[bright_idx],
            y[bright_idx],
            c="red",
            s=90,
            edgecolors="white",
            linewidths=0.9,
            alpha=0.95,
        )
        for idx, label in enumerate(bright_idx, start=1):
            ax.text(
                x[label],
                y[label],
                str(idx),
                color="white",
                fontsize=9,
                ha="center",
                va="center",
                bbox={"boxstyle": "round,pad=0.2", "facecolor": "black", "alpha": 0.55},
            )

    ax.set_title(
        "FITS image with photometry sources\n"
        f"{len(valid_results)} sources | median {magnitude_label} {np.median(mag):.3f} "
        f"| median flux {np.median(flux):.1f}",
        fontsize=11,
    )
    fig.tight_layout(rect=mentor_sidebar_rect())
    _add_mentor_sidebar(fig, caption="Mmmm salad so yummers! :3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
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
    fig.tight_layout(rect=mentor_sidebar_rect())
    _add_mentor_sidebar(fig, caption="OMG girl love this cyclospora lettuce")
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
