"""Reference-magnitude resolution: image FILTER -> catalog band / colour expression.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/utils.py
lines 605-799 (``_SAFE_NAMES``, ``_ALLOWED_TOKENS``, ``_get_catalog_filter_lookup``,
``_safe_eval_expr``, ``_resolve_filter_lookup_candidate``,
``_ref_mag_filter_token_candidates``, ``resolve_ref_mag_for_filter``), verbatim.

The legacy-Afterglow-parity notes in the docstrings and the gated
``allow_preferred_band_fallback`` behaviour are preserved exactly — they are the
documented numeric-parity contract with the previous system.
"""
from __future__ import annotations

import math
import re

from catalogs import CATALOG_OPTIONS
from .schemas import Mag  # noqa: F401  (referenced by the type annotation below)

__all__ = ["resolve_ref_mag_for_filter"]


_SAFE_NAMES = {k: getattr(math, k) for k in ("sqrt", "log10")}
_ALLOWED_TOKENS = re.compile(r"[A-Za-z0-9_+\-*/().\s]+")

def _get_catalog_filter_lookup(catalog_name: str | None) -> dict[str, str]:
    if not catalog_name:
        return {}

    catalog = CATALOG_OPTIONS.get(catalog_name)
    if catalog is None:
        return {}
    return catalog.filter_lookup

def _safe_eval_expr(expr: str, bands: dict[str, float]) -> float | None:
    if not expr or not _ALLOWED_TOKENS.fullmatch(expr):
        return None
    ns = dict(_SAFE_NAMES)
    expr2 = expr
    for k, v in bands.items():
        kid = re.sub(r"[^A-Za-z0-9_]", "_", k)
        ns[kid] = float(v)
        expr2 = re.sub(rf"\b{k}\b", kid, expr2)
    try:
        val = eval(expr2, {"__builtins__": {}}, ns)
        return float(val) if val is not None and math.isfinite(val) else None
    except Exception:
        return None


def _resolve_filter_lookup_candidate(
    candidate: str,
    band_vals: dict[str, tuple[float | None, float | None]],
    lookup: dict[str, str],
    *,
    propagate_error: bool,
) -> tuple[float | None, float | None]:
    """Resolve a lookup target, following aliases such as SII -> rprime."""
    seen: set[str] = set()
    current = candidate
    while current and current not in seen:
        seen.add(current)

        v, e = band_vals.get(current, (None, None))
        if v is not None:
            return float(v), (float(e) if e is not None else None)

        bands = {k: v for k, (v, _) in band_vals.items() if v is not None}
        val = _safe_eval_expr(current, bands)
        if val is not None:
            if not propagate_error:
                return float(val), None
            eps = 1e-7
            err2 = 0.0
            for k, (v, e) in band_vals.items():
                if v is None or e in (None, 0):
                    continue
                bands[k] = float(v) + eps
                v2 = _safe_eval_expr(current, bands)
                bands[k] = float(v)  # restore
                if v2 is not None:
                    dmdk = (v2 - val) / eps
                    err2 += (dmdk * float(e)) ** 2
            return float(val), (err2 ** 0.5 if err2 > 0 else None)

        current = lookup.get(current)

    return None, None


def _ref_mag_filter_token_candidates(image_filter: str) -> list[str]:
    """Filter-name variants to try for a *direct* catalog-band match.

    Mirrors ``query.selection._filter_token_candidates`` so reference-magnitude
    resolution and the filter-aware catalog preselection agree on which filters
    a catalog can satisfy via a direct band (e.g. both treat APASS as able to
    serve a ``B`` image from its ``Bmag`` column). Preserves the original
    token's casing first so meaningful tokens like ``g'`` / ``Halpha`` are not
    rewritten before the lookup-based steps get a chance to run.
    """
    seen: list[str] = []
    for t in (
        image_filter,
        image_filter.strip(),
        image_filter.lower(),
        image_filter.upper(),
        # Normalize typographic single-quote variants to ASCII apostrophe
        image_filter.replace("′", "'").replace("’", "'"),
    ):
        if t and t not in seen:
            seen.append(t)
    return seen


def resolve_ref_mag_for_filter(
    *,
    image_filter: str | None,
    catalog_name: str | None,
    cs_mags: dict[str, "Mag"] | dict[str, dict[str, float]],
    propagate_error: bool = True,
    custom_filter_lookup: dict[str, dict[str, str]] | None = None,
    allow_preferred_band_fallback: bool = True,
) -> tuple[float | None, float | None]:
    """
    Resolve the catalog reference magnitude for the given FITS FILTER using
    per-catalog mapping rules and (optionally) propagate error for expressions.

    Resolution order mirrors legacy Afterglow field calibration
    (``field_cal_job.py``):

      1. Direct catalog band whose key matches the image filter name
         (legacy: ``catalog_source.mags[flt]``). This takes precedence over the
         per-catalog ``filter_lookup`` so that a ``B`` image calibrates against
         the catalog ``B`` magnitude rather than an unrelated band.
      2. A ``filter_lookup`` entry (or ``"*"`` wildcard) that resolves to a
         direct band or another lookup alias.
      3. A ``filter_lookup`` entry that is a colour-mapping expression.

    ``allow_preferred_band_fallback`` controls a *non-legacy* Skynet behavior:
    when ``True`` (default), an unresolved filter falls back to a preferred band
    (``V``, ``r'``, ``g'``, ``B``, ``i'``, then any available band). Legacy
    Afterglow has no such fallback — it skips the source. Strict legacy-parity
    callers (field calibration parity mode, the Afterglow ZP diagnostic) pass
    ``False`` so an unresolved filter returns ``(None, None)`` instead of
    silently substituting a wrong reference band.
    """
    if not cs_mags:
        return None, None

    # flatten to {band: (value, error)}
    band_vals: dict[str, tuple[float | None, float | None]] = {}
    for k, v in cs_mags.items():
        if hasattr(v, "value"):
            band_vals[k] = (getattr(v, "value", None), getattr(v, "error", None))
        elif isinstance(v, dict):
            band_vals[k] = (v.get("value"), v.get("error"))
        else:
            try:
                band_vals[k] = (float(v), None)
            except Exception:
                band_vals[k] = (None, None)

    f = (image_filter or "").strip()

    # 1. Direct catalog band matching the image filter name (legacy parity).
    if f:
        for token in _ref_mag_filter_token_candidates(f):
            v, e = band_vals.get(token, (None, None))
            if v is not None:
                return float(v), (float(e) if e is not None else None)

    lookup = _get_catalog_filter_lookup(catalog_name)
    if custom_filter_lookup and catalog_name:
        lookup = {**lookup, **custom_filter_lookup.get(catalog_name, {})}

    # 2-3. Explicit filter lookup resolving to a direct band, another lookup
    #      alias, or a colour-mapping expression.
    explicit_lookup_seen = False
    for token in _ref_mag_filter_token_candidates(f):
        candidate = lookup.get(token)
        if not candidate:
            continue
        explicit_lookup_seen = True
        v, e = _resolve_filter_lookup_candidate(
            candidate,
            band_vals,
            lookup,
            propagate_error=propagate_error,
        )
        if v is not None:
            return v, e
    if explicit_lookup_seen:
        return None, None

    # Wildcard default like legacy; only use it when no explicit token matched.
    candidate = lookup.get("*")
    if candidate:
        v, e = _resolve_filter_lookup_candidate(
            candidate,
            band_vals,
            lookup,
            propagate_error=propagate_error,
        )
        if v is not None:
            return v, e

    # 4. Preferred-band fallback (NON-legacy; gated). Legacy Afterglow skips a
    #    source whose filter resolves to no direct band or mapping expression.
    if allow_preferred_band_fallback:
        for pref in ("V", "rprime", "gprime", "B", "iprime"):
            v, e = band_vals.get(pref, (None, None))
            if v is not None:
                return float(v), (float(e) if e is not None else None)
        for k, (v, e) in band_vals.items():
            if v is not None:
                return float(v), (float(e) if e is not None else None)
    return None, None
