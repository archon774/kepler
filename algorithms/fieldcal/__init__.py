"""Field calibration — photometric zero-point solve against a reference catalog.

Extracted from the Skynet optical data-processing pipeline; see docs/extraction.md, Field Calibration
for exact provenance and every severed dependency.

Field calibration does not own catalogs. Band tables and colour transforms live
in ``algorithms.catalogs``, catalog queries in ``algorithms.query`` — including the
filter-aware catalog selection and the query entry point this package used to
re-export.

Pipeline (``perform_field_calibration``):

    catalog sources  ->  variable-star rejection (VSX proximity)
                     ->  mutual nearest-neighbour match to detected sources
                     ->  photometry on the matched sources
                     ->  SNR window + max_stars trim
                     ->  reference-magnitude resolution per image FILTER
                     ->  weighted zero-point solve with Chauvenet rejection

Before calling ``perform_field_calibration``, wire the cross-domain callables
that this package does not own::

    from algorithms.fieldcal import deps
    deps.run_photometry = ...              # algorithms.photometry
    deps.run_source_extraction = ...       # algorithms.photometry
    deps.get_source_radec = ...            # algorithms.photometry
    deps.build_wcs_for_processing_run = ...  # algorithms.wcs

``deps.query_catalogs`` already has a working default backed by Kepler's
``algorithms.query`` package, so catalog fetching needs no wiring; override it to
route queries elsewhere.
"""

from . import deps
from .field_cal import perform_field_calibration
from .ref_mag import resolve_ref_mag_for_filter
from .schemas import (
    CatalogSource,
    FieldCalResult,
    Mag,
    PhotometricCalibrationSettings,
    PhotometryData,
    PhotometrySettings,
    ProcessingRunRef,
    SourceExtractionData,
    SourceExtractionSettings,
)
from .solution import calc_solution

__all__ = [
    "CatalogSource",
    "FieldCalResult",
    "Mag",
    "PhotometricCalibrationSettings",
    "PhotometryData",
    "PhotometrySettings",
    "ProcessingRunRef",
    "SourceExtractionData",
    "SourceExtractionSettings",
    "calc_solution",
    "deps",
    "perform_field_calibration",
    "resolve_ref_mag_for_filter",
]
