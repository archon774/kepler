"""Tile-compressed FITS helpers (RICE / fpack via astropy ``CompImageHDU``).

Single home for the low-level FITS-compression primitives shared by the node
(compress-at-seal), the server pipeline runners, and the backfill job:

* :func:`select_image_hdu` / :func:`select_image_hdu_index` — locate the science
  image HDU, robust to the primary→extension shift that tile compression
  introduces (a compressed file has an *empty* primary and the image in an
  extension). Every reader that used to hardcode ``hdul[0].data`` should route
  through this so it keeps working on both classic and compressed FITS.
* :func:`is_tile_compressed` — detect a tile-compressed file.
* :func:`write_compressed_image_fits` — write an ndarray as a compressed image
  FITS (empty ``PrimaryHDU`` + ``CompImageHDU``).
* :func:`seal_fits_file` — recompress an existing *plain* FITS in place
  (idempotent; a no-op on already-compressed files).

Kept to astropy + numpy only (no skynet-sdk / skynet-db imports) so it sits at
the bottom of the dependency graph and everyone can use it. The compression
*policy* (which codec/quantization per data product) lives one level up in
``skynet_sdk.compression``; callers resolve a spec there and pass its primitive
knobs into the writers here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import numpy as np
from astropy.io import fits

__all__ = [
    "select_image_hdu_index",
    "select_image_hdu",
    "is_tile_compressed",
    "write_compressed_image_fits",
    "seal_fits_file",
]

# astropy `compression_type` strings we support. RICE_1 is lossless on integer
# data; for lossless FLOAT data use GZIP_2 with quantize_level=0.
DEFAULT_COMPRESSION_TYPE = "RICE_1"

_TABLE_XTENSIONS = frozenset({"BINTABLE", "TABLE", "A3DTABLE"})


def _hdu_is_image_2d(hdu: fits.hdu.base._BaseHDU) -> bool:
    """True if this HDU carries a >=2-D image (compressed or not).

    Uses header keywords so it does not force a (possibly large / lazy) data
    load just to classify the HDU.
    """
    if isinstance(hdu, fits.CompImageHDU):
        return True
    header = hdu.header
    if int(header.get("NAXIS", 0) or 0) < 2:
        return False
    # A binary/ASCII table can have NAXIS=2 but is not an image.
    xtension = str(header.get("XTENSION", "") or "").strip().upper()
    return xtension not in _TABLE_XTENSIONS


def select_image_hdu_index(hdulist: fits.HDUList) -> int:
    """Index of the first HDU carrying a >=2-D image.

    Works for classic FITS (image in the primary HDU) and tile-compressed FITS
    (empty primary + ``CompImageHDU`` extension). Raises ``ValueError`` if the
    file has no image HDU.
    """
    for index, hdu in enumerate(hdulist):
        if _hdu_is_image_2d(hdu):
            return index
    raise ValueError("No image HDU with >=2-D data found in FITS file")


def select_image_hdu(hdulist: fits.HDUList) -> fits.hdu.base._BaseHDU:
    """The first HDU carrying a >=2-D image (see :func:`select_image_hdu_index`).

    ``.data`` on the returned HDU transparently decompresses for a
    ``CompImageHDU``.
    """
    return hdulist[select_image_hdu_index(hdulist)]


def is_tile_compressed(hdulist: fits.HDUList) -> bool:
    """True if any HDU in the list is a tile-compressed image."""
    return any(isinstance(hdu, fits.CompImageHDU) for hdu in hdulist)


def write_compressed_image_fits(
    path: str | os.PathLike,
    data: np.ndarray,
    header: fits.Header | None = None,
    *,
    compression_type: str = DEFAULT_COMPRESSION_TYPE,
    quantize_level: float = 0.0,
    tile_shape: Sequence[int] | None = None,
    overwrite: bool = True,
    **extra_kwargs,
) -> None:
    """Write ``data`` as a tile-compressed image FITS.

    Produces the standard fpack layout: an empty ``PrimaryHDU`` followed by a
    ``CompImageHDU`` holding the image. The result is a *valid* ``.fits`` that
    any FITS reader opens transparently — no ``.gz`` extension, no user-side
    decompression.

    Codec / quantization guidance (set by the policy layer, passed here as
    primitives):

    * integer data → ``RICE_1`` (lossless regardless of ``quantize_level``);
    * lossless float → ``GZIP_2`` with ``quantize_level=0``;
    * lossy float → ``RICE_1`` with ``quantize_level>0`` (fpack default q=4).

    ``extra_kwargs`` passes through astropy knobs such as ``quantize_method``,
    ``hcomp_scale`` for HCOMPRESS, etc.
    """
    kwargs: dict = {
        "compression_type": compression_type,
        "quantize_level": quantize_level,
    }
    if tile_shape is not None:
        kwargs["tile_shape"] = tuple(tile_shape)
    kwargs.update(extra_kwargs)

    comp = fits.CompImageHDU(data=data, header=header, **kwargs)
    fits.HDUList([fits.PrimaryHDU(), comp]).writeto(path, overwrite=overwrite)


def seal_fits_file(
    src_path: str | os.PathLike,
    dst_path: str | os.PathLike | None = None,
    *,
    compression_type: str = DEFAULT_COMPRESSION_TYPE,
    quantize_level: float = 0.0,
    tile_shape: Sequence[int] | None = None,
) -> bool:
    """Recompress a plain FITS at ``src_path`` into a tile-compressed file.

    The image HDU becomes a ``CompImageHDU`` behind an empty primary; any other
    (non-empty, non-image) HDUs are preserved verbatim. Writes atomically via a
    temp file + ``os.replace`` (matching the node's atomic-write convention).

    Idempotent: if the source is already tile-compressed, returns ``False`` and
    does nothing — safe for backfill re-runs and node retries. Returns ``True``
    when it compressed the file.
    """
    src = Path(src_path)
    dst = Path(dst_path) if dst_path is not None else src

    with fits.open(src, memmap=False) as hdul:
        if is_tile_compressed(hdul):
            return False
        image_index = select_image_hdu_index(hdul)

        out = fits.HDUList([fits.PrimaryHDU()])
        for index, hdu in enumerate(hdul):
            if index == image_index:
                kwargs: dict = {
                    "compression_type": compression_type,
                    "quantize_level": quantize_level,
                }
                if tile_shape is not None:
                    kwargs["tile_shape"] = tuple(tile_shape)
                out.append(
                    fits.CompImageHDU(
                        data=hdu.data, header=hdu.header.copy(), **kwargs
                    )
                )
            elif isinstance(hdu, fits.PrimaryHDU) and hdu.data is None:
                # Drop the original empty primary; we already have one.
                continue
            else:
                out.append(hdu.copy())

        tmp = dst.with_name(dst.name + ".sealtmp")
        out.writeto(tmp, overwrite=True)

    os.replace(tmp, dst)
    return True
