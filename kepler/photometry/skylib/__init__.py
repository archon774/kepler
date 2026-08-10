"""
SkyLib - a library of SkyNet-specific algorithms, mostly related to image
manipulation and based on NumPy, SciPy, AstroPy, and several other packages.

EXTRACTED: vendored subset of skynet/packages/py/skylib/skylib, limited to the
modules the photometry pipeline actually reaches. Only `photometry`,
`extraction`, `calibration.background`, and `util` are present here; the rest of
skylib (astrometry, catalogs, combine, io, quality, sonification, ...) was left
in Skynet.

# EXTRACTED: was `from ._version import __version__` (skylib/_version.py, v2.0.9)
"""
