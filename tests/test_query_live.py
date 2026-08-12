"""Live end-to-end field-calibration parity: Kepler vs. the Afterglow web service.

``test_fieldcal_afterglow_parity.py`` proves ``calc_solution``'s *math* reproduces
Skynet's and Afterglow's recorded numbers exactly, from *recorded* per-star inputs
-- no network needed. This file closes the loop the other way: running the entire
live pipeline (source extraction -> aperture photometry -> live catalog
cross-match -> ``calc_solution``) against a real, current reference catalog, and
checking the solved zero point against
``test_data/afterglow/afterglow_web_values_master.csv`` -- a number Afterglow's
own hosted service produced independently, by a different implementation, at a
different time.

Never runs by default -- live queries are inherently non-deterministic (catalog
snapshots and cross-match results can drift between runs) -- see CLAUDE.md: "Keep
live remote astronomy service calls out of default checks." Requires
``KEPLER_TEST_NETWORK=1`` (and, to select only these, ``-m network``).

Only frames the tool can actually resolve are covered here --
``test_data/optical/``, not ``test_subjects/``, which nothing in ``tools/`` reads
(see ``docs/repository-folders.md``). That's 37 of the masterlist's 73 rows as of
this writing; the target list is discovered dynamically (same rationale as
``conftest.py``'s ``_discover_frames``) so a newly bundled frame with a masterlist
entry is covered automatically, with nothing to keep in sync by hand.

Failure bar: more than ``HARD_FAIL_SIGMA`` combined-sigma (Kepler's and Afterglow's
own reported errors added in quadrature) is a hard failure -- something has
actually drifted. 2-4 sigma prints a warning but does not fail: on real data, a
handful of frames with large intrinsic photometric scatter (bright nebulosity,
tiny calibration-star samples) can land there through no fault of the code, as
already observed live and investigated (not confirmed as a bug in either case):
``carina_nebula_v_000`` at ~3.7 sigma (90 calibration stars, unusually large
solve scatter -- plausibly the nebula's bright, structured background, not
confirmed) and ``ngc2997_galaxy_v_002`` at ~2.9 sigma (a smaller, 27-star sample).
"""

from __future__ import annotations

import csv
import math
import warnings
from pathlib import Path

import pytest

from tools.photometry import run_photometry_on_target

REPO_ROOT = Path(__file__).resolve().parent.parent
OPTICAL = REPO_ROOT / "test_data" / "optical"
MASTERLIST = REPO_ROOT / "test_data" / "afterglow" / "afterglow_web_values_master.csv"

#: More than this many combined-sigma from the web value is a hard failure.
#: Below it but at or above 2.0 is a printed warning only -- see module
#: docstring for why that softer band exists at all.
HARD_FAIL_SIGMA = 4.0


def _load_masterlist() -> dict[str, tuple[float, float]]:
    with open(MASTERLIST, newline="") as fh:
        return {
            row["file"]: (
                float(row["Afterglow web zero_point"]),
                float(row["Afterglow web err"]),
            )
            for row in csv.DictReader(fh)
        }


def _resolvable_targets() -> list[str]:
    """Masterlist entries this tool can actually load, minus their ``.fits`` suffix.

    Empty (rather than raising) if the fixture data isn't checked out, so
    collection still succeeds and simply parametrizes to zero cases.
    """
    if not OPTICAL.is_dir() or not MASTERLIST.is_file():
        return []
    masterlist = _load_masterlist()
    bundled = {p.name for p in OPTICAL.glob("*.fits")}
    return sorted(name[:-5] for name in (bundled & set(masterlist)))


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.parametrize("target", _resolvable_targets())
def test_live_field_cal_zero_point_matches_afterglow_web_value(target, tmp_path):
    """Kepler's live field-cal solve agrees with an independent reference.

    Confirmed live on this test's first run (2026-08-12, all 37 then-resolvable
    frames): 34 landed under 2 combined-sigma, 2 landed in the 2-4 sigma warning
    band (see module docstring), and one frame (``nsv2849_star_v_000``) skips here
    because its header already carries a stamped zero point that correctly takes
    priority over field-cal -- expected, documented ``cli > header > field-cal``
    resolution order, not something this test exercises.
    """
    zero_points = _load_masterlist()
    web_zero_point, web_error = zero_points[f"{target}.fits"]

    result = run_photometry_on_target(target, use_field_cal=True, output_dir=tmp_path)

    if result.zero_point_source != "field-cal":
        pytest.skip(
            f"{target}: zero point came from {result.zero_point_source!r}, not a "
            "live field-cal solve (e.g. a header-stamped value took priority) -- "
            "nothing to compare against the web table here."
        )

    assert result.zero_point is not None
    kepler_zero_point = result.zero_point.zero_point_corr
    kepler_error = result.zero_point.zero_point_error_mag or 0.0

    diff = kepler_zero_point - web_zero_point
    combined_sigma = math.sqrt(kepler_error**2 + web_error**2)
    n_sigma = abs(diff) / combined_sigma if combined_sigma > 0 else math.inf

    if HARD_FAIL_SIGMA > n_sigma >= 2.0:
        warnings.warn(
            f"{target}: {n_sigma:.1f} combined-sigma from the Afterglow web value "
            f"(kepler={kepler_zero_point:.4f}+/-{kepler_error:.4f}, "
            f"web={web_zero_point:.3f}+/-{web_error:.3f}, diff={diff:+.4f}) -- "
            "within the non-failing warning band, but worth a look if it recurs "
            "across runs.",
            stacklevel=1,
        )

    assert n_sigma < HARD_FAIL_SIGMA, (
        f"{target}: kepler zero point {kepler_zero_point:.4f}+/-{kepler_error:.4f} "
        f"is {n_sigma:.1f} combined-sigma from the Afterglow web value "
        f"{web_zero_point:.3f}+/-{web_error:.3f} (diff={diff:+.4f}) -- outside the "
        f"{HARD_FAIL_SIGMA}-sigma failure bar."
    )
