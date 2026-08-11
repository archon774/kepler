"""
Kepler: UCAC catalog accessed via VizieR
"""

from __future__ import absolute_import, division, print_function

# EXTRACTED: was `from .vizier_catalogs import VizierCatalog`. In Kepler the
# VizieR backend lives in ``query/vizier.py`` and is mixed onto this class at
# import time by ``query/binding.py``, so this module stays declaration-only and
# carries no network dependency.
from .catalog import Catalog


__all__ = ['UCAC5Catalog']


class UCAC5Catalog(Catalog):
    """
    UCAC5/VizieR catalog plugin
    """
    name = 'UCAC5'
    display_name = 'Fifth U.S. Naval Observatory CCD Astrograph Catalog'
    num_sources = 107758513
    vizier_catalog = 'I/340'
    row_limit = 5000
    mags = {
        'Open': ['f.mag'], 'G': ['Gmag'], 'R': ['Rmag'], 'J': ['Jmag'],
        'H': ['Hmag'], 'K': ['Kmag'],
    }
    filter_lookup = {'*': 'Open'}  # map all unknown mags to integral bandpass
    col_mapping = {
        'id': 'SrcIDgaia', 'ra_hours': 'RAJ2000/15', 'dec_degs': 'DEJ2000',
    }
    sort = ['+f.mag']
