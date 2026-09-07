"""Solver backend configuration.

EXTRACTED seam. Upstream, ``wcs.py`` does ``from skynet_db.config import
settings`` and hands that object to ``build_anet_config`` /
``build_atlas_config``. ``skynet_db.config.settings`` is a Dynaconf instance
layered over ``config/settings.toml`` + ``config/environments/dev.local.toml``
with a ``SKYNET_`` env-var prefix — deployment plumbing, not algorithm.

The builders in ``wcs.py`` only ever read five keys, and they read them through
``getattr(cfg, NAME, None)``, so any object exposing those attributes works.
This module provides that shape, sourced from the environment. An unset key
yields ``None``, which is the same value Dynaconf's ``getattr`` fallback
produced, and each builder already handles it. ``ANET_TIMEOUT_S`` is the one
post-extraction addition: it exposes the vendored backend's existing subprocess
deadline to callers without changing its search behavior.

Callers with their own configuration can pass their object to
``solve_wcs(..., solver_settings=cfg)``, call the builders directly, or assign
``algorithms.wcs.wcs.settings``.
"""

from __future__ import annotations

import os


class SolverSettings:
    """Duck-typed stand-in for the five keys the WCS backends read.

    * ``ANET_INDEX_PATH`` — directory (or ``os.pathsep``-separated list, or a
      sequence) holding astrometry.net index files. Falsy ⇒ the astrometry.net
      backend is disabled.
    * ``ANET_TIMEOUT_S`` — astrometry.net low-level attempt limit, in seconds.
    * ``ATLAS_CATALOG_ROOT`` — root of the local star catalog used by the ATLAS
      triangle solver. Falsy ⇒ the ATLAS backend is disabled.
    * ``ATLAS_CATALOG`` — catalog name; ``ucac5`` when unset.
    * ``ATLAS_TIMEOUT_S`` — deadline for the ATLAS matcher loop, in seconds.
    """

    def __init__(
        self,
        *,
        anet_index_path=None,
        anet_timeout_s=None,
        atlas_catalog_root=None,
        atlas_catalog=None,
        atlas_timeout_s=None,
    ) -> None:
        self.ANET_INDEX_PATH = (
            anet_index_path if anet_index_path is not None
            else os.getenv("ANET_INDEX_PATH")
        )
        self.ANET_TIMEOUT_S = (
            anet_timeout_s if anet_timeout_s is not None
            else os.getenv("ANET_TIMEOUT_S")
        )
        self.ATLAS_CATALOG_ROOT = (
            atlas_catalog_root if atlas_catalog_root is not None
            else os.getenv("ATLAS_CATALOG_ROOT")
        )
        self.ATLAS_CATALOG = (
            atlas_catalog if atlas_catalog is not None
            else os.getenv("ATLAS_CATALOG")
        )
        self.ATLAS_TIMEOUT_S = (
            atlas_timeout_s if atlas_timeout_s is not None
            else os.getenv("ATLAS_TIMEOUT_S")
        )


#: EXTRACTED: was `skynet_db.config.settings` (a Dynaconf instance).
settings = SolverSettings()

__all__ = ["SolverSettings", "settings"]
