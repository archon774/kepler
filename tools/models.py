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
    "WcsSearchSummary",
    "WcsSummary",
    "CatalogSummary",
    "ReferenceBandResolution",
    "ZeropointSolution",
    "ZeropointReference",
    "ZeropointComparison",
    "CatalogResponseReference",
    "FieldCalMatch",
    "FieldCalReplay",
    "PhotometryTargetLibrary",
    "SourceSummary",
    "PhotometryRunResult",
    "PulsarScan",
    "PulsarScanList",
    "OpticalFrame",
    "OpticalFrameList",
    "PulsarLightCurve",
    "PulsarPeriodogram",
    "PulsarFoldedProfile",
    "PulsarSonification",
    "PulsarPlot",
    "VariableStarFixture",
    "VariableStarFixtureList",
    "VariableStarLightCurve",
    "VariableStarPeriodogram",
    "VariableStarFoldedLightCurve",
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


class WcsSearchSummary(KeplerToolModel):
    """The search the plate solver was asked to run.

    Present only when the solve reached the backends. ``radius_deg`` and the
    ``min``/``max_scale_arcsec`` window are what astrometry.net searched
    verbatim; ``all_sky`` is the extracted default (radius 180). The ATLAS
    backend ignores the radius -- it always searches locally around the
    pointing hint -- and unless a scale bound was explicit it narrows the
    window around the header's pixel-scale estimate, so when ATLAS was
    attempted ``atlas_min``/``atlas_max_scale_arcsec`` carry the window it was
    given. ``explicit`` names which of the caller's ``search_radius_deg`` /
    ``min_scale_arcsec`` / ``max_scale_arcsec`` set the value reported, so a
    bounded miss is distinguishable from an all-sky one. ``center_*`` is the
    frame's own pointing hint the radius was centred on.
    """

    radius_deg: float
    all_sky: bool
    min_scale_arcsec: float
    max_scale_arcsec: float
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    atlas_min_scale_arcsec: float | None = None
    atlas_max_scale_arcsec: float | None = None
    explicit: list[str] = Field(default_factory=list)


class WcsSummary(KeplerToolModel):
    """Compact celestial WCS metadata from a FITS header or plate solve.

    ``algorithms.wcs.results.WcsSolveMetadata`` carries fitted diagnostics such
    as ``pointing_error_arcsec`` and ``n_field``; this public summary
    intentionally reports only the common WCS geometry shared by header
    inspection and the plate-solving tool. ``attempted_backends`` identifies
    which configured solvers the plate-solving path actually invoked, and
    ``search`` what they were asked to search.
    """

    file: FileMetadata
    has_wcs: bool
    image_shape: tuple[int, int] | None = None
    ctype: tuple[str, str] | None = None
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    center_ra_hours: float | None = None
    pixel_scale_arcsec: tuple[float, float] | None = None
    rotation_deg: float | None = None
    attempted_backends: list[str] = Field(default_factory=list)
    search: WcsSearchSummary | None = None
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
    #: The ABSOLUTE photometric zero point in magnitudes, as ``calc_solution``
    #: returns it. Afterglow's API instead fixes ``zero_point = 20`` and
    #: reports a ``zero_point_correction``; adding the two gives this number.
    #: Confusing the conventions is a clean, plausible 20-magnitude error --
    #: see data/README.md.
    zero_point: float | None = None
    zero_point_error_mag: float | None = None
    zero_point_slop: float | None = None
    limmag5: float | None = None
    rej_percent: float | None = None
    source_count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class ZeropointReference(KeplerToolModel):
    """A recorded zero-point solve shipped as ground truth.

    Three independent numbers describe the same exposure and they do not use
    the same convention: ``skynet_zero_point`` and ``web_table_zero_point`` are
    absolute magnitudes, while Afterglow's API fixes a base of 20.0 and reports
    a correction. ``afterglow_zero_point`` is the sum, already computed, so a
    caller never has to remember which side the 20 goes on -- getting that
    wrong is a clean, plausible 20-magnitude error (data/README.md).

    Only ``ngc5128_b_002`` carries the Afterglow and web-table numbers; the
    three NGC 5286 B solves are the leaner "bad values" fixture and populate
    ``skynet_zero_point`` (the value ``calc_solution`` returned for those rows)
    only. ``skynet_zero_point`` is always ``calc_solution``'s
    ``catalog_mag = instrumental_mag + zero_point`` offset, whichever
    instrumental-magnitude scale the recorded rows use.
    """

    field: str
    frame_path: str | None = None
    catalog: str | None = None
    num_calibration_sources: int = 0
    skynet_zero_point: float | None = None
    afterglow_zero_point: float | None = None
    afterglow_base: float | None = None
    afterglow_correction: float | None = None
    web_table_zero_point: float | None = None
    parity_tolerance_mag: float | None = None
    measurements: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class ZeropointComparison(KeplerToolModel):
    """A computed zero point placed against the recorded ground truth.

    ``delta_vs_skynet``/``delta_vs_afterglow`` are ``zero_point`` minus the
    recorded value; ``within_tolerance`` tests ``abs(delta_vs_skynet)`` against
    ``tolerance_mag`` (the upstream diagnostic's own declared agreement
    threshold). A caller who hands in Afterglow's bare base-20 correction
    instead of an absolute zero point gets ``within_tolerance = False`` and an
    ``afterglow_base_convention`` warning, never a silent 20-magnitude miss.
    """

    zero_point: float | None = None
    reference: ZeropointReference | None = None
    delta_vs_skynet: float | None = None
    delta_vs_afterglow: float | None = None
    within_tolerance: bool | None = None
    tolerance_mag: float | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class CatalogResponseReference(KeplerToolModel):
    """A recorded VizieR response shipped next to a recorded zero-point solve.

    The provenance a fixture like ``apass_response.json`` carries -- what was
    asked (``query``: shape, centre, radius), of which catalog release, when,
    with which columns, under what licence (``provenance``) -- surfaced without
    the rows themselves. ``replay_catalog_sources(fixture="full_response")``
    and ``replay_variable_sources`` are what turn the rows into sources.
    """

    field: str
    catalog: str | None = None
    path: str | None = None
    vizier_catalog: str | None = None
    vizier_table: str | None = None
    query: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class FieldCalMatch(KeplerToolModel):
    """One detection the selection replay matched to a catalog candidate.

    ``detected_id`` is the recorded (Afterglow) source id; ``catalog_index``
    is the 0-based position of the matched candidate in the recorded response
    as ``replay_catalog_sources(field, fixture="full_response")`` returns it
    (the whole cone, before clipping), and ``catalog_id`` the id the
    candidate carried into ``perform_field_calibration`` -- the bookkeeping
    ``fieldcal_source_<n>`` it assigns when, as here, the response carries
    none. ``mag``/``mag_error`` are the recorded instrumental values the
    solve consumed; ``ref_mag``/``ref_mag_error`` the resolved reference
    magnitude.
    """

    detected_id: str | None = None
    catalog_index: int | None = None
    catalog_id: str | None = None
    catalog_ra_deg: float | None = None
    catalog_dec_deg: float | None = None
    separation_arcsec: float | None = None
    mag: float | None = None
    mag_error: float | None = None
    ref_mag: float | None = None
    ref_mag_error: float | None = None


class FieldCalReplay(KeplerToolModel):
    """The end-to-end selection replay of a recorded field calibration.

    The recorded detections and the recorded *full* catalog response go
    through ``perform_field_calibration`` together, so -- unlike
    ``solve_zeropoint_from_reference`` and the selected-row replay, which
    start from the rows already known to match -- the matches are chosen
    here: ``num_matched`` of ``num_catalog_candidates`` candidates against
    ``num_detected_sources`` detections, after the recorded VSX rows
    (``num_variable_sources``) have been filtered out. The candidates are
    what the solve was handed: the recorded response (``num_catalog_rows``
    in the cone; ``num_variable_rows`` for VSX) clipped to the frame first,
    exactly as the live query path clips before the solve sees a row.
    ``matches`` is in detection order, the order the solve consumed them.

    ``recorded_num_matched`` / ``recorded_num_not_selected`` are the
    counts ``fit_summary.json`` recorded, and ``selection_matches_recorded``
    is whether the replay chose exactly the recorded rows in the recorded
    order. ``solution`` is the zero point (ABSOLUTE, as ``calc_solution``
    returns it) and ``comparison`` places it against the recorded solve.
    """

    field: str
    frame_path: str | None = None
    catalog: str | None = None
    fixture: str = "full_response"
    num_catalog_rows: int = 0
    num_catalog_candidates: int = 0
    num_variable_rows: int = 0
    num_variable_sources: int = 0
    num_detected_sources: int = 0
    num_matched: int = 0
    num_catalog_not_selected: int = 0
    num_detections_not_selected: int = 0
    recorded_num_matched: int | None = None
    recorded_num_not_selected: int | None = None
    selection_matches_recorded: bool | None = None
    matches: list[FieldCalMatch] = Field(default_factory=list)
    solution: ZeropointSolution | None = None
    comparison: ZeropointComparison | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class PhotometryTargetLibrary(KeplerToolModel):
    """The local FITS library ``run_photometry_on_target`` can actually run on.

    There is no live image archive behind photometry -- ``categories`` is
    exactly ``tools.claude_photometry_haiku_tool.list_bundled_targets()``'s
    output (bundled ``data/optical/`` stems grouped by the category
    embedded in each filename), not a query result.
    """

    categories: dict[str, list[str]] = Field(default_factory=dict)
    total_count: int = 0


class SourceSummary(KeplerToolModel):
    """One detected source's position, magnitude, and flux.

    ``ra_deg``/``dec_deg`` are populated whenever the frame carries a celestial
    WCS -- the same sky position the HR-diagram pipeline's own
    ``extract_photometry_from_fits`` reports, so a source found here can be
    looked up against Gaia or any other catalog the same way.

    ``mag_error``/``flux_error`` are the extraction's own per-source formal
    errors (background/Poisson-noise based, from
    ``algorithms.skylib_lite.photometry.aperture``) -- report them alongside
    ``mag``/``flux`` whenever quoting either, and say plainly that no
    uncertainty was reported when either is ``None`` rather than omitting the
    caveat. Like ``ZeropointSolution.zero_point_error_mag``, this is a formal/
    statistical error only -- it does not include unmodeled systematics.
    """

    x: float | None = None
    y: float | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    mag: float | None = None
    mag_error: float | None = None
    flux: float | None = None
    flux_error: float | None = None


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

    ``curated_period_s`` is the exception: it is not in the file. Scans carry
    no period of their own, so it comes from the curation shipped alongside
    them and is matched by source name. It is null for a scan the curation
    does not cover, which means "not recorded", never "no period".

    It is a **check on** a measured period, not an input to the pipeline.
    Folding at it produces a profile that is a fit to a known answer rather
    than a detection, which is a different claim about the data — see
    ``docs/pulsar-tool-pipeline.md``, "Measure first, check second".
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
    curated_period_s: float | None = None
    curated_difficulty: str | None = None
    period_source: str | None = None
    #: Carried on the scan, not only on the enclosing list, because
    #: ``resolve_pulsar_scan`` returns a bare scan on a single match -- and
    #: "this archive has no curation" is exactly what a caller needs to tell
    #: apart from "this source is not in the curation". Both read as a null
    #: ``curated_period_s`` otherwise.
    warnings: list[ToolWarning] = Field(default_factory=list)


class PulsarScanList(KeplerToolModel):
    """Scans found locally, plus where they were looked for."""

    scans: list[PulsarScan] = Field(default_factory=list)
    search_root: str
    count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class VariableStarFixture(KeplerToolModel):
    """One bundled, paired-source CSV available to the variable-star tools."""

    path: str
    name: str
    source_ids: list[str] = Field(default_factory=list)
    source_count: int = 0
    row_count: int = 0


class VariableStarFixtureList(KeplerToolModel):
    """Stage 0 variable-star fixture discovery result."""

    fixtures: list[VariableStarFixture] = Field(default_factory=list)
    search_root: str
    count: int = 0
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class VariableStarLightCurve(KeplerToolModel):
    """Stage 1 merged paired-source photometry."""

    file: FileMetadata
    artifact: ArtifactRef | None = None
    rows_read: int = 0
    rows_merged: int = 0
    source_ids: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class VariableStarPeriodogram(KeplerToolModel):
    """Stage 2 fixed-grid error-weighted variable-star periodogram."""

    file: FileMetadata
    artifact: ArtifactRef | None = None
    samples: int = 0
    start_period: float | None = None
    end_period: float | None = None
    variable_star: str | None = None
    preview: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class VariableStarFoldedLightCurve(KeplerToolModel):
    """Stage 3 phase-folded differential variable-star photometry."""

    file: FileMetadata
    artifact: ArtifactRef | None = None
    period: float | None = None
    phase: float | None = None
    display_periods: int | None = None
    rows_folded: int = 0
    preview: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class OpticalFrame(KeplerToolModel):
    """An optical FITS frame available on local disk.

    ``path`` is what every image tool takes. Everything else is read from the
    primary header, so listing 39 frames stays cheap -- no pixel data is read.
    """

    path: str
    object_name: str | None = None
    category: str | None = None
    image_filter: str | None = None
    telescope: str | None = None
    date_obs: str | None = None
    exposure_s: float | None = None
    width: int | None = None
    height: int | None = None
    has_wcs: bool = False
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    pixel_scale_arcsec: float | None = None
    size_bytes: int | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)


class OpticalFrameList(KeplerToolModel):
    """Frames found locally, plus where they were looked for.

    ``search_root`` is the primary root -- the ``KEPLER_OPTICAL_DATA_DIR``
    override or the bundled optical directory -- and reports it whether or not
    that directory exists. ``search_roots`` is every root actually inspected,
    which additionally carries the archive download root once something has
    been downloaded into it, so a caller can tell the two apart (BL-11).
    """

    frames: list[OpticalFrame] = Field(default_factory=list)
    search_root: str
    search_roots: list[str] = Field(default_factory=list)
    count: int = 0
    filters: list[str] = Field(default_factory=list)
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
