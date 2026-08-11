"""Plain-object stand-ins for the Skynet ORM rows the WCS solve reads and writes.

EXTRACTED seam. Upstream, ``solve_wcs()`` is handed a SQLAlchemy
``ObservationAssetProcessingRun`` (``skynet_db/models/jobs/observation_asset_processing_run.py``)
and writes its astrometric output onto the related
``ObservationTaskAssetProcessingRunWcsSolution`` row
(``skynet_db/models/jobs/observation_asset_processing_run_details.py``), which a
job runner later flushes to Postgres.

None of that persistence is algorithm. The classes below reproduce the *shape*
the solve depends on — the same attribute names, in the same order, with the
same ``None`` defaults — as ordinary Python objects with no session, no
cascade, and no table. Every numeric field the solve assigns is present and
spelled identically, so the arithmetic in ``wcs.py`` is untouched.

Two upstream behaviours worth recording:

* ``ensure_wcs_solution()`` upstream also does ``session.add(...)`` when the run
  is attached to a SQLAlchemy session. That is pure persistence and is dropped.
* ``wcs._clear_wcs_solution_fields()`` resets a list of attribute names that
  does NOT fully match the mapped columns: it clears ``ra``, ``dec``,
  ``pixel_scale`` and ``rotation``, whereas the solve writes ``ra_deg``,
  ``dec_deg``, ``pixel_scale_arcsec_per_px`` and ``rotation_deg``. On a
  SQLAlchemy instance ``setattr`` of an unmapped name silently creates a plain
  instance attribute, so upstream those four clears are no-ops and the
  correspondingly named *columns* are left holding their previous values after a
  failed solve. This class is a plain (non-``slots``) dataclass precisely so
  that behaviour is reproduced exactly rather than turned into an
  ``AttributeError``. The mismatch is preserved, not fixed — see docs/extraction.md, WCS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# EXTRACTED: was `from skynet_db.runners.observation_asset_processing.common import now`.
# The upstream helper is exactly this one-liner.
def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class WcsSolution:
    """Astrometric solution record.

    EXTRACTED: was the ORM model ``ObservationTaskAssetProcessingRunWcsSolution``
    (table ``observation_task_asset_processing_run_wcs_solution``). Column list
    and order preserved 1:1; the ``processing_run_id`` primary key and the
    ``processing_run`` relationship are dropped as persistence-only.
    """

    science_hdu_index: Optional[int] = None
    found_solution: Optional[int] = None
    ra_deg: Optional[float] = None
    dec_deg: Optional[float] = None
    crpix1: Optional[float] = None
    crpix2: Optional[float] = None
    crval1: Optional[float] = None
    crval2: Optional[float] = None
    cdelt1: Optional[float] = None
    cdelt2: Optional[float] = None
    cd11: Optional[float] = None
    cd12: Optional[float] = None
    cd21: Optional[float] = None
    cd22: Optional[float] = None
    crota2: Optional[float] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    rotation_deg: Optional[float] = None
    pixel_scale_arcsec_per_px: Optional[float] = None
    mirrored: Optional[int] = None
    date_solved: Optional[datetime] = None
    pointing_error_arcsec: Optional[float] = None
    delta_ra_deg: Optional[float] = None
    delta_dec_deg: Optional[float] = None
    n_field: Optional[int] = None


@dataclass
class ProcessingRun:
    """The per-frame run object the solve is handed.

    EXTRACTED: was the ORM model ``ObservationAssetProcessingRun``. Only the
    three members the WCS solve and source extraction actually touch are kept —
    ``id``, ``observation_asset_id`` (used solely as a log/label ``file_id``) and
    ``wcs_solution``. The job-state machinery (stage/progress, input asset
    relationship, outputs, reduction info, photometry, S3 handles) is
    infrastructure and is not extracted.
    """

    id: Any = None
    observation_asset_id: Any = None
    wcs_solution: Optional[WcsSolution] = None

    def ensure_wcs_solution(self) -> WcsSolution:
        # EXTRACTED: upstream additionally did `session.add(self.wcs_solution)`
        # when the run was attached to a SQLAlchemy session. Persistence only.
        if self.wcs_solution is None:
            self.wcs_solution = WcsSolution()
        return self.wcs_solution


__all__ = ["ProcessingRun", "WcsSolution", "now"]
