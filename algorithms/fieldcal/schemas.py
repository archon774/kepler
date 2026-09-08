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

from algorithms.catalogs.schemas import (
    CatalogMeta,
    CatalogSource,
    IAstrometry,
    ICatalogSource,
    IPhotometry,
    KeplerBaseModel,
    Mag,
)

# ``KeplerBaseModel``, ``Mag``, ``IPhotometry``, ``IAstrometry``,
# ``ICatalogSource`` and ``CatalogSource`` are defined in ``catalogs/schemas.py``
# and imported above: they are the catalog data contract, and field calibration
# has to compare against the same classes a ``query/`` backend produces rather
# than local twins. Everything below is calibration state, which fieldcal owns.


class IAperture(KeplerBaseModel):
    aper_a: Optional[float] = None
    aper_b: Optional[float] = None
    aper_theta: Optional[float] = None
    annulus_a_in: Optional[float] = None
    annulus_b_in: Optional[float] = None
    annulus_theta_in: Optional[float] = None
    annulus_a_out: Optional[float] = None
    annulus_b_out: Optional[float] = None
    annulus_theta_out: Optional[float] = None


class PhotometrySettings(KeplerBaseModel):
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


class ISourceMeta(KeplerBaseModel):
    file_id: Optional[int] = None
    time: Optional[datetime] = None
    filter: Optional[str] = None
    telescope: Optional[str] = None
    exp_length: Optional[float] = None


class IFwhm(KeplerBaseModel):
    fwhm_x: Optional[float] = None
    fwhm_y: Optional[float] = None
    theta: Optional[float] = None


class ISourceId(KeplerBaseModel):
    id: Optional[str] = None

class SourceExtractionSettings(KeplerBaseModel):
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

# Catalog schemas are owned by Kepler's ``catalogs`` package, not by field
# calibration -- a ``CatalogSource`` handed back by a ``query/`` backend has to
# be the same class this module's matching code compares against, and a
# structurally identical local copy would not be. Re-exported under the names
# calibration call sites already use.
#
# ``Catalog`` here is the Pydantic metadata record, not the plugin base class of
# the same name in ``catalogs/catalog.py``; the two were distinct upstream too.
Catalog = CatalogMeta

# ============================================================================
# Photometric Calibration (formerly "FieldCal")
# ============================================================================

class PhotometricCalibrationSettings(KeplerBaseModel):
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

class FieldCalResult(KeplerBaseModel):
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
