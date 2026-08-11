"""Kepler: general VizieR access -- any catalog, any spectrum.

VizieR hosts roughly 20,000 tables across every wavelength, not just the
eleven photometric catalogs ``catalogs/`` declares for Kepler's own
zero-point calibration path (a different consumer -- see ``fieldcal``). This
tool goes straight to ``astroquery.vizier.Vizier`` instead, so it can reach
any catalog by ID or by VizieR's own spectrum category, with no curated list
in between.

Bypassing Kepler's ``CatalogSource``/``mags`` mapping here is deliberate, not
incidental: ``query/vizier.py`` treats any value >= 99 as VizieR's
"not measured" magnitude sentinel, which would silently drop radio flux
measurements (Cas A is ~2.72e6 mJy at 1.4 GHz) if this tool routed through
that engine. Going around it avoids the bug rather than requiring a fix
there.

Confirmed live against the installed astroquery (0.4.11): ``Vizier.__init__``
and ``query_object``/``query_region``/``find_catalogs`` signatures, and that
``keywords=["radio"]`` on the constructor actually restricts ``query_object``
to radio catalogues -- 56 matched for "Cas A" in one live check, including
NVSS (``VIII/65``), WENSS (``VIII/62``), 3CR (``VIII/1A``), 4C (``VIII/4``).
"""

from __future__ import annotations

from typing import Optional, Union

import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.vizier import Vizier

from kepler import artifacts
from kepler.config import DEFAULT_MAX_CATALOGS, PREVIEW_ROWS
from kepler.models import ArtifactRef, ToolResult, coerce_optional_int

__all__ = ["list_vizier_catalogs", "search_vizier"]


def list_vizier_catalogs(keywords: str, max_catalogs: int = 50) -> ToolResult:
    """Discover VizieR catalogs matching free-text ``keywords``.

    Metadata only -- no object data is fetched. Use this when the caller
    doesn't already know a catalog ID or VizieR's own spectrum category
    (``"radio"``, ``"optical"``, ``"infrared"``, ``"xray"``, ...) to pass to
    ``search_vizier``.
    """
    if not keywords or not keywords.strip():
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "keywords must not be blank"}],
        )

    try:
        found = Vizier.find_catalogs(keywords, max_catalogs=max_catalogs)
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if not found:
        return ToolResult(status="not_found", count=0)

    # Confirmed live: a query that matches nothing well-formed can return a
    # single resource keyed by None with no description -- not a catalog a
    # caller could ever query, so it's dropped rather than surfaced as one.
    preview = [
        {"catalog_id": catalog_id, "description": resource.description or ""}
        for catalog_id, resource in found.items()
        if catalog_id is not None
    ]
    if not preview:
        return ToolResult(status="not_found", count=0)
    return ToolResult(
        status="ok",
        count=len(preview),
        preview=preview[:PREVIEW_ROWS],
        columns=["catalog_id", "description"],
    )


def search_vizier(
    target: Optional[str] = None,
    *,
    ra_hours: Optional[float] = None,
    dec_degs: Optional[float] = None,
    radius_arcmin: float = 2.0,
    catalog: Optional[Union[list[str], str]] = None,
    category: Optional[Union[list[str], str]] = None,
    column_filters: Optional[dict] = None,
    row_limit: int = -1,
    max_catalogs: Union[int, str, None] = DEFAULT_MAX_CATALOGS,
) -> ToolResult:
    """Query any VizieR catalog (or set of catalogs) around a target.

    ``catalog``: an explicit VizieR ID or list of IDs (e.g. ``"VIII/65"`` for
    NVSS) -- direct access to any of VizieR's ~20,000 tables, known or not.
    ``category``: VizieR's own spectrum vocabulary (``"radio"``, ``"optical"``,
    ``"infrared"``, ``"xray"``, ...), restricting the search with no catalog
    ID at all. This is the mechanism for "all of <target> in radio."
    ``row_limit=-1`` (unlimited) and every column (not VizieR's curated
    default subset) are the defaults -- both matter for radio catalogs' flux
    columns and for genuinely historical, unbounded retrieval.

    A broad ``category``/keyword search can match more catalogs than are
    useful to write out by default. ``max_catalogs`` bounds how many of the
    *matched* tables get written to disk and summarized -- never how many are
    matched, which is always reported in full, with a warning (never a
    silent drop) when it exceeds ``max_catalogs``. Pass ``max_catalogs=None``
    to write every matched catalog with no cap at all -- do this whenever the
    caller actually asked for "all"/"every"/"complete" data; the default cap
    exists only to keep an unscoped exploratory query fast.
    """
    if target is None and (ra_hours is None or dec_degs is None):
        return ToolResult(
            status="error",
            errors=[
                {
                    "code": "invalid_input",
                    "message": "either target or both ra_hours and dec_degs are required",
                }
            ],
        )

    try:
        max_catalogs = coerce_optional_int(max_catalogs)
    except ValueError as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": f"max_catalogs: {exc}"}],
        )

    warnings: list[str] = []
    if target is not None and ra_hours is not None:
        warnings.append(
            f"both target={target!r} and ra_hours/dec_degs were given; "
            "coordinates were used for the query and target was ignored"
        )
    if category is not None:
        # Confirmed live: category tags whole catalogs, not individual rows --
        # "radio" also matches multi-wavelength cross-match catalogs (e.g.
        # V/138, "A catalogue of cross-matched radio/infrared/X-ray sources")
        # where only some columns are radio-derived.
        warnings.append(
            f"category={category!r} matches catalogs tagged with that spectrum "
            "as a whole, which can include multi-wavelength cross-match catalogs "
            "where only some columns are in that band -- check each artifact's "
            "columns and the catalog's own name before treating every matched "
            "row as a pure measurement in that spectrum"
        )

    # astroquery's VizierKeyword setter does `list(values)` when given a bare
    # string -- silently splitting "radio" into ['r','a','d','i','o']. List it
    # ourselves so a single category name (the common case) works correctly.
    # Confirmed live: this is the installed astroquery's (0.4.11) actual
    # behavior, not a hypothetical.
    keywords = [category] if isinstance(category, str) else category

    vizier = Vizier(
        columns=["**"],
        row_limit=row_limit,
        catalog=catalog,
        keywords=keywords,
        column_filters=column_filters or {},
    )

    try:
        if target is not None and ra_hours is None:
            result = vizier.query_object(target, catalog=catalog)
        else:
            coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_degs * u.deg)
            result = vizier.query_region(
                coord, radius=radius_arcmin * u.arcmin, catalog=catalog
            )
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if not result:
        return ToolResult(status="not_found", count=0)

    matched = list(result.keys())
    to_write = matched if max_catalogs is None else matched[:max_catalogs]
    if max_catalogs is not None and len(matched) > max_catalogs:
        warnings.append(
            f"matched {len(matched)} catalogs, wrote {len(to_write)}; raise "
            "max_catalogs, set it to JSON null for no cap, or narrow with "
            "catalog=/category= to reach the rest"
        )

    written: list[ArtifactRef] = []
    preview: list[dict] = []
    # A caller working from the JSON response alone (an agent, not a script
    # opening the artifact files) needs *some* visible content to judge
    # whether a broad category search found anything worth keeping, or
    # whether to try a narrower one -- an empty preview here was confirmed
    # live to make an agent distrust a large `count` and start re-querying
    # individual catalogs one at a time instead of trusting the bulk result.
    # A couple of rows per catalog, tagged with its ID, is enough for that
    # without duplicating the full artifact inline.
    rows_per_catalog = max(1, PREVIEW_ROWS // max(len(to_write), 1))
    for catalog_id in to_write:
        table = result[catalog_id]
        written.append(artifacts.write_table(table, catalog_id, subdir="vizier"))
        for row in artifacts.preview_rows(table, rows_per_catalog):
            if len(preview) >= PREVIEW_ROWS:
                break
            preview.append({"catalog_id": catalog_id, **row})

    return ToolResult(
        status="ok" if len(matched) == len(to_write) else "partial",
        count=sum(a.row_count or 0 for a in written),
        preview=preview,
        artifacts=written,
        warnings=warnings
        + ["columns vary per catalog -- see each artifact's own columns list"],
    )
