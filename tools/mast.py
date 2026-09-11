"""Kepler: MAST archive search and product retrieval.

The old code sliced ``obs_table[:5]`` and ``data_products[:15]`` -- arbitrary
caps, not service limits. This tool removes both: ``query_object`` and
``get_product_list`` are already unpaged for one object, and
``get_unique_product_list`` de-duplicates rather than truncating.

Confirmed live against the installed astroquery (0.4.11):
``get_product_list`` needs the ``obsid`` column (MAST Product Group ID), not
``obs_id`` (Observation ID) -- "inputting obs_id values will result in an
error," per its own docstring. Passing the query result table straight
through (as this tool does) sidesteps that gotcha entirely; it only bites a
caller who tries to rebuild a product query from ``obs_id`` values by hand.

Also confirmed live, and the reason ``max_observations`` exists: Cas A alone
matches 1436 observations within the default 12-arcmin radius, and
``get_product_list`` on all of them returns 121,515 products after roughly
90 seconds. An unbounded default would make the tool unusable for exactly
the kind of well-studied object callers ask about most.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from astroquery.exceptions import InvalidQueryError
from astroquery.mast import Observations

from tools import artifacts
from tools import config
from tools.config import DEFAULT_MAX_OBSERVATIONS, PREVIEW_ROWS
from tools.models import ToolResult, coerce_optional_int

__all__ = ["search_mast"]


def search_mast(
    name: str,
    *,
    radius_arcmin: float = 12.0,
    max_observations: Union[int, str, None] = DEFAULT_MAX_OBSERVATIONS,
    mrp_only: bool = False,
    extension: Optional[Union[str, list[str]]] = None,
    product_type: Optional[Union[str, list[str]]] = None,
    download: bool = False,
) -> ToolResult:
    """Search MAST for observations of ``name`` and list their data products.

    The full observation table is always fetched and written to disk -- that
    step is cheap even for thousands of matches. Products are the slow part,
    so ``max_observations`` bounds how many *matched* observations get a
    product-list lookup (never how many are matched, which is always
    reported in full, with a warning rather than a silent drop when it
    exceeds the cap). Pass ``max_observations=None`` to fetch products for
    every matched observation with no cap -- do this when the caller actually
    asked for "all"/"every"/"complete" data; expect it to take a while for a
    heavily-observed object (confirmed live: ~90s for Cas A's 121,515
    products). ``mrp_only``/``extension``/``product_type`` narrow the product
    list via ``filter_products`` (e.g. ``product_type="SCIENCE"``) rather than
    downloading indiscriminately. ``download=True`` fetches the filtered
    products into the archive download directory under ``data/``, which the
    local frame registry (``tools.optical``) also searches, so a downloaded
    frame is immediately resolvable by name or path for the image tools.
    Bear in mind that one ``list_optical_frames`` call reads a bounded number
    of frames, so a bulk download is better narrowed with the product filters
    above than sorted out afterwards.
    """
    if not name or not name.strip():
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": "name must not be blank"}],
        )

    try:
        max_observations = coerce_optional_int(max_observations)
    except ValueError as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "invalid_input", "message": f"max_observations: {exc}"}],
        )

    try:
        obs_table = Observations.query_object(name, radius=f"{radius_arcmin} arcmin")
    except Exception as exc:
        return ToolResult(
            status="error",
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    if obs_table is None or len(obs_table) == 0:
        return ToolResult(status="not_found", count=0)

    obs_artifact = artifacts.write_table(obs_table, f"mast_{name}_observations", subdir="mast")

    warnings: list[str] = []
    obs_for_products = obs_table
    if max_observations is not None and len(obs_table) > max_observations:
        obs_for_products = obs_table[:max_observations]
        warnings.append(
            f"matched {len(obs_table)} observations, fetched products for "
            f"{max_observations}; raise max_observations, or set it to JSON "
            "null for no cap, for the rest"
        )

    try:
        # get_unique_product_list calls get_product_list internally --
        # confirmed live that chaining them (calling get_unique_product_list
        # on an already-fetched products table) raises KeyError('target_name')
        # because it re-fetches from what it wrongly treats as an
        # observations table. Call it directly on the observations instead.
        products = Observations.get_unique_product_list(obs_for_products)
    except InvalidQueryError:
        # Confirmed live: a batch of observations with zero associated
        # products raises this rather than returning an empty table. The
        # observations themselves are real, so this is a partial result, not
        # a provider fault.
        return ToolResult(
            status="partial",
            count=len(obs_table),
            preview=artifacts.preview_rows(obs_table, PREVIEW_ROWS),
            columns=[str(c) for c in obs_table.colnames],
            artifacts=[obs_artifact],
            warnings=warnings + ["no data products found for the fetched observations"],
        )
    except Exception as exc:
        return ToolResult(
            status="error",
            count=len(obs_table),
            artifacts=[obs_artifact],
            errors=[{"code": "provider_unavailable", "message": str(exc)}],
        )

    filters = {}
    if extension is not None:
        filters["extension"] = extension
    if product_type is not None:
        filters["productType"] = product_type
    if mrp_only or filters:
        products = Observations.filter_products(products, mrp_only=mrp_only, **filters)

    products_artifact = artifacts.write_table(products, f"mast_{name}_products", subdir="mast")

    if download:
        if len(products) == 0:
            warnings.append("no products matched the given filters; nothing downloaded")
        else:
            # Read through the module, not a from-import bound at import
            # time: tools.optical resolves its download root the same way, and
            # if these two disagree the frame registry searches one directory
            # while the download lands in another -- which is BL-11 again.
            download_dir = config.FITS_DOWNLOAD_DIR
            download_dir.mkdir(parents=True, exist_ok=True)
            manifest = Observations.download_products(
                products, download_dir=str(download_dir)
            )
            local_paths = (
                list(manifest["Local Path"]) if "Local Path" in manifest.colnames else []
            )
            # Name the directories the files actually landed in. astroquery
            # nests them under mastDownload/<mission>/<obs_id>/, and once a
            # bulk download outgrows list_optical_frames' cap, directory=
            # naming one of these leaves is how a caller reaches a specific
            # product -- nothing else reports the leaf.
            leaves = sorted({str(Path(str(p)).parent) for p in local_paths if p})
            shown = ", ".join(leaves[:5]) + (
                f" (+{len(leaves) - 5} more)" if len(leaves) > 5 else ""
            )
            warnings.append(
                f"downloaded {len(local_paths)} file(s) to {download_dir}"
                + (f" under: {shown}" if leaves else "")
                + "; they now resolve through the local frame registry -- call "
                "list_optical_frames or resolve_optical_frame to pick one up, "
                "then the image tools take it by path. A listing reads a bounded "
                "number of frames, so after a large download pass directory= "
                "naming one of the directories above"
            )

    return ToolResult(
        status="ok" if len(obs_for_products) == len(obs_table) else "partial",
        count=len(obs_table),
        preview=artifacts.preview_rows(obs_table, PREVIEW_ROWS),
        columns=[str(c) for c in obs_table.colnames],
        artifacts=[obs_artifact, products_artifact],
        warnings=warnings,
    )
