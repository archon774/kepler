"""Photometry: aperture photometry and the source extraction that feeds it.

Extracted from the Skynet codebase; see EXTRACTION.md for exact provenance,
the infrastructure seams that were cut, and required dependencies.

Layout:
    pipeline/   the observation-asset processing stage (orchestration, settings,
                data objects)

The vendored Skylib algorithmic core now lives in ``kepler.skylib_lite``:
aperture photometry, source extraction, centroiding, background estimation,
exact pixel/aperture overlap, and statistics.
"""
