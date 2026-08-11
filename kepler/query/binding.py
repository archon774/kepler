"""Binding catalog declarations to query backends.

``catalogs/`` declares what each catalog contains and imports nothing that talks
to a network. ``query/`` knows how to reach providers but nothing about
individual catalogs. This module marries them, and ``query/registry.py`` is the
result.

Binding is done with multiple inheritance rather than by giving the plugins a
backend attribute, and that is deliberate: three plugins override
``table_to_sources`` and two of those call ``super().table_to_sources(...)`` to
get the raw row mapping before applying a photometric transform. Composition
would leave those ``super()`` calls pointing at the abstract base. Subclassing
``(Declaration, Backend)`` puts the backend immediately behind the declaration
in the MRO, so the calls land exactly where upstream's ``class
LandoltCatalog(VizierCatalog)`` put them::

    LandoltQueryable -> LandoltCatalog -> VizierCatalog -> Catalog -> object
                        ^ transform       ^ row mapper     ^ contract

Upstream had a single class per catalog inheriting the backend directly. Kepler
splits them so the declarations stay importable — and testable — without
astroquery, and so the same declaration could later be bound to a local backend.
The generated classes are equivalent to upstream's at runtime.
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from kepler.catalogs.catalog import Catalog

from .sdss import SDSSQueryBackend
from .skymapper import SkyMapperQueryBackend
from .vizier import VizierCatalog

__all__ = ["bind_backend", "bind_registry", "BACKENDS"]


#: Catalog name -> backend class. Anything absent gets ``VizierCatalog``, which
#: is the right default: nine of the eleven catalogs are plain VizieR tables.
BACKENDS: Dict[str, Type[VizierCatalog]] = {
    "SDSS": SDSSQueryBackend,
    "SkyMapper": SkyMapperQueryBackend,
}


def bind_backend(
    declaration: Type[Catalog],
    backend: Optional[Type[VizierCatalog]] = None,
) -> Type[Catalog]:
    """Return a queryable subclass of ``declaration`` backed by ``backend``.

    ``backend`` defaults to the entry in ``BACKENDS`` for the declaration's
    ``name``, or ``VizierCatalog``. The returned class is cached on the
    declaration, so repeated binding returns the same class and ``isinstance``
    stays meaningful across calls.
    """
    cached = declaration.__dict__.get("_bound_class")
    if cached is not None:
        return cached

    if backend is None:
        backend = BACKENDS.get(declaration.name, VizierCatalog)

    bound = type(
        f"{declaration.__name__}Queryable",
        (declaration, backend),
        {"__module__": declaration.__module__, "__doc__": declaration.__doc__},
    )
    declaration._bound_class = bound
    return bound


def bind_registry(declarations: Dict[str, Catalog]) -> Dict[str, Catalog]:
    """Bind a registry of catalog *instances* into queryable instances.

    Takes ``catalogs.CATALOGS`` — instances, already carrying their
    registry-specific ``filter_lookup`` overlays — and returns the same mapping
    with each entry rebuilt on its bound class. The overlay is carried across by
    reading each instance's own ``filter_lookup``, so the ``_OCL_TO_V`` and
    colour-transform entries applied at registration survive binding.
    """
    bound: Dict[str, Catalog] = {}
    for name, instance in declarations.items():
        declaration = type(instance)
        cls = bind_backend(declaration)
        # Pass the instance's merged lookup, not the class's, so registry-level
        # overlays are preserved. Both sides use getattr with a default:
        # ``Catalog`` annotates ``filter_lookup`` without assigning it, so a
        # plugin that declares no transforms (USNO-B1, Stetson) genuinely has no
        # such attribute — upstream included.
        declared = getattr(declaration, "filter_lookup", {})
        merged = getattr(instance, "filter_lookup", {})
        overlay = {k: v for k, v in merged.items() if declared.get(k) != v}
        bound[name] = cls(filter_lookup=overlay or None)
    return bound
