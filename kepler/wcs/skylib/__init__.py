"""
SkyLib - a library of SkyNet-specific algorithms, mostly related to image
manipulation and based on NumPy, SciPy, AstroPy, and several other packages.
"""

# EXTRACTED: the upstream skylib/__init__.py does `from ._version import __version__`.
# Only the astrometry stack (plus the two util modules and the FITS-compression
# HDU selector it needs) was vendored here, so there is no packaged version file
# and the import is dropped.
