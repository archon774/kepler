"""Kepler: the pulsar tool pipeline — light curve, periodogram, fold, sonify.

Four tools, one per stage of astromancer's pulsar tool, in the order that tool
runs them. Each stage's artifact is the next stage's input::

    load_pulsar_lightcurve(path)               -> light curve   (.ecsv)
    compute_pulsar_periodogram(lightcurve)     -> a period
    fold_pulsar_lightcurve(lightcurve, period) -> pulse profile (.ecsv)
    sonify_pulsar(lightcurve, period)          -> audio          (.wav)

The order is not a convention, it is a dependency chain: the fold needs a
period, and only the periodogram produces one. Skipping a stage means guessing
a period, which is how you end up folding on a harmonic. See
``docs/pulsar-tool-pipeline.md`` for the flow and where each stage's algorithm
was extracted from.

Every stage accepts either a raw Green Bank / Skynet pulsar file or the
light-curve artifact written by stage 1. Passing the artifact skips re-reading
and re-subtracting the scan, and guarantees later stages see exactly the
samples stage 1 produced.

All four are local: no network, no solver data, no external binaries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
from astropy.table import Table

from algorithms.pulsar import folding, ingest, periodogram, sonification
from tools import artifacts
from tools.config import PREVIEW_ROWS
from tools.models import (
    ArtifactRef,
    FileMetadata,
    PulsarScan,
    PulsarScanList,
    PulsarFoldedProfile,
    PulsarLightCurve,
    PulsarPeriodogram,
    PulsarSonification,
    ToolError,
    ToolWarning,
)

__all__ = [
    "list_pulsar_scans",
    "resolve_pulsar_scan",
    "load_pulsar_lightcurve",
    "compute_pulsar_periodogram",
    "fold_pulsar_lightcurve",
    "sonify_pulsar",
]

#: Audio longer than this is refused rather than silently truncated: a minute
#: of 44.1 kHz stereo is already ~10 MB on disk.
_MAX_AUDIO_SECONDS = 600.0

#: Guard on the periodogram grid. Each step is an O(n) pass over every sample,
#: so this bounds a single call to a few seconds on a typical scan.
_MAX_STEPS = 200_000


class _LoadError(Exception):
    """Raised inside the shared loader; each tool turns it into its own model."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _LightCurve:
    """What every stage works from, however it was obtained."""

    def __init__(
        self,
        time_s: np.ndarray,
        source1: np.ndarray,
        source2: Optional[np.ndarray],
        meta: dict[str, Any],
    ):
        self.time_s = time_s
        self.source1 = source1
        self.source2 = source2
        self.meta = meta

    @property
    def total(self) -> np.ndarray:
        """Both polarizations summed — the best single trace to search.

        Stokes I up to a scale factor. A pulsar's total intensity is what both
        linear feeds see, so summing beats picking one channel, and it is what
        the periodogram should search unless a caller says otherwise.
        """
        if self.source2 is None:
            return self.source1
        return self.source1 + self.source2

    def channel(self, name: str) -> np.ndarray:
        if name == "sum":
            return self.total
        if name == "source1":
            return self.source1
        if name == "source2":
            if self.source2 is None:
                raise _LoadError("invalid_input", "This file has one polarization.")
            return self.source2
        raise _LoadError(
            "invalid_input",
            f"channel must be 'sum', 'source1' or 'source2', got {name!r}",
        )

    def info_fields(self) -> dict[str, Any]:
        return {
            "flavour": self.meta.get("flavour", "cal"),
            "source_name": self.meta.get("source_name"),
            "date_obs": self.meta.get("date_obs"),
            "samples_read": int(self.meta.get("samples_read", self.time_s.size)),
            "samples_used": int(self.time_s.size),
            "time_span_s": self.meta.get("time_span_s"),
            "mean_sample_interval_s": self.meta.get("mean_sample_interval_s"),
            "sample_cadence_s": self.meta.get("sample_cadence_s"),
            "background_subtracted": bool(self.meta.get("background_subtracted", False)),
            "back_scale_s": self.meta.get("back_scale_s"),
        }


def _describe(path: str | Path) -> FileMetadata:
    return artifacts.describe_file(path)


def _load(
    file: FileMetadata,
    *,
    back_scale: float,
    subtract_background: bool,
    warnings: list[ToolWarning],
) -> _LightCurve:
    """Load a raw scan or a stage-1 artifact into a common shape."""

    if not file.exists:
        raise _LoadError("file_not_found", "Pulsar file does not exist.")
    if not file.is_file:
        raise _LoadError("not_a_file", "Path is not a regular file.")

    if (file.suffix or "").lower() == ".ecsv":
        return _load_artifact(file)

    try:
        observation = ingest.read_pulsar_file(file.path)
    except Exception as exc:  # noqa: BLE001 - surfaced on the model
        raise _LoadError("parse_error", str(exc)) from exc

    if observation.sample_count == 0:
        raise _LoadError(
            "no_data",
            "No usable samples. A cal file needs rows whose last column is "
            "non-zero; the leading noise-diode block is dropped by design.",
        )

    source1 = observation.source1
    source2 = observation.source2
    did_subtract = False

    if subtract_background:
        if back_scale <= 0:
            raise _LoadError(
                "invalid_input", f"back_scale must be positive, got {back_scale!r}."
            )
        spacing = observation.mean_sample_interval_s
        if spacing is not None and back_scale <= 2.2 * spacing:
            warnings.append(
                ToolWarning(
                    code="back_scale_too_narrow",
                    message=(
                        f"back_scale={back_scale:g}s is under 2.2x the mean sample "
                        f"spacing ({spacing:.6g}s); the running median degenerates "
                        f"and the subtraction removes the signal with the baseline."
                    ),
                )
            )
        source1 = ingest.background_subtraction(observation.time_s, source1, back_scale)
        if source2 is not None:
            source2 = ingest.background_subtraction(
                observation.time_s, source2, back_scale
            )
        did_subtract = True

    header = observation.header

    def _float(key: str) -> Optional[float]:
        try:
            return float(header[key])
        except (KeyError, TypeError, ValueError):
            return None

    return _LightCurve(
        observation.time_s,
        source1,
        source2,
        {
            "flavour": observation.flavour,
            "source_name": observation.source_name,
            "date_obs": observation.date_obs,
            "samples_read": observation.sample_count,
            "time_span_s": observation.time_span_s or None,
            "mean_sample_interval_s": observation.mean_sample_interval_s,
            "sample_cadence_s": observation.sample_cadence_s,
            "background_subtracted": did_subtract,
            "back_scale_s": back_scale if did_subtract else None,
            "title": observation.title,
            "periodogram_title": observation.periodogram_title,
            "folding_title": observation.folding_title,
            "receiver": header.get("RECEIVER"),
            "obs_freq_mhz": _float("OBSFREQ"),
            "ra_deg": _float("RA(deg)"),
            "dec_deg": _float("DEC(deg)"),
        },
    )


def _load_artifact(file: FileMetadata) -> _LightCurve:
    """Re-read a stage-1 light-curve artifact."""

    try:
        table = Table.read(file.path, format="ascii.ecsv")
    except Exception as exc:  # noqa: BLE001
        raise _LoadError(
            "parse_error", f"Not a readable light-curve artifact: {exc}"
        ) from exc

    if "time_s" not in table.colnames or "source1" not in table.colnames:
        raise _LoadError(
            "invalid_input",
            "Artifact has no 'time_s'/'source1' columns — pass a raw pulsar "
            "file or an artifact from load_pulsar_lightcurve.",
        )

    source2 = (
        np.asarray(table["source2"], dtype=float)
        if "source2" in table.colnames
        else None
    )
    return _LightCurve(
        np.asarray(table["time_s"], dtype=float),
        np.asarray(table["source1"], dtype=float),
        source2,
        dict(table.meta),
    )


def _label(lc: _LightCurve, file: FileMetadata, override: Optional[str]) -> str:
    return override or lc.meta.get("source_name") or Path(file.path).stem


# ---------------------------------------------------------------------------
# Stage 1 — light curve
# ---------------------------------------------------------------------------

def load_pulsar_lightcurve(
    path: str | Path,
    *,
    back_scale: float = ingest.DEFAULT_BACK_SCALE,
    subtract_background: bool = True,
    output_name: Optional[str] = None,
    subdir: Optional[str] = "pulsar",
) -> PulsarLightCurve:
    """Stage 1. Read a pulsar scan and write its light curve.

    Handles both file flavours: a ``.cal.txt`` continuum scan with two
    polarization columns, or a prefolded "standard" file with one. Drops the
    leading noise-diode calibration block, rebases the time axis onto seconds
    since the UTC header, and subtracts a running-median baseline.

    ``back_scale`` is the baseline window in seconds. Leaving the subtraction
    on is what makes the pulses stand out from the receiver's drifting
    continuum level; every later stage is far less sensitive without it.

    The artifact is the pipeline's handoff — give its path to the periodogram,
    fold and sonify stages rather than re-reading the raw scan.
    """
    file = _describe(path)
    warnings: list[ToolWarning] = []

    try:
        lc = _load(
            file,
            back_scale=back_scale,
            subtract_background=subtract_background,
            warnings=warnings,
        )
    except _LoadError as exc:
        return PulsarLightCurve(
            file=file, errors=[ToolError(code=exc.code, message=exc.message)]
        )

    columns = {"time_s": lc.time_s, "source1": lc.source1}
    if lc.source2 is not None:
        columns["source2"] = lc.source2
    table = Table(columns)
    table.meta.update({k: v for k, v in lc.meta.items() if v is not None})

    artifact = artifacts.write_table(
        table, _label(lc, file, output_name) + "_lightcurve", subdir=subdir, fmt="ecsv"
    )

    nyquist = None
    if lc.meta.get("mean_sample_interval_s"):
        nyquist = 2 * lc.meta["mean_sample_interval_s"]

    return PulsarLightCurve(
        file=file,
        artifact=artifact,
        channels=2 if lc.source2 is not None else 1,
        receiver=lc.meta.get("receiver"),
        obs_freq_mhz=lc.meta.get("obs_freq_mhz"),
        ra_deg=lc.meta.get("ra_deg"),
        dec_deg=lc.meta.get("dec_deg"),
        nyquist_period_s=nyquist,
        warnings=warnings,
        **lc.info_fields(),
    )


# ---------------------------------------------------------------------------
# Stage 2 — periodogram
# ---------------------------------------------------------------------------

def _top_peaks(
    x: np.ndarray, power: np.ndarray, count: int, min_separation: float
) -> list[dict[str, Any]]:
    """Best-separated candidates, strongest first.

    Not upstream — astromancer marks only the global maximum. A tool needs
    more, because the global peak is often a harmonic of the true period, and
    a caller that only ever sees one number has no way to notice.
    """
    peaks: list[dict[str, Any]] = []
    for index in np.argsort(power)[::-1]:
        value = float(x[index])
        if any(
            abs(value - peak["x"]) < min_separation * max(value, peak["x"])
            for peak in peaks
        ):
            continue
        peaks.append({"x": value, "power": float(power[index])})
        if len(peaks) >= count:
            break
    return peaks


def compute_pulsar_periodogram(
    path: str | Path,
    *,
    start: Optional[float] = None,
    stop: Optional[float] = None,
    steps: int = periodogram.DEFAULT_STEPS,
    freq_mode: bool = False,
    channel: str = "sum",
    back_scale: float = ingest.DEFAULT_BACK_SCALE,
    subtract_background: bool = True,
    output_name: Optional[str] = None,
    subdir: Optional[str] = "pulsar",
) -> PulsarPeriodogram:
    """Stage 2. Lomb-Scargle the light curve to find the pulsar's period.

    This is the stage that produces the period the fold and the folded
    sonification need. ``start``/``stop`` default to the observation's own
    Nyquist bounds — twice the mean sample interval, up to 3 s — which is what
    astromancer seeds its form with.

    ``channel`` selects what to search: ``"sum"`` (both polarizations added,
    the default and usually the most sensitive), ``"source1"`` or
    ``"source2"``.

    **Read ``peak_fold_snr`` before trusting ``peak_period_s``.** It folds the
    data at the peak and measures the pulse: above ~8 the peak is real, near 1
    it is not. ``peak_confidence`` is *not* that check — its false-alarm
    threshold assumes white noise, and mains interference and baseline red
    noise both clear 3 sigma while folding to nothing. On four of the five
    bundled scans the strongest peak is exactly that: a confident artifact.

    Check ``top_peaks`` too — a strong peak at twice or half the listed period
    means the fundamental may be the other one.

    A blind search on one 60-second scan only works for a bright source. If it
    fails, vary ``back_scale`` (the spurious peak often moves with it while a
    real pulsar does not), narrow ``start``/``stop`` away from the artifact, or
    take the period from ``search_atnf``.
    """
    file = _describe(path)
    warnings: list[ToolWarning] = []

    if steps <= 0 or steps > _MAX_STEPS:
        return PulsarPeriodogram(
            file=file,
            errors=[
                ToolError(
                    code="invalid_input",
                    message=f"steps must be in (0, {_MAX_STEPS}], got {steps!r}.",
                )
            ],
        )

    try:
        lc = _load(
            file,
            back_scale=back_scale,
            subtract_background=subtract_background,
            warnings=warnings,
        )
        values = lc.channel(channel)
    except _LoadError as exc:
        return PulsarPeriodogram(
            file=file, errors=[ToolError(code=exc.code, message=exc.message)]
        )

    info = lc.info_fields()

    try:
        result = periodogram.compute_periodogram(
            lc.time_s, values, start=start, stop=stop, steps=steps, freq_mode=freq_mode
        )
    except ValueError as exc:
        return PulsarPeriodogram(
            file=file,
            errors=[ToolError(code="invalid_input", message=str(exc))],
            **info,
        )

    if not info["background_subtracted"]:
        warnings.append(
            ToolWarning(
                code="background_not_subtracted",
                message="Without baseline subtraction the receiver's drifting "
                "continuum dominates the spectrum at long periods.",
            )
        )
    if result.peak_confidence_level is None:
        warnings.append(
            ToolWarning(
                code="peak_below_confidence",
                message="The peak clears no false-alarm threshold; treat the "
                "period as a non-detection rather than a measurement.",
            )
        )

    # Fold at the peak and see whether it concentrates flux. This is the check
    # that actually discriminates: the false-alarm threshold above assumes
    # white noise, and radio data is not white. Mains interference and the red
    # noise left by baseline subtraction both clear 3 sigma comfortably while
    # folding to nothing. Measured on the bundled scans, four of five have a
    # strongest peak that reads "99.73% Confidence" and is not the pulsar.
    peak_fold_snr: Optional[float] = None
    if result.peak_period_s and result.peak_period_s > 0:
        try:
            peak_fold_snr = folding.fold_lightcurve(
                lc.time_s, lc.source1, lc.source2, period_s=result.peak_period_s
            ).pulse_snr()
        except ValueError:
            peak_fold_snr = None

    if peak_fold_snr is not None and peak_fold_snr < 8:
        warnings.append(
            ToolWarning(
                code="peak_does_not_fold",
                message=(
                    f"The strongest peak folds to only {peak_fold_snr:.1f} sigma, so it "
                    f"is probably interference or baseline residual rather than a "
                    f"pulsar -- regardless of its false-alarm confidence. Try a "
                    f"different back_scale, narrow the search away from the "
                    f"suspect period, or get the period from search_atnf."
                ),
            )
        )

    table = Table(
        {
            ("frequency_hz" if freq_mode else "period_s"): result.x,
            "power": result.power,
        }
    )
    artifact = artifacts.write_table(
        table, _label(lc, file, output_name) + "_periodogram", subdir=subdir, fmt="ecsv"
    )

    return PulsarPeriodogram(
        file=file,
        artifact=artifact,
        mode="frequency" if freq_mode else "period",
        search_start=result.start,
        search_stop=result.stop,
        steps=result.steps,
        channel=channel,
        peak_period_s=result.peak_period_s,
        peak_power=result.peak_power,
        peak_confidence=result.peak_confidence_level,
        peak_fold_snr=peak_fold_snr,
        confidence_thresholds=result.confidence,
        top_peaks=_top_peaks(result.x, result.power, 5, 0.02),
        warnings=warnings,
        **info,
    )


# ---------------------------------------------------------------------------
# Stage 3 — fold
# ---------------------------------------------------------------------------

def fold_pulsar_lightcurve(
    path: str | Path,
    period_s: float,
    *,
    bins: int = folding.DEFAULT_BINS,
    phase: float = folding.DEFAULT_PHASE,
    display_period: int = folding.DEFAULT_DISPLAY_PERIOD,
    cal: float = 1.0,
    back_scale: float = ingest.DEFAULT_BACK_SCALE,
    subtract_background: bool = True,
    output_name: Optional[str] = None,
    subdir: Optional[str] = "pulsar",
) -> PulsarFoldedProfile:
    """Stage 3. Fold the light curve at ``period_s`` into a pulse profile.

    Every rotation is stacked on the others, so a real pulse adds coherently
    while noise averages down — which is why a pulsar invisible in the raw scan
    appears here. Get ``period_s`` from ``compute_pulsar_periodogram``, or from
    ``search_atnf`` for a known source.

    ``pulse_snr`` on the result is how you tell whether the period was right:
    above ~8 is a real detection, near 1 means a wrong period or a source too
    faint in this scan. **Folding at the wrong period produces a flat profile,
    not an error.**

    ``bins`` is samples per period (100 upstream), ``phase`` shifts the profile
    by that fraction of a period, and ``display_period=2`` emits two cycles
    side by side so a pulse straddling the wrap is easier to read.
    """
    file = _describe(path)
    warnings: list[ToolWarning] = []

    if bins <= 0:
        return PulsarFoldedProfile(
            file=file,
            errors=[
                ToolError(
                    code="invalid_input", message=f"bins must be positive, got {bins!r}."
                )
            ],
        )
    if display_period not in (1, 2):
        return PulsarFoldedProfile(
            file=file,
            errors=[
                ToolError(
                    code="invalid_input",
                    message=f"display_period must be 1 or 2, got {display_period!r}.",
                )
            ],
        )

    try:
        lc = _load(
            file,
            back_scale=back_scale,
            subtract_background=subtract_background,
            warnings=warnings,
        )
    except _LoadError as exc:
        return PulsarFoldedProfile(
            file=file, errors=[ToolError(code=exc.code, message=exc.message)]
        )

    info = lc.info_fields()

    span = info.get("time_span_s")
    if span and period_s > span:
        warnings.append(
            ToolWarning(
                code="period_exceeds_baseline",
                message=f"period {period_s:g}s is longer than the {span:.3g}s "
                f"observation; the fold covers less than one rotation.",
            )
        )

    try:
        profile = folding.fold_lightcurve(
            lc.time_s,
            lc.source1,
            lc.source2,
            period_s=period_s,
            bins=bins,
            phase=phase,
            display_period=display_period,
            cal=cal,
        )
    except ValueError as exc:
        return PulsarFoldedProfile(
            file=file,
            errors=[ToolError(code="invalid_input", message=str(exc))],
            **info,
        )

    snr = profile.pulse_snr()
    if snr is not None and snr < 8:
        warnings.append(
            ToolWarning(
                code="weak_or_absent_pulse",
                message=f"Profile peaks at only {snr:.1f} sigma above its own "
                f"scatter. Either the period is wrong or the source is too faint "
                f"in this scan; a wrong period folds flat, not to an error.",
            )
        )

    columns: dict[str, np.ndarray] = {
        "phase_s": profile.phase_s,
        "source1": profile.source1,
    }
    if profile.source2 is not None:
        columns["source2"] = profile.source2
        columns["difference"] = profile.difference
        columns["sum"] = profile.sum
    table = Table(columns)
    table.meta.update({k: v for k, v in lc.meta.items() if v is not None})
    table.meta["period_s"] = float(period_s)
    table.meta["bins"] = int(bins)

    artifact = artifacts.write_table(
        table, _label(lc, file, output_name) + "_folded", subdir=subdir, fmt="ecsv"
    )

    return PulsarFoldedProfile(
        file=file,
        artifact=artifact,
        period_s=float(period_s),
        bins=int(bins),
        bins_filled=profile.bin_count,
        phase=float(phase),
        display_period=int(display_period),
        cal=float(cal),
        samples_folded=profile.samples_folded,
        pulse_snr=snr,
        channels=2 if profile.source2 is not None else 1,
        preview=artifacts.preview_rows(table, PREVIEW_ROWS),
        warnings=warnings,
        **info,
    )


# ---------------------------------------------------------------------------
# Stage 4 — sonify
# ---------------------------------------------------------------------------

def sonify_pulsar(
    path: str | Path,
    *,
    period_s: Optional[float] = None,
    bins: int = folding.DEFAULT_BINS,
    phase: float = folding.DEFAULT_PHASE,
    speed: float = sonification.DEFAULT_SPEED,
    cal: float = sonification.DEFAULT_CAL,
    back_scale: float = ingest.DEFAULT_BACK_SCALE,
    subtract_background: bool = True,
    stereo: bool = True,
    audio_seconds: float = sonification.DURATION_SECONDS,
    max_input_seconds: float = sonification.MAX_INPUT_SECONDS,
    sample_rate: int = sonification.SAMPLE_RATE,
    seed: Optional[int] = sonification.DEFAULT_NOISE_SEED,
    output_name: Optional[str] = None,
    subdir: Optional[str] = "pulsar",
) -> PulsarSonification:
    """Stage 4. Render the pulsar as audio.

    The light curve becomes the amplitude envelope on white noise, so pulses
    arrive as bursts of static, and the two polarizations become the two stereo
    channels.

    **Pass ``period_s`` whenever you have one.** With it, the scan is folded
    into a pulse profile and that profile is looped at the true rotation rate —
    upstream's primary rendering, and the one that actually sounds like a
    pulsar, because every rotation reinforces the same pulse. Get the period
    from ``compute_pulsar_periodogram`` or ``search_atnf``.

    Without it, the raw scan plays through once. That is upstream's secondary
    rendering: it works, but a faint pulsar stays buried in the noise, and
    playback drifts a few percent from sky time (reported as
    ``playback_stretch``) because the synthesis ignores sample timestamps.

    ``speed`` divides the pass duration, ``audio_seconds`` sets the output
    length, and ``seed`` makes the noise carrier reproducible.
    """
    file = _describe(path)
    warnings: list[ToolWarning] = []

    if audio_seconds <= 0 or audio_seconds > _MAX_AUDIO_SECONDS:
        return PulsarSonification(
            file=file,
            errors=[
                ToolError(
                    code="invalid_input",
                    message=f"audio_seconds must be in (0, {_MAX_AUDIO_SECONDS:g}], "
                    f"got {audio_seconds!r}.",
                )
            ],
        )
    for name, value in (("speed", speed), ("sample_rate", sample_rate)):
        if value <= 0:
            return PulsarSonification(
                file=file,
                errors=[
                    ToolError(
                        code="invalid_input",
                        message=f"{name} must be positive, got {value!r}.",
                    )
                ],
            )

    try:
        lc = _load(
            file,
            back_scale=back_scale,
            subtract_background=subtract_background,
            warnings=warnings,
        )
    except _LoadError as exc:
        return PulsarSonification(
            file=file, errors=[ToolError(code=exc.code, message=exc.message)]
        )

    info = lc.info_fields()
    source2 = lc.source2 if stereo else None
    if stereo and lc.source2 is None:
        warnings.append(
            ToolWarning(
                code="mono_source",
                message=f"{info['flavour']} files carry one flux column; rendering mono.",
            )
        )

    playback_stretch: Optional[float] = None
    pulse_snr: Optional[float] = None
    used_bins: Optional[int] = None

    if period_s is not None:
        # --- Folded rendering: upstream's primary path. --------------------
        try:
            profile = folding.fold_lightcurve(
                lc.time_s,
                lc.source1,
                source2,
                period_s=period_s,
                bins=bins,
                phase=phase,
                cal=cal,
            )
            render1, render2, pass_seconds = sonification.folded_sonification_input(
                profile
            )
        except ValueError as exc:
            return PulsarSonification(
                file=file,
                errors=[ToolError(code="invalid_input", message=str(exc))],
                **info,
            )
        rendering = "folded"
        pulse_snr = profile.pulse_snr()
        used_bins = profile.bins
        # cal was already applied by the fold; applying it again would square it.
        render_cal = 1.0
        if pulse_snr is not None and pulse_snr < 8:
            warnings.append(
                ToolWarning(
                    code="weak_or_absent_pulse",
                    message=f"Folded profile peaks at only {pulse_snr:.1f} sigma; "
                    f"the render will sound like noise. Check the period.",
                )
            )
    else:
        # --- Light-curve rendering: upstream's secondary path. -------------
        _, render1, render2, pass_seconds = sonification.window_sonification_input(
            lc.time_s, lc.source1, source2, max_seconds=max_input_seconds
        )
        rendering = "lightcurve"
        render_cal = cal
        warnings.append(
            ToolWarning(
                code="unfolded_rendering",
                message="No period given, so the raw scan plays through once. "
                "Pass period_s (from compute_pulsar_periodogram or search_atnf) "
                "to fold first — that is what makes the pulse audible.",
            )
        )

        if render1.size == 0:
            return PulsarSonification(
                file=file,
                errors=[
                    ToolError(code="no_data", message="Every sample was NaN after ingest.")
                ],
                **info,
            )
        if pass_seconds <= 0:
            return PulsarSonification(
                file=file,
                errors=[
                    ToolError(
                        code="zero_duration",
                        message=f"Observation spans {pass_seconds:g}s; nothing to play back.",
                    )
                ],
                **info,
            )

    try:
        rendered = sonification.sonify(
            render1,
            render2,
            pass_seconds=pass_seconds,
            speed=speed,
            cal=render_cal,
            sample_rate=sample_rate,
            output_seconds=audio_seconds,
            seed=seed,
        )
    except ValueError as exc:
        return PulsarSonification(
            file=file,
            errors=[ToolError(code="invalid_input", message=str(exc))],
            **info,
        )

    if rendered.data_max == rendered.data_min:
        warnings.append(
            ToolWarning(
                code="flat_light_curve",
                message="Light curve is constant; the render is silent.",
            )
        )

    # How far the audio drifts from sky time. One pass of audio lasts
    # `pass_audio_seconds`; what that pass represents in the sky differs by
    # rendering. Folded, it is one rotation. Unfolded, it is however long the
    # rendered samples would span at the instrument's nominal cadence -- which
    # is not their actual span, because the synthesis compresses gaps away.
    #
    # Neither rendering is exactly 1.0: `samplesPerPoint` is floored to a whole
    # number of output samples, so a pass is quantized rather than fitted. The
    # folded path avoids only the gap-compression term, not this one.
    sky_seconds_per_pass: Optional[float] = None
    if rendering == "folded":
        sky_seconds_per_pass = period_s
    elif info.get("sample_cadence_s"):
        sky_seconds_per_pass = render1.size * info["sample_cadence_s"]

    if sky_seconds_per_pass:
        playback_stretch = rendered.pass_audio_seconds / sky_seconds_per_pass
        drift = playback_stretch * speed
        if abs(drift - 1.0) > 0.01:
            warnings.append(
                ToolWarning(
                    code="playback_not_real_time",
                    message=(
                        f"Audio runs {abs(drift - 1) * 100:.1f}% "
                        f"{'slow' if drift > 1 else 'fast'} against the observation "
                        f"clock: the synthesis ignores sample timestamps, and this "
                        f"file has gaps. A period measured off the audio will be off "
                        f"by that much -- use search_atnf for the real one."
                    ),
                )
            )

    # Stage-consistent naming: `<source>_sonification_<rendering>.wav`, matching
    # the `<source>_lightcurve/_periodogram/_folded` .ecsv names the earlier
    # stages write. Upstream's own download filename is a browser concern (it
    # was split off into `downloadWav()` at extraction) and is a poor fit here:
    # it is the *chart* title, so a folded render would land under
    # "..._prefolded_light_curve.wav", which says the opposite of what it is.
    # Both upstream titles stay available in the artifact metadata.
    label = output_name or f"{_label(lc, file, None)}_sonification_{rendering}"
    output_path = artifacts.reserve_artifact_path(label, subdir=subdir, ext="wav")
    try:
        written = sonification.write_wav(output_path, rendered)
    except OSError as exc:
        return PulsarSonification(
            file=file,
            errors=[ToolError(code="write_failed", message=str(exc))],
            **info,
        )

    return PulsarSonification(
        file=file,
        artifact=ArtifactRef(path=str(written), format="wav", row_count=rendered.frames),
        rendering=rendering,
        period_s=period_s,
        bins=used_bins,
        pulse_snr=pulse_snr,
        audio_seconds=rendered.duration_s,
        sample_rate=rendered.sample_rate,
        channels=rendered.channels,
        mode=rendered.mode,
        pass_seconds=rendered.pass_seconds,
        playback_stretch=playback_stretch,
        speed=speed,
        cal=cal,
        noise_seed=seed,
        warnings=warnings,
        **info,
    )


# ---------------------------------------------------------------------------
# Stage 0 — finding a scan
# ---------------------------------------------------------------------------

#: Where scans are looked for. Overridable so a caller with their own archive
#: does not have to move files into the repo.
PULSAR_DATA_DIR_ENV = "KEPLER_PULSAR_DATA_DIR"

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _pulsar_data_dir() -> Path:
    from tools.config import env_path

    return env_path(PULSAR_DATA_DIR_ENV, _REPO_ROOT / "test_data" / "pulsar") or (
        _REPO_ROOT / "test_data" / "pulsar"
    )


def _normalize_pulsar_name(name: str) -> str:
    """Reduce a pulsar designation to comparable characters.

    ``PSR B0329+54``, ``B0329+54``, ``psr_b0329_54`` and ``b032954`` all reduce
    to ``b032954``. The sign is dropped along with the other punctuation, which
    is lossy but matches what Skynet already did to its own filenames: it
    writes both B1133**+**16 and B2045**−**16 as ``_16``, so the sign is not
    recoverable from a scan name anyway.
    """
    lowered = name.strip().lower()
    if lowered.startswith("psr"):
        lowered = lowered[3:]
    return re.sub(r"[^a-z0-9]", "", lowered)


def _scan_summary(path: Path) -> PulsarScan:
    """Read one scan's ``#`` header without parsing its samples."""

    header: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            match = re.match(r"^#\s*([A-Za-z_][A-Za-z0-9_()]*)\s*=\s*(.*)$", line.strip())
            if match:
                header.setdefault(match.group(1), match.group(2).strip())

    def _float(key: str) -> Optional[float]:
        try:
            return float(header[key])
        except (KeyError, TypeError, ValueError):
            return None

    return PulsarScan(
        path=str(path),
        source_name=header.get("SRC_NAME"),
        date_obs=header.get("DATE_OBS"),
        receiver=header.get("RECEIVER"),
        obs_freq_mhz=_float("OBSFREQ"),
        ra_deg=_float("RA(deg)"),
        dec_deg=_float("DEC(deg)"),
        duration_s=_float("DURATION"),
        size_bytes=path.stat().st_size,
    )


def list_pulsar_scans(directory: str | Path | None = None) -> PulsarScanList:
    """Stage 0. List the pulsar scans available on local disk.

    There is no archive query behind the pulsar pipeline: every stage takes a
    file path, and a path only resolves if the scan is already here. This is
    the discovery step, so a caller asked to work on a named pulsar can find
    out what is actually on hand instead of guessing a path.

    Reads only each file's ``#`` header, so it stays cheap.
    """
    root = Path(directory).expanduser() if directory else _pulsar_data_dir()
    errors: list[ToolError] = []

    if not root.is_dir():
        errors.append(
            ToolError(
                code="directory_not_found",
                message=f"No pulsar data directory at {root}. Set "
                f"{PULSAR_DATA_DIR_ENV} to point at one.",
            )
        )
        return PulsarScanList(scans=[], search_root=str(root), count=0, errors=errors)

    scans = [_scan_summary(p) for p in sorted(root.glob("*.txt")) if p.is_file()]
    return PulsarScanList(scans=scans, search_root=str(root), count=len(scans))


def resolve_pulsar_scan(
    name: str, directory: str | Path | None = None
) -> PulsarScan | PulsarScanList:
    """Stage 0. Find the scan for a pulsar name, or an explicit path.

    Accepts a designation in any usual spelling (``B0329+54``, ``PSR
    B0329+54``, ``psr_b0329_54``), a bare filename, or a full path. Matching is
    on alphanumerics only, so punctuation and the declination sign do not have
    to agree -- which they cannot, since Skynet writes both B1133+16 and
    B2045-16 as ``_16``.

    Returns the single matching :class:`~tools.models.PulsarScan`. An
    ambiguous or unmatched name returns a
    :class:`~tools.models.PulsarScanList` carrying the candidates and an
    error, so the caller can choose rather than guess.
    """
    root = Path(directory).expanduser() if directory else _pulsar_data_dir()

    direct = Path(name).expanduser()
    if direct.is_file():
        return _scan_summary(direct)
    if (root / name).is_file():
        return _scan_summary(root / name)

    listing = list_pulsar_scans(root)
    if listing.errors:
        return listing

    wanted = _normalize_pulsar_name(name)
    if not wanted:
        listing.errors.append(
            ToolError(code="invalid_input", message="name must not be blank")
        )
        return listing

    matches = [
        scan
        for scan in listing.scans
        if wanted in _normalize_pulsar_name(scan.source_name or "")
        or wanted in _normalize_pulsar_name(Path(scan.path).name)
    ]

    if len(matches) == 1:
        return matches[0]

    known = ", ".join(sorted({s.source_name or Path(s.path).name for s in listing.scans}))
    if not matches:
        listing.errors.append(
            ToolError(
                code="not_found",
                message=f"No local scan matches {name!r}. Available: {known}.",
            )
        )
        return listing

    listing.scans = matches
    listing.count = len(matches)
    listing.errors.append(
        ToolError(
            code="ambiguous",
            message=f"{name!r} matches {len(matches)} scans; pass a path instead.",
        )
    )
    return listing
