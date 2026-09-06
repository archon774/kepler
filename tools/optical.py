"""Stage 0 for optical frames: find a FITS frame on local disk.

There is no archive query behind the image tools -- every stage takes a *file
path*, and a path only resolves if the frame is already here. This is the
discovery step, so a caller asked to work on a named object can find out what
is actually on hand instead of guessing a path or hitting a bare
FileNotFoundError.

Modelled directly on ``tools.pulsar``'s scan discovery: an env-overridable
data directory, punctuation-insensitive name matching, and ambiguity returned
as a candidate list with a ``ToolError`` rather than raised.

Reads only each file's primary header, so listing all 39 bundled frames does
not touch pixel data.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs.utils import proj_plane_pixel_scales

from algorithms.wcs.source_extraction import build_wcs_from_header
from tools.models import OpticalFrame, OpticalFrameList, ToolError, ToolWarning

__all__ = [
    "OPTICAL_DATA_DIR_ENV",
    "list_optical_frames",
    "resolve_optical_frame",
]

#: Where frames are looked for. Overridable so a caller with their own archive
#: does not have to move files into the repo.
OPTICAL_DATA_DIR_ENV = "KEPLER_OPTICAL_DATA_DIR"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _optical_data_dir() -> Path:
    from tools.config import env_path

    default = _REPO_ROOT / "test_data" / "optical"
    return env_path(OPTICAL_DATA_DIR_ENV, default) or default


def _normalize(name: str) -> str:
    """Reduce an object designation to comparable characters.

    ``NGC 5128``, ``ngc5128`` and ``NGC-5128`` all reduce to ``ngc5128``. The
    same reduction is applied to filename stems, so ``ngc5128_galaxy_b_001``
    contains ``ngc5128`` as a substring match.
    """
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


def _float(header, *keys: str) -> float | None:
    for key in keys:
        value = header.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _int(header, key: str) -> int | None:
    try:
        return int(header[key])
    except (KeyError, TypeError, ValueError):
        return None


def _summary(path: Path) -> OpticalFrame:
    """Read one frame's primary header without touching pixel data."""

    warnings: list[ToolWarning] = []
    errors: list[ToolError] = []
    try:
        header = fits.getheader(path)
    except Exception as exc:
        return OpticalFrame(
            path=str(path),
            errors=[ToolError(code="fits_header_error", message=str(exc))],
        )

    # test_data/optical is flat; the category is the second token of the stem,
    # per the <object>_<category>_<filter>_<seq> convention documented in
    # test_data/README.md.
    parts = Path(path).stem.split("_")
    category = parts[1] if len(parts) > 1 else None

    center_ra = center_dec = None
    scale = None
    wcs = build_wcs_from_header(header)
    if wcs is None:
        warnings.append(
            ToolWarning(
                code="no_celestial_wcs",
                message="FITS header does not contain a celestial WCS.",
            )
        )
    else:
        width = _int(header, "NAXIS1")
        height = _int(header, "NAXIS2")
        if width and height:
            try:
                ra_deg, dec_deg = wcs.all_pix2world(
                    (width + 1.0) / 2.0, (height + 1.0) / 2.0, 1
                )
                center_ra = float(ra_deg) % 360.0
                center_dec = float(dec_deg)
            except Exception:
                warnings.append(
                    ToolWarning(
                        code="wcs_projection_failed",
                        message="WCS present but the field centre could not be projected.",
                    )
                )
        try:
            scales = np.asarray(
                proj_plane_pixel_scales(wcs.celestial), dtype=float
            ) * 3600.0
            if len(scales) >= 2 and np.all(np.isfinite(scales[:2])):
                scale = abs(float(scales[0]))
        except Exception:
            pass

    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        size_bytes = None
        warnings.append(ToolWarning(code="stat_failed", message=str(exc)))

    return OpticalFrame(
        path=str(path),
        object_name=(str(header["OBJECT"]).strip() if "OBJECT" in header else None),
        category=category,
        image_filter=(str(header["FILTER"]).strip() if "FILTER" in header else None),
        telescope=(str(header["TELESCOP"]).strip() if "TELESCOP" in header else None),
        date_obs=(str(header["DATE-OBS"]).strip() if "DATE-OBS" in header else None),
        exposure_s=_float(header, "EXPTIME", "EXPOSURE"),
        width=_int(header, "NAXIS1"),
        height=_int(header, "NAXIS2"),
        has_wcs=wcs is not None,
        center_ra_deg=center_ra,
        center_dec_deg=center_dec,
        pixel_scale_arcsec=scale,
        size_bytes=size_bytes,
        warnings=warnings,
        errors=errors,
    )


def list_optical_frames(
    directory: str | Path | None = None, *, image_filter: str | None = None
) -> OpticalFrameList:
    """Stage 0. List the optical frames available on local disk.

    Pass ``image_filter`` to narrow to one FILTER value (case-insensitive).
    Reads headers only, so this stays cheap over the whole fixture set.
    """
    root = Path(directory).expanduser() if directory else _optical_data_dir()

    if not root.is_dir():
        return OpticalFrameList(
            frames=[],
            search_root=str(root),
            count=0,
            errors=[
                ToolError(
                    code="directory_not_found",
                    message=f"No optical data directory at {root}. Set "
                    f"{OPTICAL_DATA_DIR_ENV} to point at one.",
                )
            ],
        )

    frames = [_summary(p) for p in sorted(root.glob("*.fits")) if p.is_file()]
    if image_filter is not None:
        wanted = image_filter.strip().lower()
        frames = [f for f in frames if (f.image_filter or "").lower() == wanted]

    filters = sorted({f.image_filter for f in frames if f.image_filter})
    return OpticalFrameList(
        frames=frames, search_root=str(root), count=len(frames), filters=filters
    )


def resolve_optical_frame(
    name: str, directory: str | Path | None = None
) -> OpticalFrame | OpticalFrameList:
    """Stage 0. Find the frame for a name, stem, filename, or explicit path.

    Matching is on alphanumerics only, so ``NGC 5128``, ``ngc5128`` and
    ``NGC-5128`` are equivalent. A name that matches several frames -- which
    it will whenever a field was observed in more than one band -- returns an
    :class:`~tools.models.OpticalFrameList` of the candidates with an
    ``ambiguous`` error, so the caller chooses rather than the tool guessing.
    """
    root = Path(directory).expanduser() if directory else _optical_data_dir()

    direct = Path(name).expanduser()
    if direct.is_file():
        return _summary(direct)
    for candidate in (root / name, root / f"{name}.fits"):
        if candidate.is_file():
            return _summary(candidate)

    listing = list_optical_frames(root)
    if listing.errors:
        return listing

    wanted = _normalize(name)
    if not wanted:
        listing.errors.append(
            ToolError(code="invalid_input", message="name must not be blank")
        )
        return listing

    matches = [
        frame
        for frame in listing.frames
        if wanted in _normalize(Path(frame.path).stem)
        or wanted in _normalize(frame.object_name or "")
    ]

    if len(matches) == 1:
        return matches[0]

    if not matches:
        listing.errors.append(
            ToolError(
                code="not_found",
                message=f"No local frame matches {name!r}. "
                f"{listing.count} frames are available; call list_optical_frames "
                f"to see them.",
            )
        )
        return listing

    listing.frames = matches
    listing.count = len(matches)
    listing.filters = sorted({f.image_filter for f in matches if f.image_filter})
    listing.errors.append(
        ToolError(
            code="ambiguous",
            message=f"{name!r} matches {len(matches)} frames "
            f"({', '.join(sorted(set(f.image_filter or '?' for f in matches)))}); "
            f"pass a filename or narrow with image_filter.",
        )
    )
    return listing
