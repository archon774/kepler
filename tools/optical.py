"""Stage 0 for optical frames: find a FITS frame on local disk.

There is no archive query behind the image tools -- every stage takes a *file
path*, and a path only resolves if the frame is already here. This is the
discovery step, so a caller asked to work on a named object can find out what
is actually on hand instead of guessing a path or hitting a bare
FileNotFoundError.

Modelled directly on ``tools.pulsar``'s scan discovery: an env-overridable
data directory, punctuation-insensitive name matching, and ambiguity returned
as a candidate list with a ``ToolError`` rather than raised.

Two directories are searched: the bundled optical directory (or the
``KEPLER_OPTICAL_DATA_DIR`` override), and the archive download directory
``tools.mast``/``tools.casda`` write into, once anything has been downloaded
there. That second root is what joins **find data -> measure -> calibrate**:
before it, a downloaded product was invisible to every tool that resolves a
frame through this module (BL-11).

Reads only each file's primary header, so listing all 39 bundled frames does
not touch pixel data.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs.utils import proj_plane_pixel_scales

from algorithms.wcs.source_extraction import build_wcs_from_header
from tools.models import OpticalFrame, OpticalFrameList, ToolError, ToolWarning

__all__ = [
    "OPTICAL_DATA_DIR_ENV",
    "bundled_frame_paths",
    "list_optical_frames",
    "primary_optical_data_dir",
    "resolve_optical_frame",
]

#: Where frames are looked for. Overridable so a caller with their own archive
#: does not have to move files into the repo.
OPTICAL_DATA_DIR_ENV = "KEPLER_OPTICAL_DATA_DIR"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def primary_optical_data_dir() -> Path:
    """The bundled/override root alone, excluding the archive download root.

    Public because a caller whose contract is "a fixed, bundled set" has to be
    able to say so -- ``list_photometry_targets`` advertises exactly that, and
    would otherwise start offering archive downloads as bundled targets.

    Defaults under the repository's own ``data/`` rather than under
    ``config.DATA_DIR``. Out of the box those are the same directory; they part
    company only when an operator sets ``KEPLER_DATA_DIR``, and that override
    is about where downloads land and how far a recursive search may walk --
    not about relocating the bundled frame library. Relocating the library is
    what ``KEPLER_OPTICAL_DATA_DIR`` is for.
    """
    from tools.config import env_path

    default = _REPO_ROOT / "data" / "optical"
    return env_path(OPTICAL_DATA_DIR_ENV, default) or default


def bundled_frame_paths() -> list[Path]:
    """Every ``*.fits`` directly under the primary root, sorted, uncapped.

    For callers that want the *inventory* of the bundled library and nothing
    from the headers -- ``list_bundled_targets`` groups stems by the category
    token in the filename. Going through :func:`list_optical_frames` for that
    would read every header and, past ``KEPLER_MAX_FRAMES``, silently truncate
    an index that advertises itself as the complete fixed set.
    """
    root = primary_optical_data_dir()
    if not root.is_dir():
        return []
    paths, _ = _iter_fits([(root, False)], None)
    return paths


def _optical_data_roots() -> tuple[list[tuple[Path, bool]], list[ToolWarning]]:
    """Every directory a frame may live in, primary first, each with whether
    it is searched recursively, plus any warning about how it is searched.

    The second root is the archive download directory ``tools.mast`` and
    ``tools.casda`` write into. Without it a downloaded product was invisible
    to the registry every image tool resolves through, so ``search_mast(...,
    download=True)`` dead-ended at the file it had just fetched (BL-11).

    It is recursive because astroquery does not write products flat: MAST
    products land under ``mastDownload/<mission>/<obs_id>/``. The primary root
    stays non-recursive -- ``data/optical`` is flat, and so is the
    caller-supplied archive ``KEPLER_OPTICAL_DATA_DIR`` names.

    **Recursion is bounded by the data directory.** A recursive walk is only
    safe while it is confined to a tree that holds astronomy data and nothing
    else, and ``KEPLER_FITS_DOWNLOAD_DIR`` can name anywhere -- a home
    directory, a mount point, ``/``. So the download root is walked only when
    it resolves inside ``config.DATA_DIR``; outside it, the directory is still
    searched, but flat, and the listing says so. Downgrading rather than
    refusing keeps a flat download root working, which is what CASDA's
    ``download_files`` produces.

    ``tools.config`` values are read through the module rather than bound at
    import so a caller that reassigns them is honoured, matching how
    ``tools.artifacts.ARTIFACT_DIR`` is already overridden.
    """
    from tools import config

    warnings: list[ToolWarning] = []
    roots: list[tuple[Path, bool]] = [(primary_optical_data_dir(), False)]
    download_dir = config.FITS_DOWNLOAD_DIR
    if download_dir is not None:
        download_root = Path(download_dir).expanduser()
        data_dir = Path(config.DATA_DIR).expanduser()
        recursive = config.within(download_root, data_dir)
        # Only a root that exists earns the warning: an absent download root is
        # skipped by the lister without comment, and telling a caller that a
        # directory which is not searched at all "is searched flat" is wrong.
        if not recursive and download_root.is_dir():
            warnings.append(
                ToolWarning(
                    code="download_root_outside_data_dir",
                    message=(
                        f"{download_root} is outside the data directory "
                        f"{data_dir}, so it is searched flat rather than "
                        "walked. Products nested under "
                        "mastDownload/<mission>/<obs_id>/ will not be listed; "
                        f"point {config.FITS_DOWNLOAD_DIR_ENV} inside the data "
                        f"directory, or set {config.DATA_DIR_ENV} to a root "
                        "that covers it."
                    ),
                )
            )
        roots.append((download_root, recursive))

        # The download root used to default to a working-directory-relative
        # "fits_downloads", which for a developer running from the repository
        # root meant <repo>/fits_downloads. It now defaults under data/. A
        # non-empty directory at the old default is almost certainly earlier
        # downloads that this search no longer sees; say so rather than let
        # them resolve as not_found with no hint that the root moved.
        legacy = _REPO_ROOT / "fits_downloads"
        if (
            legacy.is_dir()
            and config.safe_resolve(legacy) != config.safe_resolve(download_root)
            and any(legacy.iterdir())
        ):
            warnings.append(
                ToolWarning(
                    code="legacy_download_root_present",
                    message=(
                        f"{legacy} exists and is not empty, but the archive "
                        f"download root is now {download_root} and this search "
                        "does not look in the old location. Move its contents "
                        f"under {download_root}, or point "
                        f"{config.FITS_DOWNLOAD_DIR_ENV} at it."
                    ),
                )
            )

    # One entry per distinct directory. Both env vars can name the same place,
    # and reporting it twice in search_roots reads as a bug. Recursion is OR-ed
    # rather than taken from the first entry: collapsing to the primary root's
    # flat search would silently stop finding nested downloads.
    collapsed: list[tuple[Path, bool]] = []
    index: dict[Path, int] = {}
    for root, recursive in roots:
        key = config.safe_resolve(root)
        if key in index:
            existing_root, existing_recursive = collapsed[index[key]]
            collapsed[index[key]] = (existing_root, existing_recursive or recursive)
            continue
        index[key] = len(collapsed)
        collapsed.append((root, recursive))
    return collapsed, warnings


def _resolve_roots(
    directory: str | Path | None,
) -> tuple[list[tuple[Path, bool]], list[ToolWarning]]:
    """An explicit ``directory`` means exactly that one directory, flat.

    Falsy rather than ``is not None``, matching the single-root code this
    replaced: ``Path("")`` is ``Path(".")``, so treating an empty string as an
    explicit choice would silently search the working directory instead of
    falling back to the default roots. A model filling in an optional string
    parameter is exactly where that arrives.
    """
    if directory:
        return [(Path(directory).expanduser(), False)], []
    return _optical_data_roots()


def _iter_fits(
    roots: list[tuple[Path, bool]], limit: int | None
) -> tuple[list[Path], int]:
    """Frames across every root, primary first, each file listed once.

    Returns at most ``limit`` paths *per root* together with how many were
    found in total, so the caller can say it truncated instead of silently
    dropping frames. The cap is per root rather than overall because the
    roots are ordered primary-first: an operator archive holding more than the
    cap would otherwise fill it entirely, and no archive download could ever
    be listed or resolved by name -- BL-11 again, quietly.

    Nothing stops a caller pointing ``KEPLER_OPTICAL_DATA_DIR`` and
    ``KEPLER_FITS_DOWNLOAD_DIR`` at the same directory, or nesting one inside
    the other, so identity is the file's ``(st_dev, st_ino)`` rather than the
    root it came from -- one ``stat`` per file, which also answers "is it a
    regular file". Resolving every path instead was a multi-syscall chain per
    file on exactly the hundred-thousand-product trees the cap exists for.

    The cap bounds the expensive half of a listing -- one FITS header read per
    frame, and one serialised summary per frame into a model's context. It does
    not bound the directory walk itself, which has to complete for the ordering
    to be deterministic; that walk is bounded instead by confining recursion to
    the data directory (see :func:`_optical_data_roots`).
    """
    paths: list[Path] = []
    seen: set[tuple[int, int]] = set()
    found = 0
    for root, recursive in roots:
        matches = root.rglob("*.fits") if recursive else root.glob("*.fits")
        kept_here = 0
        for path in sorted(matches):
            try:
                st = path.stat()
            except OSError:  # broken symlink, unreadable mount
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            found += 1
            if limit is None or kept_here < limit:
                paths.append(path)
                kept_here += 1
    return paths, found


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


def category_from_stem(path: str | Path) -> str | None:
    """The category token of a bundled frame's filename, or ``None``.

    data/optical is flat and its frames are named
    ``<object>_<category>_<filter>_<seq>`` (data/README.md), so the category
    is the second token of the stem. Shared with ``list_bundled_targets`` so
    the two cannot parse the convention differently.
    """
    parts = Path(path).stem.split("_")
    return parts[1] if len(parts) > 1 else None


def _summary(path: Path) -> OpticalFrame:
    """Read one frame's primary header without touching pixel data."""

    from tools import config

    warnings: list[ToolWarning] = []
    errors: list[ToolError] = []
    if config.is_lfs_pointer(path):
        # Reached when a caller names an unfetched frame directly; the listing
        # filters these out one level up.
        return OpticalFrame(
            path=str(path),
            errors=[
                ToolError(
                    code="frame_not_checked_out",
                    message=f"{path.name} is a Git LFS pointer, not the frame itself. "
                    "Run `git lfs install && git lfs pull` to fetch it.",
                )
            ],
        )
    try:
        header = fits.getheader(path)
    except Exception as exc:
        return OpticalFrame(
            path=str(path),
            errors=[ToolError(code="fits_header_error", message=str(exc))],
        )

    category = category_from_stem(path)

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
    from tools import config

    roots, warnings = _resolve_roots(directory)
    primary = roots[0][0]
    searched = [(root, recursive) for root, recursive in roots if root.is_dir()]

    if not searched:
        tried = " or ".join(str(root) for root, _ in roots)
        return OpticalFrameList(
            frames=[],
            search_root=str(primary),
            search_roots=[],
            count=0,
            warnings=warnings,
            errors=[
                ToolError(
                    code="directory_not_found",
                    message=f"No optical data directory at {tried}. Set "
                    f"{OPTICAL_DATA_DIR_ENV} to point at one.",
                )
            ],
        )

    limit = config.DEFAULT_MAX_FRAMES
    paths, found = _iter_fits(searched, limit)
    if found > len(paths):
        warnings.append(
            ToolWarning(
                code="listing_truncated",
                message=(
                    f"{found} frames found; read and returned the first "
                    f"{limit} from each of {len(searched)} root(s), "
                    f"{len(paths)} in all. To reach a specific frame, pass "
                    "directory= naming the directory the frame is actually "
                    "in -- search_mast reports where each download landed -- "
                    f"or raise {config.MAX_FRAMES_ENV}. image_filter narrows "
                    "what was read, not what was found, so a filter on a "
                    "truncated listing can miss frames beyond the cap."
                ),
            )
        )

    # An LFS-tracked frame that was never fetched is a ~130-byte text stub
    # wearing the frame's name. Drop those before any header read: a listing
    # that carried them would report a FITS parse error per frame and poison
    # the filter tally with a null band, where what the caller needs is one
    # line saying the objects are not checked out (P8).
    pointers = [p for p in paths if config.is_lfs_pointer(p)]
    if pointers:
        paths = [p for p in paths if p not in set(pointers)]
        warnings.append(
            ToolWarning(
                code="frames_not_checked_out",
                message=(
                    f"{len(pointers)} frame(s) are Git LFS pointers, not frames, "
                    "and were left out of this listing: "
                    f"{', '.join(sorted(p.name for p in pointers))}. Run "
                    "`git lfs install && git lfs pull` to fetch them."
                ),
            )
        )

    frames = [_summary(p) for p in paths]
    if image_filter is not None:
        wanted = image_filter.strip().lower()
        frames = [f for f in frames if (f.image_filter or "").lower() == wanted]

    filters = sorted({f.image_filter for f in frames if f.image_filter})
    return OpticalFrameList(
        frames=frames,
        search_root=str(primary),
        search_roots=[str(root) for root, _ in searched],
        count=len(frames),
        filters=filters,
        warnings=warnings,
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
    roots, _ = _resolve_roots(directory)

    direct = Path(name).expanduser()
    if direct.is_file():
        return _summary(direct)
    for root, _ in roots:
        for candidate in (root / name, root / f"{name}.fits"):
            if candidate.is_file():
                return _summary(candidate)

    listing = list_optical_frames(directory)
    if listing.errors:
        return listing

    wanted = _normalize(name)
    if not wanted:
        listing.errors.append(
            ToolError(code="invalid_input", message="name must not be blank")
        )
        return listing

    # The full filename is matched as well as the stem. A flat root resolves
    # "x.fits" through the root/name probe above, but a nested one cannot, and
    # a filename is exactly what a caller copies out of an archive manifest --
    # _normalize("x.fits") is "xfits", which is not a substring of "x".
    matches = [
        frame
        for frame in listing.frames
        if wanted in _normalize(Path(frame.path).stem)
        or wanted in _normalize(Path(frame.path).name)
        or wanted in _normalize(frame.object_name or "")
    ]

    if len(matches) == 1:
        frame = matches[0]
        if any(w.code == "listing_truncated" for w in listing.warnings):
            # Found among the frames that were read, not the frames that
            # exist. Uncapped, this name might have been ambiguous -- the same
            # field in another band, past the cap -- so say that on the frame
            # rather than drop it with the list. Only the truncation caveat
            # rides along: the containment warning describes the operator's
            # configuration, not this match, and would attach to every
            # bundled-frame resolve for anyone with a flat CASDA root.
            frame = frame.model_copy(
                update={
                    "warnings": [
                        *frame.warnings,
                        ToolWarning(
                            code="resolved_from_truncated_listing",
                            message=(
                                f"Matched {name!r} among the {listing.count} "
                                "frames read; frames past the cap were not "
                                "considered, so this may not be the only "
                                "match. Pass directory= to search where the "
                                "frame is, or list with image_filter."
                            ),
                        ),
                    ]
                }
            )
        return frame

    if not matches:
        from tools import config

        # Say when the search was partial. Reporting the capped count as though
        # it were the total is worst in exactly the case the cap creates: after
        # a bulk download the wanted frame is the one likely to have fallen
        # past it, and "N frames are available" reads as "it is not here".
        truncated = any(w.code == "listing_truncated" for w in listing.warnings)
        scope = (
            f"Only the first {listing.count} frames were read"
            if truncated
            else f"{listing.count} frames are available"
        )
        hint = (
            "pass directory= naming the directory the frame is in (search_mast "
            f"reports where each download landed), or raise {config.MAX_FRAMES_ENV}"
            if truncated
            else "call list_optical_frames to see them"
        )
        listing.errors.append(
            ToolError(
                code="not_found",
                message=f"No local frame matches {name!r}. {scope}; {hint}.",
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
