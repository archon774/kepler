"""Photometry algorithms and data models.

Extracted from the Skynet codebase; see EXTRACTION.md for exact provenance,
the infrastructure seams that were cut, and required dependencies.

Modules:
    photometry          aperture/auto photometry entry points
    source_extraction   source detection and FITS-header WCS helpers
    schemas             Pydantic settings and data objects

The vendored Skylib algorithmic core now lives in ``algorithms.skylib_lite``:
aperture photometry, source extraction, centroiding, background estimation,
exact pixel/aperture overlap, and statistics.
"""

__all__ = ["photometry", "schemas", "source_extraction"]
