"""Immutable, per-call outputs of astrometric WCS solving."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from astropy.wcs import WCS

from .schemas import CatalogSource


@dataclass(frozen=True)
class WcsSolveMetadata:
    """Scientific measurements produced while solving one FITS image.

    The ``search_*`` fields record the search the backends were asked to run
    — radius, scale window, and the pointing hint the radius was anchored on —
    so a caller can see whether a miss was an all-sky miss or a bounded one.
    They are filled on every path that reaches the backends, solution or not.
    astrometry.net searches the requested window verbatim; the ATLAS backend
    ignores the radius (its blind path always searches locally around the
    hint) and, unless the window was explicit, narrows it around the header's
    pixel-scale estimate — ``search_atlas_*`` is the window ATLAS was actually
    given, set only when that backend was attempted.
    """

    science_hdu_index: int | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    crpix1: float | None = None
    crpix2: float | None = None
    crval1: float | None = None
    crval2: float | None = None
    cdelt1: float | None = None
    cdelt2: float | None = None
    cd11: float | None = None
    cd12: float | None = None
    cd21: float | None = None
    cd22: float | None = None
    crota2: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    rotation_deg: float | None = None
    pixel_scale_arcsec_per_px: float | None = None
    mirrored: bool | None = None
    date_solved: datetime | None = None
    pointing_error_arcsec: float | None = None
    delta_ra_arcsec: float | None = None
    delta_dec_arcsec: float | None = None
    n_field: int = 0
    search_radius_deg: float | None = None
    search_min_scale_arcsec: float | None = None
    search_max_scale_arcsec: float | None = None
    search_center_ra_deg: float | None = None
    search_center_dec_deg: float | None = None
    search_atlas_min_scale_arcsec: float | None = None
    search_atlas_max_scale_arcsec: float | None = None


@dataclass(frozen=True)
class WcsSolveResult:
    """Accepted WCS, catalog rows, and measurements from one solve call."""

    wcs: WCS | None
    catalog_sources: tuple[CatalogSource, ...]
    metadata: WcsSolveMetadata


__all__ = ["WcsSolveMetadata", "WcsSolveResult"]
