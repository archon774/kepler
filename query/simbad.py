"""SIMBAD identifier resolution.

Turns a free-text identifier — ``"M31"``, ``"NGC 5286"``, ``"HD 209458"`` —
into sky coordinates plus a human-readable object type. This is name lookup,
not photometry: SIMBAD is a bibliographic database of objects, and the answer is
an identity and a position, not catalog rows. Callers wanting magnitudes go to
the photometric catalogs instead.

The object-type vocabulary lives in ``catalogs/simbad.py``; only the resolution
logic is here.

EXTRACTED FROM:
``skynet/apps/public-api/public_api/services/target_search.py`` (394 lines), the
SIMBAD branch of ``search_targets`` (lines 260-297) plus the module-level
availability probe (lines 236-242).

SEVERED: upstream's ``search_targets`` also queried four *local database*
catalogs through SQLAlchemy — NORAD satellites, major solar-system bodies, MPC
comets and MPC orbits — merging them into the same result list. Those are ORM
queries against Skynet's own tables, not remote catalog access, and they carry
the whole ``skynet_db.models`` dependency. They are not part of this extraction.
The merge-and-sort shape is preserved in ``resolve_targets``, which accepts
additional result lists so a caller with its own object database can restore the
combined behaviour without this module knowing about it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from astropy import units as u
from astropy.coordinates import Angle

from catalogs.simbad import SIMBAD_OBJECT_TYPES

__all__ = ["ResolvedTarget", "resolve_simbad", "resolve_targets", "simbad_available"]

logger = logging.getLogger(__name__)

#: J2000.0 as upstream wrote it — noon TT on 2000-01-01.
J2000 = datetime(2000, 1, 1, 12, 0, 0)

_simbad = None
_simbad_enabled: Optional[bool] = None


@dataclass
class ResolvedTarget:
    """One candidate match for a free-text identifier.

    ``object_type`` is the prose label from ``SIMBAD_OBJECT_TYPES``. It is the
    empty string when SIMBAD reports a code Kepler's table does not carry, which
    happens as SIMBAD's vocabulary evolves — treat it as "unknown", not as an
    error.
    """

    object_name: str
    ra_deg: float
    dec_deg: float
    object_type: str = ""
    source: str = "SIMBAD"
    epoch: datetime = J2000


def simbad_available() -> bool:
    """Return whether SIMBAD lookups can run.

    Resolution needs the ``otype`` VOTable field, which older astroquery
    versions and some SIMBAD mirrors do not offer. The probe runs once, on first
    use, and its result is cached — upstream ran it at import time, which made
    importing the module do network-adjacent work.
    """
    global _simbad, _simbad_enabled
    if _simbad_enabled is not None:
        return _simbad_enabled

    try:
        from astroquery.simbad import Simbad

        _simbad = Simbad()
        _simbad.add_votable_fields("otype")
        _simbad_enabled = True
    except Exception:
        logger.warning("SIMBAD object-type field unavailable; resolution disabled",
                       exc_info=True)
        _simbad_enabled = False

    return _simbad_enabled


def resolve_simbad(name: str) -> list[ResolvedTarget]:
    """Resolve ``name`` against SIMBAD.

    Returns every row SIMBAD matched, which for an ambiguous identifier is more
    than one. Rows with no coordinates, or coordinates astropy cannot parse, are
    skipped rather than failing the lookup — a partial answer beats none.

    Returns an empty list, never raises, when SIMBAD is unavailable or the query
    fails. Upstream printed such failures to stdout; Kepler logs them.

    PRESERVED BEHAVIOUR: the identifier is lower-cased before the query.
    SIMBAD's matching is case-insensitive so this is normally invisible, and it
    is kept because upstream's downstream matching assumed it.
    """
    results: list[ResolvedTarget] = []

    name = (name or "").strip().lower()
    if name == "":
        return results

    if not simbad_available():
        return results

    try:
        rows = _simbad.query_object(name, wildcard=False)
    except Exception:
        logger.warning("SIMBAD query failed for %r", name, exc_info=True)
        return results

    if not rows:
        return results

    for row in rows:
        ra = row["ra"]
        dec = row["dec"]
        if not ra or not dec:
            continue
        try:
            # SIMBAD serves these in degrees already; Angle is used for its
            # parsing of the sexagesimal forms older releases returned.
            ra = Angle(ra, unit=u.degree)
            dec = Angle(dec, unit=u.degree)
        except Exception:
            logger.debug("Skipping SIMBAD row with unparseable position", exc_info=True)
            continue

        results.append(
            ResolvedTarget(
                object_name=row["main_id"],
                ra_deg=ra.degree,
                dec_deg=dec.degree,
                object_type=SIMBAD_OBJECT_TYPES.get(row["otype"], ""),
                source="SIMBAD",
            )
        )

    return results


def resolve_targets(
    name: str,
    *,
    extra: Optional[Iterable[Sequence[ResolvedTarget]]] = None,
) -> list[ResolvedTarget]:
    """Resolve ``name`` and merge in any caller-supplied matches.

    ``extra`` is where the severed local-catalog branches plug back in: a caller
    with a satellite or minor-planet database passes its own result lists and
    gets upstream's combined, name-sorted output.

    Sorting is by lower-cased object name, so results from different sources
    interleave alphabetically rather than clustering by provider.
    """
    results = resolve_simbad(name)
    for group in extra or ():
        results.extend(group)
    results.sort(key=lambda t: (t.object_name or "").lower())
    return results
