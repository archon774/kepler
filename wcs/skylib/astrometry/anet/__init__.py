"""Optional astrometry.net backend (drives the system ``solve-field`` binary).

v2: no compiled engine, no SWIG. ``AstrometryNetBackend.is_available()`` is True
only where a ``solve-field`` binary can be resolved (explicit config → env var →
``PATH``). Failures raise the structured errors below.
"""

from .backend import AstrometryNetBackend, solve_field_glob
from .config import AstrometryNetConfig
from .engine import (
    INDEX_FILE_CONVENTIONS,
    INDEX_FITS_GLOB,
    SUPPORTED_INDEX_DESC,
    detect_index_conventions,
    find_solve_field,
    load_ngc_globular_clusters,
    resolve_index_dirs,
    solve_field_candidates,
    validate_index_dirs,
)
from .errors import (
    AstrometryNetError,
    IndexDirectoryError,
    SolveFieldFailed,
    SolveFieldNotFoundError,
    SolveFieldTimeout,
)

__all__ = [
    "AstrometryNetBackend",
    "AstrometryNetConfig",
    "AstrometryNetError",
    "IndexDirectoryError",
    "SolveFieldFailed",
    "SolveFieldNotFoundError",
    "SolveFieldTimeout",
    "INDEX_FITS_GLOB",
    "INDEX_FILE_CONVENTIONS",
    "SUPPORTED_INDEX_DESC",
    "find_solve_field",
    "solve_field_candidates",
    "resolve_index_dirs",
    "validate_index_dirs",
    "detect_index_conventions",
    "load_ngc_globular_clusters",
    "solve_field_glob",
]
