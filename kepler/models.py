"""Kepler: the shared result shape every ``kepler.tools`` function returns.

Per ``docs/tool-architecture.md`` section 3: outputs stay bounded (a short
inline preview, never a full table) and errors stay boring (a fixed, small
code set, not a taxonomy). Full results go to disk via ``kepler.artifacts``
and are referenced by an ``ArtifactRef``, not inlined.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

__all__ = [
    "ErrorCode",
    "ToolError",
    "ArtifactRef",
    "ToolResult",
    "coerce_optional_int",
]

#: The fixed error-code set from docs/tool-architecture.md section 3. Do not
#: grow this list before a tool's actual behavior requires a new code.
ErrorCode = Literal[
    "invalid_input",
    "not_found",
    "dependency_missing",
    "provider_unavailable",
    "timeout",
    "internal_error",
]


class ToolError(BaseModel):
    code: ErrorCode
    message: str


class ArtifactRef(BaseModel):
    """A file a tool wrote to disk, plus enough metadata to use it without
    reopening it."""

    path: str
    format: str
    row_count: Optional[int] = None
    columns: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """Bounded result returned by every ``kepler.tools`` function.

    ``preview`` is a small sample of rows for inline reading -- never the full
    result. Full data goes to ``artifact`` when a tool wrote one.
    """

    status: Literal["ok", "partial", "not_found", "error"]
    count: Optional[int] = None
    preview: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    artifact: Optional[ArtifactRef] = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


def coerce_optional_int(value: Union[int, str, None]) -> Optional[int]:
    """Coerce a tool-call argument to ``Optional[int]``.

    Confirmed live: a model asked to pass ``max_catalogs=None`` for "no cap"
    emitted the JSON *string* ``"None"`` instead of JSON ``null`` -- an
    Anthropic tool call's arguments are JSON, and the system prompt described
    the fix in Python syntax. ``search_vizier`` then did ``matched[:'None']``,
    a hard ``TypeError``, not a handled error. Any ``Optional[int]`` tool
    parameter is exposed to the same failure mode, so this is a shared
    coercion point rather than a fix local to one tool: treats common
    None-spellings (``"none"``, ``"null"``, ``""``) and numeric strings
    (``"20"``) leniently, and raises ``ValueError`` for anything else, which
    a caller turns into an ``invalid_input`` result.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"expected an integer or null, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in ("none", "null", ""):
            return None
        try:
            return int(stripped)
        except ValueError:
            pass
    raise ValueError(f"expected an integer or null, got {value!r}")
