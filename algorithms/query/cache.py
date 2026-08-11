"""astroquery response cache: pruning, and making cache failures non-fatal.

astroquery caches VizieR responses as files under the astropy cache directory.
Two things go wrong with that in a multi-worker deployment, and this module
handles both.

**Concurrent access.** astroquery treats a failed cache write, a failed read, or
a failed cache-file removal as an error and lets it propagate. When several
workers query overlapping fields they race on the same cache files, and a query
that would have succeeded fails on a cache operation that was only ever an
optimization. ``install_cache_error_suppression()`` replaces
``astroquery.query.to_cache`` and ``astroquery.query.AstroQuery`` with versions
that swallow those failures, so a lost cache entry costs a round trip instead of
the query.

**Unbounded growth.** Nothing in astroquery expires cache entries.
``prune_vizier_cache()`` deletes entries older than a cutoff; the patched
``to_cache`` calls it on every write, so pruning happens as a side effect of
normal use.

EXTRACTED FROM: two upstream copies of the same logic, merged here.

* ``afterglow-core/afterglow_core/resources/catalog_plugins/vizier_catalogs.py``
  (lines 27-72) — the monkey-patch, which upstream ran as a bare import-time
  side effect of importing the catalog plugins. Kepler makes it an explicit
  call: patching a third-party module's globals is not something an import
  should do silently, and a caller may legitimately want astroquery's own
  behaviour. ``query/vizier.py`` calls it on import, so the default is unchanged.
* ``skynet/packages/py/skynet-db/skynet_db/runners/utils.py::prune_vizier_cache``
  (lines 132-158) — the standalone pruner, which is the same loop as Afterglow's
  inline one plus a directory fallback.

PRESERVED BEHAVIOUR: every failure path here is silent by design. A cache is not
allowed to break a query, and callers cannot act on "the cache was busy" anyway.
The failures are logged at debug level, which upstream did not do.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import timedelta
from glob import glob
from typing import Optional

from astropy.config.paths import get_cache_dir

__all__ = ["prune_vizier_cache", "vizier_cache_dir", "install_cache_error_suppression"]

logger = logging.getLogger(__name__)

_patched = False


def vizier_cache_dir() -> str:
    """Return the directory astroquery uses for cached VizieR responses."""
    return os.path.join(get_cache_dir(), "astroquery", "Vizier")


def prune_vizier_cache(max_age: timedelta) -> None:
    """Delete cached VizieR responses last modified more than ``max_age`` ago.

    Safe to call at startup, before a query, or concurrently from several
    processes. Races, permission errors and vanished files are ignored: another
    worker deleting the file first is the expected case, not an error.
    """
    cutoff = time.time() - max_age.total_seconds()
    try:
        entries = glob(os.path.join(vizier_cache_dir(), "*"))
    except Exception:  # pragma: no cover - cache dir unreadable
        return

    for entry in entries:
        try:
            if os.stat(entry).st_mtime >= cutoff:
                continue
            try:
                os.unlink(entry)
            except IsADirectoryError:
                # Defensive: astroquery caches files today, but has cached
                # directories in the past.
                shutil.rmtree(entry, ignore_errors=True)
            except Exception:
                pass
        except Exception:
            # stat() races with another worker's unlink; nothing to do.
            pass


def install_cache_error_suppression(max_age: Optional[timedelta] = None) -> None:
    """Make astroquery cache failures non-fatal, and prune on every write.

    Idempotent: calling this more than once patches astroquery once. ``max_age``
    defaults to the configured retention at call time.

    This reaches into ``astroquery.query`` module globals, which is how upstream
    did it and the only available hook — astroquery exposes no policy for cache
    failure handling.
    """
    global _patched
    if _patched:
        return

    from astroquery import query as _aq

    from .config import settings

    original_to_cache = _aq.to_cache
    original_astro_query = _aq.AstroQuery

    def to_cache(*args, **kwargs):
        """Write a cache entry, then drop expired ones. Never raises."""
        retention = max_age if max_age is not None else settings.vizier_cache_max_age
        if not isinstance(retention, timedelta):
            retention = timedelta(days=retention)
        prune_vizier_cache(retention)

        try:
            original_to_cache(*args, **kwargs)
        except Exception:
            logger.debug("VizieR cache write failed; continuing", exc_info=True)

    class AstroQuery(original_astro_query):
        """``AstroQuery`` whose cache reads and evictions cannot raise.

        A failed ``from_cache`` returns ``None``, which astroquery already
        handles as "not cached" and answers with a live request.
        """

        def from_cache(self, *args, **kwargs):
            try:
                return super().from_cache(*args, **kwargs)
            except Exception:
                logger.debug("VizieR cache read failed; refetching", exc_info=True)
                return None

        def remove_cache_file(self, *args, **kwargs):
            try:
                return super().remove_cache_file(*args, **kwargs)
            except Exception:
                logger.debug("VizieR cache eviction failed; ignoring", exc_info=True)
                return None

    _aq.to_cache = to_cache
    _aq.AstroQuery = AstroQuery
    _patched = True
