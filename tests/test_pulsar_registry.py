"""Stage 0 for pulsar scans, and the curated period it now carries.

BL-8: the curated literature periods lived in ``Curated pulsars.docx`` and in a
literal dictionary inside ``tests/conftest.py``. Neither is reachable from the
tool layer, so an agent working offline had only the blind period search --
which ``test_pulsar_sonification.py`` pins as succeeding on **one of the five**
bundled scans, while the other four report "99.73% Confidence" for mains
interference or red noise. These tests pin the offline path: every bundled scan
resolves carrying the period the curation records, and the fixture stays the
single copy of that number.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.conftest import (
    PULSAR_ATNF,
    PULSAR_DIFFICULTY,
    PULSAR_PERIODS_S,
    PULSAR_SCANS,
    requires_curated_periods,
)
from tools import pulsar as pulsar_tools
from tools.models import PulsarScan, PulsarScanList
from tools.pulsar import (
    compute_pulsar_periodogram,
    list_pulsar_scans,
    resolve_pulsar_scan,
)

ROOT = Path(__file__).resolve().parents[1]
PULSAR = ROOT / "data" / "pulsar"
CURATED = PULSAR / "curated_periods.json"

ALL_SCANS = sorted(PULSAR_SCANS)

#: Parsed once here. Only the conftest cross-check below re-reads the file --
#: that independent read is the point of that test.
CURATED_ENTRIES = json.loads(CURATED.read_text(encoding="utf-8"))["pulsars"]

pytestmark = requires_curated_periods

#: A scan header for a pulsar the curation does not cover. B1919+21 is in the
#: document's second table -- the observing programme -- but has no scan here
#: and no literature period recorded, so it is the honest "no curated period"
#: case rather than an invented name.
UNCURATED_HEADER = """# SRC_NAME = B1919+21
# DATE_OBS = 2026-01-01T00:00:00
# RECEIVER = 1400MHz
# OBSFREQ = 1395.0
# RA(deg) = 290.4
# DEC(deg) = 21.9
# DURATION = 60.0
0.0 1.0 1.0 0
"""


# ---------------------------------------------------------------------------
# The fixture is the single copy
# ---------------------------------------------------------------------------

def test_conftest_reads_the_curated_tables_from_the_fixture() -> None:
    """The number lives in one place; this catches an edit that re-inlines it."""

    entries = json.loads(CURATED.read_text(encoding="utf-8"))["pulsars"]

    assert sorted(entries) == ALL_SCANS
    assert PULSAR_PERIODS_S == {k: v["period_s"] for k, v in entries.items()}
    assert PULSAR_ATNF == {k: v["atnf"] for k, v in entries.items()}
    assert PULSAR_DIFFICULTY == {
        k: {
            "obs": v["observation"],
            "rank": v["difficulty_rank"],
            "label": v["difficulty"],
        }
        for k, v in entries.items()
    }


def test_the_fixture_records_which_reference_the_tests_compare_against() -> None:
    """The reasoning is not derivable from the numbers, so it ships with them.

    Two things have to be readable from the file alone: that the curated
    document rather than ATNF is the arbiter, and that the scans carry no
    period of their own -- which is what makes a successful fold a detection
    rather than a self-consistency check.
    """
    payload = json.loads(CURATED.read_text(encoding="utf-8"))
    about = " ".join(payload["_about"]).lower()

    assert "not atnf" in about
    assert "curated pulsars.docx" in about
    assert "outside the data" in about
    assert "curated pulsars.docx" in payload["period_source"].lower()


# ---------------------------------------------------------------------------
# What the tool layer now reports
# ---------------------------------------------------------------------------

def test_every_bundled_scan_lists_with_its_curated_period() -> None:
    """The offline path: five scans, five literature periods, no network."""

    listing = list_pulsar_scans()

    assert listing.errors == []
    assert listing.count == len(ALL_SCANS)

    # Keyed by filename, so a regression that permutes the assignments fails
    # here rather than passing on a matching multiset of five periods.
    by_file = {Path(s.path).name: s.curated_period_s for s in listing.scans}
    assert by_file == {
        PULSAR_SCANS[key]: PULSAR_PERIODS_S[key] for key in ALL_SCANS
    }
    assert all(scan.period_source for scan in listing.scans)


@pytest.mark.parametrize("scan", ALL_SCANS)
def test_resolving_a_designation_carries_the_curated_period(scan: str) -> None:
    result = resolve_pulsar_scan(CURATED_ENTRIES[scan]["designation"])

    assert isinstance(result, PulsarScan), getattr(result, "errors", None)
    assert result.curated_period_s == PULSAR_PERIODS_S[scan]
    assert result.curated_difficulty == PULSAR_DIFFICULTY[scan]["label"]
    assert "Curated pulsars.docx" in (result.period_source or "")


@pytest.mark.parametrize("scan", ALL_SCANS)
def test_resolving_an_explicit_path_carries_it_too(scan: str) -> None:
    """A caller who already has the path gets the period without a lookup."""

    result = resolve_pulsar_scan(str(PULSAR / PULSAR_SCANS[scan]))

    assert isinstance(result, PulsarScan)
    assert result.curated_period_s == PULSAR_PERIODS_S[scan]


def test_the_period_never_comes_from_the_scan_file() -> None:
    """No scan carries a topocentric period, so the match is by name alone.

    Pinned because it is the reason the fixture exists: if the files did carry
    ``P_topo`` the tool would read it instead.
    """
    for filename in PULSAR_SCANS.values():
        with (PULSAR / filename).open("r", encoding="utf-8", errors="replace") as fh:
            header = [line for line in fh if line.startswith("#")]
        assert not any("P_topo" in line or "PERIOD" in line.upper() for line in header)


def test_an_uncurated_scan_reports_no_period(tmp_path: Path) -> None:
    """Absence is reported as absence -- never as a plausible-looking number."""

    scan_file = tmp_path / "Skynet_60000_psr_b1919_21_1_1.A.cal.txt"
    scan_file.write_text(UNCURATED_HEADER, encoding="utf-8")

    result = resolve_pulsar_scan(str(scan_file))

    assert isinstance(result, PulsarScan)
    assert result.source_name == "B1919+21"
    assert result.curated_period_s is None
    assert result.curated_difficulty is None
    assert result.period_source is None


def _bundled_copy(directory: Path, *keys: str) -> Path:
    """Copy bundled scans into ``directory``, without any curation beside them."""

    for key in keys:
        shutil.copy(PULSAR / PULSAR_SCANS[key], directory / PULSAR_SCANS[key])
    return directory


def test_a_missing_map_is_a_warning_not_an_import_error(tmp_path: Path) -> None:
    """``tools/`` has to import and run without ``data/`` present."""

    assert pulsar_tools._load_curated_periods(tmp_path / "absent.json") == ({}, None)

    root = _bundled_copy(tmp_path, *ALL_SCANS)
    listing = list_pulsar_scans(root)

    assert isinstance(listing, PulsarScanList)
    assert listing.errors == []
    assert listing.count == len(ALL_SCANS)
    assert [w.code for w in listing.warnings] == ["curated_periods_unavailable"]
    assert all(scan.curated_period_s is None for scan in listing.scans)


def test_the_warning_reaches_a_single_resolved_scan(tmp_path: Path) -> None:
    """"No curation here" and "this source is not curated" must not look alike.

    ``resolve_pulsar_scan`` returns a bare ``PulsarScan`` on a single match, so
    without a warning on the scan itself both cases read as a null
    ``curated_period_s`` and an agent would go to ATNF for a source that is in
    fact curated -- somewhere else.
    """
    root = _bundled_copy(tmp_path, "b0329")

    result = resolve_pulsar_scan("B0329+54", directory=root)

    assert isinstance(result, PulsarScan)
    assert result.curated_period_s is None
    assert [w.code for w in result.warnings] == ["curated_periods_unavailable"]
    assert str(root) in result.warnings[0].message


def test_a_malformed_map_is_also_survivable(tmp_path: Path) -> None:
    """Every unusable shape degrades to "no curation", never to an exception."""

    cases = {
        "not_json.json": "{not json",
        "wrong_container.json": '{"pulsars": []}',
        "no_source.json": '{"pulsars": {"b0329": {"period_s": 0.7}}}',
        # Rows that are not dicts, or whose period is not a number, used to
        # pass the envelope check and blow up later -- an AttributeError out of
        # list_pulsar_scans, or a pydantic ValidationError.
        "scalar_row.json": '{"pulsars": {"b0329": 0.7145197}, "period_source": "d"}',
        "string_period.json":
            '{"pulsars": {"b0329": {"period_s": "unknown"}}, "period_source": "d"}',
        "bool_period.json":
            '{"pulsars": {"b0329": {"period_s": true}}, "period_source": "d"}',
    }
    for name, body in cases.items():
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        assert pulsar_tools._load_curated_periods(path) == ({}, None), name


def test_a_row_without_a_period_is_dropped_rather_than_carried(
    tmp_path: Path,
) -> None:
    """A ``period_source`` must never cite a curation for a number it lacks."""

    root = _bundled_copy(tmp_path, "b0329", "b1133")
    (root / pulsar_tools.CURATED_PERIODS_FILENAME).write_text(
        json.dumps(
            {
                "period_source": "partial curation",
                "pulsars": {
                    "b0329": {"period_s": 0.7145197, "difficulty": "Easy"},
                    "b1133": {"difficulty": "Lightly Challenging"},
                },
            }
        ),
        encoding="utf-8",
    )

    by_file = {
        Path(scan.path).name: scan for scan in list_pulsar_scans(root).scans
    }
    kept = by_file[PULSAR_SCANS["b0329"]]
    dropped = by_file[PULSAR_SCANS["b1133"]]

    assert kept.curated_period_s == 0.7145197
    assert kept.period_source == "partial curation"
    assert dropped.curated_period_s is None
    assert dropped.curated_difficulty is None
    assert dropped.period_source is None


def test_the_curation_is_read_from_beside_the_scans(tmp_path: Path) -> None:
    """An operator's own archive gets their curation, not this repository's.

    ``KEPLER_PULSAR_DATA_DIR`` points the tools at another archive. If the map
    were pinned to a fixed repo path, these five periods would be name-matched
    onto that archive's files and stamped with a ``period_source`` naming a
    document that describes different observations.
    """
    root = _bundled_copy(tmp_path, "b0329")
    (root / pulsar_tools.CURATED_PERIODS_FILENAME).write_text(
        json.dumps(
            {
                "period_source": "the operator's own curation",
                "pulsars": {"b0329": {"period_s": 0.5, "difficulty": "Local"}},
            }
        ),
        encoding="utf-8",
    )

    scan = list_pulsar_scans(root).scans[0]

    assert scan.curated_period_s == 0.5
    assert scan.curated_difficulty == "Local"
    assert scan.period_source == "the operator's own curation"
    assert scan.warnings == []

    # The bundled directory is untouched by the other archive's map.
    assert resolve_pulsar_scan("B0329+54").curated_period_s == PULSAR_PERIODS_S["b0329"]


def test_the_bundled_listing_carries_no_warning() -> None:
    listing = list_pulsar_scans()
    assert listing.warnings == []
    assert all(scan.warnings == [] for scan in listing.scans)


# ---------------------------------------------------------------------------
# The reference is a check, not an input
# ---------------------------------------------------------------------------

def test_the_curated_period_cannot_bias_the_measurement(
    tmp_path: Path, artifact_dir
) -> None:
    """Stage 2 measures the same period whether or not a curation exists.

    This is the architectural invariant behind "measure first, check second"
    (`docs/pulsar-tool-pipeline.md`). A fold at a measured period is a
    detection; a fold at a literature period is a fit to a known answer. That
    distinction only survives while nothing downstream of stage 0 can see the
    curated value -- so if a future change wires it into the search bounds, a
    default, or a seed, this test fails.

    Run on b0329, the one scan where a blind search succeeds: a leaked
    reference period would be hardest to notice there. A deliberately WRONG
    curated period sits beside the copy, so a leak would move the answer rather
    than merely confirming it. `steps` is cut well below the default because
    the invariant is about coupling, not resolution.
    """
    root = _bundled_copy(tmp_path, "b0329")
    scan = str(root / PULSAR_SCANS["b0329"])
    kwargs = {"steps": 200, "start": 0.5, "stop": 1.0}

    uncurated = compute_pulsar_periodogram(scan, **kwargs)
    assert uncurated.errors == []

    (root / pulsar_tools.CURATED_PERIODS_FILENAME).write_text(
        json.dumps(
            {
                "period_source": "a wrong curation",
                "pulsars": {"b0329": {"period_s": 0.9, "difficulty": "Easy"}},
            }
        ),
        encoding="utf-8",
    )
    pulsar_tools._CURATED_CACHE.clear()
    assert list_pulsar_scans(root).scans[0].curated_period_s == 0.9

    curated = compute_pulsar_periodogram(scan, **kwargs)

    assert curated.errors == []
    assert curated.peak_period_s == uncurated.peak_period_s
    assert curated.peak_fold_snr == uncurated.peak_fold_snr
    assert curated.top_peaks == uncurated.top_peaks


def test_the_measured_period_is_not_the_curated_one(pulsar_path, artifact_dir) -> None:
    """A blind search lands near the literature value without landing on it.

    Equality would mean the measurement had been replaced by the reference.
    The residual gap is the evidence that stage 2 searched a grid: the
    periodogram reports a grid peak, not a literature value. The measured
    offset on this fixture is ~0.04% (docs/pulsar-tool-pipeline.md section 4).
    """
    result = compute_pulsar_periodogram(pulsar_path("b0329"))
    curated = PULSAR_PERIODS_S["b0329"]

    # Not exact float inequality: "did not land on the reference" means the
    # grid peak differs by more than rounding, not by more than zero.
    assert result.peak_period_s != pytest.approx(curated, rel=1e-6)
    assert result.peak_period_s == pytest.approx(curated, rel=0.001)
    assert result.peak_fold_snr > 8
