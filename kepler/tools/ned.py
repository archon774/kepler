"""Kepler: NED historical tables for an object.

NED (NASA/IPAC Extragalactic Database) answers "give me all historical
measurements of X" more directly than most other sources here:
``Ned.get_table(name, table="photometry")`` returns every published
flux/magnitude measurement for the object, with frequency/band and reference,
unpaged -- no row limit is documented for it.

Confirmed live against the installed astroquery (0.4.11): ``get_table``'s
signature and valid ``table`` values (see ``catalogs/ned.py``), and that an
unresolvable name raises ``astroquery.exceptions.RemoteServiceError`` rather
than returning an empty table.

Also confirmed live, via an agent transcript: NED's photometry endpoint reads
as flaky under its default 60s timeout for at least one real object (Cas A),
timing out three separate times before succeeding on a fourth attempt made
minutes later with no code change. Retried as three separate agent turns,
that cost half a 6-turn budget on one tool. This module retries internally
instead, so a transient timeout costs wall-clock time inside one tool call,
not a caller's turn budget.

NED's own ``get_table`` has no band/frequency filter -- ``output_table_format``
controls units, not which rows come back. A "photometry" request for a
well-studied object always returns its full SED, X-ray through radio, in one
table. Confirmed live via an agent transcript: without a way to narrow that
here, an agent asked for "radio only" got the full multi-band table and
reported X-ray/gamma points in its answer. ``min_frequency_hz``/
``max_frequency_hz`` filter client-side after the fetch -- the classic radio
continuum band is below roughly 3e11 Hz (300 GHz).
"""

from __future__ import annotations

import time
from typing import Optional

from astroquery.exceptions import RemoteServiceError
from astroquery.ipac.ned import Ned

from catalogs.ned import NED_TABLES
from kepler import artifacts
from kepler.config import PREVIEW_ROWS
from kepler.models import ToolResult

__all__ = ["search_ned"]

Ned.TIMEOUT = 90

_MAX_ATTEMPTS = 3
_RETRY_DELAY_S = 3


def search_ned(
    name: str,
    table: str = "photometry",
    *,
    output_table_format: int = 3,
    from_year: Optional[int] = None,
    to_year: Optional[int] = None,
    min_frequency_hz: Optional[float] = None,
    max_frequency_hz: Optional[float] = None,
) -> ToolResult:
    """Return NED's full ``table`` for ``name``.

    ``table`` defaults to ``"photometry"`` -- NED's literature-compiled flux
    history, the primary answer to "all historical [radio] data on X" from
    this source. ``output_table_format`` (photometry only) defaults to ``3``,
    "Homogenized Units (mJy)", so measurements published in inconsistent
    units over a century of literature come back comparable. ``from_year``/
    ``to_year`` apply only when ``table="references"``.

    ``min_frequency_hz``/``max_frequency_hz`` restrict the ``photometry``
    result to a band by ``Frequency`` (Hz) -- NED itself has no such filter,
    so a request that should be radio-only otherwise comes back with the
    object's full SED, X-ray through gamma-ray. Pass ``max_frequency_hz=3e11``
    (300 GHz) for a conventional radio-continuum cutoff. Ignored, with a
    warning, for any other ``table``.
    """
    if table not in NED_TABLES:
        return ToolResult(
            status="error",
            errors=[
                {
                    "code": "invalid_input",
                    "message": f"table must be one of {sorted(NED_TABLES)}, got {table!r}",
                }
            ],
        )
    if not name or not name.strip():
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "name must not be blank"}],
        )

    kwargs = {}
    if table == "photometry":
        kwargs["output_table_format"] = output_table_format
    elif table == "references":
        if from_year is not None:
            kwargs["from_year"] = from_year
        if to_year is not None:
            kwargs["to_year"] = to_year

    result = None
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            result = Ned.get_table(name, table=table, **kwargs)
            last_exc = None
            break
        except RemoteServiceError:
            # NED's name interpreter didn't recognize the object -- an
            # ordinary outcome, not a provider fault. Retrying won't help.
            return ToolResult(status="not_found", count=0)
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY_S)

    if last_exc is not None:
        return ToolResult(
            status="error",
            errors=[
                {
                    "code": "provider_unavailable",
                    "message": f"{last_exc} (after {_MAX_ATTEMPTS} attempts)",
                }
            ],
        )

    if result is None or len(result) == 0:
        return ToolResult(status="not_found", count=0)

    warnings: list[str] = []
    if min_frequency_hz is not None or max_frequency_hz is not None:
        if table != "photometry" or "Frequency" not in result.colnames:
            warnings.append(
                "min_frequency_hz/max_frequency_hz only apply to table="
                "'photometry'; ignored here"
            )
        else:
            before = len(result)
            if min_frequency_hz is not None:
                result = result[result["Frequency"] >= min_frequency_hz]
            if max_frequency_hz is not None:
                result = result[result["Frequency"] <= max_frequency_hz]
            warnings.append(
                f"frequency-filtered {before} rows to {len(result)} "
                f"(min={min_frequency_hz}, max={max_frequency_hz})"
            )
            if len(result) == 0:
                return ToolResult(status="not_found", count=0, warnings=warnings)

    artifact = artifacts.write_table(result, f"ned_{name}_{table}", subdir="ned")
    return ToolResult(
        status="ok",
        count=len(result),
        preview=artifacts.preview_rows(result, PREVIEW_ROWS),
        columns=[str(c) for c in result.colnames],
        artifact=artifact,
        warnings=warnings,
    )
