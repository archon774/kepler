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
    "PulsarScan",
    "PulsarScanList",
    "PulsarLightCurve",
    "PulsarPeriodogram",
    "PulsarFoldedProfile",
    "PulsarSonification",
    "PulsarPlot",
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


class PulsarObservationInfo(KeplerToolModel):
    """Fields every stage of the pulsar pipeline reports about its input."""

    flavour: Literal["cal", "standard"] = "cal"
    source_name: str | None = None
    date_obs: str | None = None
    samples_read: int = 0
    samples_used: int = 0
    time_span_s: float | None = None
    mean_sample_interval_s: float | None = None
    sample_cadence_s: float | None = None
    background_subtracted: bool = False
    back_scale_s: float | None = None


class PulsarScan(KeplerToolModel):
    """A pulsar scan available on local disk.

    ``path`` is what every pipeline stage takes. The rest is read from the
    file's own ``#`` header, so listing is cheap -- no sample data is parsed.
    """

    path: str
    source_name: str | None = None
    date_obs: str | None = None
    receiver: str | None = None
    obs_freq_mhz: float | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    duration_s: float | None = None
    size_bytes: int | None = None


class PulsarScanList(KeplerToolModel):
    """Scans found locally, plus where they were looked for."""

    scans: list[PulsarScan] = Field(default_factory=list)
    search_root: str
    count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class PulsarLightCurve(PulsarObservationInfo):
    """Stage 1: an ingested, background-subtracted pulsar light curve.

    The artifact is the handoff to every later stage -- pass its path back in
    as ``path`` instead of re-reading the raw scan.
    """

    file: FileMetadata
    artifact: Optional[ArtifactRef] = None
    channels: int = 1
    receiver: str | None = None
    obs_freq_mhz: float | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    nyquist_period_s: float | None = None
    """Twice the mean sample interval -- the shortest period resolvable, and
    the periodogram's default lower search bound."""

    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class PulsarPeriodogram(PulsarObservationInfo):
    """Stage 2: a Lomb-Scargle spectrum and the period it peaks at."""

    file: FileMetadata
    artifact: Optional[ArtifactRef] = None

    mode: Literal["period", "frequency"] = "period"
    search_start: float | None = None
    search_stop: float | None = None
    steps: int | None = None
    channel: str | None = None

    peak_period_s: float | None = None
    peak_power: float | None = None
    peak_confidence: str | None = None
    """Highest false-alarm level the peak clears, or null if it clears none.

    **Not a validity check.** The threshold assumes white noise, and radio data
    is not white: mains interference and post-subtraction red noise routinely
    clear the 3-sigma line. On four of the five bundled scans the strongest
    peak reads "99.73% Confidence" and is not the pulsar. Use
    ``peak_fold_snr``, which tests the peak against the data itself."""

    peak_fold_snr: float | None = None
    """Pulse significance obtained by folding at ``peak_period_s``.

    The arbiter. A periodogram peak that is a real periodicity concentrates
    flux when folded; one that is RFI or red noise does not. Above ~8 the peak
    is worth trusting, near 1 it is not, whatever ``peak_power`` says."""

    confidence_thresholds: dict[str, float] = Field(default_factory=dict)
    top_peaks: list[dict[str, Any]] = Field(default_factory=list)
    """A few best-separated candidates, strongest first, for when the global
    peak is a harmonic rather than the fundamental."""

    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class PulsarFoldedProfile(PulsarObservationInfo):
    """Stage 3: a light curve folded at a period into a pulse profile."""

    file: FileMetadata
    artifact: Optional[ArtifactRef] = None

    period_s: float | None = None
    bins: int | None = None
    bins_filled: int | None = None
    phase: float | None = None
    display_period: int | None = None
    cal: float | None = None
    samples_folded: int = 0

    pulse_snr: float | None = None
    """Peak significance against the profile's own off-pulse scatter. Above
    ~8 the fold is a real detection; near 1 the period is wrong or the source
    is too faint in this scan."""

    channels: int = 1
    preview: list[dict[str, Any]] = Field(default_factory=list)

    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class PulsarSonification(KeplerToolModel):
    """A rendered pulsar audio file, plus what it was rendered from.

    The observation fields describe the input light curve; the audio fields
    describe the WAV. ``artifact`` is the only place the complete result
    lives -- the audio itself is never inlined.
    """

    file: FileMetadata
    artifact: Optional[ArtifactRef] = None

    # What was read.
    flavour: Literal["cal", "standard"] = "cal"
    source_name: str | None = None
    date_obs: str | None = None
    samples_read: int = 0
    samples_used: int = 0
    time_span_s: float | None = None
    mean_sample_interval_s: float | None = None
    sample_cadence_s: float | None = None
    background_subtracted: bool = False
    back_scale_s: float | None = None

    # Which rendering. "folded" is upstream's primary path -- the scan folded
    # at a period into a profile, looped at the true pulse rate. "lightcurve"
    # plays the scan through once and needs no period.
    rendering: Literal["lightcurve", "folded"] = "lightcurve"
    period_s: float | None = None
    bins: int | None = None
    pulse_snr: float | None = None

    # What was rendered.
    audio_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    mode: Literal["burst", "waveform"] | None = None
    pass_seconds: float | None = None
    playback_stretch: float | None = None
    """Audio seconds per second of observation. 1.0 is real time; 1.03 means a
    feature recurring every 1.000 s in the sky is heard every 1.030 s. The
    synthesis ignores sample timestamps, so this is never exactly 1.0 -- do not
    read a pulsar period off the audio, use ``search_atnf``."""

    speed: float | None = None
    cal: float | None = None
    noise_seed: int | None = None

    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class PulsarPlot(KeplerToolModel):
    """A rendered pulsar chart.

    The chart's identity -- axis labels, series names, whether the x axis is
    logarithmic -- comes from ``algorithms.pulsar.charts``, which carries
    Astromancer's own configuration rather than choices made here.
    """

    file: FileMetadata
    artifact: Optional[ArtifactRef] = None

    kind: Literal["lightcurve", "periodogram", "folded"] | None = None
    title: str | None = None
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    x_axis_type: Literal["linear", "logarithmic"] | None = None

    series: list[str] = Field(default_factory=list)
    hidden_series: list[str] = Field(default_factory=list)
    """Series upstream declares with ``visible: false`` -- present in the
    legend but off until clicked. Pass ``show_hidden_series=True`` to draw
    them."""

    source_name: str | None = None
    period_s: float | None = None

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
