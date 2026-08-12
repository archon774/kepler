"""Green Bank / Skynet pulsar time-series ingest.

PORTED from astromancer via the Kepler TypeScript extraction:

* ``algorithms/lightcurve/pulsar/pulsar-lightcurve.ingest.ts``
  -- ``PulsarLightCurveIngest.uploadHandler`` (file-flavour discrimination,
  ``#`` header parsing, the cal-block row filter, the fixed column map, the
  UTC time rebase).
* ``algorithms/lightcurve/pulsar/pulsar-lightcurve.algorithms.ts``
  -- ``PulsarLightCurveAlgorithms.median`` and ``.backgroundSubtraction``
  (astromancer ``pulsar.service.ts`` 715-720 and 722-739).

Everything in this module is arithmetic-for-arithmetic with those sources.
Where the port had to make a choice the TypeScript did not force, the line is
marked ``# PORTED:``.

The upstream ingest lives inside a ``FileReader.onload`` callback and writes
its results through an Angular service; here it returns a plain
:class:`PulsarObservation`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

__all__ = [
    "PulsarObservation",
    "CAL_COLUMNS",
    "DEFAULT_BACK_SCALE",
    "parse_pulsar_text",
    "read_pulsar_file",
    "median",
    "background_subtraction",
]

#: The column map ``uploadHandler`` applies to a cal file, in upstream order.
#:
#: This list is **not** the order the Skynet file's own column header line
#: gives. The files write ``... El(deg)  YY1  XX1  Cal  Sweeps``; upstream
#: names index 5 ``XX1`` and index 6 ``YY1``, i.e. the two polarization labels
#: are transposed relative to the data. Upstream then reads ``row['YY1']``
#: into ``source1`` and ``row['XX1']`` into ``source2``, so in file terms
#: ``source1`` is the file's *XX1* column and ``source2`` is its *YY1* column.
#: Preserved exactly: it decides which polarization lands on which stereo
#: channel, and "fixing" it would silently swap every rendered file.
CAL_COLUMNS: tuple[str, ...] = (
    "UTC_Time(s)",
    "Ra(hr)",
    "Dec(deg)",
    "Az(deg)",
    "El(deg)",
    "XX1",
    "YY1",
    "Cal",
    "Sweeps",
)

#: ``setbackScale(3)`` in both ingest branches: running-median window, seconds.
DEFAULT_BACK_SCALE = 3.0

_SOURCE1_COLUMN = CAL_COLUMNS.index("YY1")  # = 6, the file's XX1 column
_SOURCE2_COLUMN = CAL_COLUMNS.index("XX1")  # = 5, the file's YY1 column
_TIME_COLUMN = CAL_COLUMNS.index("UTC_Time(s)")

_HEADER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_()]*)\s*=\s*(.*)$")
_P_TOPO_RE = re.compile(r"P_topo\s*\(ms\)\s*=\s*([\d.]+)")
_SRC_NAME_RE = re.compile(r"SRC_NAME=([^\s#]+)")
_UTC_RE = re.compile(r"UTC=([\d.]+)")
_DATE_OBS_RE = re.compile(r"DATE_OBS=([^\s#]+)")
_CANDIDATE_RE = re.compile(r"Candidate\s*=\s*(.+)")


@dataclass
class PulsarObservation:
    """One parsed pulsar file.

    ``time_s`` is seconds since the header ``UTC``, matching upstream's
    ``ts = row['UTC_Time(s)'] - utc`` rebase. ``source2`` is ``None`` for
    standard (prefolded) files, which carry a single flux column.
    """

    flavour: str
    time_s: np.ndarray
    source1: np.ndarray
    source2: Optional[np.ndarray] = None
    source_name: Optional[str] = None
    date_obs: Optional[str] = None
    utc_s: Optional[float] = None
    period_s: Optional[float] = None
    title: Optional[str] = None
    """Upstream's light-curve chart title (``..._prefolded_light_curve``)."""

    periodogram_title: Optional[str] = None
    folding_title: Optional[str] = None
    """Upstream's period-folding title (``..._folded_light_curve``). The
    period-folding sonifier downloads under this one, not :attr:`title`."""

    header: dict[str, str] = field(default_factory=dict)

    @property
    def sample_count(self) -> int:
        return int(self.time_s.size)

    @property
    def time_span_s(self) -> float:
        if self.time_s.size < 2:
            return 0.0
        return float(self.time_s[-1] - self.time_s[0])

    @property
    def sample_cadence_s(self) -> Optional[float]:
        """Median gap between samples -- the instrument's actual cadence.

        Not upstream; nothing in astromancer needs it. It is here because the
        sonification plays samples back at a uniform rate regardless of their
        timestamps, so comparing this against
        :attr:`mean_sample_interval_s` is the only way to tell how far the
        rendered audio has drifted from real time. They differ whenever the
        observation dropped samples.
        """
        if self.time_s.size < 2:
            return None
        return float(np.median(np.diff(self.time_s)))

    @property
    def mean_sample_interval_s(self) -> Optional[float]:
        """Upstream's ``avgDiff / 2`` -- the mean spacing, not the Nyquist limit.

        ``uploadHandler`` computes ``avgDiff = mean(diff) * 2`` and feeds that
        to the period-folding and periodogram bounds as the shortest
        resolvable period. The mean spacing itself is the more useful number
        for a caller, so it is what this returns; multiply by two for the
        upstream Nyquist bound.
        """
        if self.time_s.size < 2:
            return None
        total = float(self.time_s[-1] - self.time_s[0])
        return total / (self.time_s.size - 1)


def _parse_float(token: str) -> float:
    """``parseFloat`` semantics: unparseable is NaN, never an exception."""

    try:
        return float(token)
    except (TypeError, ValueError):
        return float("nan")


def _collect_header(comment_lines: list[str]) -> dict[str, str]:
    """Collect every ``KEY=VALUE`` pair in the ``#`` block.

    PORTED: upstream pulls only P_topo / SRC_NAME / UTC / DATE_OBS out of the
    header and discards the rest. The rest is real observation metadata
    (receiver, frequency, pointing, Tsys), so it is kept here for callers to
    report. The four upstream fields are still parsed by the upstream regexes
    below, not from this dict.
    """
    header: dict[str, str] = {}
    for line in comment_lines:
        stripped = re.sub(r"^#\s*", "", line).strip()
        match = _HEADER_KEY_RE.match(stripped)
        if match:
            header.setdefault(match.group(1), match.group(2).strip())
    return header


def _parse_cal(text: str, lines: list[str]) -> PulsarObservation:
    """The ``type === "cal"`` branch of ``uploadHandler``."""

    # Verbatim filter chain: drop comments and blanks, then drop any row whose
    # LAST whitespace-separated column parses as exactly 0. On Skynet cal files
    # that last column is the run flag, and it is 0 for the leading
    # noise-diode calibration block -- so this is what removes the ~124 rows of
    # 0.1 s-cadence cal data ahead of the 4.2 ms science samples. A row whose
    # last column will not parse yields NaN, and `NaN !== 0` is true upstream,
    # so it is kept; `nan != 0` keeps it here too.
    data_lines = [
        line
        for line in lines
        if not line.startswith("#") and line.strip() != ""
    ]
    filtered_lines = [
        line
        for line in data_lines
        if _parse_float(line.strip().split()[-1]) != 0
    ]

    comment_lines = [line for line in lines if line.startswith("#")]

    period_s: Optional[float] = None
    source_name: Optional[str] = None
    utc: Optional[float] = None
    date_obs: Optional[str] = None

    for line in comment_lines:
        trimmed = re.sub(r"^#\s*", "", line)
        if trimmed.startswith("P_topo"):
            match = _P_TOPO_RE.search(trimmed)
            if match:
                value = _parse_float(match.group(1))
                if not np.isnan(value):
                    # setPeriodFoldingPeriod(round(period/1000 * 10000)/10000)
                    period_s = round(value / 1000 * 10000) / 10000
        elif trimmed.startswith("SRC_NAME="):
            match = _SRC_NAME_RE.search(trimmed)
            if match:
                source_name = match.group(1)
        elif trimmed.startswith("UTC="):
            match = _UTC_RE.search(trimmed)
            if match:
                value = _parse_float(match.group(1))
                if not np.isnan(value):
                    utc = value
        elif trimmed.startswith("DATE_OBS="):
            match = _DATE_OBS_RE.search(trimmed)
            if match:
                date_obs = match.group(1)

    times: list[float] = []
    src1: list[float] = []
    src2: list[float] = []

    for line in filtered_lines:
        columns = line.strip().split()
        # Upstream maps the first len(CAL_COLUMNS) tokens onto the fixed header
        # list; a short row leaves the missing names undefined, and the
        # isNaN() guard below drops it.
        if len(columns) < len(CAL_COLUMNS):
            continue
        t = _parse_float(columns[_TIME_COLUMN])
        s1 = _parse_float(columns[_SOURCE1_COLUMN])
        s2 = _parse_float(columns[_SOURCE2_COLUMN])
        if np.isnan(t) or np.isnan(s1) or np.isnan(s2):
            continue
        times.append(t)
        src1.append(s1)
        src2.append(s2)

    offset = utc if utc is not None else 0.0
    time_s = np.asarray(times, dtype=np.float64) - offset

    # Upstream sets THREE titles from this block, one per tab, and each
    # sonifier downloads under a different one: the light-curve sonifier uses
    # getChartTitle(), the period-folding sonifier uses getPeriodFoldingTitle().
    # All three are carried so a caller can reproduce upstream's filenames;
    # `tools.pulsar` uses its own stage-consistent naming instead.
    title = None
    periodogram_title = None
    folding_title = None
    if utc is not None and source_name is not None:
        title = f"{source_name}_{date_obs}_prefolded_light_curve"
        periodogram_title = f"{source_name}_{date_obs}_periodogram"
        folding_title = f"{source_name}_{date_obs}_folded_light_curve"

    return PulsarObservation(
        flavour="cal",
        time_s=time_s,
        source1=np.asarray(src1, dtype=np.float64),
        source2=np.asarray(src2, dtype=np.float64),
        source_name=source_name,
        date_obs=date_obs,
        utc_s=utc,
        period_s=period_s,
        title=title,
        periodogram_title=periodogram_title,
        folding_title=folding_title,
        header=_collect_header(comment_lines),
    )


def _parse_standard(text: str, lines: list[str]) -> PulsarObservation:
    """The ``type === "standard"`` branch of ``uploadHandler``.

    Prefolded files: two numeric columns, no second polarization, and a
    ``P_topo`` the cal files do not carry.
    """

    # Upstream re-splits on normalized newlines inside this branch.
    lines = text.replace("\r\n", "\n").split("\n")

    period_s: Optional[float] = None
    title: Optional[str] = None

    for line in lines:
        trimmed = re.sub(r"^#\s*", "", line)
        if trimmed.startswith("P_topo"):
            match = _P_TOPO_RE.search(trimmed)
            if match:
                value = _parse_float(match.group(1))
                if not np.isnan(value):
                    period_s = round(value / 1000 * 10000) / 10000
        elif trimmed.startswith("Candidate"):
            match = _CANDIDATE_RE.search(trimmed)
            if match:
                title = match.group(1).strip()

    xvalues: list[float] = []
    yvalues: list[float] = []
    for line in lines:
        trimmed = line.strip()
        if trimmed == "" or trimmed.startswith("#"):
            continue
        parts = trimmed.split()
        if len(parts) >= 2:
            x = _parse_float(parts[0].strip())
            y = _parse_float(parts[1].strip())
            if not np.isnan(x) and not np.isnan(y):
                xvalues.append(x)
                yvalues.append(y)

    comment_lines = [line for line in lines if line.startswith("#")]

    return PulsarObservation(
        flavour="standard",
        # No UTC rebase in this branch -- the x column is already the axis.
        time_s=np.asarray(xvalues, dtype=np.float64),
        source1=np.asarray(yvalues, dtype=np.float64),
        source2=None,
        period_s=period_s,
        title=title,
        header=_collect_header(comment_lines),
    )


def parse_pulsar_text(text: str) -> PulsarObservation:
    """Parse pulsar file contents, discriminating cal from standard flavour."""

    lines = text.split("\n")
    # Verbatim discriminator: `lines[0].slice(0, 7) == "# Input"`.
    if lines and lines[0][:7] == "# Input":
        return _parse_standard(text, lines)
    return _parse_cal(text, lines)


def read_pulsar_file(path: str | Path) -> PulsarObservation:
    """Read and parse a pulsar file from disk."""

    resolved = Path(path).expanduser()
    return parse_pulsar_text(resolved.read_text(encoding="utf-8", errors="replace"))


def median(values: np.ndarray) -> float:
    """``PulsarLightCurveAlgorithms.median``, NaN-filtered then sorted.

    Upstream returns the middle element for odd counts and the mean of the two
    middle elements for even counts, which is what ``np.median`` computes; the
    NaN filter is applied first, exactly as upstream's ``.filter(num =>
    !isNaN(num))`` does. An empty window returns NaN, matching upstream's
    ``undefined`` propagating into the subtraction.
    """
    finite = values[~np.isnan(values)]
    if finite.size == 0:
        return float("nan")
    return float(np.median(finite))


def background_subtraction(
    time_s: np.ndarray, flux: np.ndarray, dt: float
) -> np.ndarray:
    """``PulsarLightCurveAlgorithms.backgroundSubtraction``, verbatim logic.

    A running median over the window ``[t_i - dt/2, t_i + dt/2]`` is subtracted
    from each sample. ``dt`` is ``backScale`` in seconds.

    The two window pointers advance monotonically and are never reset, exactly
    as upstream -- which is correct only for time-ordered input and is
    reproduced rather than hardened, since the upstream files are ordered.
    """
    n = int(min(len(time_s), len(flux)))
    subtracted = np.empty(n, dtype=np.float64)

    half = dt / 2
    jmin = 0
    jmax = 0
    for i in range(n):
        while jmin < n and time_s[jmin] < time_s[i] - half:
            jmin += 1
        while jmax < n and time_s[jmax] <= time_s[i] + half:
            jmax += 1
        subtracted[i] = flux[i] - median(flux[jmin:jmax])
    return subtracted
