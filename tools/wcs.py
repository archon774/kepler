"""Public plate-solving tool wrapper."""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from astropy.io import fits
from astropy.wcs import WCS

from algorithms.wcs.config import SolverSettings
from algorithms.wcs.header_utils import estimate_pixel_scale_arcsec_per_pix
from algorithms.skylib_lite.astrometry.anet.engine import (
    find_solve_field,
    resolve_index_dirs,
    validate_index_dirs,
)
from algorithms.skylib_lite.astrometry.atlas.catalog import get_catalog_spec
from algorithms.wcs.source_extraction import build_wcs_from_header
from algorithms.wcs.wcs import WCS_REGEX, solve_wcs as _solve_wcs
from tools.artifacts import describe_file
from tools.astrometry import (
    _center_from_wcs,
    _image_shape_from_header,
    _pixel_scale_arcsec,
    _rotation_deg,
    describe_image_wcs,
)
from tools.models import ToolError, ToolWarning, WcsSummary


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
#: The committed fixture tree. Pinned to this repository rather than read from
#: ``config.DATA_DIR``: an operator who points KEPLER_DATA_DIR at their own
#: archive has neither made these frames writable nor made that archive a tree
#: of fixtures, so the guard must not travel with the setting.
_FIXTURE_ROOT = (_REPOSITORY_ROOT / "data").resolve()


class _FileChangedError(RuntimeError):
    pass


def _normalise_index_path(
    index_path: str | Path | Sequence[str | Path] | None,
) -> str | list[str] | None:
    if index_path is None:
        return None
    if isinstance(index_path, (str, Path)):
        return str(index_path)
    return [str(path) for path in index_path]


def _timeout_error(name: str, value: object) -> ToolError | None:
    if value is None:
        return None
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = math.nan
    if not math.isfinite(timeout) or timeout < 1:
        return ToolError(
            code="invalid_timeout",
            message=f"{name} must be at least one finite second.",
        )
    return None


def _summary_from_wcs(
    path: str,
    header: fits.Header,
    wcs: WCS,
    *,
    attempted_backends: list[str] | None = None,
    warnings: list[ToolWarning] | None = None,
    errors: list[ToolError] | None = None,
) -> WcsSummary:
    image_shape = _image_shape_from_header(header)
    center_ra_deg, center_dec_deg = _center_from_wcs(wcs, image_shape)
    ctype = tuple(str(value) for value in list(wcs.wcs.ctype)[:2])
    return WcsSummary(
        file=describe_file(path),
        has_wcs=True,
        image_shape=image_shape,
        ctype=ctype if len(ctype) == 2 else None,
        center_ra_deg=center_ra_deg,
        center_dec_deg=center_dec_deg,
        center_ra_hours=center_ra_deg / 15.0 if center_ra_deg is not None else None,
        pixel_scale_arcsec=_pixel_scale_arcsec(wcs),
        rotation_deg=_rotation_deg(wcs),
        attempted_backends=attempted_backends or [],
        warnings=warnings or [],
        errors=errors or [],
    )


def _under_fixture_root(path: Path) -> bool:
    """Whether ``path`` is a committed fixture this tool must not rewrite.

    The guard is the data directory *minus* the archive download root. Those
    were separate trees until the download root moved inside ``data/``, and a
    downloaded frame is precisely the thing under there a caller is entitled to
    plate-solve and write a header back into -- that is the archive -> analysis
    loop BL-11 exists to join. Guarding the data directory wholesale would
    refuse exactly that write, and would do it with a message claiming the
    downloaded product was a bundled fixture.

    The download root is read through ``tools.config`` rather than bound at
    import, for the same reason ``tools.optical`` reads it that way: the two
    have to agree about where downloads land, and a test that reassigns one
    must move the other.
    """
    from tools import config

    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(_FIXTURE_ROOT):
            return False
        download_dir = config.FITS_DOWNLOAD_DIR
        if download_dir is not None and resolved.is_relative_to(
            Path(download_dir).expanduser().resolve()
        ):
            return False
    except OSError:  # pragma: no cover - symlink loop, unreadable mount
        return False
    return True


def _file_version(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _write_wcs_header(
    path: Path,
    solved_wcs: WCS,
    *,
    expected_version: tuple[int, int, int, int, int],
) -> None:
    if _file_version(path) != expected_version:
        raise _FileChangedError("FITS file changed while plate solving; WCS was not written.")

    staged_path: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=path.suffix or ".fits",
            delete=False,
        ) as staged:
            staged_path = Path(staged.name)
        shutil.copy2(path, staged_path)

        with fits.open(staged_path, mode="update", memmap=False) as hdul:
            current_header = hdul[0].header
            for key in list(current_header.keys()):
                if WCS_REGEX.match(key):
                    del current_header[key]
            current_header.add_history("WCS calibration applied by tools.wcs.solve_astrometry")
            current_header.update(solved_wcs.to_header(relax=True))
            hdul.flush()

        with staged_path.open("rb") as staged:
            os.fsync(staged.fileno())
        if _file_version(path) != expected_version:
            raise _FileChangedError("FITS file changed while plate solving; WCS was not written.")
        os.replace(staged_path, path)
        staged_path = None
    finally:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)


def _atlas_catalog_problem(settings: SolverSettings) -> str | None:
    catalog = str(settings.ATLAS_CATALOG or "ucac5").strip().lower()
    root = Path(str(settings.ATLAS_CATALOG_ROOT))
    try:
        get_catalog_spec(catalog)
    except ValueError as exc:
        return str(exc)
    if not root.is_dir():
        return f"ATLAS_CATALOG_ROOT={root} is not a directory"
    if catalog == "ucac5":
        if not (root / "u5index.asc").is_file() and not (
            root / "u5z" / "u5index.asc"
        ).is_file():
            return f"ATLAS_CATALOG_ROOT={root} contains no UCAC5 index"
    elif catalog == "ucac4" and not next(root.glob("Z*.UC4"), None):
        return f"ATLAS_CATALOG_ROOT={root} contains no UCAC4 zone files"
    return None


def _configured_backend_warnings(
    settings: SolverSettings,
) -> tuple[list[str], list[ToolWarning]]:
    available: list[str] = []
    problems: list[str] = []

    if settings.ANET_INDEX_PATH:
        if find_solve_field() is None:
            problems.append("solve-field is not available on PATH")
            settings.ANET_INDEX_PATH = None
        else:
            index_dirs = resolve_index_dirs(settings.ANET_INDEX_PATH)
            usable_dirs, rejected = validate_index_dirs(index_dirs)
            if usable_dirs:
                available.append("astrometry.net")
                settings.ANET_INDEX_PATH = usable_dirs
                problems.extend(rejected)
            else:
                detail = "; ".join(rejected) or "no index directories were configured"
                problems.append(detail)
                settings.ANET_INDEX_PATH = None

    if settings.ATLAS_CATALOG_ROOT:
        problem = _atlas_catalog_problem(settings)
        if problem is None:
            available.append("atlas")
        else:
            problems.append(problem)
            settings.ATLAS_CATALOG_ROOT = None

    if not available:
        detail = "; ".join(problems)
        message = "No plate-solving backend is available. Set ANET_INDEX_PATH "
        message += "or ATLAS_CATALOG_ROOT to a usable local data set."
        if detail:
            message += f" Configuration problems: {detail}."
        return available, [ToolWarning(code="solver_unavailable", message=message)]

    if problems:
        return available, [
            ToolWarning(
                code="solver_backend_unavailable",
                message="Some configured solver inputs were ignored: " + "; ".join(problems),
            )
        ]
    return available, []


def solve_astrometry(
    path: str | Path,
    *,
    index_path: str | Path | Sequence[str | Path] | None = None,
    write_header: bool = False,
    timeout_s: float | None = None,
    force: bool = False,
) -> WcsSummary:
    """Solve a local FITS image and optionally persist the resulting WCS.

    ``timeout_s`` is forwarded to each low-level solve attempt; extraction and
    retries mean it does not cap total call runtime. The astrometry.net
    subprocess also adds a short termination grace period to reap children.
    """

    file = describe_file(path)
    if not file.exists:
        return WcsSummary(
            file=file,
            has_wcs=False,
            errors=[ToolError(code="file_not_found", message="FITS file does not exist.")],
        )
    if not file.is_file:
        return WcsSummary(
            file=file,
            has_wcs=False,
            errors=[ToolError(code="not_a_file", message="Path is not a regular file.")],
        )

    resolved_path = Path(file.path).resolve()
    if write_header and _under_fixture_root(resolved_path):
        summary = describe_image_wcs(resolved_path)
        return summary.model_copy(
            update={
                "errors": [
                    *summary.errors,
                    ToolError(
                        code="refusing_to_modify_fixture",
                        message="Refusing to rewrite a bundled FITS fixture "
                        "under data/. Frames under the archive download root "
                        "are not fixtures and can be written.",
                    ),
                ]
            }
        )

    timeout_error = _timeout_error("timeout_s", timeout_s)
    if timeout_error is not None:
        return WcsSummary(
            file=file,
            has_wcs=False,
            errors=[timeout_error],
        )

    try:
        source_version = _file_version(resolved_path)
        with fits.open(resolved_path, memmap=False) as hdul:
            if not hdul or hdul[0].data is None:
                raise ValueError("Primary FITS HDU contains no image data.")
            data = hdul[0].data.copy()
            header = hdul[0].header.copy()
        if _file_version(resolved_path) != source_version:
            raise _FileChangedError("FITS file changed while it was being read.")
    except _FileChangedError as exc:
        return WcsSummary(
            file=file,
            has_wcs=False,
            errors=[ToolError(code="file_changed", message=str(exc))],
        )
    except Exception as exc:
        return WcsSummary(
            file=file,
            has_wcs=False,
            errors=[ToolError(code="fits_read_error", message=str(exc))],
        )

    image_shape = _image_shape_from_header(header)
    if data.ndim != 2:
        return WcsSummary(
            file=file,
            has_wcs=False,
            image_shape=image_shape,
            errors=[
                ToolError(
                    code="unsupported_image_shape",
                    message=f"Plate solving requires a 2D image; received {data.ndim} dimensions.",
                )
            ],
        )

    header_wcs = build_wcs_from_header(header)
    if header_wcs is not None and not force:
        return _summary_from_wcs(
            file.path,
            header,
            header_wcs,
            warnings=[
                ToolWarning(
                    code="wcs_from_header",
                    message="The FITS header already contains a celestial WCS; solving was skipped.",
                )
            ],
        )

    solver_settings = SolverSettings(
        anet_index_path=(
            _normalise_index_path(index_path)
            if index_path is not None
            else os.getenv("ANET_INDEX_PATH")
        ),
        anet_timeout_s=timeout_s if timeout_s is not None else os.getenv("ANET_TIMEOUT_S"),
        atlas_catalog_root=os.getenv("ATLAS_CATALOG_ROOT"),
        atlas_catalog=os.getenv("ATLAS_CATALOG"),
        atlas_timeout_s=timeout_s if timeout_s is not None else os.getenv("ATLAS_TIMEOUT_S"),
    )
    timeout_settings = (
        ("ANET_TIMEOUT_S", solver_settings.ANET_TIMEOUT_S, solver_settings.ANET_INDEX_PATH),
        (
            "ATLAS_TIMEOUT_S",
            solver_settings.ATLAS_TIMEOUT_S,
            solver_settings.ATLAS_CATALOG_ROOT,
        ),
    )
    for name, value, backend_configured in timeout_settings:
        if backend_configured:
            timeout_error = _timeout_error(name, value)
            if timeout_error is not None:
                return WcsSummary(
                    file=file,
                    has_wcs=False,
                    image_shape=image_shape,
                    errors=[timeout_error],
                )
    _, configuration_warnings = _configured_backend_warnings(solver_settings)
    if not solver_settings.ANET_INDEX_PATH and not solver_settings.ATLAS_CATALOG_ROOT:
        return WcsSummary(
            file=file,
            has_wcs=False,
            image_shape=image_shape,
            warnings=configuration_warnings,
        )

    pixel_scale_hint = estimate_pixel_scale_arcsec_per_pix(header)
    attempted_backends: list[str] = []
    solver_failures: list[str] = []
    try:
        with TemporaryDirectory(prefix="kepler-wcs-") as tmpdir:
            solve_result = _solve_wcs(
                header,
                data,
                Path(tmpdir),
                pixel_scale_hint_arcsec=pixel_scale_hint,
                solver_settings=solver_settings,
                solver_attempts=attempted_backends,
                solver_failures=solver_failures,
            )
    except Exception as exc:
        return WcsSummary(
            file=file,
            has_wcs=False,
            image_shape=image_shape,
            attempted_backends=attempted_backends,
            warnings=configuration_warnings,
            errors=[ToolError(code="solver_failed", message=str(exc))],
        )

    solved_wcs = solve_result.wcs
    if solved_wcs is None:
        if solver_failures:
            return WcsSummary(
                file=file,
                has_wcs=False,
                image_shape=image_shape,
                attempted_backends=attempted_backends,
                warnings=configuration_warnings,
                errors=[
                    ToolError(
                        code="solver_failed",
                        message="; ".join(solver_failures),
                    )
                ],
            )
        return WcsSummary(
            file=file,
            has_wcs=False,
            image_shape=image_shape,
            attempted_backends=attempted_backends,
            warnings=[
                *configuration_warnings,
                ToolWarning(
                    code="no_solution",
                    message="The configured plate-solving backends returned no solution.",
                )
            ],
        )

    if write_header:
        try:
            _write_wcs_header(
                resolved_path,
                solved_wcs,
                expected_version=source_version,
            )
        except _FileChangedError as exc:
            return _summary_from_wcs(
                file.path,
                header,
                solved_wcs,
                attempted_backends=attempted_backends,
                warnings=configuration_warnings,
                errors=[ToolError(code="file_changed", message=str(exc))],
            )
        except Exception as exc:
            return _summary_from_wcs(
                file.path,
                header,
                solved_wcs,
                attempted_backends=attempted_backends,
                warnings=configuration_warnings,
                errors=[ToolError(code="fits_write_error", message=str(exc))],
            )

    return _summary_from_wcs(
        file.path,
        header,
        solved_wcs,
        attempted_backends=attempted_backends,
        warnings=configuration_warnings,
    )


__all__ = ["solve_astrometry"]
