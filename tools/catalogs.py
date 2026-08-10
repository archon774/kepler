"""Catalog declaration tool wrappers."""

from __future__ import annotations

from algorithms.catalogs import CATALOG_OPTIONS, CATALOGS
from algorithms.fieldcal.ref_mag import resolve_ref_mag_for_filter
from tools.models import CatalogSummary, ReferenceBandResolution, ToolError, ToolWarning

_MATH_NAMES = frozenset(("abs", "exp", "log", "log10", "sqrt"))


def _filter_token_candidates(image_filter: str) -> list[str]:
    seen: list[str] = []
    for token in (
        image_filter,
        image_filter.strip(),
        image_filter.lower(),
        image_filter.upper(),
        image_filter.replace("′", "'").replace("’", "'"),
    ):
        if token and token not in seen:
            seen.append(token)
    return seen


def _expression_deps(expr: str) -> set[str]:
    try:
        return {
            name
            for name in compile(expr, "<string>", "eval").co_names
            if name not in _MATH_NAMES
        }
    except (SyntaxError, ValueError):
        return set()


def _effective_catalog(name: str):
    return CATALOG_OPTIONS.get(name) or CATALOGS.get(name)


def _effective_lookup(name: str) -> dict[str, str]:
    lookup: dict[str, str] = {}
    catalog = CATALOGS.get(name)
    if catalog is not None:
        lookup.update(getattr(catalog, "filter_lookup", {}) or {})
    option = CATALOG_OPTIONS.get(name)
    if option is not None:
        lookup.update(getattr(option, "filter_lookup", {}) or {})
    return lookup


def _resolve_target(
    target: str,
    catalog_mags: set[str],
    lookup: dict[str, str],
) -> tuple[bool, str, str]:
    seen: set[str] = set()
    current = target
    while current and current not in seen:
        seen.add(current)
        if current in catalog_mags:
            return True, current, "lookup_band"
        next_target = lookup.get(current)
        if next_target:
            current = next_target
            continue
        deps = _expression_deps(current)
        if deps and all(dep in catalog_mags for dep in deps):
            return True, current, "expression"
        return False, current, "unresolved"
    return False, target, "unresolved"


def _reference_resolves(
    *,
    catalog_name: str,
    image_filter: str,
    catalog_mags: set[str],
    lookup: dict[str, str],
) -> bool:
    dummy_mags = {
        band: {"value": 1.0, "error": 0.1}
        for band in catalog_mags
    }
    ref_mag, _ref_error = resolve_ref_mag_for_filter(
        image_filter=image_filter,
        catalog_name=catalog_name,
        cs_mags=dummy_mags,
        custom_filter_lookup={catalog_name: lookup},
        allow_preferred_band_fallback=False,
    )
    return ref_mag is not None


def list_photometric_catalogs() -> list[CatalogSummary]:
    """List local photometric catalog declarations without querying them."""

    summaries: list[CatalogSummary] = []
    for name, catalog in CATALOGS.items():
        lookup = getattr(catalog, "filter_lookup", {}) or {}
        summaries.append(
            CatalogSummary(
                name=name,
                display_name=getattr(catalog, "display_name", None),
                num_sources=getattr(catalog, "num_sources", None),
                bands=list((getattr(catalog, "mags", {}) or {}).keys()),
                filter_aliases=sorted(lookup.keys()),
            )
        )
    return summaries


def resolve_reference_band(catalog: str, image_filter: str | None) -> ReferenceBandResolution:
    """Resolve the catalog band or expression Kepler would use for an image filter."""

    catalog_name = str(catalog).strip()
    warnings: list[ToolWarning] = []
    errors: list[ToolError] = []
    declaration = _effective_catalog(catalog_name)
    if declaration is None:
        errors.append(ToolError(code="unknown_catalog", message=f"Unknown catalog: {catalog_name}"))
        return ReferenceBandResolution(
            catalog=catalog_name,
            image_filter=image_filter,
            supported=False,
            errors=errors,
        )

    normalized_filter = (image_filter or "").strip()
    if not normalized_filter:
        warnings.append(ToolWarning(code="blank_filter", message="No image filter was provided."))
        return ReferenceBandResolution(
            catalog=catalog_name,
            image_filter=normalized_filter or None,
            supported=False,
            warnings=warnings,
        )

    catalog_mags = set((getattr(declaration, "mags", {}) or {}).keys())
    lookup = _effective_lookup(catalog_name)
    wildcard_target = lookup.get("*")
    reference_resolves = _reference_resolves(
        catalog_name=catalog_name,
        image_filter=normalized_filter,
        catalog_mags=catalog_mags,
        lookup=lookup,
    )

    for token in _filter_token_candidates(normalized_filter):
        if token in catalog_mags:
            return ReferenceBandResolution(
                catalog=catalog_name,
                image_filter=normalized_filter,
                supported=reference_resolves,
                reference=token,
                kind="direct_band",
            )

        target = lookup.get(token)
        if target:
            supported, reference, kind = _resolve_target(target, catalog_mags, lookup)
            return ReferenceBandResolution(
                catalog=catalog_name,
                image_filter=normalized_filter,
                supported=supported and reference_resolves,
                reference=reference,
                kind=kind if reference_resolves else "unresolved",
            )

    if wildcard_target:
        supported, reference, kind = _resolve_target(wildcard_target, catalog_mags, lookup)
        return ReferenceBandResolution(
            catalog=catalog_name,
            image_filter=normalized_filter,
            supported=supported and reference_resolves,
            reference=reference,
            kind="wildcard" if supported and reference_resolves else kind,
        )

    warnings.append(
        ToolWarning(
            code="unsupported_filter",
            message=f"{catalog_name} has no reference-band mapping for filter {normalized_filter!r}.",
        )
    )
    return ReferenceBandResolution(
        catalog=catalog_name,
        image_filter=normalized_filter,
        supported=False,
        warnings=warnings,
    )
