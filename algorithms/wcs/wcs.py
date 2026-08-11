"""Astrometric WCS calibration pipeline."""

# EXTRACTED verbatim from Skynet:
#   packages/py/skynet-db/skynet_db/runners/observation_asset_processing/
#       optical_data_processing/wcs.py
# Only the import block below was rewritten (each change is marked `EXTRACTED:`).
# Every function body, constant, numeric expression and comment — including the
# legacy-Afterglow parity notes and the 2026-08-03 pointing-seed removal note —
# is unchanged. See EXTRACTION.md.

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

# EXTRACTED: the `skylib.astrometry.*` imports below were absolute imports of the
# installed skylib package. That package's astrometry stack is vendored under
# algorithms.skylib_lite. Nothing else changed.
from algorithms.skylib_lite.astrometry.main import (
    AstrometryNetConfig,
    AtlasBackend,
    AtlasConfig,
    Solution,
    SolveRequest,
)

try:
    from algorithms.skylib_lite.astrometry.anet import AstrometryNetError, SolveFieldTimeout
except ImportError:  # pragma: no cover - skylib predating the raising anet backend
    # Reachable when python-base.Dockerfile has not been rebuilt after a skylib
    # change. That older backend returns None instead of raising, so these
    # stand-ins keep the handlers below inert and the ATLAS fallback reachable.
    class AstrometryNetError(RuntimeError):
        pass

    class SolveFieldTimeout(AstrometryNetError):
        timeout_sec: float | None = None

from algorithms.skylib_lite.astrometry.anet.backend import (
    AstrometryNetBackend,
    solve_field_glob as anet_solve_field_glob,
)
from algorithms.skylib_lite.astrometry.atlas.catalog import get_catalog_spec
from algorithms.skylib_lite.util.fits import get_fits_exp_length, get_fits_time

# EXTRACTED: was `from skynet_db.config import settings` — a Dynaconf instance
# layered over the deployment's TOML config. See ./config.py; `build_anet_config`
# and `build_atlas_config` below read it only through `getattr(cfg, NAME, None)`.
from .config import settings
# EXTRACTED: was `from skynet_db.models import ObservationAssetProcessingRun` —
# a SQLAlchemy model. See ./state.py for the plain-object stand-in; the solve
# touches only `.observation_asset_id`, `.wcs_solution` and
# `.ensure_wcs_solution()`.
from .state import ProcessingRun as ObservationAssetProcessingRun
# EXTRACTED: was `from skynet_db.runners.common.schemas import ...` and
# `from skynet_sdk.schemas import PlateSolveSettings` — the WCS-related models
# from both are consolidated into ./schemas.py.
from .schemas import (
    CatalogSource,
    PlateSolveSettings,
    SourceExtractionSettings,
    WcsCalibrationSettings,
)
# EXTRACTED: was `from skynet_db.runners.utils import ...` — the two header-hint
# helpers are in ./header_utils.py.
from .header_utils import estimate_pixel_scale_arcsec_per_pix, guess_icrs_radec_from_header
from .source_extraction import build_wcs_from_header, get_source_xy, perform_source_extraction
# EXTRACTED: was `from ..common import now` (skynet_db.runners.
# observation_asset_processing.common) — a UTC `datetime.now`. See ./state.py.
from .state import now

logger = logging.getLogger(__name__)

WCS_REGEX = re.compile(
    r'^'
    r'(WCSAXES[A-Z]?)|'
    r'(CRVAL[1-9]\d?[A-Z]?)|'
    r'(CRPIX[1-9]\d?[A-Z]?)|'
    r'(PC[1-9]\d?_[1-9]\d?[A-Z]?)|'
    r'(CDELT[1-9]\d?[A-Z]?)|'
    r'(CD[1-9]\d?_[1-9]\d?[A-Z]?)|'
    r'(CTYPE[1-9]\d?[A-Z]?)|'
    r'(CUNIT[1-9]\d?[A-Z]?)|'
    r'(PV[1-9]\d?_\d\d?[A-Z]?)|'
    r'(PS[1-9]\d?_\d\d?[A-Z]?)|'
    r'(WCSNAME[A-Z]?)|'
    r'(CRDER[1-9]\d?[A-Z]?)|'
    r'(CSYER[1-9]\d?[A-Z]?)|'
    r'(CROTA[1-9]\d?)|'
    r'(LONPOLE[A-Z]?)|'
    r'(LATPOLE[A-Z]?)|'
    r'(RADESYS[A-Z]?)|'
    r'(C[PQ]DIS[1-9]\d?[A-Z]?)|'
    r'(D[PQ][1-9]\d?[A-Z]?)|'
    r'(C[PQ]ERR[1-9]\d?[A-Z]?)|'
    r'(DVERR[1-9]\d?[A-Z]?)|'
    r'([AB]P?_(ORDER|\d\d?_\d\d?)[A-Z]?)|'
    r'(WAT\d_\d\d\d)|'
    r'(AMD(RE)?[XY]\d\d?)|'
    r'(CNPIX[1-9]\d?)|'
    r'(PPO[1-9])|'
    r'([XY]PIXELSZ)|'
    r'(PLT((RA[HMS])|(DEC(SN|[DMS]))))|'
    r'$'
)

_OBS_TIME_KEYS = ("DATE-OBS", "MJD-OBS", "DATEREF", "MJDREFI", "MJDREFF")


# ---------------------------------------------------------------------------
# Header WCS builders
# ---------------------------------------------------------------------------

# build_wcs_from_header lives in .source_extraction (imported above) so a single
# canonical implementation serves both modules. It is re-exported here because
# .photometry imports it from this module.


def build_wcs_from_processing_run_solution(
        processing_run: ObservationAssetProcessingRun,
) -> WCS | None:
    """Build an Astropy WCS from the persisted processing-run WCS state.

    Observation asset processing stores astrometric solutions on the
    ``ObservationAssetProcessingRun`` rather than in Flask/global request
    state.  Some pipeline stages need the solved WCS before the FITS header is
    rewritten, so reconstruct the WCS directly from that run state.
    """
    solution = getattr(processing_run, "wcs_solution", None)
    if solution is None or not getattr(solution, "found_solution", None):
        return None

    required = (
        solution.crpix1,
        solution.crpix2,
        solution.crval1,
        solution.crval2,
        solution.cd11,
        solution.cd12,
        solution.cd21,
        solution.cd22,
    )
    if any(value is None for value in required):
        return None

    try:
        wcs = WCS(naxis=2)
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        wcs.wcs.crpix = [float(solution.crpix1), float(solution.crpix2)]
        wcs.wcs.crval = [float(solution.crval1) % 360.0, float(solution.crval2)]
        wcs.wcs.cd = np.array(
            [
                [float(solution.cd11), float(solution.cd12)],
                [float(solution.cd21), float(solution.cd22)],
            ],
            dtype=float,
        )
        if solution.width_px is not None and solution.height_px is not None:
            wcs.array_shape = (int(solution.height_px), int(solution.width_px))
        return wcs if wcs.has_celestial else None
    except Exception:
        logger.exception(
            "Failed to build WCS from processing run %s state",
            getattr(processing_run, "id", None),
        )
        return None


def build_wcs_for_processing_run(
        processing_run: ObservationAssetProcessingRun,
        header,
) -> WCS | None:
    """Return the WCS for this processing run.

    Tries the current FITS header first (preferred after a successful solve_wcs()
    call, which writes the accepted solution into the header).  Falls back to
    reconstructing from persisted processing-run DB state when the header has no
    celestial WCS.
    """
    return build_wcs_from_header(header) or build_wcs_from_processing_run_solution(processing_run)


# ---------------------------------------------------------------------------
# WCS matrix / parity helpers
# ---------------------------------------------------------------------------

def _wcs_matrix(wcs_obj: WCS) -> np.ndarray | None:
    """Return the effective 2×2 CD matrix for a WCS object, or None on failure."""
    try:
        wcs_p = wcs_obj.wcs
        if wcs_p.has_cd():
            return np.array(wcs_p.cd, dtype=float)
        return wcs_p.get_pc() @ np.diag([wcs_p.cdelt[0], wcs_p.cdelt[1]])
    except Exception:
        return None


def _wcs_det(wcs_obj: WCS) -> float | None:
    """Return the determinant of the effective CD matrix, or None if not computable."""
    cd = _wcs_matrix(wcs_obj)
    if cd is None:
        return None
    det = float(cd[0, 0] * cd[1, 1] - cd[0, 1] * cd[1, 0])
    return det if (math.isfinite(det) and det != 0.0) else None


def _wcs_parity(wcs_obj: WCS) -> bool | None:
    """Return True if det > 0, False if det < 0, None if indeterminate."""
    det = _wcs_det(wcs_obj)
    return None if det is None else (det > 0)


def _solve_request_parity_from_expected(expected_output_parity: bool | None) -> bool | None:
    """Map expected output parity (det sign) to SolveRequest.parity flag.

    Astrometry.net PARITY_NORMAL (request parity=True) yields det<0 output;
    PARITY_FLIP (request parity=False) yields det>0 output.  Invert here so
    that the caller works in terms of expected WCS determinant sign.
    """
    if expected_output_parity is None:
        return None
    return not expected_output_parity


# NOTE — the analysis-run pointing seed was REMOVED here (2026-08-03).
#
# `build_pointing_seed()` read `input_asset.current_analysis_run.pointing_solution`
# and handed that geometry to `solve_wcs` as a search prior ("move A"). It was the
# one hard read-coupling from the processing run to the analysis run's *active*
# measurement, and the recommended pipeline split
# (docs/internal/design/observations/ASSET_PIPELINE_RUN_REVIEW.md §3.1) removes
# the analysis solve outright — so the seed has no producer and the coupling has
# no basis. Processing now solves self-contained: hints come from the frame's own
# header WCS / FITS keywords, exactly as they did before move A.
#
# Consuming analysis *facts* (header_core, quality metrics) stays fine — that is
# what a descriptive run is for. Depending on analysis having *solved* is what
# does not. §3.5 leaves the door open to seeding from the QA run's solve instead;
# that needs a scheduler ordering (analysis → QA → processing) that does not
# exist today, so it is deliberately not wired. Git holds the removed mechanism.


def _angular_sep_deg(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    """Angular separation in degrees between two sky positions (haversine)."""
    ra1, dec1 = math.radians(ra1_deg), math.radians(dec1_deg)
    ra2, dec2 = math.radians(ra2_deg), math.radians(dec2_deg)
    dra, ddec = ra2 - ra1, dec2 - dec1
    a = math.sin(ddec / 2) ** 2 + math.cos(dec1) * math.cos(dec2) * math.sin(dra / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


def _accept_solution(
    wcs_obj: WCS,
    *,
    expected_parity: bool | None,
    ra_hint_deg: float | None,
    dec_hint_deg: float | None,
    width: int,
    height: int,
    max_sep_deg: float,
) -> tuple[bool, str | None]:
    """Validate an astrometric solution.  Returns (accepted, reason_if_rejected)."""
    if expected_parity is not None:
        result_parity = _wcs_parity(wcs_obj)
        if result_parity is not None and result_parity != expected_parity:
            return False, f"parity mismatch (expected {expected_parity}, got {result_parity})"

    if ra_hint_deg is not None and dec_hint_deg is not None:
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
        ra_result, dec_result = wcs_obj.all_pix2world(cx, cy, 0)
        ra_result = float(ra_result) % 360.0
        sep = _angular_sep_deg(ra_hint_deg, dec_hint_deg, ra_result, float(dec_result))
        if sep > max_sep_deg:
            return False, f"center {sep:.3f} deg from hint (max {max_sep_deg:.3f})"

    return True, None


# ---------------------------------------------------------------------------
# Header write-back
# ---------------------------------------------------------------------------

def _write_wcs_to_header(header: fits.Header, wcs_obj: WCS, *, solution=None) -> None:
    """Remove stale WCS keywords and write accepted solution into header in-place.

    Preserves observation-time keywords across the rewrite.
    """
    obs_time = {k: (header[k], header.comments[k]) for k in _OBS_TIME_KEYS if k in header}

    for key in list(header.keys()):
        if WCS_REGEX.match(key):
            del header[key]

    hist = "WCS calibration applied"
    if solution is not None:
        parts = []
        for attr, label in [("index_name", "index"), ("n_field", "n_field"), ("n_match", "n_match")]:
            val = getattr(solution, attr, None)
            if val is not None:
                parts.append(f"{label}={val}")
        if parts:
            hist += ": " + ", ".join(parts)
    header.add_history(hist)

    header.update(wcs_obj.to_header(relax=True))

    for k, (v, comment) in obs_time.items():
        header[k] = v
        if comment:
            header.comments[k] = comment


def _clear_wcs_solution_fields(wcs_solution) -> None:
    """Reset all astrometric fields so stale DB state is not visible after a failed solve."""
    wcs_solution.found_solution = 0
    for attr in (
        "crpix1", "crpix2", "crval1", "crval2",
        "cd11", "cd12", "cd21", "cd22",
        "ra", "dec", "pixel_scale", "crota2", "rotation", "mirrored",
        "cdelt1", "cdelt2", "pointing_error_arcsec", "delta_ra_deg", "delta_dec_deg", "date_solved",
    ):
        setattr(wcs_solution, attr, None)


# ---------------------------------------------------------------------------
# FITS keyword parsing helpers
# ---------------------------------------------------------------------------

def _parse_ra_hours(val) -> float | None:
    """Parse a FITS RA keyword to decimal hours.  Values > 24 are assumed degrees."""
    if val is None:
        return None
    try:
        r = float(val)
        return r / 15.0 if r > 24.0 else r
    except (TypeError, ValueError):
        pass
    if not isinstance(val, str):
        return None
    val = val.strip()
    for sep in (":", " "):
        parts = val.split(sep)
        if len(parts) == 3:
            try:
                h, m, s = parts
                return int(h.strip()) + int(m.strip()) / 60.0 + float(s.strip().replace(",", ".")) / 3600.0
            except Exception:
                continue
    return None


def _parse_dec_deg(val) -> float | None:
    """Parse a FITS Dec keyword to decimal degrees."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        pass
    if not isinstance(val, str):
        return None
    val = val.strip().replace("−", "-")
    for sep in (":", " "):
        parts = val.split(sep)
        if len(parts) == 3:
            try:
                d, m, s = parts
                d = d.strip()
                sign = -1 if d.startswith("-") else 1
                return sign * (abs(int(d)) + int(m.strip()) / 60.0 + float(s.strip().replace(",", ".")) / 3600.0)
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Backend config builders
# ---------------------------------------------------------------------------

def build_anet_config(cfg) -> AstrometryNetConfig | None:
    """Return an AstrometryNetConfig from application settings, or None if unconfigured.

    Passes index_path as-is (string or list) so the solver can load all index dirs.
    """
    index_path = getattr(cfg, "ANET_INDEX_PATH", None)
    if not index_path:
        logger.warning("ANET_INDEX_PATH not configured; astrometry.net backend disabled")
        return None
    return AstrometryNetConfig(index_path=index_path)


def build_atlas_config(cfg) -> AtlasConfig | None:
    """Return an AtlasConfig from application settings, or None if unconfigured."""
    catalog_root = getattr(cfg, "ATLAS_CATALOG_ROOT", None)
    if not catalog_root:
        return None
    catalog = (getattr(cfg, "ATLAS_CATALOG", None) or "ucac5").strip().lower()
    root = Path(str(catalog_root))
    # Normalize UCAC5 root: if path ends with "u5z", the loader expects its parent
    if catalog == "ucac5" and root.name.lower() == "u5z":
        root = root.parent

    timeout_raw = getattr(cfg, "ATLAS_TIMEOUT_S", None)
    try:
        timeout_s = float(timeout_raw) if timeout_raw else None
    except (TypeError, ValueError):
        logger.warning("ATLAS_TIMEOUT_S=%r is not a number; ignoring", timeout_raw)
        timeout_s = None

    return AtlasConfig(catalog=catalog, catalog_roots={catalog: root}, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# Atlas catalog loading helpers
# ---------------------------------------------------------------------------

def _gnomonic_projection(
        ra_deg: np.ndarray,
        dec_deg: np.ndarray,
        ra0_deg: float,
        dec0_deg: float,
) -> np.ndarray:
    ra = np.deg2rad(ra_deg)
    dec = np.deg2rad(dec_deg)
    ra0 = np.deg2rad(ra0_deg)
    dec0 = np.deg2rad(dec0_deg)
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / cosc
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / cosc
    return np.stack([xi, eta], axis=1)


def _limit_catalog_sources(
        ra_deg: np.ndarray,
        dec_deg: np.ndarray,
        *,
        ra0_deg: float,
        dec0_deg: float,
        max_catalog_stars: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(ra_deg) <= max_catalog_stars:
        return ra_deg, dec_deg
    cat_xy = _gnomonic_projection(ra_deg, dec_deg, ra0_deg, dec0_deg)
    order = np.argsort(np.hypot(cat_xy[:, 0], cat_xy[:, 1]))[:max_catalog_stars]
    return ra_deg[order], dec_deg[order]


def _load_atlas_catalog_sources(
        atlas_config: AtlasConfig,
        *,
        ra0_deg: float | None,
        dec0_deg: float | None,
        width: int,
        height: int,
        max_scale: float,
        file_id: int | None,
) -> list[CatalogSource]:
    if ra0_deg is None or dec0_deg is None:
        return []

    try:
        catalog_name, catalog_root = atlas_config.resolve_catalog()
    except Exception:
        logger.exception("Failed to resolve Atlas catalog configuration")
        return []

    try:
        catalog_index = get_catalog_spec(catalog_name).index_factory(catalog_root)
    except Exception:
        logger.exception("Failed to initialize Atlas catalog index for %s", catalog_name)
        return []

    if max_scale <= 0:
        return []

    fov_w = (max_scale * width) / 3600.0
    fov_h = (max_scale * height) / 3600.0
    half_diag = 0.5 * float(np.hypot(fov_w, fov_h)) * (1.0 + float(atlas_config.catalog_pad_frac))
    if half_diag <= 0:
        return []

    cos_dec = max(0.2, abs(float(np.cos(np.deg2rad(dec0_deg)))))
    ra_half = half_diag / cos_dec
    dec_half = half_diag

    try:
        cat = catalog_index.query_box(
            ra0_deg - ra_half, ra0_deg + ra_half,
            dec0_deg - dec_half, dec0_deg + dec_half,
            thin=atlas_config.thin,
        )
    except Exception:
        logger.exception("Failed to query Atlas catalog %s", catalog_name)
        return []

    if getattr(cat, "ra_deg", None) is None or cat.ra_deg.size == 0:
        return []

    ra_vals, dec_vals = cat.ra_deg, cat.dec_deg
    if atlas_config.max_catalog_stars and len(ra_vals) > atlas_config.max_catalog_stars:
        ra_vals, dec_vals = _limit_catalog_sources(
            ra_vals, dec_vals,
            ra0_deg=ra0_deg, dec0_deg=dec0_deg,
            max_catalog_stars=atlas_config.max_catalog_stars,
        )

    return [
        CatalogSource(
            catalog_name=catalog_name,
            file_id=file_id,
            ra_hours=float(ra) / 15.0,
            dec_degs=float(dec),
        )
        for ra, dec in zip(ra_vals, dec_vals)
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def solve_wcs(
        processing_run: ObservationAssetProcessingRun,
        header: fits.Header,
        data: np.ndarray,
        tmpdir: Path,
        pixel_scale_hint_arcsec: float | None = None,
        extraction_settings: SourceExtractionSettings | None = None,
        solve_settings: "PlateSolveSettings | None" = None,
) -> tuple[WCS | None, list[CatalogSource]]:

    file_id = getattr(processing_run, "observation_asset_id", None)

    wcs_settings = WcsCalibrationSettings()

    # The observer's plate-solve preferences (ASSET_PIPELINE_RUN_REVIEW.md §3.3).
    # Only the two knobs that shape the *written* WCS are exposed — SIP order and
    # where the reference pixel sits. Search radii, scale windows and source caps
    # stay internal: they are accuracy tuning, not a product choice, and an
    # observer narrowing the search would silently cause misses.
    if solve_settings is not None:
        wcs_settings.sip_order = solve_settings.sip_order
        wcs_settings.crpix_center = solve_settings.crpix_center

    if wcs_settings.ra_hours is not None and not 0 <= wcs_settings.ra_hours < 24:
        raise ValueError('wcs_settings.ra_hours', 'RA not within range [0,24)', 422)
    if wcs_settings.dec_degs is not None and not -90 <= wcs_settings.dec_degs <= 90:
        raise ValueError('wcs_settings.dec_degs', 'Dec not within range [-90,90]', 422)
    if wcs_settings.radius <= 0:
        raise ValueError('wcs_settings.radius', 'Field search radius must be positive', 422)
    if wcs_settings.min_scale >= wcs_settings.max_scale:
        raise ValueError('wcs_settings.min_scale', 'Minimum scale must be strictly less than maximum scale', 422)
    if wcs_settings.sip_order < 0:
        raise ValueError('wcs_settings.sip_order', 'SIP order must be non-negative', 422)
    if wcs_settings.max_sources is not None and wcs_settings.max_sources < 1:
        raise ValueError('wcs_settings.max_sources', 'Maximum number of sources must be positive', 422)

    extraction_settings = extraction_settings or SourceExtractionSettings()
    extraction_settings.discard_saturated = 0

    image = np.asarray(data, dtype=np.float32)
    width = int(header.get("NAXIS1", image.shape[1]))
    height = int(header.get("NAXIS2", image.shape[0]))

    sources, _, _ = perform_source_extraction(processing_run, header, data, settings=extraction_settings)

    if wcs_settings.max_sources and len(sources) > wcs_settings.max_sources:
        sources.sort(key=lambda s: s.flux or 0.0, reverse=True)
        sources = sources[:wcs_settings.max_sources]

    wcs_solution = processing_run.ensure_wcs_solution()
    atlas_catalog_sources: list[CatalogSource] = []

    # --- Coordinate hints ---
    # Priority: explicit settings → header WCS center → FITS keywords → ICRS
    # guess. Header WCS is used only when BOTH ra and dec are absent from
    # settings (mirrors legacy). Every hint comes from the frame itself — the
    # solve depends on no other run.
    ra_hint_hours: float | None = wcs_settings.ra_hours
    dec_hint_deg: float | None = wcs_settings.dec_degs

    # Build header WCS once for hints and expected parity
    header_wcs = build_wcs_from_header(header)

    if ra_hint_hours is None and dec_hint_deg is None and header_wcs is not None:
        ra_deg_c, dec_deg_c = header_wcs.all_pix2world((width - 1) / 2.0, (height - 1) / 2.0, 0)
        ra_hint_hours = float(ra_deg_c % 360) / 15.0
        dec_hint_deg = float(dec_deg_c)

    if ra_hint_hours is None and dec_hint_deg is None:
        for name in ("OBJRA", "TELRA", "RA"):
            if name in header:
                parsed = _parse_ra_hours(header[name])
                if parsed is not None:
                    ra_hint_hours = parsed
                    break
        for name in ("OBJDEC", "TELDEC", "DEC"):
            if name in header:
                parsed = _parse_dec_deg(header[name])
                if parsed is not None:
                    dec_hint_deg = parsed
                    break

    if ra_hint_hours is None and dec_hint_deg is None:
        try:
            ra_deg_g, dec_deg_g = guess_icrs_radec_from_header(header)
            if ra_deg_g is not None:
                ra_hint_hours = float(ra_deg_g % 360) / 15.0
            if dec_deg_g is not None:
                dec_hint_deg = float(dec_deg_g)
        except Exception:
            pass

    if ra_hint_hours is not None:
        ra_hint_hours = ra_hint_hours % 24.0
    ra_hint_deg: float | None = (ra_hint_hours * 15.0) if ra_hint_hours is not None else None

    # --- Parity ---
    expected_output_parity: bool | None = None
    if header_wcs is not None:
        expected_output_parity = _wcs_parity(header_wcs)

    # The two backends read SolveRequest.parity in *opposite* conventions:
    # astrometry.net's flag is inverted relative to the output determinant sign
    # (see _solve_request_parity_from_expected), while the ATLAS oriented path
    # takes it as the determinant sign directly. Derive one per backend.
    if wcs_settings.parity is not None:
        anet_request_parity = wcs_settings.parity
        atlas_request_parity = wcs_settings.parity
    else:
        anet_request_parity = _solve_request_parity_from_expected(expected_output_parity)
        atlas_request_parity = expected_output_parity

    # --- Search box ---
    # The WcsCalibrationSettings defaults (radius=180 → a true all-sky search).
    search_radius_deg = wcs_settings.radius
    anet_min_scale = wcs_settings.min_scale
    anet_max_scale = wcs_settings.max_scale

    logger.debug(
        "solve_wcs: file_id=%s hints=(ra_h=%s dec_d=%s) "
        "expected_parity=%s anet_parity=%s atlas_parity=%s",
        file_id, ra_hint_hours, dec_hint_deg,
        expected_output_parity, anet_request_parity, atlas_request_parity,
    )

    # --- Acceptance threshold ---
    _eff_scale = (
        pixel_scale_hint_arcsec
        or estimate_pixel_scale_arcsec_per_pix(header)
        or wcs_settings.max_scale
    )
    field_diag_deg = float(np.hypot(width, height)) * _eff_scale / 3600.0
    max_sep_deg = max(1.0, 3.0 * field_diag_deg)

    # --- Backend configs ---
    anet_config = build_anet_config(settings)
    atlas_config = build_atlas_config(settings)

    # Clean header for Atlas FITS input (strip stale WCS keywords)
    clean_header = header.copy()
    for key in list(clean_header.keys()):
        if WCS_REGEX.match(key):
            del clean_header[key]

    logger.info(
        "solve_wcs: file_id=%s sources=%d size=%dx%d "
        "ra_hint=%.4f dec_hint=%s max_sep_deg=%.2f radius=%.1f "
        "anet=%s atlas=%s",
        file_id, len(sources), width, height,
        ra_hint_hours or 0.0, dec_hint_deg,
        max_sep_deg, search_radius_deg,
        anet_config is not None, atlas_config is not None,
    )

    try:
        solution: Solution | None = None

        # --- astrometry.net ---
        if anet_config is not None and sources:
            if AstrometryNetBackend().is_available():
                texp = get_fits_exp_length(header)
                epoch = get_fits_time(header, texp)[1]
                positions: list[tuple[float, float]] = []
                flux_values: list[float] = []
                flux_valid = True
                for source in sources:
                    x, y = get_source_xy(source, epoch, None)
                    if x is None or y is None:
                        continue
                    positions.append((float(x), float(y)))
                    if source.flux is None:
                        flux_valid = False
                    else:
                        try:
                            flux_values.append(float(source.flux))
                        except Exception:
                            flux_valid = False

                if positions:
                    xy = np.array(positions)
                    flux = np.array(flux_values, dtype=float) if (flux_valid and flux_values) else None

                    request = SolveRequest(
                        xy=xy,
                        flux=flux,
                        width=width,
                        height=height,
                        ra_hours=ra_hint_hours,
                        dec_degs=dec_hint_deg,
                        radius=search_radius_deg,
                        min_scale=anet_min_scale,
                        max_scale=anet_max_scale,
                        parity=anet_request_parity,
                        sip_order=wcs_settings.sip_order,
                        crpix_center=wcs_settings.crpix_center,
                        max_sources=wcs_settings.max_sources,
                        retry_lost=wcs_settings.retry_lost,
                        image_path=None,
                        downsample=wcs_settings.downsample,
                    )

                    t0 = time.time()
                    try:
                        solution = anet_solve_field_glob(request, anet_config)
                    except SolveFieldTimeout as exc:
                        logger.warning(
                            "solve_wcs: anet timed out after %gs — "
                            "falling back to ATLAS (file_id=%s)",
                            exc.timeout_sec, file_id,
                        )
                        solution = None
                    except AstrometryNetError as exc:
                        logger.warning(
                            "solve_wcs: anet backend error — %s (file_id=%s)", exc, file_id
                        )
                        solution = None
                    elapsed = time.time() - t0

                    if solution and solution.wcs is not None:
                        accepted, reason = _accept_solution(
                            solution.wcs,
                            expected_parity=expected_output_parity,
                            ra_hint_deg=ra_hint_deg,
                            dec_hint_deg=dec_hint_deg,
                            width=width,
                            height=height,
                            max_sep_deg=max_sep_deg,
                        )
                        if accepted:
                            logger.info(
                                "solve_wcs: anet accepted in %.2fs — file_id=%s",
                                elapsed, file_id,
                            )
                        else:
                            logger.warning(
                                "solve_wcs: anet rejected — %s (file_id=%s)", reason, file_id
                            )
                            solution = None
                    else:
                        logger.info(
                            "solve_wcs: anet no solution in %.2fs — file_id=%s", elapsed, file_id
                        )
                else:
                    logger.info("solve_wcs: anet skipped — no valid source positions (file_id=%s)", file_id)
            else:
                logger.info("solve_wcs: anet backend not available (file_id=%s)", file_id)

        # --- Atlas fallback ---
        if (solution is None or solution.wcs is None) and atlas_config is not None:
            logger.info("solve_wcs: trying Atlas backend (file_id=%s)", file_id)
            atlas_backend = AtlasBackend()
            image_path = tmpdir / "skylib_atlas_input.fits"
            fits.writeto(image_path, image, header=clean_header, overwrite=True)

            # Narrow the scale window around the best available pixel-scale prior.
            # The full WcsCalibrationSettings range (default 0.1–60 arcsec/px) forces
            # exhaustive triangle search; with a hint the solver runs in seconds.
            _scale_hint = pixel_scale_hint_arcsec or estimate_pixel_scale_arcsec_per_pix(header)
            if _scale_hint and _scale_hint > 0:
                atlas_min_scale = max(wcs_settings.min_scale, _scale_hint * 0.5)
                atlas_max_scale = min(wcs_settings.max_scale, _scale_hint * 2.0)
            else:
                atlas_min_scale = wcs_settings.min_scale
                atlas_max_scale = wcs_settings.max_scale

            # No rotation prior: the ATLAS backend's fast *oriented* path needs a
            # verified orientation, which only a prior solve supplies. Processing
            # no longer consumes one (see the seed-removal note above), so this
            # stays None and the backend runs its general search.
            atlas_rotation_deg = None

            logger.info(
                "solve_wcs: Atlas scale range %.3f–%.3f arcsec/px "
                "(hint=%s, settings=%.1f–%.1f) rotation=%s (file_id=%s)",
                atlas_min_scale, atlas_max_scale, _scale_hint,
                wcs_settings.min_scale, wcs_settings.max_scale,
                atlas_rotation_deg, file_id,
            )

            request = SolveRequest(
                image_path=image_path,
                width=width,
                height=height,
                ra_hours=ra_hint_hours,
                dec_degs=dec_hint_deg,
                radius=search_radius_deg,
                min_scale=atlas_min_scale,
                max_scale=atlas_max_scale,
                parity=atlas_request_parity,
                rotation_deg=atlas_rotation_deg,
                crpix_center=wcs_settings.crpix_center,
            )

            t0 = time.time()
            solution = atlas_backend.solve(request, atlas_config)
            elapsed = time.time() - t0

            if solution and solution.wcs is not None:
                accepted, reason = _accept_solution(
                    solution.wcs,
                    expected_parity=expected_output_parity,
                    ra_hint_deg=ra_hint_deg,
                    dec_hint_deg=dec_hint_deg,
                    width=width,
                    height=height,
                    max_sep_deg=max_sep_deg,
                )
                if accepted:
                    logger.info(
                        "solve_wcs: Atlas accepted in %.2fs — file_id=%s", elapsed, file_id
                    )
                    atlas_catalog_sources = _load_atlas_catalog_sources(
                        atlas_config,
                        ra0_deg=ra_hint_deg,
                        dec0_deg=dec_hint_deg,
                        width=width,
                        height=height,
                        max_scale=wcs_settings.max_scale,
                        file_id=file_id,
                    )
                else:
                    logger.warning(
                        "solve_wcs: Atlas rejected — %s (file_id=%s)", reason, file_id
                    )
                    solution = None
            else:
                logger.info(
                    "solve_wcs: Atlas no solution in %.2fs — file_id=%s", elapsed, file_id
                )

    except Exception:
        logger.exception("Astrometric solution failed for file_id=%s", file_id)
        _clear_wcs_solution_fields(wcs_solution)
        wcs_solution.width_px = width
        wcs_solution.height_px = height
        wcs_solution.n_field = int(len(sources))
        return None, []

    wcs_solution.width_px = width
    wcs_solution.height_px = height
    wcs_solution.n_field = int(len(sources))

    if solution is None or solution.wcs is None:
        logger.warning("solve_wcs: no accepted solution (file_id=%s)", file_id)
        _clear_wcs_solution_fields(wcs_solution)
        wcs_solution.width_px = width
        wcs_solution.height_px = height
        wcs_solution.n_field = int(len(sources))
        return None, atlas_catalog_sources

    wcs_obj = solution.wcs
    wcs_params = wcs_obj.wcs
    wcs_solution.found_solution = 1
    wcs_solution.crpix1 = float(wcs_params.crpix[0])
    wcs_solution.crpix2 = float(wcs_params.crpix[1])
    wcs_solution.crval1 = float(wcs_params.crval[0])
    wcs_solution.crval2 = float(wcs_params.crval[1])

    if wcs_params.has_cd():
        A = wcs_params.cd
    else:
        A = wcs_params.get_pc() @ np.diag([wcs_params.cdelt[0], wcs_params.cdelt[1]])
    wcs_solution.cd11 = float(A[0, 0])
    wcs_solution.cd12 = float(A[0, 1])
    wcs_solution.cd21 = float(A[1, 0])
    wcs_solution.cd22 = float(A[1, 1])

    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    ra_c, dec_c = wcs_obj.all_pix2world(cx, cy, 0)
    ra = float(ra_c % 360.0)
    dec = float(dec_c)
    wcs_solution.ra_deg = ra
    wcs_solution.dec_deg = dec

    sx = float(np.hypot(A[0, 0], A[1, 0])) * 3600.0
    sy = float(np.hypot(A[0, 1], A[1, 1])) * 3600.0
    wcs_solution.pixel_scale_arcsec_per_px = 0.5 * (sx + sy)

    pa_x = np.degrees(np.arctan2(A[1, 0], A[0, 0]))
    pa_y = np.degrees(np.arctan2(-A[0, 1], A[1, 1]))
    if abs(pa_x - pa_y) > 90:
        if pa_x >= 90:
            pa_x -= 180
        if pa_y >= 90:
            pa_y -= 180
    wcs_solution.crota2 = float(0.5 * (pa_x + pa_y))
    wcs_solution.rotation_deg = float(180.0 - np.degrees(np.arctan2(A[0, 1], A[1, 1])))

    det = A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]
    wcs_solution.mirrored = int(det < 0)

    if wcs_params.has_cd():
        wcs_solution.cdelt1 = None
        wcs_solution.cdelt2 = None
    else:
        try:
            wcs_solution.cdelt1 = float(wcs_params.cdelt[0])
            wcs_solution.cdelt2 = float(wcs_params.cdelt[1])
        except Exception:
            wcs_solution.cdelt1 = None
            wcs_solution.cdelt2 = None

    wcs_solution.date_solved = now()

    if ra_hint_deg is not None and dec_hint_deg is not None:
        dra_deg = ((ra - ra_hint_deg + 180.0) % 360.0) - 180.0
        dra = dra_deg * math.cos(math.radians(dec))
        ddec = dec - dec_hint_deg
        wcs_solution.pointing_error_arcsec = math.hypot(dra * 3600.0, ddec * 3600.0)
        wcs_solution.delta_ra_deg = dra * 3600.0
        wcs_solution.delta_dec_deg = ddec * 3600.0

    logger.info(
        "solve_wcs: accepted — file_id=%s "
        "crval=(%.6f, %.6f) crpix=(%.2f, %.2f) "
        "cd=[[%.8f, %.8f], [%.8f, %.8f]] "
        "size=%dx%d scale=%.3f mirrored=%s",
        file_id,
        wcs_solution.crval1, wcs_solution.crval2,
        wcs_solution.crpix1, wcs_solution.crpix2,
        wcs_solution.cd11, wcs_solution.cd12,
        wcs_solution.cd21, wcs_solution.cd22,
        width, height,
        wcs_solution.pixel_scale_arcsec_per_px, bool(wcs_solution.mirrored),
    )

    _write_wcs_to_header(header, wcs_obj, solution=solution)

    return wcs_obj, atlas_catalog_sources
