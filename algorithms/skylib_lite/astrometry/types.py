"""Common astrometry request/solution types and backend protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

import numpy as np
from astropy.wcs import WCS


@dataclass(frozen=True)
class SolveRequest:
    xy: Optional[np.ndarray] = None
    flux: Optional[np.ndarray] = None
    width: Optional[int] = None
    height: Optional[int] = None
    ra_hours: Optional[float] = 0.0
    dec_degs: Optional[float] = 0.0
    radius: float = 180.0
    min_scale: float = 0.1
    max_scale: float = 10.0
    fov: Optional[float] = None
    parity: Optional[bool] = None
    sip_order: int = 3
    crpix_center: bool = True
    max_sources: Optional[int] = None
    retry_lost: bool = True
    callback: Optional[Callable[[], int]] = None
    image_path: Optional[Path] = None
    downsample: Optional[int] = None
    # Orientation prior for the fast "on-the-fly" ATLAS path. When rotation_deg
    # is provided (locked in by a prior calibration), the solver treats rotation,
    # parity, and pixel scale as known and only searches for the pointing offset
    # (translation) within `radius`. parity above carries the locked flip.
    rotation_deg: Optional[float] = None


class SolveMethod:
    """Which search the solver ran. Part of the persisted contract."""

    #: Orientation + scale locked by a prior; only the pointing offset is searched.
    ORIENTED = "oriented"
    #: Rotation, scale and position all unknown; triangle-invariant search.
    BLIND = "blind"

    ALL = (ORIENTED, BLIND)


class SolveFailure:
    """Normalized reason a solve stopped without a WCS.

    Deliberately short and stable: callers persist these values and group by
    them, so they are contract rather than log text. Backends map their own
    finer-grained internal reasons onto this vocabulary and keep the raw one in
    ``metadata["reason"]``.
    """

    #: Too few sources were extracted from the image to attempt a match.
    NO_SOURCES = "no_sources"
    #: The reference catalog returned too few stars for the searched footprint.
    NO_CATALOG = "no_catalog"
    #: Sources and catalog were both adequate, but no candidate transform emerged.
    NO_MATCH = "no_match"
    #: A candidate transform was found and rejected by the acceptance gates.
    VERIFICATION_FAILED = "verification_failed"
    #: The search was cut short by the configured time budget.
    TIMEOUT = "timeout"
    #: The request could not be turned into a searchable problem (no FOV/scale).
    BAD_INPUT = "bad_input"

    ALL = (
        NO_SOURCES,
        NO_CATALOG,
        NO_MATCH,
        VERIFICATION_FAILED,
        TIMEOUT,
        BAD_INPUT,
    )


@dataclass(frozen=True)
class SolveAttempt:
    """The search that was actually run, echoed back from the request.

    Exists so a caller recording solve diagnostics reports the parameters the
    solve *used* rather than re-deriving them from its own settings at the
    record site — a derivation that can (and did) disagree with the request it
    was meant to describe.
    """

    method: str
    radius_deg: float
    min_scale_arcsec_per_pix: float
    max_scale_arcsec_per_pix: float
    rotation_deg: Optional[float] = None
    parity: Optional[bool] = None
    max_sources: Optional[int] = None
    downsample: Optional[int] = None

    @classmethod
    def from_request(cls, request: "SolveRequest", method: str) -> "SolveAttempt":
        return cls(
            method=method,
            radius_deg=float(request.radius),
            min_scale_arcsec_per_pix=float(request.min_scale),
            max_scale_arcsec_per_pix=float(request.max_scale),
            rotation_deg=(
                None if request.rotation_deg is None else float(request.rotation_deg)
            ),
            parity=request.parity,
            max_sources=request.max_sources,
            downsample=request.downsample,
        )


@dataclass
class SolveSolution:
    wcs: Optional[WCS] = None
    log_odds: Optional[float] = None
    n_match: Optional[int] = None
    n_conflict: Optional[int] = None
    n_field: Optional[int] = None
    index_name: Optional[str] = None
    backend: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    # Diagnostics recorded on every attempt, hit or miss. A miss used to carry
    # nothing but `wcs is None`, which left callers unable to tell a fast
    # star-poor rejection from a solver that ground against its time budget.
    attempt: Optional[SolveAttempt] = None
    failure_reason: Optional[str] = None
    source_count: Optional[int] = None
    duration_sec: Optional[float] = None

    @property
    def solved(self) -> bool:
        """True when the solve produced a WCS.

        A property, not a field, so it cannot drift from ``wcs`` the way
        separately-assigned success flags do.
        """
        return self.wcs is not None


class Backend(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def solve(self, request: SolveRequest, config) -> SolveSolution: ...


__all__ = [
    "Backend",
    "SolveAttempt",
    "SolveFailure",
    "SolveMethod",
    "SolveRequest",
    "SolveSolution",
]
