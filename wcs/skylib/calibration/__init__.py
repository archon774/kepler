"""
SkyLib functions for bias/dark/flat/cosmetic calibration.

background: sky background estimation and subtraction.
bias: bias correction
cosmic: cosmic ray rejection
cosmetic: bright/dead pixel/column correction
dark: dark correction
flat: flat correction
"""

# EXTRACTED: only `background` was vendored — `skylib.extraction` needs
# `estimate_background` / `sep_compatible` from it. The bias/dark/flat/cosmic/
# cosmetic reduction modules are a separate pipeline stage, not reachable from
# the WCS solve. The upstream docstring is kept verbatim.
