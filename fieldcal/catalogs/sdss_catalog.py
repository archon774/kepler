"""
Afterglow Core: SDSS catalog
"""

# EXTRACTED: was `from .vizier_catalogs import VizierCatalog` (VizieR backend).
from .catalog import Catalog


__all__ = ['SDSSCatalog']


# EXTRACTED / DROPPED: the original module also defined ``AfterglowSDSS``
# (a subclass of ``astroquery.sdss.SDSSClass`` that builds a bespoke SDSS SQL
# query for rectangular/circular regions, handling pole and RA-wrap cases) and
# the ``SDSSCatalog.query_objects`` / ``query_box`` / ``query_circ`` overrides
# that drive it.  That is ~110 lines of catalog query backend with an
# ``astroquery.sdss`` dependency — see the EXTRACTION.md section on
# catalog-backend code destined for Kepler/catalogs/.  Only the photometric
# metadata below participates in zero-point calibration.


class SDSSCatalog(Catalog):
    """
    SDSS catalog plugin
    """
    name = 'SDSS'
    data_release = 17
    display_name = f'Sloan Digital Sky Survey Data Release {data_release}'
    num_sources = 260562744
    row_limit = 5000
    col_mapping = {
        'id': 'objID', 'ra_hours': 'ra/15', 'dec_degs': 'dec',
    }
    mags = {
        'u': ['u', 'err_u'], 'g': ['g', 'err_g'], 'r': ['r', 'err_r'],
        'i': ['i', 'err_i'], 'z': ['z', 'err_z'],
    }
    filter_lookup = {
        'uprime': 'u',
        'gprime': 'g - 0.06*(g - r - 0.53)',
        'rprime': 'r - 0.035*(r - i - 0.21)',
        'iprime': 'i - 0.041*(r - i - 0.21)',
        'zprime': 'z + 0.03*(i - z - 0.09)',
        'U': 'g + 0.39*(g - r) + 0.78*(u - g) - 0.67',
        'B': 'u - 0.8116*(u - g) + 0.1313',
        'V': 'g - 0.5784*(g - r) - 0.0038',
        'R': 'r - 0.2936*(r - i) - 0.1439',
        'I': 'i - 0.378*(i - z) - 0.3974',
        'SII': 'rprime',
        'Halpha': 'rprime',
        'H_alpha': 'rprime',
        'OIII': 'gprime',
        'Hbeta': 'gprime',
        'H_beta': 'gprime',
    }
