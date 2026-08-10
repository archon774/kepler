"""
SkyLib - a library of SkyNet-specific algorithms, mostly related to image
manipulation and based on NumPy, SciPy, AstroPy, and several other packages.

EXTRACTED: vendored subset of skynet/packages/py/skylib/skylib, limited to the
modules field calibration actually reaches — `util.stats` (Chauvenet rejection
inside the zero-point solve), `util.angle` (angular separation for variable-star
rejection) and `util.fits` (exposure epoch from the FITS header). All three are
byte-for-byte copies and are self-contained (no intra-skylib imports).

Kepler/photometry/ vendors its own, larger subset of skylib the same way; the
duplication is deliberate so each extracted domain stands alone and neither
folder reaches into the other.

# EXTRACTED: was `from ._version import __version__` (skylib/_version.py)
"""
