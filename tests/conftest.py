"""Shared fixtures for Kepler's algorithm tests.

Two rules shape everything here, both from ``CLAUDE.md``:

* **Default checks stay deterministic and bounded.** Nothing in this suite opens
  a socket unless it is marked ``network``, and nothing marked ``network`` runs
  without ``KEPLER_TEST_NETWORK=1``.
* **The Python folders are byte-preserving extractions.** So the fixtures are
  real Skynet frames and real recorded Skynet solver output, not synthesised
  arrays — see ``test_data/README.md``.

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

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = REPO_ROOT / "test_data"
OPTICAL = TEST_DATA / "optical"
ZP_SOLUTIONS = TEST_DATA / "fieldcal" / "zp_solutions"
AFTERGLOW = TEST_DATA / "afterglow"

#: Short aliases for the frames individual tests single out, each chosen for a
#: specific header or geometry property. See ``test_data/README.md``.
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
    # API response in test_data/afterglow/.
    "ngc5128_b": "ngc5128_galaxy_b_001.fits",
    # 1600x1200 from a third instrument, with FOCALLEN and a WCS.
    "ngc1982": "ngc1982_nebula_r_000.fits",
}


def _discover_frames() -> list[str]:
    """Every frame filename in ``test_data/optical``, sorted.

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
            f"missing fixture {path.relative_to(REPO_ROOT)} — see test_data/README.md "
            f"for how to re-sync it from the Skynet pipeline data repository"
        )
    return path


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    return _require(TEST_DATA)


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
    read; the 39-frame directory is never loaded wholesale.
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
    ``test_data/optical`` appear.
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
def ocl_filter_report(test_data_dir) -> dict:
    """Skynet's Open/Clear/Lum substitute-filter trial report."""
    with open(_require(test_data_dir / "fieldcal" / "ocl_filter_report.json")) as fh:
        return json.load(fh)


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
    """Deselect ``network`` tests unless ``KEPLER_TEST_NETWORK=1``.

    A marker alone would still let ``-m network`` fire live queries by accident
    in CI; requiring the environment variable too makes the opt-in explicit, as
    CLAUDE.md asks for remote astronomy calls.
    """
    if os.environ.get("KEPLER_TEST_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="live catalog query; set KEPLER_TEST_NETWORK=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
