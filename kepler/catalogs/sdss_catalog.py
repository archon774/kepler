"""
Kepler: SDSS catalog
"""

# EXTRACTED: was `from .vizier_catalogs import VizierCatalog`. In Kepler the
# VizieR backend lives in ``query/vizier.py`` and is mixed onto this class at
# import time by ``query/binding.py``, so this module stays declaration-only and
# carries no network dependency.
from .catalog import Catalog


__all__ = ['SDSSCatalog']


class SDSSCatalog(Catalog):
    """SDSS catalog plugin.

    SDSS is the one catalog Kepler does not reach through VizieR: it is served
    by SkyServer's SQL endpoint, so its backend hand-writes SQL rather than
    building a VizieR column list. That backend — a ``astroquery.sdss.SDSSClass``
    subclass plus the ``query_objects`` / ``query_box`` / ``query_circ``
    overrides driving it — lives in ``query/sdss.py``. Everything below is the
    declaration it operates on.

    Note ``col_mapping`` here names SkyServer columns (``ra``, ``dec``,
    ``objID``), not VizieR ones, and ``vizier_catalog`` is deliberately absent.
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
