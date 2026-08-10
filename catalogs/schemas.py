"""Kepler: catalog source data objects.

This module is Kepler's canonical catalog-source schema. It is the data
contract between ``catalogs/`` (which declares what a catalog contains) and
``query/`` (which fetches rows and maps them onto these objects).

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/common/schemas.py
(331 lines total; the catalog subset is reproduced here, field-for-field).
Field names, aliases, defaults and the NaN-stripping serializer are preserved
because they are wire-visible; the upstream class *names* are not, since Kepler
is a separate service and does not present itself as Skynet.

Kepler previously carried these classes inside ``fieldcal/schemas.py``; that
module now re-exports them, so a ``CatalogSource`` produced by a ``query/``
backend is the *same* class field calibration matches against rather than a
structurally identical twin.

Only what ``CatalogSource`` needs lives here. Detection-side schemas
(``IAperture``, ``PhotometrySettings``, ``ISourceMeta``, ``IFwhm``,
``SourceExtractionData``, ``PhotometryData``, ``FieldCalResult``, ...) stay in
``fieldcal/schemas.py`` — they are calibration state, not catalog state.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from pydantic.alias_generators import to_camel

__all__ = [
    "KeplerBaseModel",
    "Mag",
    "IPhotometry",
    "IAstrometry",
    "ICatalogSource",
    "CatalogSource",
    "CatalogMeta",
]


def _clean_nans(obj):
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        t = type(obj)
        return t(_clean_nans(v) for v in obj)
    return obj


def _strip_schema_titles(schema: Dict[str, Any], _model: Type[BaseModel]) -> None:
    for prop in schema.get("properties", {}).values():
        if prop.get("title", None) not in [None, ""]:
            prop.pop("title", None)


class KeplerBaseModel(BaseModel):
    """Base model for Kepler catalog schemas.

    EXTRACTED: was ``skynet_sdk.schemas.base.SkynetBaseModel``, renamed because
    this is Kepler's own base class, not a Skynet import. The upstream base
    additionally carried a cross-package model/union registry
    (``model_registry``, ``register_union``, ``rebuild_all_models``) used by its
    FastAPI/SDK layer; that machinery is service infrastructure and is dropped.

    Two upstream behaviours *are* load-bearing and are preserved exactly:

    * ``model_config`` — the camelCase alias generator plus ``populate_by_name``,
      so ``model_dump()`` / ``Model(**mapping)`` round-trips keep working on
      field names as well as aliases;
    * ``_clean_nans`` — a wrap serializer turning NaN/inf floats into ``None`` on
      every ``model_dump()``. Callers rely on this when re-hydrating sources.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        use_enum_values=True,
        protected_namespaces=("protect_me_", "also_protect_"),
        json_schema_extra=_strip_schema_titles,
    )

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)  # dict ready for JSON
        return _clean_nans(data)


class Mag(KeplerBaseModel):
    value: Optional[float] = None
    error: Optional[float] = None


class IPhotometry(KeplerBaseModel):
    # Upstream's Marshmallow schema made flux/flux_err_counts required; they are
    # Optional here for robustness in pipeline flows. The ``flux_err_counts`` and
    # ``magnitude_err_mag`` aliases are wire-visible and preserved.
    catalog_name: Optional[str] = None
    ref_mag: Optional[float] = None
    ref_mag_error: Optional[float] = None
    flux: Optional[float] = None
    flux_error: Optional[float] = Field(default=None, alias="flux_err_counts")
    mag: Optional[float] = None
    mag_error: Optional[float] = Field(default=None, alias="magnitude_err_mag")


class IAstrometry(KeplerBaseModel):
    ra_hours: Optional[float] = None
    dec_degs: Optional[float] = None
    pm_ra: Optional[float] = None
    pm_dec: Optional[float] = None
    pm_ra_error: Optional[float] = None
    pm_dec_error: Optional[float] = None
    pm_sky: Optional[float] = None
    pm_pos_angle_sky: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    pm_pixel: Optional[float] = None
    pm_pos_angle_pixel: Optional[float] = None
    pm_epoch: Optional[datetime] = None
    flux: Optional[float] = None
    sat_pixels: Optional[int] = None


class ICatalogSource(KeplerBaseModel):
    """Generic catalog source definition without astrometry."""

    id: Optional[str] = None
    file_id: Optional[int] = None
    label: Optional[str] = None
    catalog_name: Optional[str] = None
    mags: Dict[str, Mag] = Field(default_factory=dict)


class CatalogSource(ICatalogSource, IAstrometry, IPhotometry):
    """A single row returned by a catalog query.

    PRESERVED QUIRK: this model declares no ``name`` / ``type`` / ``amplitude``
    / ``period`` fields, and Pydantic's default ``extra='ignore'`` therefore
    silently drops those keyword arguments. ``VSXCatalog.table_to_sources``
    passes all four (see ``catalogs/vsx_catalog.py``). Upstream behaves the same
    way; do not add the fields to "fix" it without re-checking the VSX
    variable-star rejection path in ``fieldcal/field_cal.py``, which depends on
    the current shape.
    """


class CatalogMeta(KeplerBaseModel):
    """Serializable description of a catalog, for API/config surfaces.

    EXTRACTED: was named ``Catalog`` upstream. Renamed here because
    ``catalogs.catalog.Catalog`` — the plugin base class the 11 plugins actually
    subclass — occupies that name in this package. The two are unrelated
    upstream as well: this is a settings record, that is the plugin ABC.
    """

    name: Optional[str] = None
    display_name: Optional[str] = None
    num_sources: Optional[int] = None
    mags: Dict[str, List[str]] = Field(default_factory=dict)
    filter_lookup: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_display_name(self) -> "CatalogMeta":
        if self.display_name is None:
            self.display_name = self.name
        return self
