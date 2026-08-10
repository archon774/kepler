"""Field calibration — photometric zero-point solve against a reference catalog.

Extracted from the Skynet optical data-processing pipeline; see EXTRACTION.md
for exact provenance, every severed dependency, and the catalog-backend code
that was deliberately left out.

Pipeline (``perform_field_calibration``):

    catalog sources  ->  variable-star rejection (VSX proximity)
                     ->  mutual nearest-neighbour match to detected sources
                     ->  photometry on the matched sources
                     ->  SNR window + max_stars trim
                     ->  reference-magnitude resolution per image FILTER
                     ->  weighted zero-point solve with Chauvenet rejection

Before calling ``perform_field_calibration``, wire the cross-domain callables
that this package does not own::

    from fieldcal import deps
    deps.run_photometry = ...              # Kepler/photometry/
    deps.run_source_extraction = ...       # Kepler/photometry/
    deps.get_source_radec = ...            # Kepler/photometry/
    deps.build_wcs_for_processing_run = ...  # Kepler/wcs/
"""

from . import deps
from .catalog_query import (
    catalog_supports_filter,
    query_catalogs_for_processing_run,
    select_catalogs_for_filter,
)
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
    "catalog_supports_filter",
    "deps",
    "perform_field_calibration",
    "query_catalogs_for_processing_run",
    "resolve_ref_mag_for_filter",
    "select_catalogs_for_filter",
]
