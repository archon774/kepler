"""Catalog plugin registry for optical data processing.

EXTRACTED FROM:
skynet/packages/py/skynet-db/skynet_db/runners/observation_asset_processing/
optical_data_processing/catalogs/__init__.py (87 lines).  The ``_OCL_TO_V``
mapping and every per-catalog ``filter_lookup`` colour transform below are
verbatim — they are part of the calibration's numeric behaviour.

SCOPE NOTE: this package is METADATA ONLY.  Each plugin keeps its band table
(``mags``) and its filter/colour transforms (``filter_lookup``), which are what
``catalog_query.catalog_supports_filter`` and
``ref_mag.resolve_ref_mag_for_filter`` read.  The VizieR/SDSS network query
backends were severed (see EXTRACTION.md); ``query_box`` / ``query_circ`` /
``query_objects`` therefore raise ``NotImplementedError`` until Kepler/catalogs/
supplies real backends.  Filter-aware catalog selection, reference-magnitude
resolution and the whole zero-point solve work without them, provided catalog
sources are passed in via ``catalog_sources`` / ``detected_sources``.
"""

from .apass_catalog import APASSCatalog
from .catalog import Catalog
from .landolt_catalog import LandoltCatalog
from .panstarrs_catalog import PanSTARRSCatalog
from .sdss_catalog import SDSSCatalog
from .skymapper_catalog import SkyMapperCatalog
from .stetson_globs_catalog import StetsonGlobsCatalog
from .twomass_catalog import TwoMASSCatalog
from .tycho_catalog import Tycho2Catalog
from .ucac_catalog import UCAC5Catalog
from .usno_catalog import USNOB1Catalog
from .vsx_catalog import VSXCatalog

__all__ = ["CATALOGS", "Catalog"]

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
