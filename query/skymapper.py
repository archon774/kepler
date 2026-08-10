"""SkyMapper query backend.

SkyMapper is a VizieR catalog like the others, with one difference: its table
includes sources with non-zero SExtractor flags — blended, saturated, truncated,
or otherwise compromised detections. Photometry against those is unreliable, so
every SkyMapper query defaults to ``flags=0`` unless the caller says otherwise.

That is the whole backend. Everything else comes from ``VizierCatalog``.

EXTRACTED FROM:
``afterglow-core/afterglow_core/resources/catalog_plugins/skymapper_catalog.py``
(the ``query_region`` override, lines 39-58).
"""

from __future__ import annotations

from typing import Dict as TDict, List as TList, Optional

from catalogs.schemas import CatalogSource

from .vizier import VizierCatalog

__all__ = ["SkyMapperQueryBackend"]


class SkyMapperQueryBackend(VizierCatalog):
    """VizieR backend that defaults SkyMapper's quality constraint."""

    def query_region(
        self,
        ra_hours: float,
        dec_degs: float,
        constraints: Optional[TDict[str, str]] = None,
        limit: Optional[int] = None,
        **region,
    ) -> TList[CatalogSource]:
        """Query a region, defaulting ``flags`` to ``0``.

        ``setdefault`` rather than assignment: a caller that explicitly passes
        ``flags`` — including a wider filter like ``'<4'`` — keeps it.

        PRESERVED BEHAVIOUR: when the caller supplies a ``constraints`` dict,
        this mutates it in place. A caller reusing one dict across catalogs will
        find ``flags`` added to it after querying SkyMapper. Upstream did the
        same, and Kepler's query runner passes a fresh dict per call, so nothing
        in-tree is affected.
        """
        if constraints is None:
            constraints = {}
        constraints.setdefault('flags', '0')
        return super().query_region(
            ra_hours, dec_degs, constraints, limit, **region)
