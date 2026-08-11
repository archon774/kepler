"""Kepler: shared name resolution for ``kepler.tools``.

Wraps ``query.simbad.resolve_simbad`` so every tool that needs "which sky
position is this object" goes through the same path, and a name that doesn't
resolve produces one consistent ``not_found`` result instead of a different
astroquery exception per service.

Most name-based astroquery calls (VizieR/NED/MAST ``query_object``) already
resolve names internally, so calling this first is not required before using
them -- it exists to give a caller ``resolve_target`` as a tool in its own
right (``docs/tool-architecture.md`` section 4) and a shared not-found path.
CASDA's region query is the one backend here that only accepts coordinates,
not a name, so ``kepler.tools.casda`` uses ``resolve_target_coords`` directly.
"""

from __future__ import annotations

from typing import Optional

from query.simbad import ResolvedTarget, resolve_simbad

from kepler.models import ToolResult

__all__ = ["resolve_target", "resolve_target_coords"]


def resolve_target(name: str) -> ToolResult:
    """Resolve a free-text identifier to sky coordinates and an object type.

    Returns every SIMBAD match for an ambiguous name (there is usually one).
    A name that simply isn't a known SIMBAD object is an ordinary outcome,
    reported as ``not_found`` rather than an error.
    """
    if not name or not name.strip():
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "name must not be blank"}],
        )

    matches = resolve_simbad(name)
    if not matches:
        return ToolResult(status="not_found", count=0)

    preview = [
        {
            "object_name": m.object_name,
            "ra_deg": m.ra_deg,
            "dec_deg": m.dec_deg,
            "object_type": m.object_type,
            "source": m.source,
        }
        for m in matches
    ]
    return ToolResult(
        status="ok",
        count=len(preview),
        preview=preview,
        columns=["object_name", "ra_deg", "dec_deg", "object_type", "source"],
    )


def resolve_target_coords(name: str) -> Optional[ResolvedTarget]:
    """Return the first SIMBAD match for ``name``, or ``None``.

    For tools that need numeric coordinates directly (``kepler.tools.casda``)
    rather than a ``ToolResult`` to hand back to a caller.
    """
    matches = resolve_simbad(name)
    return matches[0] if matches else None
