"""
SkyLib functions for image I/O, including conversion to JPEG and other
non-astronomical image formats.
"""

# EXTRACTED: only `fits_compression` was vendored (the ATLAS extractor calls
# `select_image_hdu` so it reads the science HDU of a tile-compressed frame).
# `conversion` is not reachable from the WCS solve.
