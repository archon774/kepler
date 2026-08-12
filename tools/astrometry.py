"""Astrometry tool wrappers."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs.utils import proj_plane_pixel_scales

from tools.artifacts import describe_file
from tools.models import TargetPixelLocation, ToolError, ToolWarning, WcsSummary
from tools.resolve import resolve_target_coords
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
    # wcs.wcs.ctype is a StrListProxy, not a plain list -- list() first;
    # astropy 8.x's StrListProxy.__getitem__ rejects slice indices directly
    # (list(...)[:2] works since list()'s __iter__ path is unaffected).
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


def locate_target_in_image(
    path: str | Path,
    target_name: str | None = None,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
) -> TargetPixelLocation:
    """Where a target falls in one FITS frame's pixel grid, via the frame's
    own WCS (astropy.wcs -- i.e. WCSLIB, already the engine behind every
    sky<->pixel transform in this repo; there is no separate WCSLIB
    integration to add).

    Pass either `target_name` (resolved via SIMBAD, see tools.resolve) or
    `ra_deg`/`dec_deg` directly -- e.g. an ATNF pulsar position, which SIMBAD
    sometimes doesn't carry under the same name. Two uses this exists for:
    confirming a cluster is actually in-frame before running the (slow) HR-
    diagram extraction pipeline on it (see
    tools.hr_diagram.run_hr_diagram_pipeline), and locating a pulsar's sky
    position within an optical follow-up frame for targeted photometry of
    its counterpart, rather than searching the whole frame blind.
    """
    file = describe_file(path)
    errors: list[ToolError] = []
    warnings: list[ToolWarning] = []

    if not file.exists:
        errors.append(ToolError(code="file_not_found", message="FITS file does not exist."))
        return TargetPixelLocation(file=file, target_name=target_name, errors=errors)
    if not file.is_file:
        errors.append(ToolError(code="not_a_file", message="Path is not a regular file."))
        return TargetPixelLocation(file=file, target_name=target_name, errors=errors)

    resolved_name = target_name
    if ra_deg is None or dec_deg is None:
        if not target_name:
            errors.append(
                ToolError(code="invalid_input", message="Pass target_name, or both ra_deg and dec_deg.")
            )
            return TargetPixelLocation(file=file, target_name=target_name, errors=errors)
        resolved = resolve_target_coords(target_name)
        if resolved is None:
            errors.append(ToolError(code="not_found", message=f"{target_name!r} did not resolve via SIMBAD."))
            return TargetPixelLocation(file=file, target_name=target_name, errors=errors)
        ra_deg, dec_deg = resolved.ra_deg, resolved.dec_deg
        resolved_name = resolved.object_name

    try:
        header = fits.getheader(file.path)
    except Exception as exc:
        errors.append(ToolError(code="fits_header_error", message=str(exc)))
        return TargetPixelLocation(
            file=file, target_name=target_name, resolved_name=resolved_name,
            ra_deg=ra_deg, dec_deg=dec_deg, errors=errors,
        )

    image_shape = _image_shape_from_header(header)
    wcs = build_wcs_from_header(header)
    if wcs is None:
        errors.append(ToolError(code="no_celestial_wcs", message="FITS header does not contain a celestial WCS."))
        return TargetPixelLocation(
            file=file, target_name=target_name, resolved_name=resolved_name,
            ra_deg=ra_deg, dec_deg=dec_deg, image_shape=image_shape, errors=errors,
        )

    try:
        pixel_x, pixel_y = wcs.all_world2pix(ra_deg, dec_deg, 1)
        pixel_x, pixel_y = float(pixel_x), float(pixel_y)
    except Exception as exc:
        errors.append(ToolError(code="wcs_projection_error", message=str(exc)))
        return TargetPixelLocation(
            file=file, target_name=target_name, resolved_name=resolved_name,
            ra_deg=ra_deg, dec_deg=dec_deg, image_shape=image_shape, errors=errors,
        )

    in_bounds = None
    if image_shape is not None:
        height, width = image_shape
        in_bounds = (1.0 <= pixel_x <= width) and (1.0 <= pixel_y <= height)
        if not in_bounds:
            warnings.append(
                ToolWarning(
                    code="target_out_of_bounds",
                    message=f"({pixel_x:.1f}, {pixel_y:.1f}) falls outside the {width}x{height} image.",
                )
            )
    else:
        warnings.append(
            ToolWarning(code="missing_image_shape", message="No NAXIS1/NAXIS2 in header; in_bounds not determined.")
        )

    return TargetPixelLocation(
        file=file, target_name=target_name, resolved_name=resolved_name,
        ra_deg=ra_deg, dec_deg=dec_deg, pixel_x=pixel_x, pixel_y=pixel_y,
        in_bounds=in_bounds, image_shape=image_shape, warnings=warnings,
    )
