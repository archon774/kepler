"""Kepler: CASDA (CSIRO ASKAP Science Data Archive) search.

CASDA serves ASKAP continuum images, spectral-line/polarization cubes,
source catalogues, spectra, and visibilities -- a radio archive distinct
from any VizieR-hosted survey.

**Honest caveat, confirmed live:** ASKAP is a Southern Hemisphere instrument.
Cas A (declination +58 deg) returns zero CASDA results -- confirmed against
the real service, not assumed from its footprint. A southern target (tested
near the SMC, declination -73 deg) returns thousands. This tool is for
southern-sky radio targets generally, not an additional source for Cas A.

Confirmed live against the installed astroquery (0.4.11): plain
``query_region`` needs no authentication; only staging/download
(``stage_data``) does, via OPAL credentials (``Casda.login``, password from
the system keyring or an interactive prompt). A tool function shouldn't block
on an interactive password prompt, so ``download=True`` without
``CASDA_OPAL_USERNAME`` configured (``tools.config``) returns
``provider_unavailable`` rather than hanging.
"""

from __future__ import annotations

from typing import Optional, Union

import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.casda import Casda

from tools import artifacts
from tools.config import CASDA_OPAL_USERNAME, FITS_DOWNLOAD_DIR, PREVIEW_ROWS
from tools.models import ToolResult
from tools.resolve import resolve_target_coords

__all__ = ["search_casda"]


def search_casda(
    target: Optional[str] = None,
    *,
    ra_deg: Optional[float] = None,
    dec_deg: Optional[float] = None,
    radius_arcmin: float = 2.0,
    dataproduct_type: Optional[Union[str, list[str]]] = None,
    released_only: bool = True,
    download: bool = False,
) -> ToolResult:
    """Search CASDA for ASKAP data products around a target.

    Unlike VizieR/NED/MAST, CASDA's ``query_region`` does not resolve a name
    itself -- pass ``target`` to resolve it via SIMBAD first, or pass
    ``ra_deg``/``dec_deg`` directly. ``released_only=True`` (default) drops
    non-public data via ``filter_out_unreleased``. ``dataproduct_type``
    narrows by CASDA's own vocabulary (``"image"``, ``"cube"``,
    ``"catalogue"``, ``"spectrum"``, ``"visibility"``).
    """
    if target is None and (ra_deg is None or dec_deg is None):
        return ToolResult(
            status="error",
            errors=[
                {
                    "code": "invalid_input",
                    "message": "either target or both ra_deg and dec_deg are required",
                }
            ],
        )

    if target is not None and ra_deg is None:
        resolved = resolve_target_coords(target)
        if resolved is None:
            return ToolResult(status="not_found", count=0)
        ra_deg, dec_deg = resolved.ra_deg, resolved.dec_deg

    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)

    casda = Casda()
    try:
        table = casda.query_region(coord, radius=radius_arcmin * u.arcmin)
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if table is None or len(table) == 0:
        return ToolResult(status="not_found", count=0)

    if released_only:
        table = casda.filter_out_unreleased(table)
        if len(table) == 0:
            return ToolResult(status="not_found", count=0)

    if dataproduct_type is not None:
        wanted = {dataproduct_type} if isinstance(dataproduct_type, str) else set(dataproduct_type)
        table = table[[v in wanted for v in table["dataproduct_type"]]]
        if len(table) == 0:
            return ToolResult(status="not_found", count=0)

    artifact = artifacts.write_table(
        table, f"casda_{target or f'{ra_deg}_{dec_deg}'}", subdir="casda"
    )
    warnings: list[str] = []

    if download:
        if not CASDA_OPAL_USERNAME:
            return ToolResult(
                status="partial",
                count=len(table),
                preview=artifacts.preview_rows(table, PREVIEW_ROWS),
                columns=[str(c) for c in table.colnames],
                artifact=artifact,
                errors=[
                    {
                        "code": "provider_unavailable",
                        "message": "download=True requires CASDA_OPAL_USERNAME to be set; "
                        "staging needs OPAL credentials and this tool will not "
                        "prompt interactively for a password",
                    }
                ],
            )
        casda.login(username=CASDA_OPAL_USERNAME)
        url_list = casda.stage_data(table)
        # The literal "fits_downloads" this used to pass ignored
        # KEPLER_FITS_DOWNLOAD_DIR, so a configured operator got downloads in
        # one directory and a frame registry searching another. Same directory
        # as tools.mast now, which is the one tools.optical searches.
        FITS_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        casda.download_files(url_list, savedir=str(FITS_DOWNLOAD_DIR))
        warnings.append(
            f"staged and downloaded {len(url_list)} file(s) to {FITS_DOWNLOAD_DIR}; "
            "they now resolve through the local frame registry -- call "
            "list_optical_frames or resolve_optical_frame to pick one up, "
            "then the image tools take it by path"
        )

    return ToolResult(
        status="ok",
        count=len(table),
        preview=artifacts.preview_rows(table, PREVIEW_ROWS),
        columns=[str(c) for c in table.colnames],
        artifact=artifact,
        warnings=warnings,
    )
