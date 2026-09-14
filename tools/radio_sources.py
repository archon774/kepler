"""Kepler: radio FITS frame -> known-source identification -> labeled SED plot.

Replaces two non-functional scratch scripts (``Spectral_Plot.py``,
``Best_Fit_Analysis.py``) with one tool. The main deliverable is
``plot_field_sed``: identify what's actually in a processed radio FITS
frame by comparing detected sources against catalogs, then plot every
identified source's spectral energy distribution together on one labeled
plot, with each source's best-fit spectral model drawn and annotated --
"the best-fit analysis is for the spectral plot," not a separate step.

Three functions, the first two usable standalone, the third chaining them:

    identify_radio_sources    processed radio FITS -> detected sources,
                              cross-matched against VizieR radio catalogs by
                              position, so "what's actually in this field"
                              has a catalogued answer where one exists.
    analyze_source_spectrum   a named source (or an explicit frequency/flux
                              table) -> a fitted spectral index and a
                              flux-vs-frequency plot, for one source.
    plot_field_sed            the combined tool: runs identify_radio_sources
                              on a FITS frame, then analyze_source_spectrum's
                              NED lookup for every identified source, and
                              draws them all on one SED plot, each labeled
                              by name with its own fitted curve.

Source extraction reuses ``algorithms.photometry`` directly (the same two
calls ``algorithms/hrdiagram_py/observations.py`` and
``tools/photometry_pipeline.py`` each already make, with their own
settings) rather than importing either of those -- this domain needs neither
a Gaia handoff nor an optical zero-point solve: a calibrated radio map's
pixel values are already physical flux density, so magnitudes do not apply
here at all. The spectral half reuses ``tools.ned.search_ned``'s
already-homogenized ``Frequency``/``Flux Density`` photometry columns rather
than hand-parsing raw per-catalog VizieR flux columns, which differ in name
and unit from one radio survey to the next.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from astropy.io import fits
from astropy.table import Table
from astropy.wcs.utils import proj_plane_pixel_scales

from algorithms.hrdiagram_py.matching import field_footprint
from algorithms.photometry.photometry import run_photometry
from algorithms.photometry.schemas import PhotometrySettings, SourceExtractionSettings
from algorithms.photometry.source_extraction import build_wcs_from_header, run_source_extraction
from algorithms.radio import spectral_fitting
from algorithms.radio.matching import match_sources_to_catalog
from tools import artifacts
from tools.config import ARTIFACT_DIR, PREVIEW_ROWS
from tools.models import ArtifactRef, ToolResult
from tools.ned import search_ned
from tools.vizier import search_vizier

__all__ = ["identify_radio_sources", "analyze_source_spectrum", "plot_field_sed"]

#: plot_field_sed: how many identified sources (brightest first) to attempt
#: an SED for. Bounds how many NED lookups one call makes.
_DEFAULT_MAX_SED_SOURCES = 5

#: identify_radio_sources: field_footprint sizes its cone-search radius from
#: the detected sources' own angular spread, which is right for a compact
#: optical field but breaks down for a wide single-dish radio map -- a real
#: GreenBank 20m L-band scan tested here span roughly 20-24 degrees, giving a
#: computed radius near 14 degrees (850') and an effectively whole-sky VizieR
#: query that never returns in practical time. Cap it here, not in
#: algorithms.hrdiagram_py.matching.field_footprint (a shared, correct helper
#: whose assumptions are fine for its own, compact-field domain). Pass
#: max_field_radius_arcmin=None to search the true full extent anyway --
#: much slower, but sometimes wanted for a genuinely wide map.
_DEFAULT_MAX_FIELD_RADIUS_ARCMIN = 60.0

_SUBDIR = "radio"
#: NED's own "photometry" table has no band filter of its own -- this is the
#: conventional radio-continuum cutoff, same default tools.ned.search_ned's
#: own docstring recommends.
_RADIO_MAX_FREQUENCY_HZ = 3e11

#: Common per-catalog "what is this" columns, tried in order. Not
#: standardized across VizieR tables the way RA/Dec conventions roughly are
#: (see algorithms.radio.matching) -- this is a best-effort label only.
_NAME_COLUMNS = ["Name", "MAIN_ID", "ID", "_2MASS", "NVSS", "recno"]


class _NotFound(Exception):
    """A lookup came back empty -- an ordinary outcome, not a tool error."""


def _safe_stem(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "radio"


def _output_path(stem: str, suffix: str, output_dir: str | Path | None = None) -> Path:
    directory = Path(output_dir).expanduser().resolve() if output_dir else (ARTIFACT_DIR / _SUBDIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{_safe_stem(stem)}{suffix}"


def _write_df_artifact(df: pd.DataFrame, stem: str) -> ArtifactRef:
    return artifacts.write_table(Table.from_pandas(df), stem, subdir=_SUBDIR)


def _preview(df: pd.DataFrame) -> list[dict]:
    return df.head(PREVIEW_ROWS).to_dict(orient="records")


def _best_name(row: dict[str, Any]) -> str | None:
    for column in _NAME_COLUMNS:
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value)
    return None


#: A bare coordinate-style designation ("232325+584856") -- the native "Name"
#: for NVSS and several other radio surveys -- is not itself NED-resolvable.
_COORD_NAME_RE = re.compile(r"^\d{6,}\.?\d*[+-]\d{6,}\.?\d*$")


def _ned_lookup_candidates(raw_name: str) -> list[str]:
    """Names to try against NED for one matched-catalog name, in order.

    Confirmed live: NVSS's own bare coordinate-style name (e.g.
    ``"232325+584856"``) does not resolve, but its published designation
    convention (``"NVSS J232325+584856"``) does -- so a name matching that
    pattern is tried both as published and with the ``"NVSS J"`` prefix
    (the most common survey using this bare style). Any other name is
    typically already NED/SIMBAD-resolvable as published and is tried as-is.
    """
    if _COORD_NAME_RE.match(raw_name):
        return [f"NVSS J{raw_name}", raw_name]
    return [raw_name]


# ---------------------------------------------------------------------------
# 1. Radio FITS -> detected sources (position + raw flux, no magnitude system)
# ---------------------------------------------------------------------------
def _extract_radio_sources(fits_path: str, threshold: float = 3.0) -> pd.DataFrame:
    """Detect sources in a radio FITS map and return their sky position and
    aperture-summed flux.

    ``flux`` is a raw aperture sum over the map's own pixel values -- for a
    map already calibrated in Jy/beam this is proportional to flux density,
    but is not itself beam-corrected (this generic extractor has no beam
    solid angle to divide by). Good for position-based identification and
    relative brightness; for an absolute flux at a catalogued position, use
    the matched catalog's own reported value instead (see
    ``identify_radio_sources``).
    """
    with fits.open(fits_path) as hdul:
        header = hdul[0].header
        data = np.asarray(hdul[0].data, dtype=np.float64)

    wcs = build_wcs_from_header(header)
    if wcs is None:
        raise ValueError(
            f"{fits_path!r} has no celestial WCS in its header. Plate-solve/reproject "
            "the map first; this only measures positions and flux, it does not solve astrometry."
        )

    extraction_settings = SourceExtractionSettings(threshold=threshold)
    # "auto" (Kron-like, sized from each source's own detected extent) rather
    # than a fixed aperture radius tuned for stellar PSFs -- radio source
    # sizes vary far more than optical PSFs do (point sources to resolved lobes).
    photometry_settings = PhotometrySettings(mode="auto")
    sources, background, background_rms = run_source_extraction(
        data, header, extraction_settings,
    )
    results = run_photometry(
        data, header, sources, photometry_settings,
        wcs=wcs, background=background, background_rms=background_rms,
    )
    if not results:
        raise RuntimeError(f"No sources detected in {fits_path!r}")

    rows = [
        {
            "x": r.x,
            "y": r.y,
            "ra_deg": (r.ra_hours * 15.0) if r.ra_hours is not None else None,
            "dec_deg": r.dec_degs,
            "flux": r.flux,
            "flux_error": r.flux_error,
        }
        for r in results
    ]
    df = pd.DataFrame(rows).dropna(subset=["ra_deg", "dec_deg"]).reset_index(drop=True)
    # Carried via DataFrame.attrs (metadata, not a column) so identify_radio_sources
    # can size a pixel-scale-aware cross-match radius without reopening the FITS file.
    df.attrs["pixel_scale_arcsec"] = _pixel_scale_arcsec(wcs)
    return df


def _pixel_scale_arcsec(wcs) -> float | None:
    try:
        scales = np.abs(np.asarray(proj_plane_pixel_scales(wcs.celestial), dtype=float)) * 3600.0
        if len(scales) < 2 or not np.all(np.isfinite(scales[:2])):
            return None
        return float(np.mean(scales[:2]))
    except Exception:
        return None


def identify_radio_sources(
    fits_path: str,
    threshold: float = 3.0,
    radius_arcsec: float | None = None,
    category: str = "radio",
    max_catalogs: int | None = 5,
    max_field_radius_arcmin: float | None = _DEFAULT_MAX_FIELD_RADIUS_ARCMIN,
) -> ToolResult:
    """Detect sources in a processed radio FITS map and identify which ones
    have a known counterpart in VizieR's radio catalogs.

    One cone search over the whole field (not one per source) against
    ``category="radio"`` (NVSS, TGSS, VLSSr, SUMSS, GLEAM, and whatever else
    VizieR tags radio and has coverage there); each returned catalog's table
    is cross-matched against every detected source by position
    (``radius_arcsec``). A source matching no catalog is a real, ordinary
    outcome -- it does not make the overall result an error, since a field
    can genuinely contain uncatalogued sources.

    ``radius_arcsec`` (the per-source cross-match radius) defaults to
    ``max(15.0, 1.5 * pixel_scale_arcsec)`` when left ``None`` -- 15" assumes
    a fine, optical-like pixel scale; a coarse single-dish map (confirmed
    live: a GreenBank 20m L-band scan at ~122"/pixel) needs a radius at least
    comparable to one pixel or it can never match anything, regardless of
    whether a real catalogued source is right there.

    ``max_field_radius_arcmin`` caps the cone-search radius
    ``algorithms.hrdiagram_py.matching.field_footprint`` computes from the
    detected sources' own angular spread. That function sizes correctly for
    a compact optical field but not for a wide single-dish radio map --
    confirmed live, the same GreenBank scan above spans ~20-24 degrees,
    computing a ~14-degree search radius that turns into an effectively
    whole-sky VizieR query with no practical runtime. When the computed
    radius exceeds the cap, catalog coverage is centred on the field but
    limited to the capped radius (reported in ``warnings``, with how many
    degrees were actually requested) rather than hanging. Pass ``None`` to
    search the true full extent anyway.

    Returns one row per detected source in the artifact CSV: position, flux,
    how many catalogs matched, the nearest match's catalog/name/separation,
    and ``matched_names`` -- every distinct name found across *all* matched
    catalogs (``"; "``-joined), since the nearest match is not always the
    most identifiable one.
    """
    try:
        sources = _extract_radio_sources(fits_path, threshold=threshold)
    except ValueError as exc:
        return ToolResult(status="error", errors=[{"code": "invalid_input", "message": str(exc)}])
    except RuntimeError as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])

    if radius_arcsec is None:
        pixel_scale_arcsec = sources.attrs.get("pixel_scale_arcsec")
        radius_arcsec = max(15.0, 1.5 * pixel_scale_arcsec) if pixel_scale_arcsec else 15.0

    ra0, dec0, radius_deg = field_footprint(sources, pad_arcsec=radius_arcsec)
    field_capped = max_field_radius_arcmin is not None and radius_deg * 60.0 > max_field_radius_arcmin
    search_radius_arcmin = min(radius_deg * 60.0, max_field_radius_arcmin) if field_capped else radius_deg * 60.0

    catalog_result = search_vizier(
        ra_hours=ra0 / 15.0,
        dec_degs=dec0,
        radius_arcmin=search_radius_arcmin,
        category=category,
        max_catalogs=max_catalogs,
    )
    if catalog_result.status == "error":
        return ToolResult(status="error", errors=catalog_result.errors)

    n_matches = [0] * len(sources)
    best_match: list[tuple[float, str, dict] | None] = [None] * len(sources)
    # Every matched catalog's name, not just the astrometrically nearest one --
    # a source's nearest catalog match (e.g. NVSS, whose own name column is a
    # bare coordinate designation) is often not its most *identifiable* one
    # (e.g. a cross-ID catalog matched a little farther away but carrying the
    # object's common name). plot_field_sed tries all of these against NED in
    # order rather than committing to whichever matched closest.
    all_names: list[list[str]] = [[] for _ in range(len(sources))]

    if catalog_result.status in ("ok", "partial"):
        for artifact in catalog_result.artifacts:
            catalog_df = Table.read(artifact.path).to_pandas()
            catalog_label = Path(artifact.path).stem
            for match in match_sources_to_catalog(sources, catalog_df, radius_arcsec):
                position = sources.index.get_loc(match["source_index"])
                n_matches[position] += 1
                separation = match["separation_arcsec"]
                if best_match[position] is None or separation < best_match[position][0]:
                    best_match[position] = (separation, catalog_label, match["catalog_row"])
                name = _best_name(match["catalog_row"])
                if name and name not in all_names[position]:
                    all_names[position].append(name)

    sources = sources.copy()
    sources["n_catalog_matches"] = n_matches
    sources["best_match_catalog"] = [bm[1] if bm else None for bm in best_match]
    sources["best_match_name"] = [_best_name(bm[2]) if bm else None for bm in best_match]
    sources["best_match_separation_arcsec"] = [bm[0] if bm else None for bm in best_match]
    sources["matched_names"] = ["; ".join(names) if names else None for names in all_names]

    matched_count = sum(1 for n in n_matches if n > 0)
    artifact = _write_df_artifact(sources, f"{Path(fits_path).stem}_radio_sources")

    warnings = list(catalog_result.warnings)
    if field_capped:
        warnings.append(
            f"the detected sources span roughly {2 * radius_deg:.1f} degrees, wider than the "
            f"{max_field_radius_arcmin / 60.0:.1f}-degree search cap -- catalog coverage is "
            "centred on the field but limited to the cap, and may miss real matches for "
            "sources far from the centre. Pass max_field_radius_arcmin=None to search the "
            "full extent instead (much slower for a field this wide)."
        )
    warnings.append(
        f"{matched_count} / {len(sources)} detected sources matched at least one "
        f"catalog within {radius_arcsec:.1f}\""
    )

    return ToolResult(
        status="ok",
        count=len(sources),
        preview=_preview(sources),
        columns=list(sources.columns),
        artifact=artifact,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 2. A source's multi-frequency flux history -> fitted spectrum + plot
# ---------------------------------------------------------------------------
def _load_spectrum_csv(csv_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    df = pd.read_csv(csv_path)
    if df.shape[1] < 2:
        raise ValueError(f"{csv_path!r} needs at least two columns: frequency, flux")
    freq = df.iloc[:, 0].to_numpy(dtype=float)
    flux = df.iloc[:, 1].to_numpy(dtype=float)
    flux_err = df.iloc[:, 2].to_numpy(dtype=float) if df.shape[1] >= 3 else None
    return freq, flux, flux_err


def _load_spectrum_from_ned(name: str, max_frequency_hz: float) -> tuple[np.ndarray, np.ndarray, str]:
    result = search_ned(name, table="photometry", max_frequency_hz=max_frequency_hz)
    if result.status == "not_found":
        raise _NotFound(f"NED has no photometry for {name!r} below {max_frequency_hz:.3g} Hz")
    if result.status == "error":
        raise RuntimeError("; ".join(e.message for e in result.errors) or "search_ned failed")

    table = Table.read(result.artifact.path).to_pandas()
    table = table.dropna(subset=["Frequency", "Flux Density"])
    freq = table["Frequency"].to_numpy(dtype=float)
    flux = table["Flux Density"].to_numpy(dtype=float)
    if freq.size == 0:
        raise _NotFound(f"NED's photometry for {name!r} has no usable Frequency/Flux Density rows")
    return freq, flux, str(result.artifact.path)


def analyze_source_spectrum(
    name: str | None = None,
    csv_path: str | None = None,
    frequencies_hz: list[float] | None = None,
    fluxes_jy: list[float] | None = None,
    max_frequency_hz: float = _RADIO_MAX_FREQUENCY_HZ,
    output_dir: str | Path | None = None,
) -> ToolResult:
    """Fit and plot a source's flux-vs-frequency spectrum.

    Exactly one input is used, in this priority order: explicit
    ``frequencies_hz``/``fluxes_jy`` arrays, then ``csv_path`` (columns:
    frequency, flux[, flux error] -- any units, consistent across rows), then
    ``name`` resolved through NED's photometry table (homogenized units,
    filtered to ``max_frequency_hz`` -- the conventional radio-continuum
    cutoff). Fits both a pure power law (spectral index) and a log-parabola
    (spectral curvature); reports whichever the data actually supports (see
    ``algorithms.radio.spectral_fitting.analyze_spectrum``).

    Always writes one PNG (flux vs. frequency, log-log, fitted curve
    overlaid) to ``output_dir`` (default: the shared artifact directory).
    """
    source_label = name
    try:
        if frequencies_hz is not None and fluxes_jy is not None:
            freq = np.asarray(frequencies_hz, dtype=float)
            flux = np.asarray(fluxes_jy, dtype=float)
        elif csv_path is not None:
            freq, flux, _ = _load_spectrum_csv(csv_path)
            source_label = source_label or Path(csv_path).stem
        elif name is not None:
            freq, flux, _ = _load_spectrum_from_ned(name, max_frequency_hz)
        else:
            return ToolResult(
                status="error",
                errors=[{
                    "code": "invalid_input",
                    "message": "provide frequencies_hz+fluxes_jy, csv_path, or name",
                }],
            )
    except _NotFound as exc:
        return ToolResult(status="not_found", errors=[{"code": "invalid_input", "message": str(exc)}])
    except (RuntimeError, ValueError) as exc:
        return ToolResult(status="error", errors=[{"code": "provider_unavailable", "message": str(exc)}])

    try:
        fit = spectral_fitting.analyze_spectrum(freq, flux)
    except ValueError as exc:
        return ToolResult(status="error", errors=[{"code": "invalid_input", "message": str(exc)}])

    stem = _safe_stem(source_label or "spectrum")
    plot_path = _output_path(f"{stem}_spectrum", ".png", output_dir)
    _plot_spectrum(freq, flux, fit, plot_path, title=source_label)

    fit["source_name"] = source_label
    fit["n_points"] = fit["power_law"]["n_points"]
    return ToolResult(
        status="ok",
        count=1,
        preview=[fit],
        artifacts=[ArtifactRef(path=str(plot_path), format="png")],
    )


def _plot_spectrum(freq_hz: np.ndarray, flux: np.ndarray, fit: dict, path: Path,
                   title: str | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(freq_hz, flux, s=30, c="#33b3e6", zorder=3, label="Measured flux")

    freq_grid = np.logspace(np.log10(freq_hz.min()), np.log10(freq_hz.max()), 200)
    power_law = fit["power_law"]
    ax.plot(
        freq_grid,
        spectral_fitting.evaluate_power_law(freq_grid, power_law["amplitude"], power_law["spectral_index"]),
        color="#5b3fd6", lw=2, zorder=2,
        label=f"Power law (alpha={power_law['spectral_index']:.2f}, R2={power_law['r_squared']:.3f})",
    )
    if fit["log_parabola"] is not None:
        lp = fit["log_parabola"]
        ax.plot(
            freq_grid,
            spectral_fitting.evaluate_log_parabola(
                freq_grid, lp["curvature"], lp["spectral_index_at_ref"], lp["log_amplitude"]
            ),
            color="#e67e22", lw=2, ls="--", zorder=2,
            label=f"Log-parabola (R2={lp['r_squared']:.3f})",
        )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Flux density")
    ax.set_title(title or "Radio spectrum")
    ax.grid(alpha=0.15, which="both")
    ax.legend(loc="best", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 3. Combined: identify sources in a FITS frame, plot all their SEDs together
# ---------------------------------------------------------------------------
def plot_field_sed(
    fits_path: str,
    threshold: float = 3.0,
    radius_arcsec: float | None = None,
    category: str = "radio",
    max_catalogs: int | None = 5,
    max_sources: int = _DEFAULT_MAX_SED_SOURCES,
    max_frequency_hz: float = _RADIO_MAX_FREQUENCY_HZ,
    output_dir: str | Path | None = None,
    max_field_radius_arcmin: float | None = _DEFAULT_MAX_FIELD_RADIUS_ARCMIN,
) -> ToolResult:
    """Identify sources in a radio FITS frame and plot their spectral energy
    distributions together on one labeled SED plot.

    This is the combined tool: ``identify_radio_sources`` finds and names
    whatever in the frame has a catalogued counterpart; for each named source
    (brightest first, up to ``max_sources``), this fetches its multi-frequency
    flux history from NED and fits it exactly as ``analyze_source_spectrum``
    does. Every source that yields a usable spectrum is drawn together on one
    plot -- its own color, its own fitted curve, labeled by name -- rather
    than one plot per source, so the frame's known emission sources are
    visible and identified at a glance.

    ``radius_arcsec``/``max_field_radius_arcmin`` pass straight through to
    ``identify_radio_sources`` -- see its docstring for what each defaults to
    and why (a wide single-dish map needs both a coarser cross-match radius
    and a capped search field).

    A source with no catalogued name, or no usable NED photometry, is skipped
    and reported in ``warnings`` rather than failing the whole call -- some
    detected sources genuinely won't have either.
    """
    id_result = identify_radio_sources(
        fits_path, threshold=threshold, radius_arcsec=radius_arcsec,
        category=category, max_catalogs=max_catalogs,
        max_field_radius_arcmin=max_field_radius_arcmin,
    )
    if id_result.status != "ok":
        return id_result

    sources_df = Table.read(id_result.artifact.path).to_pandas()
    named = sources_df.dropna(subset=["matched_names"]).sort_values("flux", ascending=False)
    if named.empty:
        return ToolResult(
            status="not_found",
            errors=[{
                "code": "invalid_input",
                "message": "No detected source matched a named catalog entry to build an SED for.",
            }],
            warnings=id_result.warnings,
        )

    named = named.drop_duplicates(subset=["matched_names"])

    spectra: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    fits_by_source: dict[str, dict] = {}
    skipped: list[str] = []
    for _, row in named.iterrows():
        if len(spectra) >= max_sources:
            break

        # A source's astrometrically nearest catalog match is not always its
        # most identifiable one (e.g. NVSS's own bare coordinate name vs. a
        # cross-ID catalog matched a little farther away) -- try every
        # matched name, and every NED-resolvable form of each, before giving
        # up on this source.
        candidate_names = str(row["matched_names"]).split("; ")
        resolved: tuple[str, np.ndarray, np.ndarray, dict] | None = None
        last_error: Exception | None = None
        for candidate in candidate_names:
            for lookup_name in _ned_lookup_candidates(candidate):
                try:
                    freq, flux, _ = _load_spectrum_from_ned(lookup_name, max_frequency_hz)
                    fit = spectral_fitting.analyze_spectrum(freq, flux)
                except (_NotFound, RuntimeError, ValueError) as exc:
                    last_error = exc
                    continue
                resolved = (candidate, freq, flux, fit)
                break
            if resolved is not None:
                break

        if resolved is None:
            skipped.append(f"{candidate_names[0]}: {last_error}")
            continue

        source_name, freq, flux, fit = resolved
        fits_by_source[source_name] = fit
        spectra[source_name] = (freq, flux)

    if not spectra:
        return ToolResult(
            status="not_found",
            errors=[{
                "code": "provider_unavailable",
                "message": "None of the identified sources had usable NED photometry: "
                + "; ".join(skipped),
            }],
            warnings=id_result.warnings,
        )

    stem = Path(fits_path).stem
    plot_path = _output_path(f"{stem}_field_sed", ".png", output_dir)
    _plot_field_sed(spectra, fits_by_source, plot_path, title=f"SED -- {stem}")

    preview = [{"source_name": name, **fit} for name, fit in fits_by_source.items()]
    warnings = list(id_result.warnings)
    if skipped:
        warnings.append(f"{len(skipped)} identified source(s) skipped: " + "; ".join(skipped))

    return ToolResult(
        status="ok",
        count=len(spectra),
        preview=preview,
        artifacts=[ArtifactRef(path=str(plot_path), format="png")],
        warnings=warnings,
    )


_SED_COLORS = ["#33b3e6", "#e67e22", "#5b3fd6", "#2ecc71", "#e74c3c", "#f1c40f", "#1abc9c"]


def _plot_field_sed(
    spectra: dict[str, tuple[np.ndarray, np.ndarray]],
    fits_by_source: dict[str, dict],
    path: Path,
    title: str | None = None,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))

    for i, (source_name, (freq, flux)) in enumerate(spectra.items()):
        color = _SED_COLORS[i % len(_SED_COLORS)]
        fit = fits_by_source[source_name]
        power_law = fit["power_law"]
        ax.scatter(freq, flux, s=30, color=color, zorder=3)

        freq_grid = np.logspace(np.log10(freq.min()), np.log10(freq.max()), 200)
        curve = spectral_fitting.evaluate_power_law(
            freq_grid, power_law["amplitude"], power_law["spectral_index"]
        )
        ax.plot(
            freq_grid, curve, color=color, lw=2, zorder=2,
            label=f"{source_name} (alpha={power_law['spectral_index']:.2f})",
        )
        # Label the source directly on the plot, next to its faint-frequency
        # end -- the legend alone gets crowded past 3-4 sources.
        ax.annotate(
            source_name, xy=(freq_grid[-1], curve[-1]), xytext=(4, 0),
            textcoords="offset points", fontsize=8, color=color, va="center",
        )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Flux density")
    ax.set_title(title or "Field spectral energy distribution")
    ax.grid(alpha=0.15, which="both")
    ax.legend(loc="best", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
