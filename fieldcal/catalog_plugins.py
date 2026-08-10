"""Afterglow-parity catalog filter-lookup registry (``CATALOG_OPTIONS``).

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/common/catalog_plugins/
  * ``catalog.py``            (45 lines)  -> ``Catalog`` base, verbatim
  * ``apass_catalog.py``      (37 lines)  -> ``APASSCatalog`` metadata, verbatim
  * ``panstarrs_catalog.py``  (43 lines)  -> ``PanSTARRSCatalog`` metadata, verbatim
  * ``__init__.py``           (49 lines)  -> ``NARROWBAND_FILTER_LOOKUP`` + ``CATALOG_OPTIONS``, verbatim

WHY THIS EXISTS SEPARATELY FROM ``fieldcal/catalogs/``:
Skynet carries *two* catalog plugin registries and field calibration reads both:

  * ``runners/observation_asset_processing/optical_data_processing/catalogs``
    exposes ``CATALOGS`` — the full 11-catalog registry used for querying and
    for ``catalog_supports_filter`` / ``_catalog_filter_lookup``;
  * ``runners/common/catalog_plugins`` exposes ``CATALOG_OPTIONS`` — a
    2-catalog (APASS, PanSTARRS) Afterglow-parity subset read *only* by
    ``resolve_ref_mag_for_filter._get_catalog_filter_lookup``.

The two are not identical, and the difference is load-bearing: ``CATALOG_OPTIONS``
carries the ``NARROWBAND_FILTER_LOOKUP`` aliases ``H_alpha`` / ``H_beta``, which
``CATALOGS['APASS']`` does not.  ``resolve_ref_mag_for_filter`` starts from the
``CATALOG_OPTIONS`` lookup and overlays the caller-supplied lookup on top, so
collapsing the two registries would silently change which reference band a
narrowband image resolves to.  Both are therefore reproduced as-is.

SEVERED: the per-catalog classes originally subclassed ``VizierCatalog``
(astroquery/VizieR network backend).  Only the metadata is needed here.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .schemas import CatalogSource

__all__ = ["CATALOG_OPTIONS", "Catalog", "NARROWBAND_FILTER_LOOKUP"]


class Catalog:
    """
    Base class for catalog plugins.
    Override query_* methods in subclasses.
    """
    # For union-discriminated polymorphism later if desired:
    name: Optional[str] = None
    display_name: Optional[str] = None
    num_sources: Optional[int] = None
    mags: Dict[str, List[str]]
    filter_lookup: Dict[str, str]

    def __init__(self, filter_lookup: Optional[Dict[str, str]] = None):
        # NOTE (preserved verbatim): this mutates the *class-level* dict in
        # place, unlike the sibling registry in ``fieldcal/catalogs/catalog.py``
        # which rebinds an instance-level copy.  Effective merged content is the
        # same; the aliasing difference is preserved rather than "fixed".
        if filter_lookup:
            self.filter_lookup.update(filter_lookup)


    def query_objects(self, names: List[str]) -> List[CatalogSource]:
        raise NotImplementedError("query_objects not implemented")

    def query_box(
        self,
        ra_hours: float,
        dec_degs: float,
        width_arcmins: float,
        height_arcmins: Optional[float] = None,
        constraints: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogSource]:
        # Default implementation may rely on query_circ in concrete subclasses
        raise NotImplementedError("query_box not implemented")

    def query_circ(
        self,
        ra_hours: float,
        dec_degs: float,
        radius_arcmins: float,
        constraints: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogSource]:
        raise NotImplementedError("query_circ not implemented")


# EXTRACTED: was `class APASSCatalog(VizierCatalog)` in
# runners/common/catalog_plugins/apass_catalog.py.  Base changed to `Catalog`;
# the VizieR query backend (`vizier_catalog`, `col_mapping`, `row_limit`,
# `sort`) is retained as inert metadata for provenance.
class APASSCatalog(Catalog):
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


# EXTRACTED: was `class PanSTARRSCatalog(VizierCatalog)` in
# runners/common/catalog_plugins/panstarrs_catalog.py.  Base changed to
# `Catalog`; VizieR backend attributes kept as inert metadata.
class PanSTARRSCatalog(Catalog):
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
