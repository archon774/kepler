"""Pulsar ingest and sonification.

Unlike the rest of this suite, ``algorithms/pulsar/`` is a **language port**
rather than a byte-preserving extraction — the upstream sonifier is astromancer
TypeScript welded to browser APIs, so it cannot be executed to compare against.
That changes what these tests can be. They check three separable things:

1. **Arithmetic identity with the TypeScript**, where the TypeScript is short
   enough to work out by hand — ``interpolate_linear``'s weights and length,
   ``median``'s even/odd rule, the ``Math.floor`` in the PCM conversion.
2. **The preserved upstream quirks**, each pinned with the reason it is
   preserved, so a later "cleanup" fails here rather than silently changing
   what every rendered file sounds like.
3. **That the output is actually a pulsar** — the one check that does not
   depend on the port being faithful. PSR B0329+54 is the brightest pulsar in
   the northern sky; folding the ingested scan at its catalogued period has to
   produce a pulse, and it does at >100 sigma.

Everything here is local, deterministic and bounded: renders are short, and
the noise carrier is seeded.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from algorithms.pulsar import folding, ingest, periodogram, sonification
from tests.conftest import (
    PULSAR_ATNF,
    PULSAR_DIFFICULTY,
    PULSAR_PERIODS_S,
    PULSAR_SCANS,
)
from tools.pulsar import (
    compute_pulsar_periodogram,
    fold_pulsar_lightcurve,
    load_pulsar_lightcurve,
    sonify_pulsar,
)

ALL_SCANS = sorted(PULSAR_SCANS)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scan", ALL_SCANS)
def test_every_scan_ingests(pulsar_path, scan) -> None:
    obs = ingest.read_pulsar_file(pulsar_path(scan))

    assert obs.flavour == "cal"
    assert obs.sample_count > 10_000
    assert obs.source1.size == obs.source2.size == obs.sample_count
    assert obs.source_name
    assert obs.date_obs
    assert obs.utc_s is not None
    # Rebased onto seconds-since-UTC-start. It starts a few seconds in rather
    # than at zero because the dropped noise-diode block occupies the opening
    # of every scan — 124 rows at 0.1 s is ~12 s of wall clock.
    assert 0 < obs.time_s[0] < 20.0
    assert np.all(np.diff(obs.time_s) > 0)
    assert 50 < obs.time_span_s < 70


def test_leading_calibration_block_is_dropped(pulsar_path) -> None:
    """The last-column filter is what removes the noise-diode block.

    Skynet cal files open with a ~124-row noise-diode calibration block sampled
    at 0.1 s, ahead of the 4.2 ms science data. Upstream drops it with
    ``lastValue !== 0`` on the final column, not by reading the ``Cal`` flag.
    If that filter is ever "simplified" away, the ingest silently gains a
    hundred rows of 24x-slower samples at the head of the series — which the
    sonification, playing back uniformly in index, would smear across the
    opening seconds of every rendered file.
    """
    path = pulsar_path("b0329")
    text = path.read_text()

    raw_rows = [
        line for line in text.split("\n")
        if line.strip() and not line.startswith("#")
    ]
    obs = ingest.read_pulsar_file(path)

    assert len(raw_rows) == 13_178, "fixture changed; update the counts below"
    assert obs.sample_count == 13_054
    assert len(raw_rows) - obs.sample_count == 124

    # Every dropped row is one whose final column is zero.
    kept = {
        line for line in raw_rows
        if float(line.strip().split()[-1]) != 0
    }
    assert len(kept) == obs.sample_count


def test_polarization_columns_are_read_in_upstream_order(pulsar_path) -> None:
    """PRESERVED UPSTREAM QUIRK — the two polarization labels are transposed.

    The Skynet files write ``... El(deg)  YY1  XX1  Cal  Sweeps``, but
    ``uploadHandler``'s fixed header list names index 5 ``XX1`` and index 6
    ``YY1``. It then reads ``row['YY1']`` into ``source1``. Net effect:
    ``source1`` carries the file's *XX1* column and ``source2`` its *YY1*.

    Verified against astromancer ``pulsar-light-curve.component.ts`` (the
    ``headers`` array and the ``this.ys``/``this.xs`` assignments below it).
    Preserved because it decides which polarization reaches which stereo
    channel; correcting it would swap the channels of every rendered file.
    """
    obs = ingest.read_pulsar_file(pulsar_path("b0329"))

    first_row = next(
        line for line in pulsar_path("b0329").read_text().split("\n")
        if line.strip() and not line.startswith("#")
        and float(line.strip().split()[-1]) != 0
    )
    columns = [float(token) for token in first_row.split()]

    # File column 5 is labelled YY1, column 6 XX1 — and they land the other way.
    assert obs.source1[0] == columns[6]
    assert obs.source2[0] == columns[5]
    assert ingest.CAL_COLUMNS[5] == "XX1"
    assert ingest.CAL_COLUMNS[6] == "YY1"


def test_standard_flavour_is_detected_and_parsed() -> None:
    """The ``"# Input"`` discriminator and the prefolded single-column branch.

    No standard-flavour file ships in ``test_data`` — all five scans are cal
    files — so this exercises the branch on a minimal literal built to the
    upstream format.
    """
    text = "\n".join(
        [
            "# Input file",
            "# P_topo (ms) = 714.5199",
            "# Candidate = B0329+54",
            "0.0   1.0",
            "0.1   2.5",
            "0.2   1.5",
            "",
        ]
    )

    obs = ingest.parse_pulsar_text(text)

    assert obs.flavour == "standard"
    assert obs.source2 is None
    assert obs.title == "B0329+54"
    # round(714.5199 / 1000 * 10000) / 10000
    assert obs.period_s == 0.7145
    np.testing.assert_allclose(obs.time_s, [0.0, 0.1, 0.2])
    np.testing.assert_allclose(obs.source1, [1.0, 2.5, 1.5])


def test_median_follows_the_javascript_even_odd_rule() -> None:
    assert ingest.median(np.array([3.0, 1.0, 2.0])) == 2.0
    assert ingest.median(np.array([4.0, 1.0, 3.0, 2.0])) == 2.5
    assert ingest.median(np.array([1.0, np.nan, 3.0])) == 2.0
    assert np.isnan(ingest.median(np.array([])))


def test_background_subtraction_removes_a_drifting_baseline() -> None:
    """Running median over ``[t - dt/2, t + dt/2]``, subtracted per sample."""
    t = np.arange(0.0, 10.0, 0.01)
    baseline = 100.0 + 5.0 * t
    signal = np.zeros_like(t)
    signal[::100] = 20.0  # a spike once a second

    subtracted = ingest.background_subtraction(t, baseline + signal, 1.0)

    # The ramp is gone; the spikes survive.
    assert abs(np.median(subtracted)) < 0.5
    assert subtracted[::100].min() > 15.0


def test_background_subtraction_window_is_inclusive_at_the_upper_edge() -> None:
    """``jmax`` advances on ``<=`` and ``jmin`` on ``<`` — an asymmetric window.

    Verified against ``pulsar.service.ts`` 722-739. On evenly spaced samples
    with ``dt`` an exact multiple of the spacing, this makes the window carry
    one more sample above the centre than below it.
    """
    t = np.arange(5, dtype=float)
    flux = np.array([0.0, 0.0, 10.0, 0.0, 0.0])

    subtracted = ingest.background_subtraction(t, flux, 2.0)

    # At i=2 the window is [1, 3] inclusive -> {0, 10, 0}, median 0.
    assert subtracted[2] == 10.0
    # At i=1 the window is t in [0, 2] -> {0, 0, 10}, median 0.
    assert subtracted[1] == 0.0


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def test_interpolate_linear_matches_the_typescript_by_hand() -> None:
    """``(n - 1) * (factor + 1) + 1`` points, weights ``j / (factor + 1)``."""
    result = sonification.interpolate_linear(np.array([0.0, 1.0]), 3)

    assert result.size == (2 - 1) * (3 + 1) + 1
    np.testing.assert_allclose(result, [0.0, 0.25, 0.5, 0.75, 1.0])


def test_interpolate_linear_length_and_endpoints() -> None:
    data = np.array([2.0, 4.0, 8.0])
    result = sonification.interpolate_linear(data, 1)

    assert result.size == (3 - 1) * (1 + 1) + 1
    np.testing.assert_allclose(result, [2.0, 3.0, 4.0, 6.0, 8.0])
    assert result[0] == data[0]
    assert result[-1] == data[-1]


def test_interpolate_linear_degenerate_inputs() -> None:
    np.testing.assert_allclose(
        sonification.interpolate_linear(np.array([5.0]), 4), [5.0]
    )
    assert sonification.interpolate_linear(np.array([]), 4).size == 0


def test_window_keeps_the_first_sixty_seconds() -> None:
    t = np.arange(0.0, 120.0, 0.5)
    y = np.ones_like(t)

    _, kept, _, duration = sonification.window_sonification_input(t, y, None)

    assert duration <= sonification.MAX_INPUT_SECONDS
    assert kept.size == int(sonification.MAX_INPUT_SECONDS / 0.5) + 1


def test_window_drops_nan_rows() -> None:
    t = np.array([0.0, 1.0, 2.0, 3.0])
    y1 = np.array([1.0, np.nan, 3.0, 4.0])
    y2 = np.array([1.0, 2.0, 3.0, np.nan])

    _, kept1, kept2, _ = sonification.window_sonification_input(t, y1, y2)

    np.testing.assert_allclose(kept1, [1.0, 3.0])
    np.testing.assert_allclose(kept2, [1.0, 3.0])


def test_sonify_renders_bounded_interleaved_stereo_pcm() -> None:
    rng = np.random.default_rng(1)
    y1 = rng.random(500)
    y2 = rng.random(500)

    result = sonification.sonify(y1, y2, pass_seconds=2.0, output_seconds=0.5)

    assert result.channels == 2
    assert result.mode == "burst"
    assert result.pcm.dtype == np.int16
    assert result.frames == int(0.5 * sonification.SAMPLE_RATE)
    assert result.pcm.size == result.frames * 2
    # Peak-normalized to 0.95 before the int16 scale, never clipped. The bounds
    # are asymmetric because the conversion floors: +0.95 lands on 31128 and
    # -0.95 on -31129.
    assert result.pcm.max() <= 31128
    assert result.pcm.min() >= -31129
    assert np.abs(result.pcm).max() > int(0.9 * 32767)


def test_sonify_is_mono_without_a_second_polarization() -> None:
    result = sonification.sonify(
        np.random.default_rng(2).random(200), None, pass_seconds=1.0, output_seconds=0.2
    )

    assert result.channels == 1
    assert result.pcm.size == result.frames


def test_sonify_is_deterministic_under_a_seed() -> None:
    y = np.random.default_rng(3).random(300)
    kwargs = dict(pass_seconds=1.0, output_seconds=0.2)

    first = sonification.sonify(y, None, seed=11, **kwargs)
    second = sonification.sonify(y, None, seed=11, **kwargs)
    other = sonification.sonify(y, None, seed=12, **kwargs)

    np.testing.assert_array_equal(first.pcm, second.pcm)
    assert not np.array_equal(first.pcm, other.pcm)


def test_flat_light_curve_renders_silence_without_dividing_by_zero() -> None:
    """``(globalMax - globalMin || 1)`` — a constant curve divides by 1."""
    result = sonification.sonify(
        np.full(100, 7.0), None, pass_seconds=1.0, output_seconds=0.1
    )

    assert result.data_min == result.data_max == 7.0
    assert np.abs(result.pcm).max() == 0


def test_pcm_conversion_floors_rather_than_rounds() -> None:
    """PRESERVED UPSTREAM BEHAVIOUR — ``Math.floor``, not rounding.

    Upstream writes ``Math.floor(sample * 32767)``, which truncates toward
    negative infinity and so biases every sample down by up to one LSB. It is
    inaudible, but it is what upstream emits, and rounding instead would make
    byte-comparison against a reference render fail everywhere.
    """
    # Peak normalization puts the loudest sample at exactly +/-0.95, and
    # 0.95 * 32767 = 31128.65. Flooring sends +0.95 to 31128 and -0.95 to
    # -31129; rounding would send both to +/-31129. So +31129 must never
    # appear, while the extreme sample lands on one of the floored values.
    result = sonification.sonify(
        np.array([0.0, 1.0]), None, pass_seconds=1.0, output_seconds=0.1, seed=0
    )

    assert result.pcm.max() != 31129
    assert result.pcm.max() == 31128 or result.pcm.min() == -31129


def test_speed_compresses_one_pass(tmp_path) -> None:
    y = np.random.default_rng(4).random(400)

    normal = sonification.sonify(y, None, pass_seconds=4.0, output_seconds=0.5)
    fast = sonification.sonify(y, None, pass_seconds=4.0, speed=4.0, output_seconds=0.5)

    assert normal.pass_seconds == 4.0
    assert fast.pass_seconds == 1.0
    assert fast.pass_audio_seconds < normal.pass_audio_seconds


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pass_seconds": 0.0},
        {"pass_seconds": 1.0, "speed": 0.0},
        {"pass_seconds": 1.0, "output_seconds": 0.0},
        {"pass_seconds": 1.0, "sample_rate": 0},
    ],
)
def test_sonify_rejects_nonpositive_settings(kwargs) -> None:
    with pytest.raises(ValueError):
        sonification.sonify(np.ones(10), None, **kwargs)


def test_sonify_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="no data"):
        sonification.sonify(np.array([]), None, pass_seconds=1.0)


def test_sonify_rejects_mismatched_channels() -> None:
    with pytest.raises(ValueError, match="same length"):
        sonification.sonify(np.ones(10), np.ones(9), pass_seconds=1.0)


def test_write_wav_round_trips(tmp_path) -> None:
    result = sonification.sonify(
        np.random.default_rng(5).random(200), np.random.default_rng(6).random(200),
        pass_seconds=1.0, output_seconds=0.25,
    )
    path = sonification.write_wav(tmp_path / "out.wav", result)

    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == sonification.SAMPLE_RATE
        assert handle.getnframes() == result.frames
        frames = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")

    np.testing.assert_array_equal(frames, result.pcm)


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scan", ALL_SCANS)
def test_tool_renders_every_scan(pulsar_path, artifact_dir, scan) -> None:
    result = sonify_pulsar(pulsar_path(scan), audio_seconds=1.0)

    assert result.errors == []
    assert result.artifact is not None
    assert result.channels == 2
    assert result.mode == "burst"
    assert result.background_subtracted is True
    assert result.samples_used > 10_000

    path = artifact_dir / "pulsar"
    assert path.is_dir()
    with wave.open(result.artifact.path, "rb") as handle:
        assert handle.getnframes() == result.artifact.row_count


def test_tool_reports_playback_drift_against_the_observation_clock(
    pulsar_path, artifact_dir
) -> None:
    """The synthesis never reads the time axis, so audio time is not sky time.

    Upstream's first parameter is ``_xValues`` and goes unused: samples play
    back at a uniform rate in index. The B0329+54 scan drops 1.44 s of samples
    across 15 gaps, so those gaps are compressed away and everything else
    stretches to compensate. The tool has to say so — an agent that measured a
    period off this audio would be ~3% wrong and have no way to know.
    """
    result = sonify_pulsar(pulsar_path("b0329"), audio_seconds=1.0)

    assert result.playback_stretch is not None
    assert result.playback_stretch > 1.01
    assert result.mean_sample_interval_s > result.sample_cadence_s
    assert "playback_not_real_time" in [w.code for w in result.warnings]


def test_tool_render_is_reproducible(pulsar_path, artifact_dir) -> None:
    first = sonify_pulsar(pulsar_path("b0329"), audio_seconds=0.5, output_name="a")
    second = sonify_pulsar(pulsar_path("b0329"), audio_seconds=0.5, output_name="b")

    assert (artifact_dir / "pulsar" / "a.wav").read_bytes() == (
        artifact_dir / "pulsar" / "b.wav"
    ).read_bytes()


def test_tool_mono_and_raw_paths(pulsar_path, artifact_dir) -> None:
    result = sonify_pulsar(
        pulsar_path("b0329"),
        audio_seconds=0.5,
        stereo=False,
        subtract_background=False,
    )

    assert result.channels == 1
    assert result.background_subtracted is False
    assert result.back_scale_s is None


def test_tool_warns_when_the_background_window_degenerates(
    pulsar_path, artifact_dir
) -> None:
    """Upstream's form refuses windows under ~2.2x the sample spacing.

    Below that the running median is taken over a couple of samples, so it
    tracks the signal instead of the baseline and subtracts the pulses away.
    Upstream enforces it as a UI validator; here it is a warning, because the
    tool still has to return something an agent can act on.
    """
    result = sonify_pulsar(pulsar_path("b0329"), audio_seconds=0.5, back_scale=0.005)

    assert "back_scale_too_narrow" in [w.code for w in result.warnings]
    assert result.errors == []


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"audio_seconds": 0}, "invalid_input"),
        ({"audio_seconds": 10_000}, "invalid_input"),
        ({"speed": -1}, "invalid_input"),
        ({"back_scale": 0}, "invalid_input"),
    ],
)
def test_tool_reports_bad_settings_as_errors(pulsar_path, kwargs, code) -> None:
    result = sonify_pulsar(pulsar_path("b0329"), **kwargs)

    assert [error.code for error in result.errors] == [code]
    assert result.artifact is None


def test_tool_reports_a_missing_file_as_an_error(tmp_path) -> None:
    result = sonify_pulsar(tmp_path / "absent.txt")

    assert [error.code for error in result.errors] == ["file_not_found"]


def test_tool_reports_an_empty_file_as_no_data(tmp_path) -> None:
    empty = tmp_path / "empty.cal.txt"
    empty.write_text("# SRC_NAME=nothing\n")

    result = sonify_pulsar(empty)

    assert [error.code for error in result.errors] == ["no_data"]


def test_registry_exposes_the_tool() -> None:
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    assert TOOL_FUNCTIONS["sonify_pulsar"] is sonify_pulsar
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "sonify_pulsar")
    assert schema["input_schema"]["required"] == ["path"]


# ---------------------------------------------------------------------------
# Is it actually a pulsar?
# ---------------------------------------------------------------------------

def test_ingested_scan_folds_into_a_pulse_at_the_catalogued_period(
    pulsar_path,
) -> None:
    """The one check here that does not assume the port is faithful.

    PSR B0329+54 is the brightest pulsar in the northern sky. Folding the
    background-subtracted scan at its ATNF period (0.714520 s, from the
    catalogue — the file carries no period) has to concentrate the flux into a
    narrow pulse. Nothing in this repository supplied that period, so a passing
    fold means the ingest really did recover the pulsar's signal.
    """
    obs = ingest.read_pulsar_file(pulsar_path("b0329"))
    total = ingest.background_subtraction(
        obs.time_s, obs.source1, 3.0
    ) + ingest.background_subtraction(obs.time_s, obs.source2, 3.0)

    bins = 64
    phase = np.mod(obs.time_s, PULSAR_PERIODS_S["b0329"]) / PULSAR_PERIODS_S["b0329"]
    index = (phase * bins).astype(int)
    profile = np.array([total[index == b].mean() for b in range(bins)])

    off_pulse = np.median(profile)
    scatter = np.median(np.abs(profile - off_pulse)) * 1.4826
    snr = (profile.max() - off_pulse) / scatter

    assert snr > 100, f"expected an unmistakable pulse, got {snr:.1f} sigma"
    # A pulsar's duty cycle is small: the pulse occupies a few percent of the
    # period, so only a handful of the 64 bins should be above half-maximum.
    above_half = np.count_nonzero(profile - off_pulse > 0.5 * (profile.max() - off_pulse))
    assert above_half <= 6, f"{above_half}/64 bins above half max — not a pulse"


def test_rendered_audio_carries_the_pulse_train(pulsar_path, artifact_dir) -> None:
    """End to end: the pulses survive into the WAV, at the reported stretch.

    Recovers the amplitude envelope of the noise carrier and folds it, which is
    what a listener's ear does. The expected period is the catalogued one
    scaled by the tool's own reported ``playback_stretch`` — so this pins the
    stretch figure to something measurable rather than trusting the arithmetic.
    """
    result = sonify_pulsar(pulsar_path("b0329"), audio_seconds=20.0)
    assert result.errors == []

    with wave.open(result.artifact.path, "rb") as handle:
        frames = np.frombuffer(
            handle.readframes(handle.getnframes()), dtype="<i2"
        ).reshape(-1, 2)

    envelope = np.abs(frames[:, 0].astype(np.float64))
    window = 221  # ~5 ms boxcar, well under the pulse width
    envelope = np.convolve(envelope, np.ones(window) / window, mode="same")

    expected = PULSAR_PERIODS_S["b0329"] * result.playback_stretch
    t = np.arange(envelope.size) / result.sample_rate

    bins = 64
    index = (np.mod(t, expected) / expected * bins).astype(int)
    profile = np.bincount(index, weights=envelope, minlength=bins) / np.bincount(
        index, minlength=bins
    )
    off_pulse = np.median(profile)
    scatter = np.median(np.abs(profile - off_pulse)) * 1.4826
    snr = (profile.max() - off_pulse) / scatter

    assert snr > 20, f"no pulse train in the rendered audio ({snr:.1f} sigma)"


# ---------------------------------------------------------------------------
# Stage 2 — periodogram
# ---------------------------------------------------------------------------

def test_lomb_scargle_grid_is_logarithmic_in_period_mode() -> None:
    """PRESERVED: a linear loop drives a logarithmic grid.

    ``lombScargle``'s loop variable steps linearly and is then discarded; the
    evaluated point is ``exp(log(start) + (log(stop)-log(start)) * i/steps)``.
    Frequency mode overwrites both with the linear variable. Verified against
    ``lomb-scargle.ts`` 101-143.
    """
    t = np.linspace(0, 10, 200)
    y = np.sin(2 * np.pi * t / 1.5)

    x, _ = periodogram.lomb_scargle(t, y, 0.1, 10.0, 50, freq_mode=False)

    ratios = x[1:] / x[:-1]
    np.testing.assert_allclose(ratios, ratios[0], rtol=1e-9)
    assert x[0] == pytest.approx(0.1)
    # `i / steps` with i ending at steps-1 stops one step short of `stop`.
    assert x[-1] < 10.0


def test_lomb_scargle_grid_is_linear_in_frequency_mode() -> None:
    t = np.linspace(0, 10, 200)
    y = np.sin(2 * np.pi * t / 1.5)

    x, _ = periodogram.lomb_scargle(t, y, 0.1, 5.0, 50, freq_mode=True)

    diffs = np.diff(x)
    np.testing.assert_allclose(diffs, diffs[0], rtol=1e-9)


def test_lomb_scargle_recovers_a_known_sine_period() -> None:
    rng = np.random.default_rng(0)
    t = np.sort(rng.uniform(0, 40, 800))
    y = 3.0 * np.sin(2 * np.pi * t / 2.5) + rng.normal(0, 0.5, t.size)

    result = periodogram.compute_periodogram(t, y, start=0.5, stop=6.0, steps=3000)

    assert result.peak_period_s == pytest.approx(2.5, rel=0.01)
    assert result.peak_confidence_level == "99.73% Confidence"


def test_confidence_threshold_matches_the_typescript() -> None:
    # -Math.log(1 - (1 - alpha) ** (1 / points))
    alpha, points = 1 - 0.954, 1000
    expected = -np.log(1 - (1 - alpha) ** (1 / points))
    assert periodogram.confidence_threshold(alpha, points) == pytest.approx(expected)


def test_nyquist_range_is_twice_the_mean_interval_rounded() -> None:
    t = np.arange(0, 10, 0.01)

    bounds = periodogram.nyquist_periodogram_range(t, freq_mode=False)

    assert bounds["startPeriod"] == pytest.approx(0.02, abs=1e-5)
    assert bounds["endPeriod"] == 3.0
    assert periodogram.nyquist_periodogram_range(np.array([1.0]), False) is None


def test_find_global_max_keeps_the_earliest_on_a_tie() -> None:
    """`points[i][1] > globalMax[1]` is strict, so ties keep the first seen."""
    x = np.array([1.0, 2.0, 3.0])
    power = np.array([5.0, 5.0, 1.0])

    peak_x, peak_power = periodogram.find_global_max(x, power)

    assert (peak_x, peak_power) == (1.0, 5.0)


def test_periodogram_tool_finds_the_pulsar(pulsar_path, artifact_dir) -> None:
    """Stage 2 on real data: B0329+54 against its ATNF period.

    Nothing in this repository tells the periodogram what to look for; the
    search bounds come from the file's own sampling. Recovering the catalogued
    period is therefore a genuine detection, not a fit to a known answer.

    This is the ONLY bundled scan a blind search succeeds on -- see
    ``test_blind_search_only_succeeds_on_the_bright_source`` for the rest.
    """
    result = compute_pulsar_periodogram(pulsar_path("b0329"))

    assert result.errors == []
    assert result.peak_period_s == pytest.approx(PULSAR_PERIODS_S["b0329"], rel=0.002)
    assert result.peak_confidence == "99.73% Confidence"
    assert result.peak_power > result.confidence_thresholds["conf-3-sigma"]
    assert result.peak_fold_snr > 100
    assert "peak_does_not_fold" not in [w.code for w in result.warnings]
    assert result.artifact is not None


#: What a default blind search actually returns for each bundled scan, measured
#: 2026-08-11. Only the bright source works; the rest land on interference or
#: baseline residual. Recorded so a change in that outcome is visible rather
#: than silent -- if a future edit makes b1133/b1933/b2021/b2045 succeed, this
#: test fails and the improvement gets written down.
_BLIND_SEARCH_SUCCEEDS = {"b0329": True, "b1133": False, "b1933": False,
                          "b2021": False, "b2045": False}


@pytest.mark.parametrize("scan", ALL_SCANS)
def test_blind_search_only_succeeds_on_the_bright_source(
    pulsar_path, artifact_dir, scan
) -> None:
    """The honest state of stage 2 on 60-second scans.

    B0329+54 is ~200 mJy at 1400 MHz; the other four are 20-58 mJy. On a single
    60 s scan only the bright one survives a blind search. The others peak on
    60 Hz mains interference (b1133, b2045 both land on 0.016665 s = 60.006 Hz)
    or on red noise left by the baseline subtraction (~2.1-2.2 s).

    Crucially all four **still report "99.73% Confidence"**, because that
    threshold assumes white noise. ``peak_fold_snr`` is what separates them,
    and this test pins that it does.
    """
    result = compute_pulsar_periodogram(pulsar_path(scan))
    assert result.errors == []

    period = PULSAR_PERIODS_S[scan]
    found = abs(result.peak_period_s - period) / period < 0.005
    folds = "peak_does_not_fold" not in [w.code for w in result.warnings]

    assert found is _BLIND_SEARCH_SUCCEEDS[scan], (
        f"{scan}: blind search returned {result.peak_period_s:.6f}s against an "
        f"ATNF period of {period:.6f}s"
    )
    # The fold check and the period check must agree -- that is the point of it.
    assert folds is _BLIND_SEARCH_SUCCEEDS[scan]
    # ...while the false-alarm confidence does NOT discriminate: every scan,
    # right or wrong, clears three sigma.
    assert result.peak_confidence == "99.73% Confidence"


@pytest.mark.parametrize("scan", ALL_SCANS)
def test_folding_at_the_catalogued_period_is_the_reliable_path(
    pulsar_path, artifact_dir, scan
) -> None:
    """With the ATNF period supplied, the fold is a detection or a clear null.

    This is why every tool points at ``search_atnf`` for a known source: the
    catalogued period beats what a 60-second scan can measure, and it turns
    four of these five from failures into usable folds.

    The recorded significances are properties of the sources and the dish, not
    of this code. B1933+16 is the instructive one: at 58 mJy it is brighter
    than B1133+16, but its DM of 158.6 smears the pulse by ~11% of its 359 ms
    period across the 80 MHz band, and nothing here dedisperses.
    """
    expected_snr = {"b0329": 300, "b1133": 15, "b1933": 5, "b2021": 4, "b2045": 4}

    result = fold_pulsar_lightcurve(pulsar_path(scan), PULSAR_PERIODS_S[scan])

    assert result.errors == []
    assert result.pulse_snr > expected_snr[scan], (
        f"{scan}: folding at the catalogued period gave {result.pulse_snr:.1f} sigma"
    )


def test_curated_and_atnf_periods_agree_where_it_matters() -> None:
    """Two independent references, and the difference is below what a fold sees.

    ``PULSAR_PERIODS_S`` comes from ``test_data/pulsar/Curated pulsars.docx``,
    the curation shipped with the scans. ``PULSAR_ATNF[...]["p0"]`` is the live
    catalogue. They agree to 4e-10 for two sources and differ by up to 2e-5 for
    the rest -- different epochs or source references.

    Neither is "more correct" for this data. Both are *barycentric*, while the
    scans are topocentric, and Earth's orbital motion shifts the observed
    period by v/c = 1e-4 -- an order of magnitude more than the disagreement
    between them. What matters is only whether the choice changes a fold, and
    across a 56 s scan it cannot: the accumulated phase drift stays under a
    hundredth of a rotation.
    """
    for scan, curated in PULSAR_PERIODS_S.items():
        catalogue = PULSAR_ATNF[scan]["p0"]
        assert abs(curated - catalogue) / catalogue < 5e-5

        rotations = 56.0 / curated
        phase_drift = rotations * abs(curated - catalogue) / curated
        assert phase_drift < 0.01, (
            f"{scan}: choosing between the curated and catalogue period would "
            f"smear the fold by {phase_drift:.3f} of a period"
        )


def test_measured_detectability_tracks_the_curated_difficulty(
    pulsar_path, artifact_dir
) -> None:
    """The curator's difficulty rating is an independent check on the pipeline.

    ``Curated pulsars.docx`` rates each source before any of this code ran, so
    agreement is real corroboration rather than self-consistency. Folding at
    the curated period should put the "Easy" source far above the rest and the
    "Most Challenging" one near the floor.

    B2021+51 is the one that does not fit -- rated "Lightly Challenging" but
    folding weakest of the five. It is the only scan from a different
    programme (its SRC_NAME is ``3_Pulsar_Team_B2021+51_ERIRA``), so this looks
    like a property of that particular observation rather than of the source,
    and it is left as found rather than tuned away.
    """
    snr = {}
    for scan in ALL_SCANS:
        result = fold_pulsar_lightcurve(pulsar_path(scan), PULSAR_PERIODS_S[scan])
        assert result.errors == []
        snr[scan] = result.pulse_snr

    # The one source rated "Easy" is the one that folds unmistakably.
    easy = [s for s in ALL_SCANS if PULSAR_DIFFICULTY[s]["rank"] == 0]
    assert easy == ["b0329"]
    assert snr["b0329"] > 100
    assert all(snr[s] < 50 for s in ALL_SCANS if s != "b0329")

    # And the one rated hardest folds near the floor.
    hardest = max(ALL_SCANS, key=lambda s: PULSAR_DIFFICULTY[s]["rank"])
    assert hardest == "b2045"
    assert snr[hardest] < 10

    # Ignoring the known B2021+51 outlier, measured order matches curated order.
    ranked = sorted(
        (s for s in ALL_SCANS if s != "b2021"),
        key=lambda s: PULSAR_DIFFICULTY[s]["rank"],
    )
    measured = sorted((s for s in ALL_SCANS if s != "b2021"),
                      key=lambda s: -snr[s])
    assert ranked == measured, f"curated {ranked} vs measured {measured}"


def test_periodogram_top_peaks_expose_harmonics(pulsar_path, artifact_dir) -> None:
    """Harmonics are why `top_peaks` exists.

    A pulsar's periodogram peaks at P and at P/n. Reporting only the global
    maximum would leave a caller no way to notice when the strongest peak is a
    harmonic rather than the fundamental.
    """
    result = compute_pulsar_periodogram(pulsar_path("b0329"))
    period = PULSAR_PERIODS_S["b0329"]

    assert len(result.top_peaks) > 1
    harmonics = [
        peak for peak in result.top_peaks[1:]
        if any(abs(peak["x"] - period / n) < 0.01 * period for n in range(2, 9))
    ]
    assert harmonics, f"expected harmonics among {[p['x'] for p in result.top_peaks]}"


def test_periodogram_tool_rejects_an_absurd_grid(pulsar_path) -> None:
    result = compute_pulsar_periodogram(pulsar_path("b0329"), steps=10_000_000)

    assert [e.code for e in result.errors] == ["invalid_input"]


# ---------------------------------------------------------------------------
# Stage 3 — folding
# ---------------------------------------------------------------------------

def test_float_mod_is_repeated_subtraction_not_fmod() -> None:
    """PRESERVED: `while (a > b) a -= b`, so the result lands in (0, b].

    An exact multiple returns ``b`` rather than 0, and a value already at or
    below ``b`` — including a negative one — is returned untouched. ``fmod``
    would return 0 and would wrap negatives. Verified against
    ``numeric-utils.ts``.
    """
    result = folding.float_mod(np.array([0.0, 0.5, 1.0, 2.0, 2.5, -0.5]), 1.0)

    np.testing.assert_allclose(result, [0.0, 0.5, 1.0, 1.0, 0.5, -0.5])


def test_bin_data_drops_the_point_at_the_upper_edge() -> None:
    """PRESERVED: `floor((x-xMin)/binSize)` guarded by `< bins`.

    The single point at ``x == xMax`` computes an index of exactly ``bins`` and
    is discarded. Upstream does the same (``binData``, pulsar.service.ts
    850-886); it costs one sample out of thousands.
    """
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    y = np.array([1.0, 1.0, 1.0, 1.0, 99.0])

    centres, values = folding.bin_data(x, y, 4)

    assert centres.size == 4
    assert 99.0 not in values


def test_bin_data_averages_within_bins_and_drops_empty_ones() -> None:
    x = np.array([0.0, 0.05, 0.5, 0.55])
    y = np.array([1.0, 3.0, 10.0, 20.0])

    centres, values = folding.bin_data(x, y, 10)

    # Two bins survive: the first two points average together, and 10.0 lands
    # alone in the last filled bin. 20.0 sits at x == xMax and is dropped by
    # the `binIndex < bins` guard, per the test above.
    assert centres.size == 2
    np.testing.assert_allclose(values, [2.0, 10.0])


def test_fold_and_bin_bins_before_shifting() -> None:
    """PRESERVED ORDER: bin first, then phase-shift and wrap.

    ``binData`` does no phase shifting precisely because ``foldAndBin`` applies
    it afterwards. Reversing the two changes which samples share a bin.
    """
    x = np.linspace(0, 1, 100, endpoint=False)
    y = np.zeros(100)
    y[:10] = 1.0

    unshifted, _ = folding.fold_and_bin(x, y, 10, 1.0, 0.0)
    shifted, values = folding.fold_and_bin(x, y, 10, 1.0, 0.5)

    assert np.all(shifted >= 0) and np.all(shifted < 1.0)
    np.testing.assert_allclose(np.sort(unshifted), unshifted)
    np.testing.assert_allclose(np.sort(shifted), shifted)
    assert values.size == 10


def test_duplicate_if_needed_only_fires_for_two() -> None:
    x = np.array([0.0, 0.5])
    y = np.array([1.0, 2.0])

    same_x, _ = folding.duplicate_if_needed(x, y, 1, 1.0)
    two_x, two_y = folding.duplicate_if_needed(x, y, 2, 1.0)

    np.testing.assert_array_equal(same_x, x)
    np.testing.assert_allclose(two_x, [0.0, 0.5, 1.0, 1.5])
    np.testing.assert_allclose(two_y, [1.0, 2.0, 1.0, 2.0])


def test_folding_a_synthetic_pulse_concentrates_it() -> None:
    period = 0.5
    t = np.arange(0, 60, 0.002)
    rng = np.random.default_rng(0)
    flux = np.where(np.mod(t, period) < 0.02, 10.0, 0.0) + rng.normal(0, 1.0, t.size)

    profile = folding.fold_lightcurve(t, flux, None, period_s=period, bins=50)

    assert profile.pulse_snr() > 10
    above = np.count_nonzero(profile.source1 > 0.5 * profile.source1.max())
    assert above <= 4, "a 4% duty cycle should occupy ~2 of 50 bins"


def test_folding_at_the_wrong_period_goes_flat_not_error() -> None:
    """The quiet failure the pipeline ordering exists to prevent."""
    period = 0.5
    t = np.arange(0, 60, 0.002)
    rng = np.random.default_rng(0)
    flux = np.where(np.mod(t, period) < 0.02, 10.0, 0.0) + rng.normal(0, 1.0, t.size)

    right = folding.fold_lightcurve(t, flux, None, period_s=period, bins=50)
    wrong = folding.fold_lightcurve(t, flux, None, period_s=0.37, bins=50)

    assert right.pulse_snr() > 10
    assert wrong.pulse_snr() < right.pulse_snr() / 3


def test_fold_tool_on_real_data(pulsar_path, artifact_dir) -> None:
    result = fold_pulsar_lightcurve(pulsar_path("b0329"), PULSAR_PERIODS_S["b0329"])

    assert result.errors == []
    assert result.pulse_snr > 100
    assert result.bins_filled == 100
    assert result.channels == 2
    assert result.artifact is not None
    assert result.preview


def test_fold_tool_warns_on_a_wrong_period(pulsar_path, artifact_dir) -> None:
    result = fold_pulsar_lightcurve(pulsar_path("b0329"), 0.31337)

    assert result.errors == []
    assert "weak_or_absent_pulse" in [w.code for w in result.warnings]


@pytest.mark.parametrize(
    "args, code",
    [
        ((0.0,), "invalid_input"),
        ((-1.0,), "invalid_input"),
    ],
)
def test_fold_tool_rejects_bad_periods(pulsar_path, artifact_dir, args, code) -> None:
    result = fold_pulsar_lightcurve(pulsar_path("b0329"), *args)

    assert [e.code for e in result.errors] == [code]


# ---------------------------------------------------------------------------
# The pipeline end to end
# ---------------------------------------------------------------------------

def test_stage_one_artifact_feeds_every_later_stage(pulsar_path, artifact_dir) -> None:
    """The handoff contract: stages 2-4 accept the stage-1 .ecsv."""
    lightcurve = load_pulsar_lightcurve(pulsar_path("b0329"))

    assert lightcurve.errors == []
    assert lightcurve.channels == 2
    assert lightcurve.receiver
    assert lightcurve.nyquist_period_s > 0

    path = lightcurve.artifact.path
    spectrum = compute_pulsar_periodogram(path)
    profile = fold_pulsar_lightcurve(path, spectrum.peak_period_s)
    audio = sonify_pulsar(path, period_s=spectrum.peak_period_s, audio_seconds=1.0)

    for stage in (spectrum, profile, audio):
        assert stage.errors == []
        # Header metadata survives the round trip through the artifact.
        assert stage.source_name == "psr_b0329_54"
        assert stage.background_subtracted is True

    assert profile.pulse_snr > 100
    assert audio.rendering == "folded"


def test_reloading_the_artifact_does_not_subtract_twice(
    pulsar_path, artifact_dir
) -> None:
    """Stage 1 already subtracted; later stages must not do it again."""
    lightcurve = load_pulsar_lightcurve(pulsar_path("b0329"))

    direct = fold_pulsar_lightcurve(pulsar_path("b0329"), PULSAR_PERIODS_S["b0329"])
    chained = fold_pulsar_lightcurve(
        lightcurve.artifact.path, PULSAR_PERIODS_S["b0329"]
    )

    assert chained.pulse_snr == pytest.approx(direct.pulse_snr, rel=1e-9)


def test_folded_rendering_beats_the_unfolded_one(pulsar_path, artifact_dir) -> None:
    """Why stage 4 wants a period.

    The folded render loops one rotation, so the pulse recurs on a clean
    schedule; the unfolded render plays the scan once and inherits the
    gap-compression drift. The difference is visible in `playback_stretch`.
    """
    folded = sonify_pulsar(
        pulsar_path("b0329"),
        period_s=PULSAR_PERIODS_S["b0329"],
        audio_seconds=1.0,
        output_name="folded",
    )
    plain = sonify_pulsar(pulsar_path("b0329"), audio_seconds=1.0, output_name="plain")

    assert folded.rendering == "folded"
    assert folded.pulse_snr > 100
    assert abs(folded.playback_stretch - 1.0) < 0.01

    assert plain.rendering == "lightcurve"
    assert "unfolded_rendering" in [w.code for w in plain.warnings]
    assert abs(plain.playback_stretch - 1.0) > abs(folded.playback_stretch - 1.0)


def test_folded_audio_pulses_at_the_requested_period(
    pulsar_path, artifact_dir
) -> None:
    """End to end: the pulse survives folding, synthesis and WAV encoding."""
    result = sonify_pulsar(
        pulsar_path("b0329"), period_s=PULSAR_PERIODS_S["b0329"], audio_seconds=8.0
    )

    with wave.open(result.artifact.path, "rb") as handle:
        frames = np.frombuffer(
            handle.readframes(handle.getnframes()), dtype="<i2"
        ).reshape(-1, 2)

    envelope = np.abs(frames[:, 0].astype(np.float64))
    envelope = np.convolve(envelope, np.ones(221) / 221, mode="same")
    t = np.arange(envelope.size) / result.sample_rate

    expected = PULSAR_PERIODS_S["b0329"] * result.playback_stretch
    bins = 64
    index = (np.mod(t, expected) / expected * bins).astype(int)
    profile = np.bincount(index, weights=envelope, minlength=bins) / np.bincount(
        index, minlength=bins
    )
    off = np.median(profile)
    snr = (profile.max() - off) / (np.median(np.abs(profile - off)) * 1.4826)

    assert snr > 20, f"no pulse train in the folded render ({snr:.1f} sigma)"


def test_registry_exposes_all_four_pipeline_stages() -> None:
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    names = [
        "load_pulsar_lightcurve",
        "compute_pulsar_periodogram",
        "fold_pulsar_lightcurve",
        "sonify_pulsar",
    ]
    for name in names:
        assert name in TOOL_FUNCTIONS
        schema = next(s for s in TOOL_SCHEMAS if s["name"] == name)
        # Each stage names its place in the chain, so an agent reading only the
        # schema list can order them without this document.
        assert "PULSAR PIPELINE STAGE" in schema["description"]

    assert TOOL_SCHEMAS[-4]["name"] == "load_pulsar_lightcurve"


# ---------------------------------------------------------------------------
# Where the output lands
# ---------------------------------------------------------------------------

def test_audio_lands_under_the_artifact_dir_with_a_stage_consistent_name(
    pulsar_path, artifact_dir
) -> None:
    """The WAV path is predictable, absolute, and names its rendering.

    Absolute matters: a caller may change directory or hand the path to
    another process, and a bare ``artifacts/...`` means something different in
    each case. It also keeps ``artifact.path`` consistent with ``file.path``,
    which has always been resolved.
    """
    folded = sonify_pulsar(
        pulsar_path("b0329"), period_s=PULSAR_PERIODS_S["b0329"], audio_seconds=0.5
    )
    plain = sonify_pulsar(pulsar_path("b0329"), audio_seconds=0.5)

    for result, rendering in ((folded, "folded"), (plain, "lightcurve")):
        path = Path(result.artifact.path)
        assert path.is_absolute(), f"{path} is not absolute"
        assert path.is_file()
        assert path.parent == artifact_dir / "pulsar"
        assert path.name == f"psr_b0329_54_sonification_{rendering}.wav"


def test_the_folded_render_is_not_named_prefolded(pulsar_path, artifact_dir) -> None:
    """Upstream's download filename is the *chart* title, and it lies here.

    ``setChartTitle`` produces ``..._prefolded_light_curve`` for the light-curve
    tab, while ``setPeriodFoldingTitle`` produces ``..._folded_light_curve`` for
    the folding tab; the two sonifiers download under different ones. Naming a
    folded render "prefolded" says the opposite of what it is, so the tools use
    their own stage-consistent scheme and keep both upstream titles in the
    ingest for anyone reproducing the browser filenames.
    """
    result = sonify_pulsar(
        pulsar_path("b0329"), period_s=PULSAR_PERIODS_S["b0329"], audio_seconds=0.5
    )

    assert "prefolded" not in Path(result.artifact.path).name

    observation = ingest.read_pulsar_file(pulsar_path("b0329"))
    assert observation.title.endswith("_prefolded_light_curve")
    assert observation.folding_title.endswith("_folded_light_curve")
    assert observation.periodogram_title.endswith("_periodogram")


def test_every_stage_writes_beside_the_others(pulsar_path, artifact_dir) -> None:
    """One directory per run, four predictable names."""
    lightcurve = load_pulsar_lightcurve(pulsar_path("b0329"))
    spectrum = compute_pulsar_periodogram(lightcurve.artifact.path)
    profile = fold_pulsar_lightcurve(lightcurve.artifact.path, spectrum.peak_period_s)
    audio = sonify_pulsar(
        lightcurve.artifact.path, period_s=spectrum.peak_period_s, audio_seconds=0.5
    )

    names = sorted(p.name for p in (artifact_dir / "pulsar").iterdir())
    assert names == [
        "psr_b0329_54_folded.ecsv",
        "psr_b0329_54_lightcurve.ecsv",
        "psr_b0329_54_periodogram.ecsv",
        "psr_b0329_54_sonification_folded.wav",
    ]
    for stage in (lightcurve, spectrum, profile, audio):
        assert Path(stage.artifact.path).is_absolute()
