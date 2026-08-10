"""Catalog plugin base class.

EXTRACTED FROM:
skynet/packages/py/skynet-db/skynet_db/runners/observation_asset_processing/
optical_data_processing/catalogs/catalog.py (45 lines), verbatim apart from the
``table_to_sources`` seam noted below.
"""
from typing import Optional, Dict, List

from ..schemas import CatalogSource

class Catalog:
    """
    Base class for catalog plugins.
    Override query_* methods in subclasses.
    """
    # For union-discriminated polymorphism later if desired:
    name: Optional[str] = None
    display_name: Optional[str] = None
    num_sources: Optional[int] = None
    mags: Dict[str, List[str]]
    filter_lookup: Dict[str, str]

    def __init__(self, filter_lookup: Optional[Dict[str, str]] = None):
        if filter_lookup:
            self.filter_lookup = {**dict(getattr(type(self), 'filter_lookup', {})), **filter_lookup}


    def query_objects(self, names: List[str]) -> List[CatalogSource]:
        raise NotImplementedError("query_objects not implemented")

    def query_box(
        self,
        ra_hours: float,
        dec_degs: float,
        width_arcmins: float,
        height_arcmins: Optional[float] = None,
        constraints: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogSource]:
        # Default implementation may rely on query_circ in concrete subclasses
        raise NotImplementedError("query_box not implemented")

    def query_circ(
        self,
        ra_hours: float,
        dec_degs: float,
        radius_arcmins: float,
        constraints: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogSource]:
        raise NotImplementedError("query_circ not implemented")

    # EXTRACTED SEAM: in Skynet this method is defined on ``VizierCatalog``
    # (catalogs/vizier_catalogs.py, 352 lines) and maps an astropy ``Table`` of
    # VizieR rows onto ``CatalogSource`` objects using each plugin's
    # ``col_mapping`` / ``mags`` declarations.  That is catalog *backend*
    # plumbing (astroquery, column-name eval, VizieR cache monkey-patching), so
    # it is not part of this extraction — see EXTRACTION.md.  It is declared
    # here because two plugins (Landolt, USNO-B1) override it to perform real
    # photometric transforms and call ``super().table_to_sources(...)``; those
    # overrides are preserved verbatim and become live as soon as a backend
    # implementation is supplied.
    def table_to_sources(self, table) -> List[CatalogSource]:
        raise NotImplementedError(
            "table_to_sources not implemented. EXTRACTED: was "
            "VizierCatalog.table_to_sources (catalog query backend); belongs in "
            "Kepler/catalogs/."
        )
