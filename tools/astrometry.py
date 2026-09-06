"""Astrometry tool wrappers."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs.utils import proj_plane_pixel_scales

from tools.artifacts import describe_file
from tools.models import ToolError, ToolWarning, WcsSummary
from algorithms.wcs.source_extraction import build_wcs_from_header


def _image_shape_from_header(header) -> tuple[int, int] | None:
    width = header.get("NAXIS1")
    height = header.get("NAXIS2")
    if width is None or height is None:
        return None
    try:
        return int(height), int(width)
    except Exception:
        return None


def _center_from_wcs(wcs, image_shape: tuple[int, int] | None) -> tuple[float | None, float | None]:
    if image_shape is not None:
        height, width = image_shape
        x = (width + 1.0) / 2.0
        y = (height + 1.0) / 2.0
    elif getattr(wcs, "pixel_shape", None):
        width, height = wcs.pixel_shape
        x = (float(width) + 1.0) / 2.0
        y = (float(height) + 1.0) / 2.0
    else:
        return None, None

    try:
        ra_deg, dec_deg = wcs.all_pix2world(x, y, 1)
        return float(ra_deg) % 360.0, float(dec_deg)
    except Exception:
        return None, None


def _pixel_scale_arcsec(wcs) -> tuple[float, float] | None:
    try:
        scales = np.asarray(proj_plane_pixel_scales(wcs.celestial), dtype=float) * 3600.0
        if len(scales) < 2 or not np.all(np.isfinite(scales[:2])):
            return None
        return abs(float(scales[0])), abs(float(scales[1]))
    except Exception:
        return None


def _rotation_deg(wcs) -> float | None:
    try:
        matrix = np.asarray(wcs.pixel_scale_matrix, dtype=float)
        if matrix.shape[0] < 2 or matrix.shape[1] < 2:
            return None
        return math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
    except Exception:
        return None


def describe_image_wcs(path: str | Path) -> WcsSummary:
    """Describe celestial WCS metadata in a FITS image header."""

    file = describe_file(path)
    errors: list[ToolError] = []
    warnings: list[ToolWarning] = []

    if not file.exists:
        errors.append(ToolError(code="file_not_found", message="FITS file does not exist."))
        return WcsSummary(file=file, has_wcs=False, errors=errors)
    if not file.is_file:
        errors.append(ToolError(code="not_a_file", message="Path is not a regular file."))
        return WcsSummary(file=file, has_wcs=False, errors=errors)

    try:
        header = fits.getheader(file.path)
    except Exception as exc:
        errors.append(ToolError(code="fits_header_error", message=str(exc)))
        return WcsSummary(file=file, has_wcs=False, errors=errors)

    image_shape = _image_shape_from_header(header)
    if image_shape is None:
        warnings.append(
            ToolWarning(code="missing_image_shape", message="FITS header has no usable NAXIS1/NAXIS2 image shape.")
        )

    wcs = build_wcs_from_header(header)
    if wcs is None:
        warnings.append(ToolWarning(code="no_celestial_wcs", message="FITS header does not contain a celestial WCS."))
        return WcsSummary(file=file, has_wcs=False, image_shape=image_shape, warnings=warnings)

    center_ra_deg, center_dec_deg = _center_from_wcs(wcs, image_shape)
    center_ra_hours = center_ra_deg / 15.0 if center_ra_deg is not None else None
    # ``wcs.wcs.ctype`` is an astropy ``StrListProxy`` on the installed
    # astropy version -- it supports integer indexing but not slicing
    # (``TypeError: sequence index must be integer, not 'slice'``).
    ctype = tuple(str(value) for value in list(wcs.wcs.ctype)[:2])

    return WcsSummary(
        file=file,
        has_wcs=True,
        image_shape=image_shape,
        ctype=ctype if len(ctype) == 2 else None,
        center_ra_deg=center_ra_deg,
        center_dec_deg=center_dec_deg,
        center_ra_hours=center_ra_hours,
        pixel_scale_arcsec=_pixel_scale_arcsec(wcs),
        rotation_deg=_rotation_deg(wcs),
        warnings=warnings,
    )
