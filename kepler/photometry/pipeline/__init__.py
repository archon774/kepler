"""Pipeline-level photometry stage extracted from Skynet.

photometry: aperture/auto photometry of a source list against a calibrated frame.
source_extraction: source detection that feeds photometry, plus the pixel<->sky
    helpers (`get_source_xy`, `get_source_radec`, `build_wcs_from_header`) that
    both stages share.
schemas: the settings and data objects the two stages exchange.

The photometric math itself lives in the vendored skylib packages one level up
(``photometry/skylib``); these modules are the orchestration around it.
"""
