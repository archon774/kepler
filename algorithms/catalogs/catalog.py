"""Kepler: catalog plugin base class.

A catalog plugin is a *declaration*: what the catalog is called, how many
sources it holds, which VizieR table backs it, which of its columns carry
magnitudes, and how to convert those magnitudes into the photometric band a
caller asked for. Plugins hold no network code — fetching rows is the job of
``algorithms.query``, which binds a backend onto these declarations at import time
(see ``algorithms.query.binding``).

That split is why the ``query_*`` methods below raise: a bare plugin knows what
it *contains*, not how to reach it. Import ``algorithms.query.registry`` instead of
``algorithms.catalogs`` when you need live, queryable catalogs.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/
observation_asset_processing/optical_data_processing/catalogs/catalog.py
(45 lines). The attribute set and the ``filter_lookup`` merge semantics are
preserved; the docstrings are Kepler's.
"""

from typing import Dict, List, Optional

from .schemas import CatalogSource

__all__ = ["Catalog"]


class Catalog:
    """Base class for catalog plugins.

    Subclasses declare, as class attributes:

    ``name``
        Kepler's identifier for the catalog, and the key it is registered under.
    ``display_name``
        Human-readable name.
    ``num_sources``
        Approximate row count, used for cost estimation and display.
    ``mags``
        ``{band: [mag_column, error_column]}``. The error column is optional;
        an empty list means the band exists but is synthesized by a
        ``table_to_sources`` override rather than read from a column.
    ``filter_lookup``
        ``{filter_name: band_or_expression}``. Values are either a band name
        present in ``mags`` or a Python expression over such names, e.g.
        ``'rprime - 0.2936*(rprime - iprime) - 0.1439'``. ``'*'`` is a wildcard
        matching any filter the caller did not name explicitly.
    ``col_mapping``
        ``{source_attribute: column_or_expression}`` used by the backend's row
        mapper to populate ``CatalogSource`` fields.
    ``vizier_catalog``, ``row_limit``, ``sort``, ``extra_cols``
        Backend hints consumed by ``query/vizier.py``. Inert without a backend.
    """

    name: Optional[str] = None
    display_name: Optional[str] = None
    num_sources: Optional[int] = None
    mags: Dict[str, List[str]]
    filter_lookup: Dict[str, str]

    def __init__(self, filter_lookup: Optional[Dict[str, str]] = None):
        # Rebinds an instance-level copy rather than mutating the class dict, so
        # registering the same plugin class twice with different lookups (which
        # ``catalogs/__init__.py`` and ``catalogs/catalog_options.py`` both do)
        # cannot leak entries between registries.
        if filter_lookup:
            self.filter_lookup = {
                **dict(getattr(type(self), "filter_lookup", {})),
                **filter_lookup,
            }

    def query_objects(self, names: List[str]) -> List[CatalogSource]:
        raise NotImplementedError(
            "query_objects requires a query backend; import from algorithms.query.registry"
        )

    def query_box(
        self,
        ra_hours: float,
        dec_degs: float,
        width_arcmins: float,
        height_arcmins: Optional[float] = None,
        constraints: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogSource]:
        raise NotImplementedError(
            "query_box requires a query backend; import from algorithms.query.registry"
        )

    def query_circ(
        self,
        ra_hours: float,
        dec_degs: float,
        radius_arcmins: float,
        constraints: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogSource]:
        raise NotImplementedError(
            "query_circ requires a query backend; import from algorithms.query.registry"
        )

    def table_to_sources(self, table) -> List[CatalogSource]:
        """Map backend rows onto ``CatalogSource`` objects.

        Implemented by the backend (``algorithms.query.vizier``), because the
        mapping is driven by ``col_mapping`` expressions evaluated against
        provider-specific column names. Declared here because three plugins —
        Landolt, USNO-B1 and VSX — override it to apply photometric transforms,
        and two of those call ``super().table_to_sources(...)`` to get the raw
        mapping first. Method resolution reaches the backend implementation once
        a plugin is bound.
        """
        raise NotImplementedError(
            "table_to_sources requires a query backend; import from algorithms.query.registry"
        )
