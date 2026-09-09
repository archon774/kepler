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
from pathlib import Path

import pytest

from tests.conftest import (
    PULSAR_ATNF,
    PULSAR_DIFFICULTY,
    PULSAR_PERIODS_S,
    PULSAR_SCANS,
)
from tools import pulsar as pulsar_tools
from tools.models import PulsarScan, PulsarScanList
from tools.pulsar import list_pulsar_scans, resolve_pulsar_scan

ROOT = Path(__file__).resolve().parents[1]
PULSAR = ROOT / "test_data" / "pulsar"
CURATED = PULSAR / "curated_periods.json"

ALL_SCANS = sorted(PULSAR_SCANS)

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
    by_period = {scan.curated_period_s for scan in listing.scans}
    assert by_period == set(PULSAR_PERIODS_S.values())
    assert all(scan.period_source for scan in listing.scans)


@pytest.mark.parametrize("scan", ALL_SCANS)
def test_resolving_a_designation_carries_the_curated_period(scan: str) -> None:
    designation = json.loads(CURATED.read_text(encoding="utf-8"))["pulsars"][scan][
        "designation"
    ]

    result = resolve_pulsar_scan(designation)

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


def test_a_missing_fixture_is_a_warning_not_an_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tools/`` has to import and run without ``test_data/`` present."""

    assert pulsar_tools._load_curated_periods(tmp_path / "absent.json") == ({}, None)

    monkeypatch.setattr(pulsar_tools, "_CURATED_PERIODS", {})
    monkeypatch.setattr(pulsar_tools, "_CURATED_PERIOD_SOURCE", None)

    listing = list_pulsar_scans()

    assert isinstance(listing, PulsarScanList)
    assert listing.errors == []
    assert listing.count == len(ALL_SCANS)
    assert [w.code for w in listing.warnings] == ["curated_periods_unavailable"]
    assert all(scan.curated_period_s is None for scan in listing.scans)


def test_a_malformed_fixture_is_also_survivable(tmp_path: Path) -> None:
    broken = tmp_path / "curated_periods.json"
    broken.write_text("{not json", encoding="utf-8")
    assert pulsar_tools._load_curated_periods(broken) == ({}, None)

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('{"pulsars": []}', encoding="utf-8")
    assert pulsar_tools._load_curated_periods(wrong_shape) == ({}, None)


def test_the_listing_warns_only_when_the_map_is_missing() -> None:
    listing = list_pulsar_scans()
    assert listing.warnings == []
