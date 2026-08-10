"""Photometry: aperture photometry and the source extraction that feeds it.

Extracted from the Skynet codebase; see EXTRACTION.md for exact provenance,
the infrastructure seams that were cut, and required dependencies.

Layout:
    pipeline/   the observation-asset processing stage (orchestration, settings,
                data objects)
    skylib/     the vendored algorithmic core (aperture photometry, source
                extraction, centroiding, background, exact pixel/aperture
                overlap, statistics)
"""
