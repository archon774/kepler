# schemas.py  (updated)
#
# EXTRACTED from skynet/packages/py/skynet-db/skynet_db/runners/common/schemas.py
# (331 lines). Only the photometry / source-extraction settings and data objects
# are kept here. Left behind in Skynet, because they belong to other pipeline
# stages and other Kepler modules:
#   - Mag                            (unused by the photometry path)
#   - WcsCalibrationSettings         -> astrometry / Kepler wcs/
#   - ICatalogSource, CatalogSource,
#     Catalog                        -> Kepler catalogs/
#   - PhotometricCalibrationSettings,
#     FieldCalResult                 -> Kepler fieldcal/
#   - ImageProperties                (image reduction bookkeeping)
# Class bodies below are verbatim; only the base-model import was severed.

from __future__ import annotations
from datetime import datetime
import math
import re
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_serializer
from pydantic.alias_generators import to_pascal

# ============================================================================
# EXTRACTED: was `from skynet_sdk.schemas import SkynetBaseModel`
# (skynet/packages/py/skynet-sdk/skynet_sdk/schemas/base.py:139).
#
# The Skynet base model carries FastAPI/OpenAPI and SQLAlchemy plumbing that the
# photometric math does not need. Reproduced verbatim below are the two pieces
# that DO affect the data these models carry:
#   * `model_config` (camelCase alias generator + populate_by_name +
#     from_attributes + use_enum_values), because the pipeline constructs and
#     round-trips these models by snake_case field name, and
#     `IPhotometry.flux_error` / `mag_error` rely on their explicit aliases
#     ("flux_err_counts" / "magnitude_err_mag") matching the renamed skylib
#     output columns; and
#   * the `_clean_nans` wrap serializer, which turns NaN/Inf floats into None on
#     every `model_dump()` — `PhotometryData.from_source_and_row()` dumps the
#     source model, so this is numeric behavior, not just JSON cosmetics.
#
# Dropped (pure infrastructure): the `model_registry` / `union_registry` /
# `rebuilt_models` class registries and `rebuild_all_models()` /
# `register_union()` / `get_registered_models()` / `clear_registry()`, plus the
# `_strip_schema_titles` json_schema_extra hook and the
# `protected_namespaces=("protect_me_", "also_protect_")` config entry — all of
# which exist to serve Skynet's generated API schema.
# ============================================================================


def to_camel(snake: str) -> str:
    """Convert a snake_case string to camelCase and convert trailing underscores to leading hyphens.

    Args:
        snake: The string to convert.

    Returns:
        The converted camelCase string.
    """
    hyphenate = False
    if snake[-1] == "_":
        hyphenate = True
        snake = snake[:-1]

    camel = to_pascal(snake)
    camel = re.sub("(^_*[A-Z])", lambda m: m.group(1).lower(), camel)
    if hyphenate:
        camel = "-" + camel
    return camel


def _clean_nans(obj):
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: _clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        t = type(obj)
        return t(_clean_nans(v) for v in obj)
    return obj


class SkynetBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        use_enum_values=True,
    )

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)  # dict ready for JSON
        return _clean_nans(data)


# ============================================================================
# Photometry & Source Extraction
# ============================================================================


class IPhotometry(SkynetBaseModel):
    # In legacy Marshmallow, flux/flux_err_counts were required;
    # we keep them Optional here for robustness in pipeline flows.
    catalog_name: Optional[str] = None
    ref_mag: Optional[float] = None
    ref_mag_error: Optional[float] = None
    flux: Optional[float] = None
    flux_error: Optional[float] = Field(default=None, alias="flux_err_counts")
    mag: Optional[float] = None
    mag_error: Optional[float] = Field(default=None, alias="magnitude_err_mag")


class IAperture(SkynetBaseModel):
    aper_a: Optional[float] = None
    aper_b: Optional[float] = None
    aper_theta: Optional[float] = None
    annulus_a_in: Optional[float] = None
    annulus_b_in: Optional[float] = None
    annulus_theta_in: Optional[float] = None
    annulus_a_out: Optional[float] = None
    annulus_b_out: Optional[float] = None
    annulus_theta_out: Optional[float] = None


class PhotometrySettings(SkynetBaseModel):
    # Mirrors PhotSettings defaults from legacy
    mode: str = "aperture"
    a: Optional[float] = None
    b: Optional[float] = None
    theta: float = 0.0
    a_in_px: Optional[float] = None
    a_out_px: Optional[float] = None
    b_out_px: Optional[float] = None
    theta_out_deg: Optional[float] = None
    gain: Optional[float] = None
    centroid_radius: float = 0.0
    zero_point_mag: float = 0.0
    fix_aper: bool = False
    fix_ell: bool = True
    fix_rot: bool = True
    apcorr_tol: float = 1e-4
    reject_bkg_outliers: bool = False


class ISourceMeta(SkynetBaseModel):
    file_id: Optional[int] = None
    time: Optional[datetime] = None
    filter: Optional[str] = None
    telescope: Optional[str] = None
    exp_length: Optional[float] = None


class IAstrometry(SkynetBaseModel):
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


class IFwhm(SkynetBaseModel):
    fwhm_x: Optional[float] = None
    fwhm_y: Optional[float] = None
    theta: Optional[float] = None


class ISourceId(SkynetBaseModel):
    id: Optional[str] = None


class SourceExtractionSettings(SkynetBaseModel):
    x: int = Field(1)
    y: int = Field(1)
    width: int = Field(0)
    height: int = Field(0)
    downsample: int = Field(1)
    threshold: float = Field(2.5)
    bk_size: float = Field(1/64)
    bk_filter_size: int = Field(3)
    fwhm: float = Field(0.0)
    ratio: float = Field(1.0)
    theta: float = Field(0.0)
    min_pixels: int = Field(3)
    min_fwhm: float = Field(0.8)
    max_fwhm: float = Field(50.0)
    max_ellipticity: float = Field(3.0)
    deblend: bool = Field(True)
    deblend_levels: int = Field(32)
    deblend_contrast: float = Field(0.005)
    gain: Optional[float] = Field(None)
    clean: float = Field(1.0)
    centroid: bool = Field(True)
    limit: Optional[int] = Field(None)
    sat_level: float = Field(63000.0)
    auto_sat_level: bool = Field(False)
    discard_saturated: int = Field(1)
    max_sources: int = Field(10000)
    clip_lo: float = Field(0.0)
    clip_hi: float = Field(100.0)


class SourceExtractionData(ISourceMeta, IAstrometry, IFwhm, ISourceId):
    @classmethod
    def from_numpy_row(
        cls,
        row: Any,
        *,
        ofs_x: int = 0,
        ofs_y: int = 0,
        wcs: Any = None,
        **kwargs: Any,
    ) -> "SourceExtractionData":
        import numpy as np
        sigma_to_fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0))
        data = dict(kwargs)
        data["x"] = float(row["x"]) + ofs_x
        data["y"] = float(row["y"]) + ofs_y
        data["fwhm_x"] = float(row["a"]) * sigma_to_fwhm
        data["fwhm_y"] = float(row["b"]) * sigma_to_fwhm
        data["theta"] = float(np.rad2deg(row["theta"]))
        data["flux"] = float(row["flux"])
        try:
            data["sat_pixels"] = int(row["saturated"])
        except Exception:
            pass
        if wcs is not None and data.get("x") is not None and data.get("y") is not None:
            ra_deg, dec_deg = wcs.all_pix2world(data["x"], data["y"], 1)
            data["ra_hours"] = (float(ra_deg) % 360.0) / 15.0
            data["dec_degs"] = float(dec_deg)
        return cls(**data)


class Photometry(SkynetBaseModel):
    # Not referenced by run_photometry(); kept because it is the photometry
    # record shape the pipeline persists, and it documents the unit-suffixed
    # names that run_photometry() translates the skylib columns into.
    flux: Optional[float] = None
    flux_err_counts: Optional[float] = None
    mag: Optional[float] = None
    magnitude_err_mag: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    a: Optional[float] = None
    b: Optional[float] = None
    theta: Optional[float] = None
    a_in_px: Optional[float] = None
    a_out_px: Optional[float] = None
    b_out_px: Optional[float] = None
    theta_out_deg: Optional[float] = None
    area: Optional[float] = None
    background_area_px: Optional[float] = None
    background: Optional[float] = None


class PhotometryData(SourceExtractionData, IPhotometry, IAperture):
    @classmethod
    def from_source_and_row(
        cls,
        source: Optional[SourceExtractionData] = None,
        row: Optional[Any] = None,
        zero_point_mag: float = 0.0,
        **kwargs: Any,
    ) -> "PhotometryData":
        base: Dict[str, Any] = {}
        if source:
            base.update(source.model_dump(exclude_unset=True))
        if row is not None:
            # x/y from the row (post-centroid positions) override source positions — legacy parity
            x = row.get("x")
            if x is not None:
                base["x"] = float(x)
            y = row.get("y")
            if y is not None:
                base["y"] = float(y)
            flux = row.get("flux")
            if flux is not None:
                base["flux"] = float(flux)
            flux_err_counts = row.get("flux_err_counts")
            if flux_err_counts is not None:
                base["flux_error"] = float(flux_err_counts)
            mag = row.get("mag")
            if mag is not None:
                base["mag"] = float(mag) + float(zero_point_mag)
            magnitude_err_mag = row.get("magnitude_err_mag")
            if magnitude_err_mag is not None:
                base["mag_error"] = float(magnitude_err_mag)
            if row.get("aper_a") is not None:
                base["aper_a"] = float(row["aper_a"])
                base["aper_b"] = float(row["aper_b"])
                base["aper_theta"] = float(row["aper_theta"])
                aper_a_out = float(row.get("aper_a_out") or 0)
                if aper_a_out > 0:
                    base["annulus_a_in"] = float(row["aper_a_in"])
                    base["annulus_a_out"] = aper_a_out
                    base["annulus_b_out"] = float(row["aper_b_out"])
                    base["annulus_b_in"] = float(row["aper_a_in"]) * float(row["aper_b_out"]) / aper_a_out
                    base["annulus_theta_in"] = float(row["aper_theta_out"])
                    base["annulus_theta_out"] = float(row["aper_theta_out"])
        base.update(kwargs)
        return cls(**base)
