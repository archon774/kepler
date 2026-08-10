"""
Kepler: SkyMapper catalog accessed via VizieR
"""

# EXTRACTED: was `from .vizier_catalogs import VizierCatalog`. In Kepler the
# VizieR backend lives in ``query/vizier.py`` and is mixed onto this class at
# import time by ``query/binding.py``, so this module stays declaration-only and
# carries no network dependency.
from .catalog import Catalog


__all__ = ['SkyMapperCatalog']


class SkyMapperCatalog(Catalog):
    """
    SkyMapper/VizieR catalog plugin
    """
    name = 'SkyMapper'
    display_name = 'SkyMapper Southern Sky Survey Data Release 1.1'
    num_sources = 285159194
    vizier_catalog = 'II/358/smss'
    row_limit = 5000
    col_mapping = {
        'id': 'ObjectId', 'ra_hours': 'RAICRS/15', 'dec_degs': 'DEICRS',
    }
    mags = {
        'u': ['uPSF', 'e_uPSF'], 'v': ['vPSF', 'e_vPSF'],
        'g': ['gPSF', 'e_gPSF'], 'r': ['rPSF', 'e_rPSF'],
        'i': ['iPSF', 'e_iPSF'], 'z': ['zPSF', 'e_zPSF'],
    }
    sort = ['+rPSF']
    filter_lookup = {
        # See row F5V of the table at
        # https://skymapper.anu.edu.au/filter-transformations/
        'uprime': 'u - 0.069', 'gprime': 'g + 0.088', 'rprime': 'r - 0.006',
        'iprime': 'i + 0.001', 'zprime': 'z - 0.005',
    }

    # SkyMapper is the only catalog that applies a default column constraint:
    # unless the caller says otherwise its queries add ``flags=0``, dropping
    # sources with non-zero SExtractor flags. That is enforced by a
    # ``query_region`` override in ``query/skymapper.py``, since it acts on the
    # request rather than on the photometry.
