"""Kepler: star-cluster HR/colour-magnitude diagram fitting.

Layout::

    hrfit.py         frozen reference math -- CCM89 extinction, isochrone
                     load/select, the CM<->HR transform, the distance/E(B-V)
                     fit, and the CMD plotter. Self-contained, no network.
    observations.py  FITS -> instrumental photometry (via algorithms.photometry /
                     algorithms.wcs), and photometry-table loading (no network).
    gaia.py          Gaia DR3 crossmatch for multi-band photometry + astrometry.
    literature.py    published cluster parameters (open via Cantat-Gaudin &
                     Anders 2020; globular via Harris 2010 + Vasiliev &
                     Baumgardt 2021), by name, with SIMBAD alias resolution.
    isochrones.py    MIST (default, whole-grid download + cache) and PARSEC
                     (per-request fallback) isochrone grids.
    membership.py    field-star removal (parallax + proper-motion cut).
    fit.py           ties the above together: fit distance/E(B-V)/age against
                     an isochrone, compare to literature, plot.

See kepler/tools/hr_diagram.py for the thin tool-layer wrappers built on this
package.
"""
