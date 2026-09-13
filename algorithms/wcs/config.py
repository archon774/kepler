"""Solver backend configuration.

EXTRACTED seam. Upstream, ``wcs.py`` does ``from skynet_db.config import
settings`` and hands that object to ``build_anet_config`` /
``build_atlas_config``. ``skynet_db.config.settings`` is a Dynaconf instance
layered over ``config/settings.toml`` + ``config/environments/dev.local.toml``
with a ``SKYNET_`` env-var prefix — deployment plumbing, not algorithm.

The builders in ``wcs.py`` only ever read five keys, and they read them through
``getattr(cfg, NAME, None)``, so any object exposing those attributes works.
This module provides that shape as a pure per-call value object. Tool wrappers
own environment lookup and pass the resulting values in. ``ANET_TIMEOUT_S`` is
the one post-extraction addition: it exposes the vendored backend's existing
subprocess deadline to callers without changing its search behavior.

Callers with their own configuration can pass their object to
``solve_wcs(..., solver_settings=cfg)`` or call the builders directly.
"""

from __future__ import annotations

from dataclasses import dataclass


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
        self.ANET_INDEX_PATH = anet_index_path
        self.ANET_TIMEOUT_S = anet_timeout_s
        self.ATLAS_CATALOG_ROOT = atlas_catalog_root
        self.ATLAS_CATALOG = atlas_catalog
        self.ATLAS_TIMEOUT_S = atlas_timeout_s


@dataclass(frozen=True)
class WcsSearchBounds:
    """Optional, caller-supplied bounds on the plate-solve search (P6).

    Post-extraction seam. Upstream ``solve_wcs`` builds a fresh
    ``WcsCalibrationSettings()`` on every call and searches all-sky
    (``radius=180``) over 0.1–60 arcsec/px; its ``PlateSolveSettings`` exposes
    only ``sip_order`` and ``crpix_center`` on the stated grounds that an
    observer narrowing the search would silently cause misses. That default is
    parity and is untouched: a field left ``None`` keeps the extracted value,
    so ``WcsSearchBounds()`` is the same call as passing nothing.

    * ``radius_deg`` — search radius around the frame's own pointing hint;
      ``180`` is all-sky. A radius below 180 needs a hint to anchor on, and
      ``solve_wcs`` refuses (``SearchRadiusWithoutHint``) when the header
      yields none rather than widening back to all-sky behind the caller.
    * ``min_scale_arcsec`` / ``max_scale_arcsec`` — pixel-scale window in
      arcsec/px. Either may be given alone; the other keeps its default. An
      explicit window is used verbatim by both backends: the ATLAS branch's
      narrowing around the header's pixel-scale estimate is skipped, because
      a caller overriding the window is doing so precisely when that estimate
      cannot be trusted. That holds for a single bound too — intersecting the
      unspecified side with the header-derived one would re-admit the header
      the caller is contradicting (header 0.25, truth 0.586, ``min=0.4``:
      intersection gives 0.4–0.5 and misses; verbatim 0.4–60 finds it), so
      callers who want a narrow ATLAS window pass both bounds.

    Range checking is upstream's own (``wcs.py``): the values land on the
    settings object before its ``radius > 0`` and ``min_scale < max_scale``
    checks run.
    """

    radius_deg: float | None = None
    min_scale_arcsec: float | None = None
    max_scale_arcsec: float | None = None

    @property
    def explicit(self) -> tuple[str, ...]:
        """Names of the bounds the caller actually set."""
        return tuple(
            name
            for name in ("radius_deg", "min_scale_arcsec", "max_scale_arcsec")
            if getattr(self, name) is not None
        )

    @property
    def scale_window_is_explicit(self) -> bool:
        return self.min_scale_arcsec is not None or self.max_scale_arcsec is not None


__all__ = ["SolverSettings", "WcsSearchBounds"]
