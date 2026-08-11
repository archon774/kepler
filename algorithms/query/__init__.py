"""Kepler: remote catalog access.

Where ``algorithms.catalogs`` declares what Kepler knows about each catalog, this
package goes and gets the rows. It owns every network call in the catalog path.

Start here:

``algorithms.query.registry.CATALOGS``
    The eleven catalogs, bound to their backends and ready to query.
``algorithms.query.runner.query_catalogs``
    Query several catalogs over a region, a set of solved images, or a list of
    object names, with filter-aware narrowing and footprint clipping.
``algorithms.query.simbad.resolve_simbad``
    Resolve a free-text identifier to coordinates and an object type.

Layout::

    config.py      environment-sourced settings (VizieR mirror, cache policy)
    cache.py       astroquery cache pruning; makes cache failures non-fatal
    vizier.py      the VizieR engine — column derivation, row mapping, queries
    sdss.py        SkyServer SQL backend (SDSS is not on VizieR)
    skymapper.py   VizieR backend defaulting SkyMapper's quality constraint
    binding.py     joins declarations to backends via the MRO
    registry.py    the live, queryable registry
    selection.py   narrow a catalog list to those that can resolve a filter
    geometry.py    sky/image geometry: query regions, clipping, deduplication
    runner.py      orchestration entry points
    simbad.py      identifier resolution

Importing ``algorithms.query.registry``, ``algorithms.query.runner`` or any backend
pulls in astroquery and installs the cache patch described in ``cache.py``.
Importing ``algorithms.query.selection`` or ``algorithms.query.geometry`` does not —
filter matching and geometry work on declarations alone.

Nothing here is imported at Kepler start-up, and no module makes a network call
at import time.
"""

__all__: list[str] = []
