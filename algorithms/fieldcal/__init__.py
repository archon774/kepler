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

Callers provide WCS, catalog rows, optional variable-star rows, and any desired
source-extraction or photometry settings explicitly. Catalog queries belong at
the public tool boundary, not in this deterministic algorithm package.
"""

from .field_cal import perform_field_calibration
from .ref_mag import resolve_ref_mag_for_filter
from .schemas import (
    CatalogSource,
    FieldCalResult,
    Mag,
    PhotometricCalibrationSettings,
    PhotometryData,
    PhotometrySettings,
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
    "SourceExtractionData",
    "SourceExtractionSettings",
    "calc_solution",
    "perform_field_calibration",
    "resolve_ref_mag_for_filter",
]
