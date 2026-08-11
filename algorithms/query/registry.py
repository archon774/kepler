"""The live, queryable catalog registry.

``algorithms.catalogs.CATALOGS`` holds declarations that cannot be queried;
``algorithms.query.registry.CATALOGS`` holds the same eleven catalogs bound to their
backends. Import this one to actually fetch sources::

    from algorithms.query.registry import CATALOGS

    sources = CATALOGS["APASS"].query_circ(ra_hours=13.77, dec_degs=28.38,
                                           radius_arcmins=10)

Band tables and colour transforms are identical between the two registries —
binding adds query methods and changes nothing about the photometry. Code that
only reads ``mags`` or ``filter_lookup`` should import from ``algorithms.catalogs``
and stay free of the astroquery dependency.

Importing this module imports astroquery and installs the cache patch described
in ``algorithms.query.cache``. It makes no network calls.
"""

from __future__ import annotations

from typing import Dict

from algorithms.catalogs import CATALOGS as _DECLARATIONS
from algorithms.catalogs.catalog import Catalog

from .binding import bind_registry

__all__ = ["CATALOGS", "get_catalog", "UnknownCatalogError"]


class UnknownCatalogError(ValueError):
    """Raised when a caller names a catalog that is not registered.

    EXTRACTED FROM: ``afterglow-core/afterglow_core/errors/catalog.py``, which
    defined this as an HTTP-404-carrying ``AfterglowError``. Kepler is a library
    here, not a web service, so it is a plain ``ValueError`` subclass — callers
    that need a 404 can map it at their edge. Subclassing ``ValueError`` keeps
    the ``raise ValueError(f'Unknown catalog "{name}"')` that the query runner
    used catchable the same way.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f'Unknown catalog "{name}"')
        self.name = name


#: Catalog name -> queryable catalog instance.
CATALOGS: Dict[str, Catalog] = bind_registry(_DECLARATIONS)


def get_catalog(name: str) -> Catalog:
    """Return a queryable catalog by name, or raise ``UnknownCatalogError``."""
    try:
        return CATALOGS[name]
    except KeyError:
        raise UnknownCatalogError(name) from None
