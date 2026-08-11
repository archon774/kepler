"""Structured errors for the system astrometry.net (``solve-field``) backend.

These exceptions give the optical WCS pipeline actionable diagnostics instead
of a silent ``None``. They carry the exact command invoked, the exit status,
and captured ``stdout``/``stderr`` (and, for a missing solution, a listing of
the temporary working directory) so a failed solve can be debugged from a log
line without re-running by hand.

``AstrometryNetError`` is the common base, so callers that want to keep the
existing ATLAS fallback can simply ``except AstrometryNetError``.
"""

from __future__ import annotations

import shlex
from typing import List, Optional, Sequence

#: Hard cap on how much captured stdout/stderr we embed in an error message so a
#: runaway solver log can't blow up the exception string / log line.
_OUTPUT_CLIP = 4000


def format_command(cmd: Sequence[str]) -> str:
    """Render an argv list as a copy-pasteable shell command string."""
    return shlex.join(str(part) for part in cmd)


def _clip(text: Optional[str], limit: int = _OUTPUT_CLIP) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    return f"{head}\n… (truncated, {len(text) - limit} more chars)"


def _diagnostic_block(
    *,
    command: Optional[Sequence[str]] = None,
    returncode: Optional[int] = None,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    workdir_listing: Optional[Sequence[str]] = None,
) -> str:
    parts: List[str] = []
    if command is not None:
        parts.append(f"command: {format_command(command)}")
    if returncode is not None:
        parts.append(f"exit status: {returncode}")
    out = _clip(stdout)
    if out:
        parts.append(f"stdout:\n{out}")
    err = _clip(stderr)
    if err:
        parts.append(f"stderr:\n{err}")
    if workdir_listing is not None:
        listing = ", ".join(workdir_listing) or "(empty)"
        parts.append(f"workdir contents: {listing}")
    return "\n".join(parts)


class AstrometryNetError(RuntimeError):
    """Base class for failures from the system astrometry.net backend."""


class SolveFieldNotFoundError(AstrometryNetError):
    """The ``solve-field`` executable could not be located."""

    def __init__(self, tried: Optional[Sequence[str]] = None) -> None:
        self.tried = list(tried or [])
        tried_str = ", ".join(self.tried) if self.tried else "solve-field"
        super().__init__(
            "Could not find the astrometry.net 'solve-field' binary "
            f"(tried: {tried_str}). Install astrometry.net with your system "
            "package manager (Fedora: 'dnf install astrometry'; Debian/Ubuntu: "
            "'apt install astrometry.net'), ensure 'solve-field' is on PATH, or "
            "set the binary path explicitly via the ANET_SOLVE_FIELD_PATH config "
            "key (config/environments/dev.local.toml) or the "
            "SKYLIB_ASTROMETRYNET_SOLVE_FIELD environment variable."
        )


class IndexDirectoryError(AstrometryNetError):
    """No usable astrometry.net index directory was configured."""

    def __init__(
        self,
        *,
        configured: Optional[Sequence[str]] = None,
        problems: Optional[Sequence[str]] = None,
    ) -> None:
        self.configured = list(configured or [])
        self.problems = list(problems or [])
        message = (
            "No usable astrometry.net index directories. Configure one or more "
            "directories containing index files (index-*.fits, vendor-prefixed "
            "*-index-*.fits such as UCAC5, or suffixless index-NNN such as TYCHO2) "
            "via the ANET_INDEX_PATH config key (config/environments/dev.local.toml) "
            "or the SKYLIB_ASTROMETRYNET_INDEX_PATH environment variable."
        )
        if self.problems:
            message += " Problems: " + "; ".join(self.problems)
        super().__init__(message)


class SolveFieldTimeout(AstrometryNetError):
    """``solve-field`` exceeded its wall-clock budget and was terminated."""

    def __init__(
        self,
        command: Sequence[str],
        timeout_sec: float,
        *,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
    ) -> None:
        self.command = list(command)
        self.timeout_sec = timeout_sec
        self.stdout = stdout
        self.stderr = stderr
        block = _diagnostic_block(command=command, stdout=stdout, stderr=stderr)
        super().__init__(
            f"solve-field timed out after {timeout_sec:g}s and was terminated.\n{block}"
        )


class SolveFieldFailed(AstrometryNetError):
    """``solve-field`` exited with a nonzero status."""

    def __init__(
        self,
        command: Sequence[str],
        returncode: int,
        *,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        workdir_listing: Optional[Sequence[str]] = None,
    ) -> None:
        self.command = list(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.workdir_listing = list(workdir_listing) if workdir_listing is not None else None
        block = _diagnostic_block(
            command=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            workdir_listing=workdir_listing,
        )
        super().__init__(f"solve-field failed (exit {returncode}).\n{block}")


__all__ = [
    "AstrometryNetError",
    "SolveFieldNotFoundError",
    "IndexDirectoryError",
    "SolveFieldTimeout",
    "SolveFieldFailed",
    "format_command",
]
