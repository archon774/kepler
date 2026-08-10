"""Field-calibration data objects and settings.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/common/schemas.py
(331 lines total; the field-calibration subset is reproduced here verbatim).

Left behind in the Skynet original (not field-cal related):
``WcsCalibrationSettings``, ``Photometry``, ``ImageProperties``.
"""

# schemas.py  (updated)

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from pydantic.alias_generators import to_camel

# EXTRACTED: was `from skynet_sdk.schemas import SkynetBaseModel`.
# The Skynet base model additionally carries a cross-package model/union
# registry (``model_registry``, ``register_union``, ``rebuild_all_models``)
# used by the FastAPI/SDK layer.  That machinery is service infrastructure and
# is dropped here.  The parts that are *behaviourally* load-bearing for field
# calibration are preserved verbatim:
#   * ``model_config`` (camelCase alias generator + ``populate_by_name``, so the
#     ``model_dump()`` / ``Model(**mapping)`` round-trips used all over
#     ``field_cal.py`` keep working on field names);
#   * the ``_clean_nans`` wrap serializer, which turns NaN/inf floats into
#     ``None`` on every ``model_dump()`` — field calibration relies on this when
#     re-hydrating matched sources.


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


class SkynetBaseModel(BaseModel):
    """EXTRACTED: reduced ``skynet_sdk.schemas.base.SkynetBaseModel``."""

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


# ============================================================================
# Photometry & Source Extraction (unchanged parts elided for brevity)
# ============================================================================

class Mag(SkynetBaseModel):
    value: Optional[float] = None
    error: Optional[float] = None


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

# ============================================================================
# Catalogs
# ============================================================================

class ICatalogSource(SkynetBaseModel):
    """Generic catalog source definition without astrometry."""

    id: Optional[str] = None
    file_id: Optional[int] = None
    label: Optional[str] = None
    catalog_name: Optional[str] = None
    mags: Dict[str, Mag] = Field(default_factory=dict)


class CatalogSource(ICatalogSource, IAstrometry, IPhotometry):
    """Catalog source definition for field calibration."""


class Catalog(SkynetBaseModel):
    """Base class for catalog plugin metadata/settings."""

    name: Optional[str] = None
    display_name: Optional[str] = None
    num_sources: Optional[int] = None
    mags: Dict[str, List[str]] = Field(default_factory=dict)
    filter_lookup: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_display_name(self) -> "Catalog":
        if self.display_name is None:
            self.display_name = self.name
        return self

# ============================================================================
# Photometric Calibration (formerly "FieldCal")
# ============================================================================

class PhotometricCalibrationSettings(SkynetBaseModel):
    """
    Settings used to perform photometric (field) calibration / zero-point solve.
    """
    id: Optional[int] = None
    user_id: Optional[int] = None
    name: Optional[str] = None
    catalog_sources: List[CatalogSource] = Field(default_factory=list)
    catalogs: List[str] = Field(default_factory=lambda: ["APASS"])
    custom_filter_lookup: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    source_inclusion_percent: Optional[float] = 100
    min_snr: Optional[float] = 10
    max_snr: Optional[float] = None
    source_match_tol: Optional[float] = 5
    variable_check_tol: Optional[float] = 5
    max_star_rms: Optional[float] = None
    max_stars: Optional[int] = None
    # When True, reference-magnitude resolution follows strict legacy Afterglow
    # parity: a source whose image filter resolves to no direct catalog band or
    # mapping expression is skipped, instead of falling back to a preferred band
    # (V, r', g', B, i'). The direct-band-by-filter-name match (e.g. a B image
    # against the catalog Bmag) applies regardless of this flag.
    strict_filter_parity: bool = False
# (Ports legacy FieldCal fields 1:1.)  # :contentReference[oaicite:4]{index=4}

class FieldCalResult(SkynetBaseModel):
    """
    Result of photometric calibration for a single file.
    """
    file_id: Optional[int] = None
    phot_results: List[PhotometryData] = Field(default_factory=list)
    zero_point_corr: Optional[float] = None
    zero_point_error_mag: Optional[float] = None
    zero_point_slop: Optional[float] = None
    limmag5: Optional[float] = None
    rej_percent: Optional[float] = None
# (Ports legacy FieldCalResult fields.)  # :contentReference[oaicite:5]{index=5}


# ============================================================================
# EXTRACTED: stand-in for the Skynet ORM row
# ============================================================================

class ProcessingRunRef(SkynetBaseModel):
    """EXTRACTED: stand-in for ``skynet_db.models.ObservationAssetProcessingRun``.

    Field calibration reads exactly two attributes off the processing-run
    object it is handed:

      * ``.id``                   — used only to build the unique source-ID
                                    prefix in ``_ensure_unique_source_ids`` and
                                    for log lines;
      * ``.observation_asset_id`` — used as ``file_id`` on emitted sources.

    Everything else on the SQLAlchemy row (session binding, S3 asset locators,
    job state, WCS solution rows) is persistence/job-runner infrastructure and
    is not used by the calibration algorithm.  ``perform_field_calibration``
    duck-types this parameter, so any object exposing those two attributes
    works; this model is provided so standalone callers have something concrete
    to construct.
    """

    id: Optional[int] = None
    observation_asset_id: Optional[int] = None
