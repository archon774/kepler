"""Kepler: the reference-magnitude catalog subset (``CATALOG_OPTIONS``).

Kepler carries *two* catalog registries and field calibration reads both:

* ``catalogs/__init__.py`` exposes ``CATALOGS`` — all 11 catalogs, used for
  querying and for filter-aware catalog selection;
* this module exposes ``CATALOG_OPTIONS`` — a two-catalog (APASS, PanSTARRS)
  subset read only by ``fieldcal.ref_mag.resolve_ref_mag_for_filter``.

They are not the same, and the difference is load-bearing: ``CATALOG_OPTIONS``
carries the narrowband aliases ``H_alpha`` and ``H_beta``, which
``CATALOGS['APASS']`` does not. ``resolve_ref_mag_for_filter`` starts from the
``CATALOG_OPTIONS`` lookup and overlays the caller-supplied lookup on top, so
collapsing the two registries would silently change which reference band a
narrowband image calibrates against. Both are therefore kept as they are.

The classes below are deliberately separate from the ones in
``apass_catalog.py`` / ``panstarrs_catalog.py``: upstream had two parallel plugin
packages whose APASS and PanSTARRS definitions had drifted apart, and the drift
is exactly what this module exists to preserve.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/common/catalog_plugins/
  * ``catalog.py``            (45 lines)  -> ``Catalog`` base
  * ``apass_catalog.py``      (37 lines)  -> ``APASSCatalog`` metadata, verbatim
  * ``panstarrs_catalog.py``  (43 lines)  -> ``PanSTARRSCatalog`` metadata, verbatim
  * ``__init__.py``           (49 lines)  -> ``NARROWBAND_FILTER_LOOKUP`` +
    ``CATALOG_OPTIONS``, verbatim
"""
from __future__ import annotations

from typing import Dict, Optional

from .catalog import Catalog

__all__ = ["CATALOG_OPTIONS", "NARROWBAND_FILTER_LOOKUP"]


class _MutatingCatalog(Catalog):
    """``Catalog`` with upstream's in-place ``filter_lookup`` merge.

    PRESERVED DIFFERENCE: this registry's base mutated the *class-level*
    ``filter_lookup`` dict in place, where ``catalogs.catalog.Catalog`` rebinds an
    instance-level copy. The merged content ends up the same for the two
    single-instantiation classes below; the aliasing difference is preserved
    rather than "fixed", because these classes are private to this module and
    nothing else observes their class dicts.
    """

    def __init__(self, filter_lookup: Optional[Dict[str, str]] = None):
        if filter_lookup:
            self.filter_lookup.update(filter_lookup)


# NOTE: distinct from ``catalogs.apass_catalog.APASSCatalog`` -- see the module
# docstring. VizieR backend hints are kept as inert metadata; this registry is
# never queried, only read for its ``filter_lookup``.
class APASSCatalog(_MutatingCatalog):
    """
    APASS/VizieR catalog plugin
    """
    name = 'APASS'
    display_name = 'AAVSO Photometric All Sky Survey Data Release 9'
    num_sources = 61176401
    vizier_catalog = 'II/336'
    row_limit = 1000
    mags = {
        'B': ['Bmag', 'e_Bmag'], 'V': ['Vmag', 'e_Vmag'],
        'gprime': ["g'mag", "e_g'mag"], 'rprime': ["r'mag", "e_r'mag"],
        'iprime': ["i'mag", "e_i'mag"],
    }
    col_mapping = {
        'id': 'recno', 'ra_hours': 'RAJ2000/15', 'dec_degs': 'DEJ2000',
    }
    sort = ['+Bmag']
    filter_lookup = {
        # naming
        "g'": 'gprime', "r'": 'rprime', "i'": 'iprime',
        # Jester et al. (2005), Jordi et al. (2005)
        'U': 'B + 0.78*(uprime - gprime) - 0.88',
        # Lupton (2005)
        'R': "rprime - 0.2936*(rprime - iprime) - 0.1439",
        'I': "iprime - 0.3136*(rprime - iprime) - 0.3539",
    }


# NOTE: distinct from ``catalogs.panstarrs_catalog.PanSTARRSCatalog`` -- see the
# module docstring.
class PanSTARRSCatalog(_MutatingCatalog):
    """
    PanSTARRS/VizieR catalog plugin
    """
    name = 'PanSTARRS'
    display_name = 'Pan-STARRS Release 1 Survey Data Release 1'
    num_sources = 1919106885
    vizier_catalog = 'II/349'
    row_limit = 5000
    col_mapping = {
        'id': 'objID', 'ra_hours': 'RAJ2000/15', 'dec_degs': 'DEJ2000',
    }
    mags = {
        'g': ['gmag', 'e_gmag'], 'r': ['rmag', 'e_rmag'],
        'i': ['imag', 'e_imag'], 'z': ['zmag', 'e_zmag'],
        'y': ['ymag', 'e_ymag'],
    }
    sort = ['+rmag']
    filter_lookup = {
        # griz(P1) -> griz(SDSS) as per
        # https://iopscience.iop.org/article/10.1088/0004-637X/750/2/99
        # then the inverse of g'r'i'z' -> griz(SDSS) as per
        # http://classic.sdss.org/dr7/algorithms/jeg_photometric_eq_dr1.html
        # (see also sdss_catalog)
        'gprime': '0.94*(g + 0.013 + 0.145*(g - r) + 0.019*(g - r)**2) + '
        '0.06*(r - 0.001 + 0.004*(g - r) + 0.007*(g - r)**2) + 0.0318',
        'rprime': '0.965*(r - 0.001 + 0.004*(g - r) + 0.007*(g - r)**2) + '
        '0.035*(i - 0.005 + 0.011*(g - r) + 0.010*(g - r)**2) + 0.00735',
        'iprime': '1.041*(i - 0.005 + 0.011*(g - r) + 0.010*(g - r)**2) - '
        '0.041*(r - 0.001 + 0.004*(g - r) + 0.007*(g - r)**2) + 0.00861',
        'zprime': '0.97*(z + 0.013 - 0.039*(g - r) - 0.012*(g - r)**2) + '
        '0.03*(i - 0.005 + 0.011*(g - r) + 0.010*(g - r)**2) - 0.0027',
    }


NARROWBAND_FILTER_LOOKUP = {
    'SII': 'rprime',
    'Halpha': 'rprime',
    'H_alpha': 'rprime',
    'OIII': 'gprime',
    'Hbeta': 'gprime',
    'H_beta': 'gprime',
}

CATALOG_OPTIONS: dict[str, Catalog] = {
    'APASS': APASSCatalog(filter_lookup={
        # naming
        "g'": 'gprime', "r'": 'rprime', "i'": 'iprime',
        'gp': 'gprime', 'rp': 'rprime', 'ip': 'iprime',
        # Jester et al. (2005), Jordi et al. (2005)
        'U': 'B + 0.78*(uprime - gprime) - 0.88',
        # Lupton (2005)
        'R': "rprime - 0.2936*(rprime - iprime) - 0.1439",
        'I': "iprime - 0.3136*(rprime - iprime) - 0.3539",
        # Map astrophotography filters to JC
        'Red': "rprime - 0.2936*(rprime - iprime) - 0.1439",
        'Green': 'V',
        'Blue': 'B',
        **NARROWBAND_FILTER_LOOKUP,
        # Curriculum
        'R+Red': "rprime - 0.2936*(rprime - iprime) - 0.1439", 'R,Red': "rprime - 0.2936*(rprime - iprime) - 0.1439",
        'Red+R': "rprime - 0.2936*(rprime - iprime) - 0.1439", 'Red,R': "rprime - 0.2936*(rprime - iprime) - 0.1439",
        'Green+V': 'V', 'Green,V': 'V',
        'V+Green': 'V', 'V,Green': 'V',
        'Blue+B': 'B', 'Blue,B': 'B',
        'B+Blue': 'B', 'B,Blue': 'B',
    }),
    'PanSTARRS': PanSTARRSCatalog(filter_lookup={
        # naming
        "g'": 'gprime', "r'": 'rprime', "i'": 'iprime', "z'": 'zprime',
        'gp': 'gprime', 'rp': 'rprime', 'ip': 'iprime', 'zp': 'zprime',
        **NARROWBAND_FILTER_LOOKUP,
    }),
}
