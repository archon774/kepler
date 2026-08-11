"""Configuration for the (optional) astrometry.net subprocess backend.

v2 note: the in-process SWIG engine is gone. The backend now shells out to the
system ``solve-field`` binary, so configuration is about *where* that binary and
its index files live — not an in-process engine handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Union


@dataclass
class AstrometryNetConfig:
    #: Directory or directories containing astrometry.net index files. Recognized
    #: naming conventions (no renaming required): the standard ``index-*.fits``,
    #: vendor-prefixed ``*-index-*.fits`` (e.g. UCAC5 ``ucac5-index-00-00.fits``),
    #: and suffixless ``index-NNN`` (e.g. TYCHO2 ``index-205``). If None, the
    #: backend falls back to the SKYLIB_ASTROMETRYNET_INDEX_PATH (then
    #: SKYLIB_ANET_INDEX_ROOT) environment variable, os.pathsep-separated.
    #: Directories are validated at solve time; those that are missing or hold no
    #: recognized index files are dropped.
    index_path: Optional[Union[str, Sequence[str]]] = None
    #: Override the ``solve-field`` executable (absolute path or a name on PATH).
    #: If None, it is resolved from SKYLIB_ASTROMETRYNET_SOLVE_FIELD /
    #: SKYLIB_ANET_SOLVE_FIELD and then ``shutil.which("solve-field")``.
    solve_field_path: Optional[str] = None
    #: Wall-clock + CPU limit handed to solve-field (seconds). None = no limit.
    timeout_s: Optional[float] = None
    #: Extra raw arguments appended to the solve-field command line.
    extra_args: Sequence[str] = field(default_factory=tuple)


__all__ = ["AstrometryNetConfig"]
