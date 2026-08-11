"""Kepler: SIMBAD identity, historical measurements, and bibliography.

SIMBAD is richer than a name-to-coordinates lookup (that's
``kepler.tools.resolve``). Historical per-paper measurements live in
dedicated TAP tables (``flux``, ``mesPM``, ``mesDiameter``, ...) joined to an
object by SIMBAD's internal ``oidref``/``oid``, not by name -- a plain
``query_object`` with extra VOTable fields only ever returns one best-value
row per band. Bibliography works the same way, joined through
``has_ref``/``ref``.

Confirmed live against the installed astroquery (0.4.11) TAP schema, not
guessed from documentation prose: every table below has an ``oidref`` join
column (``Simbad.list_columns``), and ``"year"`` is a reserved ADQL word --
quoting it in ``SELECT`` works, but ``ORDER BY`` on it does not in this TAP
dialect, so bibliography results are sorted client-side instead.

``get_paper_abstract`` exists because of a confirmed real failure: without any
way to fetch abstract text, an agent asked to confirm a specific decline rate
from "Trotter et al. 2017" answered "0.3-0.7%/yr depending on frequency" --
plausible-sounding, attributed to a real paper by name, and wrong. The actual
abstract (fetched via this function) says "0.670 +/- 0.019 per cent yr^-1"
averaged over 1950s-2010s, explicitly *not* constant. The number came from the
model's own training data, not from any tool call, and was presented as if
the pipeline had verified it. This function is the one way this tool set can
ground a specific quantitative literature claim in retrieved text instead.
"""

from __future__ import annotations

from typing import Optional

from astroquery.simbad import Simbad

from kepler import artifacts
from kepler.config import PREVIEW_ROWS
from kepler.models import ToolResult

__all__ = [
    "MEASUREMENT_TABLES",
    "search_simbad",
    "search_simbad_measurements",
    "search_simbad_bibliography",
    "get_paper_abstract",
]

#: TAP tables holding historical per-paper measurements, joined to an object
#: by ``oidref``. Confirmed live via ``Simbad.list_columns(<table>)``.
MEASUREMENT_TABLES: dict[str, str] = {
    "flux": "Magnitude/flux measurements by filter and bibcode.",
    "mesPM": "Proper motion measurements.",
    "mesPLX": "Trigonometric parallax measurements.",
    "mesDiameter": "Stellar diameter measurements.",
    "mesVelocities": "Radial velocity / Vlsr / cz / redshift measurements.",
    "mesVar": "Variability type and period measurements.",
    "mesRot": "Stellar rotational velocity measurements.",
    "mesSpT": "Spectral type measurements.",
    "mesFe_h": "Metallicity / Teff / logg measurements.",
    "mesDistance": "Distance measurements (pc/kpc/Mpc) by various means.",
    "mesOtype": "Object-type classifications with origin.",
    "mesISO": "ISO observing log entries.",
    "mesXmm": "XMM-Newton observing log entries.",
    "mesIUE": "IUE observing log entries.",
    "mesHerschel": "Herschel observing log entries.",
}


def _blank_name_error() -> ToolResult:
    return ToolResult(
        status="error",
        errors=[{"code": "invalid_input", "message": "name must not be blank"}],
    )


def _provider_error(exc: Exception) -> ToolResult:
    return ToolResult(
        status="error",
        errors=[{"code": "provider_unavailable", "message": str(exc)}],
    )


def _escape(value: str) -> str:
    """Escape a single-quoted ADQL string literal."""
    return value.replace("'", "''")


def search_simbad(name: str, fields: Optional[list[str]] = None) -> ToolResult:
    """Look up ``name`` on SIMBAD with its default fields plus ``fields``.

    ``fields`` are any of ``Simbad.list_votable_fields()``'s names (e.g.
    ``"otype"``, ``"allfluxes"``). Returns SIMBAD's *current best-value* row
    per object -- for historical per-paper measurement rows use
    ``search_simbad_measurements`` instead.
    """
    if not name or not name.strip():
        return _blank_name_error()

    simbad = Simbad()
    if fields:
        simbad.add_votable_fields(*fields)

    try:
        table = simbad.query_object(name)
    except Exception as exc:
        return _provider_error(exc)

    if table is None or len(table) == 0:
        return ToolResult(status="not_found", count=0)

    artifact = artifacts.write_table(table, f"simbad_{name}", subdir="simbad")
    return ToolResult(
        status="ok",
        count=len(table),
        preview=artifacts.preview_rows(table, PREVIEW_ROWS),
        columns=[str(c) for c in table.colnames],
        artifact=artifact,
    )


def search_simbad_measurements(name: str, table: str = "flux") -> ToolResult:
    """Return every historical measurement of ``table`` kind SIMBAD has for
    ``name`` -- one row per publication, not a single best value.

    ``table`` must be a key of ``MEASUREMENT_TABLES`` (``"flux"`` by
    default -- the historical flux/magnitude record).
    """
    if table not in MEASUREMENT_TABLES:
        return ToolResult(
            status="error",
            errors=[
                {
                    "code": "invalid_input",
                    "message": f"table must be one of {sorted(MEASUREMENT_TABLES)}, "
                    f"got {table!r}",
                }
            ],
        )
    if not name or not name.strip():
        return _blank_name_error()

    adql = (
        f'SELECT m.* FROM ident i '
        f'JOIN basic b ON b.oid = i.oidref '
        f'JOIN "{table}" m ON m.oidref = b.oid '
        f"WHERE i.id = '{_escape(name)}'"
    )
    try:
        rows = Simbad.query_tap(adql)
    except Exception as exc:
        return _provider_error(exc)

    if rows is None or len(rows) == 0:
        return ToolResult(status="not_found", count=0)

    artifact = artifacts.write_table(rows, f"simbad_{name}_{table}", subdir="simbad")
    return ToolResult(
        status="ok",
        count=len(rows),
        preview=artifacts.preview_rows(rows, PREVIEW_ROWS),
        columns=[str(c) for c in rows.colnames],
        artifact=artifact,
    )


def search_simbad_bibliography(name: str) -> ToolResult:
    """Return every paper SIMBAD has on file that discusses ``name``.

    A partial, incidental substitute for literature search while ADS support
    is deferred -- not equivalent to it.
    """
    if not name or not name.strip():
        return _blank_name_error()

    adql = (
        'SELECT r.bibcode, r."year", r.journal, r.title, r.doi FROM ident i '
        "JOIN basic b ON b.oid = i.oidref "
        "JOIN has_ref hr ON hr.oidref = b.oid "
        "JOIN ref r ON r.oidbib = hr.oidbibref "
        f"WHERE i.id = '{_escape(name)}'"
    )
    try:
        rows = Simbad.query_tap(adql)
    except Exception as exc:
        return _provider_error(exc)

    if rows is None or len(rows) == 0:
        return ToolResult(status="not_found", count=0)

    # ORDER BY on the quoted "year" column fails in this TAP dialect --
    # confirmed live -- so results are sorted client-side instead.
    rows.sort("year", reverse=True)

    artifact = artifacts.write_table(rows, f"simbad_{name}_bibliography", subdir="simbad")
    return ToolResult(
        status="ok",
        count=len(rows),
        preview=artifacts.preview_rows(rows, PREVIEW_ROWS),
        columns=[str(c) for c in rows.colnames],
        artifact=artifact,
    )


def get_paper_abstract(bibcode: str) -> ToolResult:
    """Return title, year, journal, and abstract text for one bibcode.

    Use this to ground a specific quantitative claim from a paper -- found via
    ``search_simbad_bibliography`` or ``search_ned`` (``table="references"``)
    -- in text that was actually retrieved, rather than recalling it. Not
    every bibcode has abstract text on file (coverage thins for older or
    non-open-access papers); that returns ``not_found``, not an error -- do
    not substitute a recalled figure for a missing abstract without saying so.
    """
    if not bibcode or not bibcode.strip():
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "bibcode must not be blank"}],
        )

    try:
        row = Simbad.query_bibcode(bibcode, abstract=True)
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if row is None or len(row) == 0:
        return ToolResult(status="not_found", count=0)

    abstract = row["abstract"][0] if "abstract" in row.colnames else None
    if not abstract:
        return ToolResult(
            status="not_found",
            count=0,
            warnings=["bibcode found but no abstract text is on file for it"],
        )

    return ToolResult(
        status="ok",
        count=1,
        preview=[
            {
                "bibcode": str(row["bibcode"][0]),
                "title": str(row["title"][0]),
                "year": int(row["year"][0]) if row["year"][0] else None,
                "journal": str(row["journal"][0]),
                "abstract": str(abstract),
            }
        ],
        columns=["bibcode", "title", "year", "journal", "abstract"],
    )
