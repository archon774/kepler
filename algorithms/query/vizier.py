"""VizieR query backend.

Nine of Kepler's eleven catalogs are hosted at VizieR, and they differ only in
their declarations: which table, which columns, which bands. This module is the
one engine that drives all of them.

Three jobs:

1. **Work out which columns to request.** A plugin's ``col_mapping`` values are
   Python expressions over provider column names (``'RAJ2000/15'``), not column
   names. ``_derive_columns`` compiles each one and reads the identifiers back
   out, so the request asks VizieR only for columns the plugin can actually use.
2. **Map rows onto ``CatalogSource``.** ``table_to_sources`` evaluates those
   same expressions against each row and builds the per-band ``Mag`` objects.
3. **Issue the query.** Object, box and circle queries, with cache-friendly
   rounding of the region.

EXTRACTED FROM:
``afterglow-core/afterglow_core/resources/catalog_plugins/vizier_catalogs.py``
(373 lines) and its de-Flasked counterpart at
``skynet/.../optical_data_processing/catalogs/vizier_catalogs.py`` (352 lines).
Kepler takes Afterglow's version — it is the superset — and replaces
``current_app.config`` with ``query/config.py``. The two upstreams had drifted:
Skynet dropped the configurable server and the custom-catalog factory, both of
which are restored here.
"""

from __future__ import annotations

import logging
import re
from typing import Dict as TDict, List as TList, Optional, Union

import numpy
from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy.units import arcmin, deg, hour
from astroquery.vizier import Vizier

from algorithms.catalogs.catalog import Catalog
from algorithms.catalogs.schemas import CatalogSource, Mag

from .cache import install_cache_error_suppression
from .config import settings

__all__ = ["VizierCatalog", "build_custom_vizier_catalog"]

logger = logging.getLogger(__name__)

# astroquery treats cache failures as query failures; Kepler does not. See
# query/cache.py. Installed on import so that merely importing this module gives
# the same behaviour upstream had, where the patch was a side effect of
# importing the catalog plugins.
install_cache_error_suppression()


class VizierCatalog(Catalog):
    """Query backend for a VizieR-hosted catalog.

    Mixed onto a plugin declaration by ``query/binding.py``; not instantiated
    directly. The declaration supplies ``vizier_catalog``, ``col_mapping``,
    ``mags``, ``row_limit``, ``sort`` and ``extra_cols``.

    ``col_mapping`` values may be plain column names (``'DEJ2000'``),
    arithmetic over them (``'RAJ2000/15'``), NumPy calls, or Python expressions
    against string columns — Landolt parses sexagesimal RA out of a text column
    that way. Anything that is not a valid expression is treated as a literal
    column name.

    ``sort`` entries are VizieR's signed column syntax: ``'+Rmag'`` ascending,
    ``'-Rmag'`` descending. They are folded into the requested column list,
    replacing the unsigned name if it is already there.
    """

    vizier_server = None
    cache: bool = False
    vizier_catalog = None
    row_limit = None
    col_mapping = {"ra_hours": "RAJ2000/15", "dec_degs": "DEJ2000"}
    extra_cols: TList[str] = []
    sort: TList[str] = []

    _columns = None

    def __init__(self, filter_lookup: Optional[TDict[str, str]] = None, **kwargs):
        """Build the backend and resolve the VizieR column list.

        ``vizier_server`` and ``cache`` fall back to ``query/config.py``, which
        is the seam where Afterglow read Flask's ``current_app.config``.
        """
        super().__init__(filter_lookup)

        for key, value in kwargs.items():
            setattr(self, key, value)

        if self.vizier_server is None:
            self.vizier_server = settings.VIZIER_SERVER
        if "cache" not in kwargs:
            self.cache = settings.VIZIER_CACHE_ENABLED

        self._columns = self._derive_columns()

    def _derive_columns(self) -> TList[str]:
        """Return the VizieR column names this catalog needs.

        Reads them out of the compiled ``col_mapping`` expressions rather than
        requiring plugins to list columns twice. Identifiers that name a NumPy
        export or a ``str`` method are call targets, not columns, and are
        skipped — that is how ``'DEJ2000.strip().startswith("-")'`` contributes
        only ``DEJ2000``.

        PRESERVED BUG: the filter checks NumPy's namespace and ``dir('')`` but
        not Python's builtins, so an expression calling ``int()`` or ``float()``
        contributes ``'int'`` and ``'float'`` as column names. Landolt's
        sexagesimal parsing does exactly that, and its request asks VizieR for
        two columns that do not exist. VizieR ignores unknown column names, so
        the query still returns the right data — which is why this survived
        upstream unnoticed. Left as-is: filtering builtins out would change the
        request Kepler sends, and that deserves its own validation against a
        live VizieR rather than a silent fix here.
        """
        columns: TList[str] = []

        if self.col_mapping:
            for attrname, expr in self.col_mapping.items():
                try:
                    for name in compile(expr, "<string>", "eval").co_names:
                        if name not in numpy.__dict__ and name not in dir(""):
                            columns.append(name)
                except SyntaxError:
                    # Not a Python expression: a literal column name, possibly
                    # one that is not a valid identifier (e.g. 'USNO-B1.0').
                    columns.append(expr)
                except ValueError as e:
                    raise ValueError(
                        'Bad column definition "{}" for attribute "{}" of '
                        'catalog "{}": {}'.format(expr, attrname, self.name, e)
                    )

        if self.extra_cols:
            columns += self.extra_cols

        if getattr(self, "mags", None):
            for item in self.mags.values():
                mag_col, mag_err_col = _mag_columns(item)
                if mag_col:
                    columns.append(mag_col)
                    if mag_err_col:
                        columns.append(mag_err_col)

        if self.sort:
            for col in self.sort:
                _, colname = col[:1], col[1:]
                if colname in columns:
                    columns[columns.index(colname)] = col
                else:
                    columns.append(col)

        return columns

    def table_to_sources(
        self, table: Union[TList, Table]
    ) -> TList[CatalogSource]:
        """Map an astropy table of VizieR rows onto ``CatalogSource`` objects.

        Per row: evaluate every ``col_mapping`` expression to fill the source's
        attributes, then read each declared band into a ``Mag``.

        Two preserved behaviours worth knowing:

        * **Rows with no magnitudes are dropped.** A source Kepler cannot
          photometer is not useful to a caller, and upstream's field calibration
          depends on the filtering. It means ``len(table)`` and
          ``len(sources)`` differ routinely.
        * **A magnitude of 99 or more is "not measured".** VizieR uses 99 as a
          null in several tables, and a 99th-magnitude star would be
          meaningless anyway.

        Column lookups retry with apostrophes replaced by underscores, because
        astroquery renames columns like ``g'mag`` to ``g_mag`` depending on the
        table and version.
        """
        sources: TList[CatalogSource] = []
        if table is None:
            # Empty response
            return sources

        context = dict(numpy.__dict__)

        for row in table:
            source = CatalogSource(catalog_name=self.name, mags={})

            if self.col_mapping:
                for attr, expr in self.col_mapping.items():
                    try:
                        # Fast path: the mapping is a plain column name
                        val = row[expr]
                    except KeyError:
                        ctx = dict(context)
                        ctx.update({name: row[name] for name in row.colnames})
                        try:
                            val = eval(expr, ctx, {})
                        except Exception:
                            # A row that cannot supply this attribute leaves it
                            # unset rather than failing the whole query.
                            val = None
                    if val is not None:
                        setattr(source, attr, val)

            if getattr(self, "mags", None):
                for mag, item in self.mags.items():
                    mag_col, mag_err_col = _mag_columns(item)
                    if not mag_col:
                        continue
                    try:
                        val = _row_value(row, mag_col)
                        if val and val < 99:
                            m = Mag(value=val)
                            try:
                                err = _row_value(row, mag_err_col)
                                if err:
                                    m.error = err
                            except Exception:
                                # Band present, uncertainty absent.
                                pass
                            source.mags[mag] = m
                    except Exception:
                        # No such magnitude in this table.
                        pass

            if source.mags:
                sources.append(source)

        return sources

    def _vizier(self, **kwargs) -> Vizier:
        """Construct an astroquery ``Vizier`` bound to this catalog."""
        if self.vizier_server:
            kwargs["vizier_server"] = self.vizier_server
        return Vizier(
            catalog=self.vizier_catalog, columns=self._columns, **kwargs
        )

    def query_objects(self, names: TList[str]) -> TList[CatalogSource]:
        """Return catalog objects with the given names.

        One request per name, keeping only the first row of each: VizieR name
        resolution can return several rows and upstream took the first. Names
        that resolve to nothing are silently absent from the result, so the
        output is not positionally aligned with ``names``.
        """
        viz = self._vizier(row_limit=len(names))
        rows = []
        for name in names:
            resp = viz.query_object(name, catalog=viz.catalog, cache=self.cache)
            if resp:
                rows.append(resp[0][0])
        return self.table_to_sources(rows)

    def query_region(
        self,
        ra_hours: float,
        dec_degs: float,
        constraints: Optional[TDict[str, str]] = None,
        limit: Optional[int] = None,
        **region,
    ) -> TList[CatalogSource]:
        """Return catalog objects in a region given by astroquery keywords.

        ``constraints`` splits two ways, which is easy to miss: an entry with a
        value becomes a VizieR *column filter* (``{'flags': '0'}`` ->
        ``flags=0``), while an entry whose value is ``None`` becomes a VizieR
        *keyword* instead. Both are passed through untranslated.
        """
        kwargs = {}
        if not limit:
            limit = self.row_limit
        if limit:
            kwargs["row_limit"] = limit

        viz = self._vizier(
            column_filters={
                name: val for name, val in constraints.items() if val is not None
            } if constraints else {},
            keywords=[
                name for name, val in constraints.items() if val is None
            ] if constraints else None,
            **kwargs,
        )
        resp = viz.query_region(
            SkyCoord(ra=ra_hours, dec=dec_degs, unit=(hour, deg), frame="fk5"),
            catalog=viz.catalog,
            cache=self.cache,
            **region,
        )
        if resp:
            return self.table_to_sources(resp[0])
        return []

    def query_box(
        self,
        ra_hours: float,
        dec_degs: float,
        width_arcmins: float,
        height_arcmins: Optional[float] = None,
        constraints: Optional[TDict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> TList[CatalogSource]:
        """Return catalog objects in a rectangular region.

        ``height_arcmins`` defaults to ``width_arcmins``.
        """
        if self.cache:
            ra_hours, dec_degs, (width_arcmins, height_arcmins) = _round_for_cache(
                ra_hours, dec_degs, width_arcmins, height_arcmins
            )
        return self.query_region(
            ra_hours,
            dec_degs,
            constraints,
            limit,
            width=width_arcmins * arcmin,
            height=(height_arcmins if height_arcmins else width_arcmins) * arcmin,
        )

    def query_circ(
        self,
        ra_hours: float,
        dec_degs: float,
        radius_arcmins: float,
        constraints: Optional[TDict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> TList[CatalogSource]:
        """Return catalog objects within a circular region."""
        if self.cache:
            ra_hours, dec_degs, (radius_arcmins,) = _round_for_cache(
                ra_hours, dec_degs, radius_arcmins
            )
        return self.query_region(
            ra_hours, dec_degs, constraints, limit, radius=radius_arcmins * arcmin
        )


def _mag_columns(item) -> tuple[Optional[str], Optional[str]]:
    """Unpack a ``mags`` entry into ``(mag_column, error_column)``.

    Entries are ``[mag, err]``, ``[mag]``, or empty — empty meaning the band is
    synthesized by a ``table_to_sources`` override rather than read from a
    column (Landolt's U/B/R/I, for instance).
    """
    try:
        mag_col, mag_err_col = item[:2]
        return mag_col, mag_err_col
    except ValueError:
        pass
    try:
        return item[0], None
    except (IndexError, TypeError, ValueError):
        return None, None


def _row_value(row, column: Optional[str]):
    """Read a column, retrying with apostrophes as underscores.

    astroquery exposes VizieR's ``g'mag`` as either ``g'mag`` or ``g_mag``
    depending on the table and the astroquery version.
    """
    if column is None:
        raise KeyError(column)
    try:
        return row[column]
    except KeyError:
        return row[column.replace("'", "_")]


def _round_for_cache(ra_hours: float, dec_degs: float, *sizes):
    """Snap a query region to a fixed grid so near-identical fields share a cache entry.

    Without this, two queries of the same field differing by a milliarcsecond
    are two cache entries and two round trips. Centres go to 10 arcsec, sizes
    round *up* to 0.2 arcmin so the requested region is never shrunk.

    This is observable: with the cache on, a query returns rows for a slightly
    larger, grid-aligned region than the caller asked for. Callers that need an
    exact region should clip the result, which the WCS path in ``runner.py``
    already does.
    """
    ra_hours = round(ra_hours * 5400) / 5400 % 24  # 10 arcsec
    dec_degs = round(dec_degs * 360) / 360
    if dec_degs > 90:
        dec_degs = 90
    elif dec_degs < -90:
        dec_degs = -90
    rounded = tuple(
        numpy.ceil(size * 5) / 5 if size is not None else None for size in sizes
    )
    return ra_hours, dec_degs, rounded


def build_custom_vizier_catalog(spec: TDict) -> type:
    """Build a ``VizierCatalog`` subclass from a plain declaration.

    Lets a deployment add a VizieR table Kepler does not ship a plugin for, by
    supplying the same attributes a plugin would (``name``, ``vizier_catalog``,
    ``mags``, ``col_mapping``, ...). The class name is derived from ``name`` by
    stripping illegal characters and prefixing an underscore if it starts with a
    digit.

    PRESERVED BUG: the character class below reads ``a-zA-z``, not ``a-zA-Z``.
    The range ``Z-a`` additionally admits ``[ \\ ] ^ _ ` ``, so a catalog named
    ``my^cat`` keeps the caret in its class name. Harmless — the name is
    cosmetic and Python accepts the resulting identifier via ``type()`` — and
    left as upstream wrote it.

    EXTRACTED FROM: the ``CUSTOM_VIZIER_CATALOGS`` loop at the bottom of
    Afterglow's ``vizier_catalogs.py``, which ran at import time over Flask
    config and swallowed every error into a log line. Kepler makes it an
    ordinary function that raises, because a misconfigured catalog should be
    visible at the point it is registered rather than absent at query time.
    """
    name = spec["name"]
    classname = re.sub(r"(^\d)", r"_\1", re.sub(r"[^a-zA-z0-9_]", "", name)) + "Catalog"
    newclass = type(classname, (VizierCatalog,), dict(spec))
    newclass.__module__ = VizierCatalog.__module__
    return newclass
