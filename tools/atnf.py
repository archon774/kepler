"""Kepler: ATNF Pulsar Catalogue lookup.

The old code hardcoded ``params=['PSRJ', 'P0', 'DM', 'AGE']`` -- four columns
out of the roughly 150 the catalogue can carry. The fix is not to force the
*full* list (``algorithms.catalogs.atnf.PSR_ALL_PARAMS``) as the default: confirmed
live, requesting every parameter explicitly raises a "not in index" error for
any pulsar missing an optional one (glitch parameters, for instance, only
exist for pulsars that have glitched). Leaving ``params`` unset lets psrqpy
return whatever it actually has for that pulsar, which is already the
complete available set -- including ``_ERR``/``_REF`` columns via
``include_errs``/``include_refs``. ``algorithms.catalogs.atnf.PSR_ALL_PARAMS`` remains
useful as a reference vocabulary for a caller who wants to request a
deliberate subset (e.g. ``algorithms.catalogs.atnf.PSR_BINARY_PARAMS``).

``include_refs=True`` attaches the literature reference each parameter's
value came from -- as close to "historical data" as ATNF's
single-current-value catalogue gets; it does not carry a value history the
way SIMBAD's measurement tables or NED's photometry table do.
"""

from __future__ import annotations

from typing import Optional

import psrqpy

from tools import artifacts
from tools.config import PREVIEW_ROWS
from tools.models import ToolResult

__all__ = ["search_atnf"]


def search_atnf(
    name: str, params: Optional[list[str]] = None, include_refs: bool = True
) -> ToolResult:
    """Return every ATNF Pulsar Catalogue parameter available for ``name``.

    ``params`` defaults to ``None``, which asks psrqpy for whatever it
    actually has for this pulsar rather than a fixed column list -- pass a
    subset (e.g. ``algorithms.catalogs.atnf.PSR_BINARY_PARAMS``) to narrow it. A name
    that isn't a pulsar returns ``not_found`` -- ATNF has no special-cased
    rejection for any particular non-pulsar object.
    """
    if not name or not name.strip():
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "name must not be blank"}],
        )

    try:
        query = psrqpy.QueryATNF(psrs=[name], params=params, include_refs=include_refs)
        table = query.table
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if table is None or len(table) == 0:
        return ToolResult(status="not_found", count=0)

    artifact = artifacts.write_table(table, f"atnf_{name}", subdir="atnf")
    return ToolResult(
        status="ok",
        count=len(table),
        preview=artifacts.preview_rows(table, PREVIEW_ROWS),
        columns=[str(c) for c in table.colnames],
        artifact=artifact,
    )
