"""Kepler: catalog and provider declarations.

This package answers "what does Kepler know about each catalog/provider" —
band tables, colour transforms, VizieR table IDs, row limits, photometric
conversions, and static provider vocabularies. It answers nothing about
*reaching* them: no module here imports ``astroquery``, ``psrqpy``, or opens a
socket. Fetching is ``algorithms.query`` or ``tools.*``'s job.

The package-level registry exports the photometric catalog declarations used
by field calibration and query orchestration. Provider-specific helpers for
database tools live in direct submodules such as ``algorithms.catalogs.ads``,
``algorithms.catalogs.atnf``, and ``algorithms.catalogs.ned``.

Two registries live here, and the difference between them is load-bearing:

``CATALOGS``
    All 11 catalogs, keyed by Kepler catalog name. Read by filter-aware catalog
    selection (``algorithms.query.selection``) and by the query runner.
``CATALOG_OPTIONS``
    A two-catalog (APASS, PanSTARRS) subset in ``catalog_options.py``, read only
    by reference-magnitude resolution. It carries narrowband aliases —
    ``H_alpha``, ``H_beta`` — that ``CATALOGS['APASS']`` does not. Collapsing the
    two would silently change which reference band a narrowband image resolves
    to. See ``catalog_options.py`` for the full reasoning.

EXTRACTED FROM: skynet/packages/py/skynet-db/skynet_db/runners/
observation_asset_processing/optical_data_processing/catalogs/__init__.py
(87 lines). ``_OCL_TO_V`` and every per-catalog ``filter_lookup`` colour
transform below are verbatim — they are numeric calibration behaviour, not
style.
"""

from .apass_catalog import APASSCatalog
from .catalog import Catalog
from .catalog_options import CATALOG_OPTIONS, NARROWBAND_FILTER_LOOKUP
from .landolt_catalog import LandoltCatalog
from .panstarrs_catalog import PanSTARRSCatalog
from .schemas import CatalogMeta, CatalogSource, ICatalogSource, Mag
from .sdss_catalog import SDSSCatalog
from .simbad import SIMBAD_OBJECT_TYPES
from .skymapper_catalog import SkyMapperCatalog
from .stetson_globs_catalog import StetsonGlobsCatalog
from .twomass_catalog import TwoMASSCatalog
from .tycho_catalog import Tycho2Catalog
from .ucac_catalog import UCAC5Catalog
from .usno_catalog import USNOB1Catalog
from .vsx_catalog import VSXCatalog

__all__ = [
    "CATALOGS",
    "CATALOG_OPTIONS",
    "NARROWBAND_FILTER_LOOKUP",
    "SIMBAD_OBJECT_TYPES",
    "Catalog",
    "CatalogMeta",
    "CatalogSource",
    "ICatalogSource",
    "Mag",
    "APASSCatalog",
    "LandoltCatalog",
    "PanSTARRSCatalog",
    "SDSSCatalog",
    "SkyMapperCatalog",
    "StetsonGlobsCatalog",
    "TwoMASSCatalog",
    "Tycho2Catalog",
    "UCAC5Catalog",
    "USNOB1Catalog",
    "VSXCatalog",
]

# Open/Clear/Lum are broadband unfiltered passes; V is the closest standard
# photometric reference band for all V-capable catalogs.
_OCL_TO_V: dict[str, str] = {
    "Open": "V",
    "Clear": "V",
    "Lum": "V",
}

CATALOGS: dict[str, Catalog] = {
    "APASS": APASSCatalog(
        filter_lookup={
            **_OCL_TO_V,
            # naming
            "g'": "gprime",
            "r'": "rprime",
            "i'": "iprime",
            "gp": "gprime",
            "rp": "rprime",
            "ip": "iprime",
            # Jester et al. (2005), Jordi et al. (2005)
            "U": "B + 0.78*(uprime - gprime) - 0.88",
            # Lupton (2005)
            "R": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            "I": "iprime - 0.3136*(rprime - iprime) - 0.3539",
            # Map astrophotography filters to JC
            "Red": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            "Green": "V",
            "Blue": "B",
            "Halpha": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            'OIII': 'gprime',
            "SII": "rprime",
            "Hbeta": 'gprime',
            # Curriculum
            "R+Red": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            "R,Red": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            "Red+R": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            "Red,R": "rprime - 0.2936*(rprime - iprime) - 0.1439",
            "Green+V": "V",
            "Green,V": "V",
            "V+Green": "V",
            "V,Green": "V",
            "Blue+B": "B",
            "Blue,B": "B",
            "B+Blue": "B",
            "B,Blue": "B",
        }
    ),
    "PanSTARRS": PanSTARRSCatalog(
        filter_lookup={
            # naming
            "g'": "gprime",
            "r'": "rprime",
            "i'": "iprime",
            "z'": "zprime",
            "gp": "gprime",
            "rp": "rprime",
            "ip": "iprime",
            "zp": "zprime",
        }
    ),
    "SDSS": SDSSCatalog(),
    "SkyMapper": SkyMapperCatalog(),
    "Landolt": LandoltCatalog(filter_lookup=_OCL_TO_V),
    "Stetson": StetsonGlobsCatalog(filter_lookup=_OCL_TO_V),
    "2MASS": TwoMASSCatalog(),
    "Tycho": Tycho2Catalog(filter_lookup=_OCL_TO_V),
    "UCAC": UCAC5Catalog(),
    "USNO": USNOB1Catalog(),
    "VSX": VSXCatalog(),
}
