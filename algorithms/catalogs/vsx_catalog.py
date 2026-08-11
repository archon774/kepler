"""
Kepler: AAVSO International Variable Star indeX (VSX) interface
"""

from typing import List as TList, Union

from astropy.table import Table

from .schemas import CatalogSource
# EXTRACTED: was `from .vizier_catalogs import VizierCatalog`. In Kepler the
# VizieR backend lives in ``query/vizier.py`` and is mixed onto this class at
# import time by ``query/binding.py``, so this module stays declaration-only and
# carries no network dependency.
from .catalog import Catalog


__all__ = ['VSXCatalog']


class VSXCatalog(Catalog):
    """
    VSX/VizieR catalog plugin
    """
    name = 'VSX'
    display_name = 'AAVSO International Variable Star Index'
    num_sources = 2115593
    vizier_catalog = 'B/vsx/vsx'
    mags = {
        # Johnson broad-band
        'U': '', 'B': '', 'V': '', 'R': '', 'I': '',
        # Johnson infra-red (1.2, 1.6, 2.2, 3.5, 5µm)
        'J': '', 'H': '', 'K': '', 'L': '', 'M': '',
        # Cousins' red and infra-red
        'Rc': '', 'Ic': '',
        # Stroemgren intermediate-band
        'Su': '', 'Sv': '', 'Sb': '', 'Sy': '',
        # Sloan (SDSS)
        'uprime': '', 'gprime': '', 'rprime': '', 'iprime': '', 'zprime': '',
        # photographic blue (pg, bj) visual (pv), red (rf)
        'pg': '', 'pv': '', 'bj': '', 'rf': '',
        # white (clear); R or V used for comparison star.
        'w': '', 'C': '', 'CR': '', 'CV': '',
        # ROTSE-I (450-1000nm)
        'R1': '',
        # Hipparcos and Tycho (Cat. I/239)
        'Hp': '', 'T': '',
        # near-UV (Galex)
        'NUV': '',
        # STEREO mission filter (essentially 600-800nm)
        'H1A': '', 'H1B': '',
    }
    _mag_mapping = {  # VSX n_max band code -> Kepler band name
        'u': 'Su', 'v': 'Sv', 'b': 'Sb', 'y': 'Sy',
        "u'": 'uprime', "g'": 'gprime', "r'": 'rprime', "i'": 'iprime',
        "z'": 'zprime',
    }
    extra_cols = [
        'OID', 'Name', 'V', 'Type', 'max', 'n_max', 'f_min', 'min', 'Period',
    ]

    # Preserved verbatim. Unlike the Landolt and USNO overrides this one does
    # not call ``super()``, so it works on any VizieR-shaped rows without a
    # bound backend. Field calibration uses VSX only for positional
    # variable-star rejection (``fieldcal.field_cal._filter_variable_stars``);
    # the inline notes below record two defects whose regression would silently
    # disable that rejection rather than raise.
    def table_to_sources(self, table: Union[list, Table]) \
            -> TList[CatalogSource]:
        """
        Return a list of :class:`CatalogSource` objects from an Astropy table

        Converts color indices to magnitudes.

        :param table: table of sources returned by astroquery

        :return: list of catalog objects
        """
        sources = []
        for row in table:
            if row['V'] not in (0, 1):
                # Skip constant/non-existing/duplicates
                continue
            source = CatalogSource(
                catalog_name=self.name,
                # OID is an integer in the VizieR table, but CatalogSource.id is
                # typed as a string. Passing the raw int through the constructor
                # raises a pydantic validation error which _filter_variable_stars
                # swallows, silently disabling variable-star filtering. Coerce to
                # str so the VSX query succeeds and variables are excluded.
                id=str(row['OID']),
                name=row['Name'],
                type=row['Type'],
                mag=row['max'] or row['min'] or None,
                amplitude=row['min'] if row['f_min'] == '('
                else row['min'] - row['max'] or None,
                period=row['Period'] or None,
                ra_hours=row['RAJ2000']/15,
                dec_degs=row['DEJ2000'],
            )

            # Map mag to specific passband. CatalogSource (pydantic) has no
            # arbitrary passband fields (e.g. "G"); assigning one raises. VSX is
            # used only for positional variable-star proximity checks, so the
            # passband value is not needed — guard the assignment so an
            # unsupported band does not crash the query (and thereby silently
            # disable variable-star filtering).
            try:
                setattr(source, self._mag_mapping.get(row['n_max'], row['n_max']),
                        row['max'])
            except (ValueError, AttributeError):
                pass

            sources.append(source)

        return sources
