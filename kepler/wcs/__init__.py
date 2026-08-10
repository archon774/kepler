"""Astrometric (WCS) calibration — algorithmic core extracted from Skynet.

Entry point: :func:`wcs.wcs.solve_wcs`. It extracts sources from a frame, tries
the local astrometry.net ``solve-field`` backend first, falls back to the
in-process ATLAS triangle solver, validates the result against the frame's own
parity and pointing hints, records the solution and writes it into the FITS
header.

Layout::

    wcs.py              the pipeline: hints, parity, acceptance, header write-back
    source_extraction.py header-WCS construction + the source list the solve uses
    schemas.py          WCS-related settings / data objects
    header_utils.py     pixel-scale and RA/Dec guesses from FITS keywords
    config.py           backend configuration seam (was Dynaconf)
    state.py            plain-object seam for the Skynet ORM rows
    skylib/             vendored subset of Skynet's skylib: the whole astrometry
                        stack (anet subprocess backend + ATLAS triangle solver),
                        plus the FITS/angle/HDU helpers it calls

See EXTRACTION.md for provenance, what was left behind, and the external
dependencies required.
"""
