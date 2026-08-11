"""Remote catalog query configuration.

EXTRACTED seam. Two upstream configuration systems collapse into this module.
Afterglow read ``VIZIER_SERVER``, ``VIZIER_CACHE`` and ``VIZIER_CACHE_AGE`` from
Flask's ``current_app.config``, which meant importing this package required an
application context. Skynet replaced that with a five-line module of literals.
Kepler is neither a Flask app nor a single deployment, so the values come from
the environment with the upstream defaults preserved.

Nothing here changes query results. The server choice affects latency and
availability, and the cache settings affect how often a query goes out over the
wire — but a cache hit and a cache miss return the same rows.

Callers with their own configuration should assign
``kepler.query.config.settings`` before the first query, or pass an object
exposing the same four attributes to whichever backend they construct.
"""

from __future__ import annotations

import os
from datetime import timedelta

__all__ = ["QuerySettings", "settings"]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class QuerySettings:
    """Configuration for the remote catalog backends.

    * ``VIZIER_SERVER`` — VizieR mirror hostname. Upstream disagreed on the
      default: Afterglow used ``vizier.cfa.harvard.edu``, Skynet moved to
      ``vizier.cds.unistra.fr`` (the CDS home site) and left the Harvard mirror
      commented out. Kepler follows the newer choice.
    * ``VIZIER_CACHE_ENABLED`` — whether astroquery caches responses on disk.
      When on, the backends also round query centres and sizes to a fixed
      granularity so that near-identical fields hit the same cache entry; see
      ``kepler.query.vizier``. That rounding is observable, so turning the
      cache on or off can change which sources a query returns near a field
      edge.
    * ``VIZIER_CACHE_AGE_DAYS`` — entries older than this are deleted the next
      time anything is written to the cache.
    The SDSS data release is deliberately *not* here: it lives on the plugin in
    ``kepler.catalogs.sdss_catalog``, which derives its ``display_name`` from
    it.
    """

    def __init__(
        self,
        *,
        vizier_server: str | None = None,
        vizier_cache_enabled: bool | None = None,
        vizier_cache_age_days: float | None = None,
    ) -> None:
        self.VIZIER_SERVER = (
            vizier_server if vizier_server is not None
            else os.getenv("VIZIER_SERVER", "vizier.cds.unistra.fr")
        )
        self.VIZIER_CACHE_ENABLED = (
            vizier_cache_enabled if vizier_cache_enabled is not None
            else _env_bool("VIZIER_CACHE_ENABLED", True)
        )
        self.VIZIER_CACHE_AGE_DAYS = (
            vizier_cache_age_days if vizier_cache_age_days is not None
            else _env_float("VIZIER_CACHE_AGE_DAYS", 30.0)
        )

    @property
    def vizier_cache_max_age(self) -> timedelta:
        return timedelta(days=self.VIZIER_CACHE_AGE_DAYS)


settings = QuerySettings()
