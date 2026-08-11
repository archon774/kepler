"""Sky and image geometry for catalog queries.

Everything here answers one of three questions: what region should we ask a
catalog for, which of the rows it sent back actually fall inside the region we
wanted, and are any of them the same source twice.

The functions are pure — no network, no catalog objects beyond reading
``ra_hours`` / ``dec_degs`` / ``x`` / ``y`` off them — which is what makes the
query paths testable without a provider.

EXTRACTED FROM:

* ``afterglow-core/afterglow_core/models/catalogs.py::Catalog.query_box``
  (lines 108-170) -> ``clip_sources_to_box``.
* ``afterglow-core/afterglow_core/resources/job_plugins/catalog_query_job.py``
  (lines 140-215) -> ``boxes_from_wcs``, ``combined_bounding_box``.
* ``skynet/.../optical_data_processing/catalog_query.py`` (lines 194-249)
  -> ``wcs_array_shape``, ``boxes_from_wcs``, ``remove_duplicate_sources``,
  ``clip_sources_to_wcs``.
* ``skynet/packages/py/skynet-db/skynet_db/runners/utils.py`` (lines 800-872)
  -> ``infer_image_shape``, ``image_boxes_from_wcs``.

The two upstream box-from-WCS implementations differ and both are kept — see
``boxes_from_wcs`` versus ``image_boxes_from_wcs``.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Sequence

import numpy as np
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

__all__ = [
    "clip_sources_to_box",
    "wcs_array_shape",
    "infer_image_shape",
    "boxes_from_wcs",
    "image_boxes_from_wcs",
    "combined_bounding_box",
    "normalize_wcs_list",
    "remove_duplicate_sources",
    "clip_sources_to_wcs",
]

logger = logging.getLogger(__name__)


def clip_sources_to_box(
    sources: list,
    ra_hours: float,
    dec_degs: float,
    width_arcmins: float,
    height_arcmins: float,
) -> list:
    """Keep only sources inside a rectangular sky region.

    Used when a provider can only answer circular queries: ask for the
    circumscribing circle, then clip. The RA half-width is *not* simply
    ``width/2/cos(dec)`` — that overshoots near the poles. The correct bound is

        Δra = arcsin(sin(width/2) / cos(dec))

    which is the tangent-meridian result from
    http://janmatuschek.de/LatitudeLongitudeBoundingCoordinates.

    Four cases follow, and all four are load-bearing near the poles and the RA
    seam: a pole inside the region means every RA qualifies, and a region
    straddling RA=0 or RA=24 splits into two disjoint RA ranges.

    Preserved verbatim, including that a region enclosing a pole is clipped in
    declination only.
    """
    h = height_arcmins / 120
    dec_min, dec_max = dec_degs - h, dec_degs + h

    if dec_min < -90:
        # South Pole in FOV, use the whole RA range
        return [s for s in sources if s.dec_degs <= dec_max]

    if dec_max > 90:
        # North Pole in FOV, use the whole RA range
        return [s for s in sources if s.dec_degs >= dec_min]

    dra = np.rad2deg(
        np.arcsin(
            np.sin(np.deg2rad(width_arcmins / 120)) / np.cos(np.deg2rad(dec_degs))
        )
    ) / 15
    ra_min, ra_max = ra_hours - dra, ra_hours + dra

    if ra_max >= ra_min + 24:
        # RA spans the whole 24h range
        return [s for s in sources if dec_min <= s.dec_degs <= dec_max]

    if ra_min < 0:
        # RA range encloses RA=0 => two separate RA ranges:
        # ra_min + 24 <= ra <= 24 and 0 <= ra <= ra_max
        return [
            s for s in sources
            if (s.ra_hours >= ra_min + 24 or s.ra_hours <= ra_max)
            and dec_min <= s.dec_degs <= dec_max
        ]

    if ra_max > 24:
        # RA range encloses RA=24 => two separate RA ranges:
        # ra_min <= ra <= 24 and 0 <= ra <= ra_max - 24
        return [
            s for s in sources
            if (s.ra_hours >= ra_min or s.ra_hours <= ra_max - 24)
            and dec_min <= s.dec_degs <= dec_max
        ]

    # RA range fully within [0, 24)
    return [
        s for s in sources
        if ra_min <= s.ra_hours <= ra_max and dec_min <= s.dec_degs <= dec_max
    ]


def wcs_array_shape(wcs: WCS) -> tuple[int, int]:
    """Return ``(height, width)`` from a WCS, requiring ``array_shape``.

    Strict by design: the catalog query path treats a WCS with no shape as a
    caller error, because guessing a footprint produces a plausible-looking but
    wrong query region. ``infer_image_shape`` is the lenient variant.
    """
    shape = getattr(wcs, "array_shape", None)
    if not shape:
        raise ValueError("WCS array_shape is required for catalog query")
    height, width = shape
    return int(height), int(width)


def infer_image_shape(
    wcs: WCS,
    shape: Optional[tuple[int, int]] = None,
    header=None,
    data: Optional[np.ndarray] = None,
) -> tuple[int, int]:
    """Return ``(height, width)``, trying every source in turn.

    Order: explicit ``shape``, ``wcs.array_shape``, ``wcs.pixel_shape``, the
    header's ``NAXIS2``/``NAXIS1``, then ``data.shape``. Note ``pixel_shape`` is
    ``(naxis1, naxis2)`` — width first — while everything else here is height
    first.

    Raises ``ValueError`` if none of them answer.
    """
    if shape is not None:
        h, w = shape
        return int(h), int(w)

    arr = getattr(wcs, "array_shape", None)
    if arr:
        h, w = arr
        return int(h), int(w)

    px = getattr(wcs, "pixel_shape", None)
    if px:
        w, h = px
        return int(h), int(w)

    if header is not None:
        naxis1 = header.get("NAXIS1")
        naxis2 = header.get("NAXIS2")
        if naxis1 and naxis2:
            return int(naxis2), int(naxis1)

    if data is not None and hasattr(data, "shape") and len(data.shape) >= 2:
        h, w = data.shape[:2]
        return int(h), int(w)

    raise ValueError("Cannot determine image shape for WCS")


def boxes_from_wcs(wcs: WCS) -> list[tuple[float, float, float, float]]:
    """Return ``[(ra_deg, dec_deg, width_deg, height_deg)]`` for a WCS footprint.

    The width has to be the *catalog-query* width — an angular extent already
    multiplied by cos(dec) — not the raw span of corner RAs, which inflates as
    the field moves toward a pole.

    The trick, preserved from upstream: copy the WCS, move ``CRVAL`` to
    (0, 0), and project the four corners there. At the equator the RA span is
    the true angular width. The relocated box is guaranteed to straddle RA=0,
    so the left edge is the smallest corner RA above 180 and the right edge the
    largest below 180, and the width is their difference plus 360.

    Declination is simpler: max minus min over the corners, which stays correct
    even for a field crossing a pole.

    KNOWN LIMITATION, from upstream: the RA reconstruction can fail for a highly
    skewed field whose relocated corners do not split cleanly around 180. It is
    left as-is because the geometry is not reachable from any real detector.

    Compare ``image_boxes_from_wcs``, which computes the same thing from pixel
    scales instead and does not handle rotation.
    """
    height, width = wcs_array_shape(wcs)
    center = wcs.all_pix2world((width - 1) / 2, (height - 1) / 2, 0)
    center[0] %= 360

    wcs0 = wcs.deepcopy()
    wcs0.wcs.crval = [0, 0]
    ras, decs = wcs0.all_pix2world(
        [(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)],
        0,
    ).T
    ras %= 360
    width_deg = ras[ras < 180].max() - ras[ras >= 180].min() + 360
    height_deg = decs.max() - decs.min()

    return [(center[0], center[1], width_deg, height_deg)]


def image_boxes_from_wcs(
    wcs: WCS,
    *,
    shape: Optional[tuple[int, int]] = None,
    header=None,
    data: Optional[np.ndarray] = None,
) -> list[tuple[float, float, float, float]]:
    """Return ``[(ra_deg, dec_deg, width_deg, height_deg)]`` from pixel scales.

    The second of upstream's two footprint implementations. It multiplies the
    per-axis pixel scale by the axis length rather than projecting corners,
    which makes it tolerant of a missing ``array_shape`` (it accepts a header or
    data array instead) but blind to rotation and to the cos(dec) narrowing that
    ``boxes_from_wcs`` handles.

    Prefer ``boxes_from_wcs`` when the WCS carries its shape. This exists for
    the image-oriented entry point, where callers may only have a header.
    """
    h, w = infer_image_shape(wcs, shape=shape, header=header, data=data)

    ra_c, dec_c = wcs.all_pix2world((w - 1) / 2.0, (h - 1) / 2.0, 0)
    ra_c = float(ra_c) % 360.0
    dec_c = float(dec_c)

    # proj_plane_pixel_scales returns degrees/pixel, y axis first
    scale_y, scale_x = proj_plane_pixel_scales(wcs)[:2]
    width_deg = float(scale_x) * float(w)
    height_deg = float(scale_y) * float(h)

    return [(ra_c, dec_c, width_deg, height_deg)]


def combined_bounding_box(
    boxes: Sequence[tuple[float, float, float, float]],
) -> Optional[tuple[float, float, float, float]]:
    """Enclose several sky boxes in one, or return ``None`` to query separately.

    DISABLED UPSTREAM, PRESERVED HERE. Afterglow guarded the call site with
    ``if False:`` and fell through to querying each field individually. The
    algorithm was never deleted, and the reason it was switched off was never
    recorded, so it is kept as a working function rather than as a comment —
    but nothing in Kepler calls it, and turning it on is a behaviour change that
    needs its own validation.

    How it works: a query region given as centre plus width/height is really a
    spherical rectangle bounded by two pairs of great circles. The boxes are
    first widened into Lambert rectangles bounded by parallels and meridians
    (dividing the half-width by the smaller cos(dec) of the two dec edges, when
    the box does not straddle the equator), then combined with the standard GIS
    minimal-bounding-box trick: sort all the RA edges, find the widest gap that
    no input box spans, and take the complement of that gap as the combined RA
    range. Finally the Lambert rectangle is re-narrowed back into a spherical
    one.

    Returns ``None`` when the combined box covers more area than the inputs do
    separately — sparse, non-overlapping fields, where one big query would fetch
    far more than the caller needs.
    """
    lats: list[float] = []
    lons: list[tuple[float, float]] = []
    for ra, dec, width, height in boxes:
        hw, hh = width / 2, height / 2
        min_dec, max_dec = dec - hh, dec + hh
        if min_dec > 0 or max_dec < 0:
            hw /= max(
                np.cos(np.deg2rad(min_dec)), np.cos(np.deg2rad(max_dec))
            )
        lats += [min_dec, max_dec]
        lons.append(((ra - hw) % 360, (ra + hw) % 360))

    min_dec, max_dec = min(lats), max(lats)
    height = max_dec - min_dec
    dec = min_dec + height / 2

    xs = np.array(lons).ravel()
    xs.sort()
    xs = np.r_[xs, xs[0] + 360]
    biggest_gap = np.argmax(
        np.ma.masked_array(
            xs[1:] - xs[:-1],
            [
                any(
                    bb[0] <= xs[i] and bb[1] >= xs[i + 1]
                    for bb in np.rad2deg(np.unwrap(np.deg2rad(lons)))
                )
                for i in range(len(xs) - 1)
            ],
        )
    )
    ra_right, ra_left = xs[biggest_gap:biggest_gap + 2] % 360
    if (ra_left, ra_right) == (0, 360):
        width = 360
    else:
        width = (ra_right - ra_left) % 360
    ra = (ra_left + width / 2) % 360
    if min_dec > 0 or max_dec < 0:
        width *= max(np.cos(np.deg2rad(min_dec)), np.cos(np.deg2rad(max_dec)))

    if width * height > sum(w * h for _, _, w, h in boxes):
        # Individual FOVs are possibly too sparse for a combined FOV to be
        # smaller; the caller should query them one by one.
        return None

    return (ra, dec, width, height)


def normalize_wcs_list(wcs: WCS | Iterable[WCS] | None) -> list[WCS]:
    """Accept one WCS, many, or none, and always return a list."""
    if wcs is None:
        return []
    if isinstance(wcs, WCS):
        return [wcs]
    return [item for item in wcs if item is not None]


def remove_duplicate_sources(sources: list) -> list:
    """Drop sources repeated across overlapping fields, in place.

    Identity is the triple ``(id, ra_hours, dec_degs)``. Comparing coordinates
    exactly is safe here because duplicates come from the *same provider row*
    being returned by two overlapping queries, not from cross-matching two
    catalogs — the floats are bit-identical.

    Preserved as the original O(n²) scan. It runs only when a request covers
    more than one field.
    """
    i = 0
    while i < len(sources):
        source = sources[i]
        source_id = [
            getattr(source, name, None) for name in ("id", "ra_hours", "dec_degs")
        ]
        j = i + 1
        while j < len(sources):
            other = sources[j]
            other_id = [
                getattr(other, name, None) for name in ("id", "ra_hours", "dec_degs")
            ]
            if other_id == source_id:
                del sources[j]
            else:
                j += 1
        i += 1
    return sources


def clip_sources_to_wcs(sources: list, wcs_list: list[WCS]) -> list:
    """Keep sources landing on at least one image, stamping pixel coordinates.

    A catalog query covers the *bounding box* of a field, which for a rotated or
    non-square detector is larger than the field itself. This does the final
    cut, and as a side effect sets ``x`` / ``y`` on each surviving source to its
    pixel position in the first image that contains it — which is what the
    photometry path then measures at.

    Sources are matched against images in list order and stop at the first hit,
    so for overlapping images the pixel coordinates come from the earliest one.
    """
    final_sources = []
    for source in sources:
        for wcs_item in wcs_list:
            x, y = wcs_item.all_world2pix(
                source.ra_hours * 15.0, source.dec_degs, 0, quiet=True
            )
            height, width = wcs_item.array_shape
            if 0 <= x < width and 0 <= y < height:
                source.x, source.y = float(x), float(y)
                final_sources.append(source)
                break

    return final_sources
