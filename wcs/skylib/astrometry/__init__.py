"""
SkyLib astrometric reduction package.

v2: the pure-Python **ATLAS** solver is the default and works on every platform.
The **astrometry.net** backend is optional and active only where the system
``solve-field`` binary is installed (Linux hosts); elsewhere it reports itself
unavailable and callers fall back to ATLAS.
"""

from .main import *  # noqa: F401,F403
