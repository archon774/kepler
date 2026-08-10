"""
Afterglow Core: SkyMapper catalog accessed via VizieR
"""

# EXTRACTED: was `from .vizier_catalogs import VizierCatalog` (VizieR backend).
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

    # EXTRACTED / DROPPED: the original also overrode ``query_region`` purely to
    # default the VizieR ``flags=0`` column constraint (drop sources with
    # non-zero SExtractor flags) before delegating to
    # ``VizierCatalog.query_region``.  That is query-backend behaviour, not
    # calibration math; it must be re-applied by whatever backend Kepler/catalogs/
    # provides.  Original body:
    #
    #     if constraints is None:
    #         constraints = {}
    #     constraints.setdefault('flags', '0')
    #     return super().query_region(
    #         ra_hours, dec_degs, constraints, limit, **region)
