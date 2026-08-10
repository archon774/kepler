"""WCS-related settings and data objects.

EXTRACTED from two Skynet modules, verbatim except where marked:

* ``skynet_db/runners/common/schemas.py`` — every model reachable from the WCS
  solve (``WcsCalibrationSettings``, ``SourceExtractionSettings``,
  ``SourceExtractionData``, ``CatalogSource`` and their mixins). The photometry /
  field-calibration models in that file (``PhotometrySettings``, ``Photometry``,
  ``PhotometryData``, ``IAperture``, ``Catalog``,
  ``PhotometricCalibrationSettings``, ``FieldCalResult``, ``ImageProperties``)
  are deliberately NOT extracted — they belong to the photometry/fieldcal
  pipelines, not the astrometric solve.
* ``skynet_sdk/schemas/processing_settings.py`` — ``PlateSolveSettings`` only.
"""

# schemas.py  (updated)

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

# EXTRACTED: was `from skynet_sdk.schemas import SkynetBaseModel`.
# The upstream base is a pydantic BaseModel carrying Skynet's API-serialization
# machinery: a camelCase alias generator, a model/union registry used to rebuild
# forward references across the SDK, a NaN-scrubbing serializer, and FastAPI
# schema-title stripping. None of that is part of the WCS algorithm — it is
# transport concern. Replaced here by a minimal base that preserves the two
# behaviours the models below actually rely on: construction by field name
# (``populate_by_name``, so ``Field(alias=...)`` fields still accept their
# python names) and ORM-attribute population (``from_attributes``).
class SkynetBaseModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        use_enum_values=True,
        protected_namespaces=("protect_me_", "also_protect_"),
    )


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

class WcsCalibrationSettings(SkynetBaseModel):
    ra_hours: Optional[float] = None
    dec_degs: Optional[float] = None
    radius: float = 180
    min_scale: float = 0.1
    max_scale: float = 60
    fov: Optional[float] = None
    parity: Optional[bool] = None
    sip_order: int = 0
    crpix_center: bool = False
    max_sources: Optional[int] = 100
    retry_lost: bool = False
    downsample: Optional[int] = None


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


# ============================================================================
# Observer-facing plate-solve preferences
# EXTRACTED from skynet_sdk/schemas/processing_settings.py (this class only).
# ============================================================================

class PlateSolveSettings(SkynetBaseModel):
    """Whether — and how tightly — to solve the frame's astrometry.

    Off means the output keeps whatever WCS the node wrote (often none), and no
    photometry or field calibration is possible.
    """

    enabled: bool = Field(
        default=True,
        description="Plate-solve the frame and write the solution into the header.",
    )
    # Both defaults are PARITY values, matching `WcsCalibrationSettings`, which
    # the solve read unconditionally before these became observer-settable.
    # `sip_order=0` means the pipeline writes a plain TAN solution today —
    # despite older docs describing the output as "SIP-precise". Raising the
    # default is a real product change and belongs in its own decision, not
    # smuggled in with the plumbing that makes it configurable.
    sip_order: int = Field(
        default=0,
        ge=0,
        le=9,
        description=(
            "Order of the SIP distortion polynomial fitted into the written WCS. "
            "0 (the default) writes a plain TAN solution."
        ),
    )
    crpix_center: bool = Field(
        default=False,
        description="Place the WCS reference pixel at the image centre.",
    )
