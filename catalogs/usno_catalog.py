"""
Kepler: USNO-B1.0 catalog accessed via VizieR
"""

from typing import List as TList, Union

from astropy.table import Table

from .schemas import CatalogSource, Mag
# EXTRACTED: was `from .vizier_catalogs import VizierCatalog`. In Kepler the
# VizieR backend lives in ``query/vizier.py`` and is mixed onto this class at
# import time by ``query/binding.py``, so this module stays declaration-only and
# carries no network dependency.
from .catalog import Catalog


__all__ = ['USNOB1Catalog']


class USNOB1Catalog(Catalog):
    """
    USNO-B1.0/VizieR catalog plugin
    """
    name = 'USNOB1'
    display_name = 'U.S. Naval Observatory Catalog of Astrometric Standards ' \
        '(USNO-B1.0)'
    num_sources = 1045175762
    vizier_catalog = 'I/284'
    row_limit = 5000
    mags = {
        'B': ['Bmag'], 'R': ['Rmag'], 'B1': ['B1mag'], 'B2': ['B2mag'], 'R1': ['R1mag'],
        'R2': ['R2mag'],
    }
    col_mapping = {
        'id': 'USNO-B1.0', 'ra_hours': 'RAJ2000/15', 'dec_degs': 'DEJ2000',
    }
    sort = ['+B1mag']

    # Photometric transform, preserved verbatim. ``super().table_to_sources``
    # resolves to the bound VizieR row mapper in ``query/vizier.py``; this
    # method then synthesizes standard B and R by averaging the two survey
    # epochs, falling back to whichever single epoch is present.
    def table_to_sources(self, table: Union[list, Table]) \
            -> TList[CatalogSource]:
        """
        Return a list of CatalogSource objects from an Astropy table

        Adds the standard B and R magnitudes based on B1, B2 and R1, R2.

        :param table: table of sources returned by astroquery

        :return: list of catalog objects
        """
        sources = super(USNOB1Catalog, self).table_to_sources(table)

        for source in sources:
            mags = source.mags
            for m in ('B', 'R'):
                m1, m2 = m + '1', m + '2'
                try:
                    mags[m] = Mag(value=(mags[m1].value + mags[m2].value)/2)
                except (KeyError, ValueError):
                    try:
                        mags[m] = mags[m1]
                    except KeyError:
                        try:
                            mags[m] = mags[m2]
                        except KeyError:
                            pass

        return sources
