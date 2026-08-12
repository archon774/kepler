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
    "PhotometryTargetLibrary",
    "SourceSummary",
    "PhotometryRunResult",
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


class PhotometryTargetLibrary(KeplerToolModel):
    """The local FITS library ``run_photometry_on_target`` can actually run on.

    There is no live image archive behind photometry -- ``categories`` is
    exactly ``tools.claude_photometry_haiku_tool.list_bundled_targets()``'s
    output (bundled ``test_data/optical/`` stems grouped by the category
    embedded in each filename), not a query result.
    """

    categories: dict[str, list[str]] = Field(default_factory=dict)
    total_count: int = 0


class SourceSummary(KeplerToolModel):
    """One detected source's position, magnitude, and flux."""

    x: float | None = None
    y: float | None = None
    mag: float | None = None
    flux: float | None = None


class PhotometryRunResult(KeplerToolModel):
    """Result of running source extraction (and optionally a verified
    zero-point solve) on one bundled FITS target.

    ``zero_point`` is only populated when ``zero_point_source == "field-cal"``
    -- a CLI override or FITS-header value is applied to ``magnitude_label``'s
    magnitudes but was never independently checked against a catalog, so
    there is no ``ZeropointSolution`` to report for those paths.

    ``exposure_seconds``, confirmed live: every ``mag`` here is
    ``-2.5*log10(flux / exposure_seconds) + zero_point`` -- never the bare
    ``-2.5*log10(flux) + zero_point`` a reader would otherwise assume. Without
    this field, ``flux`` and ``mag`` looked mutually inconsistent by several
    magnitudes on a real bundled frame (the reader has no way to know ``flux``
    is a raw per-exposure sum, not a per-second rate) -- report this alongside
    ``flux``/``mag`` whenever discussing either.
    """

    file: FileMetadata
    source_count: int = 0
    magnitude_label: str = "instrumental magnitude"
    exposure_seconds: float | None = None
    zero_point_source: str = "none"  # "cli" | "header" | "field-cal" | "none"
    zero_point: ZeropointSolution | None = None
    brightest: SourceSummary | None = None
    faintest: SourceSummary | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
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
