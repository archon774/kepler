"""SkyLib astrometric reduction — backend dispatch.

v2: ATLAS (pure-Python) is the default solver and works everywhere. The
astrometry.net backend is optional and only available where the system
``solve-field`` binary is installed (see :mod:`skylib.astrometry.anet`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

from astropy.io import fits
from astropy.wcs import WCS

from .anet import (
    AstrometryNetBackend,
    AstrometryNetConfig,
    solve_field_glob as _anet_solve_field_glob,
)
from .atlas import AtlasBackend, AtlasConfig
from .types import (
    Backend,
    SolveAttempt,
    SolveFailure,
    SolveMethod,
    SolveRequest,
    SolveSolution,
)

BackendConfig = Union[AstrometryNetConfig, AtlasConfig]

#: ATLAS is the cross-platform default solver in v2.
Solver = AtlasBackend
Solution = SolveSolution


def _anet_config(
    index_path: Optional[Union[str, Sequence[str]]],
    config: Optional[AstrometryNetConfig],
) -> AstrometryNetConfig:
    if config is not None:
        return config
    return AstrometryNetConfig(index_path=index_path)


def solve_field(
    xy=None,
    flux=None,
    width=None,
    height=None,
    ra_hours=0,
    dec_degs=0,
    radius=180,
    min_scale=0.1,
    max_scale=10,
    fov=None,
    parity=None,
    sip_order=3,
    crpix_center=True,
    max_sources=None,
    retry_lost=True,
    callback=None,
    image_path: Optional[Path] = None,
    downsample: Optional[int] = None,
    index_path: Optional[Union[str, Sequence[str]]] = None,
    config: Optional[AstrometryNetConfig] = None,
) -> SolveSolution:
    """Solve a field with the astrometry.net backend (system ``solve-field``).

    Provide index files via ``index_path`` / ``config`` or the
    ``SKYLIB_ASTROMETRYNET_INDEX_PATH`` env var. For pure-Python/cross-platform
    solving use :class:`~skylib.astrometry.atlas.AtlasBackend` directly.
    """

    backend = AstrometryNetBackend()
    if not backend.is_available():
        raise RuntimeError(
            "astrometry.net backend unavailable (solve-field not on PATH); "
            "use AtlasBackend for pure-Python solving."
        )

    request = SolveRequest(
        xy=xy,
        flux=flux,
        width=width,
        height=height,
        ra_hours=ra_hours,
        dec_degs=dec_degs,
        radius=radius,
        min_scale=min_scale,
        max_scale=max_scale,
        fov=fov,
        parity=parity,
        sip_order=sip_order,
        crpix_center=crpix_center,
        max_sources=max_sources,
        retry_lost=retry_lost,
        callback=callback,
        image_path=image_path,
        downsample=downsample,
    )
    return backend.solve(request, _anet_config(index_path, config))


def solve_field_glob(
    xy,
    flux=None,
    width=None,
    height=None,
    ra_hours=0,
    dec_degs=0,
    radius=180,
    min_scale=0.1,
    max_scale=10,
    parity=None,
    sip_order=3,
    crpix_center=True,
    max_sources=None,
    retry_lost=True,
    callback=None,
    index_path: Optional[Union[str, Sequence[str]]] = None,
    config: Optional[AstrometryNetConfig] = None,
    min_sources=10,
    initial_radius=1,
    radius_step=0.8,
) -> SolveSolution:
    """astrometry.net solve with globular-cluster core masking (subprocess)."""

    request = SolveRequest(
        xy=xy,
        flux=flux,
        width=width,
        height=height,
        ra_hours=ra_hours,
        dec_degs=dec_degs,
        radius=radius,
        min_scale=min_scale,
        max_scale=max_scale,
        parity=parity,
        sip_order=sip_order,
        crpix_center=crpix_center,
        max_sources=max_sources,
        retry_lost=retry_lost,
        callback=callback,
    )
    return _anet_solve_field_glob(
        request,
        _anet_config(index_path, config),
        min_sources=min_sources,
        initial_radius=initial_radius,
        radius_step=radius_step,
    )


def _load_wcs(path: Path) -> Optional[WCS]:
    if not path.exists():
        return None
    try:
        header = fits.Header.fromtextfile(str(path))
        return WCS(header)
    except Exception:
        try:
            header = fits.getheader(str(path))
            return WCS(header)
        except Exception:
            return None


__all__ = [
    "AstrometryNetBackend",
    "AstrometryNetConfig",
    "AtlasBackend",
    "AtlasConfig",
    "Backend",
    "BackendConfig",
    "SolveAttempt",
    "SolveFailure",
    "SolveMethod",
    "SolveRequest",
    "SolveSolution",
    "Solver",
    "Solution",
    "solve_field",
    "solve_field_glob",
]
