"""Kepler: environment-backed settings for ``kepler.tools``.

Only what the first tool slice needs -- see ``docs/tool-architecture.md``
section 3 ("simple environment-backed settings helpers only where a first
tool needs them"). Not a general configuration framework.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Where kepler.tools writes full result tables. Already covered by
#: .gitignore's `artifacts/` entry.
ARTIFACT_DIR = Path(os.environ.get("KEPLER_ARTIFACT_DIR", "artifacts"))

#: Where kepler.tools.mast writes downloaded FITS products -- the directory
#: name database_tools.py used, already covered by .gitignore's
#: `fits_downloads/` entry. Kept separate from ARTIFACT_DIR: binary downloads
#: and written-out result tables are different kinds of output.
FITS_DOWNLOAD_DIR = Path(os.environ.get("KEPLER_FITS_DOWNLOAD_DIR", "fits_downloads"))

#: Rows shown inline in a ToolResult.preview. Never the row cap on the
#: underlying query -- that stays unbounded by default.
PREVIEW_ROWS = int(os.environ.get("KEPLER_PREVIEW_ROWS", "10"))

#: Ceiling on how many VizieR catalogs one broad category/keyword search will
#: actually fetch data from. Does not cap how many are *matched* -- that count
#: is always reported in full, never silently dropped. Raise via
#: KEPLER_MAX_CATALOGS or search_vizier's `max_catalogs` argument.
DEFAULT_MAX_CATALOGS = int(os.environ.get("KEPLER_MAX_CATALOGS", "20"))

#: Ceiling on how many MAST observations get a product-list lookup in one
#: search_mast call. Confirmed live: a heavily-observed target like Cas A
#: matches 1436 observations and 121,515 products, ~90s just for the product
#: list -- an unbounded default would make the tool unusable for exactly the
#: kind of well-studied object callers ask about most. Does not cap how many
#: observations are *matched* -- the full observation table is always
#: written. Raise via KEPLER_MAX_OBSERVATIONS or search_mast's
#: `max_observations` argument.
DEFAULT_MAX_OBSERVATIONS = int(os.environ.get("KEPLER_MAX_OBSERVATIONS", "25"))

#: OPAL username for CASDA staging/download (see kepler.tools.casda). Not a
#: secret by itself -- OPAL passwords come from the system keyring or an
#: interactive prompt, never from an environment variable.
CASDA_OPAL_USERNAME = os.environ.get("CASDA_OPAL_USERNAME")
