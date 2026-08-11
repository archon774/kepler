"""Kepler: Minor Planet Center observation history.

The old code tried an ephemeris lookup first (5 points, forward-looking) and
fell back to observations only on failure -- conflating two different
questions. ``get_observations`` is the actual "historical data" answer for a
minor planet: the full reported observation history, unpaged (6849 rows for
asteroid 1/Ceres in one live check).

Confirmed live against the installed astroquery (0.4.11): an unresolvable
designation raises ``ValueError`` (mapped to ``invalid_input``); an empty
result raises ``RuntimeError`` (mapped to ``not_found``) per
``get_observations``'s own documented behavior. Single-target only -- no
name-based search, no batching multiple designations in one call.
"""

from __future__ import annotations

from astroquery.mpc import MPC

from kepler import artifacts
from kepler.config import PREVIEW_ROWS
from kepler.models import ToolResult

__all__ = ["search_mpc"]


def search_mpc(designation) -> ToolResult:
    """Return the full reported observation history for one minor planet.

    ``designation`` is an asteroid number (int or str), an asteroid
    designation, a periodic comet number with a trailing ``"P"``, or a comet
    designation starting with its type letter (e.g. ``"C/2018 E1"``) -- see
    ``astroquery.mpc.MPC.get_observations`` for the exact accepted forms.
    Comet/asteroid *names*, Palomar-Leiden Survey designations, and
    individual comet fragments cannot be queried this way.
    """
    if designation is None or (isinstance(designation, str) and not designation.strip()):
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "designation must not be blank"}],
        )

    try:
        table = MPC.get_observations(designation)
    except ValueError as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": str(exc)}],
        )
    except RuntimeError:
        return ToolResult(status="not_found", count=0)
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if table is None or len(table) == 0:
        return ToolResult(status="not_found", count=0)

    artifact = artifacts.write_table(table, f"mpc_{designation}_observations", subdir="mpc")
    return ToolResult(
        status="ok",
        count=len(table),
        preview=artifacts.preview_rows(table, PREVIEW_ROWS),
        columns=[str(c) for c in table.colnames],
        artifact=artifact,
    )
