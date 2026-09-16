"""Shared fixtures for Kepler's algorithm tests.

Two rules shape everything here, both from ``CLAUDE.md``:

* **Default checks stay deterministic and bounded.** Nothing in this suite opens
  a socket unless it is marked ``network``, and nothing marked ``network`` runs
  without ``KEPLER_TEST_NETWORK=1``.
* **The Python folders are byte-preserving extractions.** So the fixtures are
  real Skynet frames and real recorded Skynet solver output, not synthesised
  arrays — see ``data/README.md``.

Fixtures that need data the repo cannot carry (astrometry.net indexes, a local
UCAC catalog) skip themselves rather than failing, mirroring how the upstream
skylib suite handles its S3-hosted fixtures.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from tools.config import is_lfs_pointer

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"
OPTICAL = DATA_ROOT / "optical"
ZP_SOLUTIONS = DATA_ROOT / "fieldcal" / "zp_solutions"
AFTERGLOW = DATA_ROOT / "afterglow"
PULSAR = DATA_ROOT / "pulsar"

#: Short aliases for the pulsar scans, keyed by the source they point at.
#: ``b0329`` is the loud one — the brightest pulsar in the northern sky, and
#: the only fixture where a single 60 s scan gives an unmistakable pulse train.
PULSAR_SCANS: dict[str, str] = {
    "b0329": "Skynet_60898_psr_b0329_54_138326_88255.A.cal.txt",
    "b1133": "Skynet_60898_psr_b1133_16_138335_88262.A.cal.txt",
    "b1933": "Skynet_60900_psr_b1933_16_138461_88378.A.cal.txt",
    "b2021": "Skynet_60901_3_Pulsar_Team_B2021+51_ERIRA_138497_88413.A.cal.txt",
    "b2045": "Skynet_60902_psr_b2045_16_138488_88426.A.cal.txt",
}

#: The curated tables, read from ``data/pulsar/curated_periods.json``
#: rather than restated here, so the tool layer and the suite compare against
#: one copy of each number (BL-8). The reasoning below is not in the JSON.
#:
#: Guarded the same way ``_discover_frames`` and ``_require`` are: this file is
#: conftest, so an unguarded read would make a missing or malformed fixture
#: uncollect the whole suite -- every WCS, photometry, fieldcal and LLM test --
#: rather than skipping the pulsar tests that actually need it. Consumers guard
#: on ``PULSAR_PERIODS_S`` being empty.
def _load_curated_pulsars() -> dict[str, dict]:
    try:
        payload = json.loads(
            (PULSAR / "curated_periods.json").read_text(encoding="utf-8")
        )
        return payload["pulsars"]
    except (OSError, ValueError, KeyError):
        return {}


_CURATED_PULSARS: dict[str, dict] = _load_curated_pulsars()

#: Reference periods (s), from ``data/pulsar/Curated pulsars.docx`` — the
#: curation shipped alongside the scans, column "Period(Literature)". That
#: document is the intended verification reference for this data set, so it is
#: what the tests compare against.
#:
#: Independent of anything in the code: the scans carry no period in-file, so a
#: successful fold is a real detection rather than a fit to a known answer.
PULSAR_PERIODS_S: dict[str, float] = {
    key: entry["period_s"] for key, entry in _CURATED_PULSARS.items()
}

#: The live ATNF Pulsar Catalogue values, retrieved 2026-08-11 via
#: ``tools.atnf.search_atnf`` (psrqpy 1.3.2). Kept as a cross-check on the
#: curated periods above, and because ``DM``/``S1400`` explain the
#: detectability spread across the five scans.
#:
#: ``p0`` agrees with the curated value to 4e-10 for B0329+54 and B2021+51, and
#: differs by 4e-6 to 2e-5 relative for the other three — different epochs or
#: source references. **That difference does not matter here**: across a 56 s
#: scan it moves the fold by at most 3e-3 of a period, and it is itself 10-25x
#: smaller than the topocentric-vs-barycentric shift (v/c = 1e-4) that neither
#: value corrects for. ``test_curated_and_atnf_periods_agree_where_it_matters``
#: pins that.
#:
#: The identifications were confirmed against each scan's own
#: ``RA(deg)``/``DEC(deg)`` header, which agrees with the catalogue position to
#: within arcseconds. That check matters here: Skynet's ``SRC_NAME`` renders
#: both B1133**+**16 and B2045**−**16 as ``_16``, so the declination sign
#: cannot be read off the filename.
PULSAR_ATNF: dict[str, dict[str, float]] = {
    key: dict(entry["atnf"]) for key, entry in _CURATED_PULSARS.items()
}

#: Difficulty rating and archival observation number, from the same curated
#: document. The rating is the curator's judgement of how hard each source is
#: to detect, and it is an independent check on the pipeline: what the code
#: measures should track what the curator expected.
PULSAR_DIFFICULTY: dict[str, dict[str, object]] = {
    key: {
        "obs": entry["observation"],
        "rank": entry["difficulty_rank"],
        "label": entry["difficulty"],
    }
    for key, entry in _CURATED_PULSARS.items()
}

#: Guard for tests that read the tables above without going through
#: ``pulsar_path`` (which skips on its own when the scans are absent).
requires_curated_periods = pytest.mark.skipif(
    not _CURATED_PULSARS,
    reason="missing fixture data/pulsar/curated_periods.json — see data/README.md",
)

#: Short aliases for the frames individual tests single out, each chosen for a
#: specific header or geometry property. See ``data/README.md``.
FRAMES: dict[str, str] = {
    # WCS written as PC + CDELT rather than CD.
    "nsv2849": "nsv2849_star_v_000.fits",
    # Photometry workhorse: CD matrix, ~2 deg rotation, positive parity.
    "ngc3628": "ngc3628_galaxy_v_000.fits",
    # Negative parity, 1024^2, comma-decimal RA/Dec strings.
    "m31": "m31_galaxy_v_000.fits",
    # ~90 deg rotation: CD1_1 near zero, scale carried off-diagonal.
    "carina": "carina_nebula_v_000.fits",
    # Real FOCALLEN (4565 mm) driving the optics-based pixel-scale path.
    "ngc5286": "ngc5286_globular_v_000.fits",
    # Unfiltered OCL passes: Lum has a WCS, Open has none at all.
    "m15_lum": "m15_globular_lum_000.fits",
    "m15_open": "m15_globular_open_000.fits",
    # Southern field at dec -69, where cos(dec) stops being negligible.
    "ngc2070": "ngc2070_nebula_v_000.fits",
    # The exact frame behind the recorded NGC 5128 solve and the Afterglow
    # API response in data/afterglow/.
    "ngc5128_b": "ngc5128_galaxy_b_001.fits",
    # The three frames behind the recorded NGC 5286 B solves (P8). Git LFS
    # objects, and the only multi-HDU frames in the tree: four Afterglow-aligned
    # exposures each, of which Kepler reads only the primary.
    "ngc5286_b_000": "ngc5286_globular_b_000.fits",
    "ngc5286_b_001": "ngc5286_globular_b_001.fits",
    "ngc5286_b_002": "ngc5286_globular_b_002.fits",
    # 1600x1200 from a third instrument, with FOCALLEN and a WCS.
    "ngc1982": "ngc1982_nebula_r_000.fits",
}


def _discover_frames() -> list[str]:
    """Every frame filename in ``data/optical``, sorted.

    Discovered rather than listed so that adding a frame to the directory
    extends the sweep tests automatically — several tests parametrize over the
    whole set to check a property holds for every real header, not just the
    handful with aliases above.
    """
    if not OPTICAL.is_dir():
        return []
    return sorted(p.name for p in OPTICAL.glob("*.fits"))


#: All frames present, for property sweeps. Empty if the data is not checked out,
#: in which case the sweeps collect zero cases and the explicit fixtures skip.
ALL_FRAMES: list[str] = _discover_frames()

#: The four recorded zero-point solves, newest-format last.
ZP_CASES: tuple[str, ...] = (
    "ngc5286_b_000",
    "ngc5286_b_001",
    "ngc5286_b_002",
    "ngc5128_b_002",
)


# ---------------------------------------------------------------------------
# Test-data location
# ---------------------------------------------------------------------------

def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(
            f"missing fixture {path.relative_to(REPO_ROOT)} — see data/README.md "
            f"for how to re-sync it from the Skynet pipeline data repository"
        )
    if is_lfs_pointer(path):
        pytest.skip(
            f"{path.relative_to(REPO_ROOT)} is an unfetched Git LFS pointer — run "
            "`git lfs install && git lfs pull` to fetch it (data/README.md)"
        )
    return path


@pytest.fixture(autouse=True)
def download_root(tmp_path, monkeypatch):
    """Point the archive download root at an empty tmp path for every test.

    ``fits_downloads/`` is gitignored but real: a developer who has ever run
    ``search_mast(..., download=True)`` has one in the working tree. It is now
    a genuine second search root for ``tools.optical``, so without this any
    test that resolves a frame -- test_optical_registry, test_fieldcal_reference,
    test_photometry_tool_smoke -- depends on untracked local state. A
    downloaded frame whose name normalizes to contain a probed name turns a
    clean resolve into an ``ambiguous`` error.

    ``DATA_DIR`` is patched alongside it, not just the download root:
    ``tools.optical`` only *walks* the download root while it resolves inside
    ``config.DATA_DIR``, so a download root sandboxed to tmp while the data
    root still pointed at the repository would be searched flat -- and every
    nested-product case would quietly stop being exercised while still passing.

    Patched on ``tools.config`` rather than the environment because both are
    computed at import.
    """
    from tools import config

    root = tmp_path / "fits_downloads"
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FITS_DOWNLOAD_DIR", root)
    return root


#: The frames stored as Git LFS objects rather than in the git tree itself
#: (P8). Everything else under ``data/optical`` is plain git, so these are the
#: only fixtures a clone can be missing while still looking complete.
LFS_FRAMES: tuple[str, ...] = (
    "ngc5286_globular_b_000.fits",
    "ngc5286_globular_b_001.fits",
    "ngc5286_globular_b_002.fits",
)


@pytest.fixture(scope="session")
def lfs_frames() -> list[Path]:
    """The LFS-tracked frames, skipping the test unless all are fetched.

    For tests that assert over the *whole* fixture tree -- counts, filter
    tallies -- where a partial checkout would otherwise read as a real
    mismatch. Individual frame tests get the same skip from ``frame_path``.
    """
    return [_require(OPTICAL / name) for name in LFS_FRAMES]


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _require(DATA_ROOT)


@pytest.fixture(scope="session")
def frame_path():
    """Return the path of a frame, by short alias or by bare filename."""

    def _get(name: str) -> Path:
        filename = FRAMES.get(name, name)
        if not filename.endswith(".fits"):  # pragma: no cover - test typo
            raise KeyError(f"unknown frame {name!r}; aliases: {sorted(FRAMES)}")
        return _require(OPTICAL / filename)

    return _get


@pytest.fixture(scope="session")
def frame_header(frame_path):
    """Return the primary header of a frame. Session-cached: headers are read-only.

    Tests that mutate a header must ask for ``frame_header_copy`` instead.
    """
    cache: dict[str, fits.Header] = {}

    def _get(name: str) -> fits.Header:
        if name not in cache:
            cache[name] = fits.getheader(frame_path(name))
        return cache[name]

    return _get


@pytest.fixture
def frame_header_copy(frame_header):
    """Return a mutable copy of a frame header, for write-back tests."""

    def _get(name: str) -> fits.Header:
        return frame_header(name).copy()

    return _get


@pytest.fixture(scope="session")
def frame_image(frame_path):
    """Return ``(data, header)`` for a frame, data as native-endian float32.

    Cached because pixel-level tests are the slowest thing in the suite, and
    ``sep`` needs native byte order — these frames are big-endian on disk
    (``>f4``), as FITS always is. Only the frames a test actually asks for are
    read; the 42-frame directory is never loaded wholesale.
    """
    cache: dict[str, tuple[np.ndarray, fits.Header]] = {}

    def _get(name: str) -> tuple[np.ndarray, fits.Header]:
        if name not in cache:
            with fits.open(frame_path(name)) as hdul:
                data = np.ascontiguousarray(hdul[0].data, dtype=np.float32)
                data.flags.writeable = False
                cache[name] = (data, hdul[0].header.copy())
        data, header = cache[name]
        return data, header

    return _get


# ---------------------------------------------------------------------------
# Recorded zero-point solves
# ---------------------------------------------------------------------------

def _to_float(value: str) -> float | None:
    """CSV cells are strings; empty means the column had no value upstream.

    ``ref_mag_error`` is blank for a good fraction of APASS rows, and
    ``calc_solution`` distinguishes "no error" from "zero error", so this must
    return ``None`` rather than 0.0.
    """
    return float(value) if value not in ("", None) else None


@pytest.fixture(scope="session")
def zp_case():
    """Return ``(calibration_rows, expected)`` for a recorded zero-point solve.

    ``calibration_rows`` are exactly the CSV rows Skynet flagged
    ``used_for_calibration``, i.e. the input list ``calc_solution`` was called
    with. ``expected`` is the ``production_calc_solution`` block from the
    matching summary — the five numbers it returned.

    The two upstream diagnostics that produced these summaries (``zp_fit.py``
    and ``zp_afterglow_fit.py``) do not agree on key names, so the count fields
    the tests read are normalised into ``num_candidates`` here. The
    ``production_calc_solution`` block itself is identical in both and is passed
    through untouched.
    """
    cache: dict[str, tuple[list[dict], dict]] = {}

    def _get(name: str) -> tuple[list[dict], dict]:
        if name not in cache:
            case_dir = _require(ZP_SOLUTIONS / name)
            with open(case_dir / "fit_data.csv", newline="") as fh:
                rows = [
                    {
                        "mag": _to_float(r["mag"]),
                        "mag_error": _to_float(r["mag_error"]),
                        "ref_mag": _to_float(r["ref_mag"]),
                        "ref_mag_error": _to_float(r["ref_mag_error"]),
                        "used": r["used_for_calibration"].strip().lower() == "true",
                        "accepted": r["accepted_by_fit"].strip().lower() == "true",
                    }
                    for r in csv.DictReader(fh)
                ]
            with open(case_dir / "fit_summary.json") as fh:
                summary = json.load(fh)
            summary["num_candidates"] = (
                summary.get("num_calibration_sources_before_fit_rejection")
                or summary["num_calibration_candidates"]
            )
            cache[name] = ([r for r in rows if r["used"]], summary)
        return cache[name]

    return _get


@pytest.fixture(scope="session")
def afterglow_web_zero_points() -> dict[str, tuple[float, float]]:
    """Afterglow web service zero points, keyed by frame filename.

    Independent ground truth: these came out of the hosted Afterglow
    field-calibration service, not out of Skynet's local pipeline, so agreement
    between them and Kepler's solver is a cross-implementation check rather than
    a self-comparison. 73 subjects; six of the eight frames in
    ``data/optical`` appear.
    """
    path = _require(AFTERGLOW / "afterglow_web_values_master.csv")
    with open(path, newline="") as fh:
        return {
            row["file"]: (
                float(row["Afterglow web zero_point"]),
                float(row["Afterglow web err"]),
            )
            for row in csv.DictReader(fh)
        }


@pytest.fixture(scope="session")
def afterglow_fieldcal_response() -> dict:
    """The full Afterglow field-calibration API response for NGC 5128 B.

    Carries the settings Afterglow itself ran with — including
    ``apcorr_tol: 0`` and ``zero_point: 20`` — alongside its per-source
    photometry. Same run as the ``ngc5128_b_002`` recorded solve.
    """
    with open(_require(AFTERGLOW / "fieldcal" / "ngc_5128_test_vals.json")) as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def afterglow_photometry_rows() -> list[dict]:
    """Afterglow's per-source photometry export for the same NGC 5128 run."""
    path = _require(AFTERGLOW / "photometry" / "afterglow_photometry_ngc5128_b.csv")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="session")
def ocl_filter_report(data_dir) -> dict:
    """Skynet's Open/Clear/Lum substitute-filter trial report."""
    with open(_require(data_dir / "fieldcal" / "ocl_filter_report.json")) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Pulsar scans
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pulsar_path():
    """Return the path of a pulsar scan, by short alias or bare filename."""

    def _get(name: str) -> Path:
        filename = PULSAR_SCANS.get(name, name)
        if not filename.endswith(".txt"):  # pragma: no cover - test typo
            raise KeyError(f"unknown scan {name!r}; aliases: {sorted(PULSAR_SCANS)}")
        return _require(PULSAR / filename)

    return _get


@pytest.fixture
def artifact_dir(tmp_path, monkeypatch):
    """Point ``tools.artifacts`` at a temp directory for one test.

    ``ARTIFACT_DIR`` is bound at import time, so the patch has to land on the
    ``tools.artifacts`` name rather than on ``tools.config``.
    """
    import tools.artifacts as artifacts_module

    monkeypatch.setattr(artifacts_module, "ARTIFACT_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Opt-in / availability gates
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def anet_available() -> bool:
    """Whether a usable astrometry.net install is present.

    ``solve-field`` on PATH is necessary but not sufficient: a blind solve also
    needs index files covering the field scale. Callers that only need the
    binary check this; callers that need a real solve are marked
    ``solver_data`` and skip on their own.
    """
    return shutil.which("solve-field") is not None


@pytest.fixture(scope="session")
def atlas_catalog_root() -> str | None:
    """Root of a local UCAC4/UCAC5 tree, or ``None`` if not configured."""
    root = os.environ.get("ATLAS_CATALOG_ROOT")
    return root if root and Path(root).is_dir() else None


def pytest_collection_modifyitems(config, items):
    """Deselect the opt-in live markers unless their environment gate is set.

    A marker alone would still let ``-m network`` (or ``-m model_api``) fire a
    live call by accident in CI; requiring the environment variable too makes
    the opt-in explicit, as CLAUDE.md asks for remote calls.
    """
    net_on = os.environ.get("KEPLER_TEST_NETWORK") == "1"
    model_on = os.environ.get("KEPLER_TEST_MODEL_API") == "1"

    net_skip = pytest.mark.skip(
        reason="live catalog query; set KEPLER_TEST_NETWORK=1 to run"
    )
    model_skip = pytest.mark.skip(
        reason="live model provider; set KEPLER_TEST_MODEL_API=1 to run"
    )
    for item in items:
        if not net_on and "network" in item.keywords:
            item.add_marker(net_skip)
        if not model_on and (
            "model_api" in item.keywords or "ollama" in item.keywords
        ):
            item.add_marker(model_skip)
