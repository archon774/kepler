"""Small shared models for Kepler tool results."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "KeplerToolModel",
    "ToolWarning",
    "ToolError",
    "ArtifactRef",
    "ToolResult",
    "FileMetadata",
    "ArtifactMetadata",
    "TableSummary",
    "WcsSummary",
    "CatalogSummary",
    "ReferenceBandResolution",
    "ZeropointSolution",
    "coerce_optional_int",
]


class KeplerToolModel(BaseModel):
    """Base model for public tool summaries."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ToolWarning(KeplerToolModel):
    code: str
    message: str


class ToolError(KeplerToolModel):
    code: str
    message: str


class ArtifactRef(KeplerToolModel):
    """A file a tool wrote to disk, plus enough metadata to use it."""

    path: str
    format: str
    row_count: Optional[int] = None
    columns: list[str] = Field(default_factory=list)


class ToolResult(KeplerToolModel):
    """Bounded result returned by remote/catalog database tools.

    ``preview`` is a small inline sample only. Full data goes to ``artifact``
    or ``artifacts`` when a tool writes files.
    """

    status: Literal["ok", "partial", "not_found", "error"]
    count: Optional[int] = None
    preview: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    artifact: Optional[ArtifactRef] = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class FileMetadata(KeplerToolModel):
    path: str
    exists: bool
    is_file: bool = False
    size_bytes: int | None = None
    modified_time: str | None = None
    suffix: str | None = None


class ArtifactMetadata(KeplerToolModel):
    file: FileMetadata
    artifact_type: str
    media_type: str | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class TableSummary(KeplerToolModel):
    name: str | None = None
    row_count: int | None = None
    columns: list[str] = Field(default_factory=list)


class WcsSummary(KeplerToolModel):
    file: FileMetadata
    has_wcs: bool
    image_shape: tuple[int, int] | None = None
    ctype: tuple[str, str] | None = None
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    center_ra_hours: float | None = None
    pixel_scale_arcsec: tuple[float, float] | None = None
    rotation_deg: float | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class CatalogSummary(KeplerToolModel):
    name: str
    display_name: str | None = None
    num_sources: int | None = None
    bands: list[str] = Field(default_factory=list)
    filter_aliases: list[str] = Field(default_factory=list)


class ReferenceBandResolution(KeplerToolModel):
    catalog: str
    image_filter: str | None = None
    supported: bool
    reference: str | None = None
    kind: Literal[
        "direct_band",
        "lookup_band",
        "expression",
        "wildcard",
        "unresolved",
    ] = "unresolved"
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class ZeropointSolution(KeplerToolModel):
    zero_point_corr: float | None = None
    zero_point_error_mag: float | None = None
    zero_point_slop: float | None = None
    limmag5: float | None = None
    rej_percent: float | None = None
    source_count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


def coerce_optional_int(value: Union[int, str, None]) -> Optional[int]:
    """Coerce a JSON-ish tool argument to ``Optional[int]``."""

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
