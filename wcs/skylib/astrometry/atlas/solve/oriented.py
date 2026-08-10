"""Fast "on-the-fly check" plate solver: known orientation, unknown shift.

This is the SkyNode steady-state path. A prior calibration has locked in the
camera's pixel scale, field rotation, and parity (the linear pixel->sky map).
The only unknown is the pointing error: a 2-D translation, bounded by the
operator-configured pointing uncertainty.

Algorithm (no triangle search, no rotation/scale search):
  1. Extract the brightest sources.
  2. Map source pixels -> tangent-plane radians with the KNOWN CD (scale +
     rotation + parity). Project catalog stars -> the same tangent plane about
     the commanded center. The two sets now differ only by the pointing shift.
  3. Vote: histogram every (catalog - source) offset within the pointing
     uncertainty. The shift is the peak (a Hough peak in 2-D offset space).
  4. Apply the shift, nearest-neighbour match, least-squares the similarity,
     then re-match once with the fitted transform (absorbs small rotation/scale
     drift in the prior) and re-fit. Accept on inlier COUNT, not RMS.

Everything scales with the configured uncertainty: tighter pointing/rotation
priors -> smaller catalog box and cleaner peak -> faster, more certain solve.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# EXTRACTED: were absolute `skylib.astrometry.atlas.*` imports — made relative.
from ..config import AtlasConfig
from ..extract.sources import extract_sources
from ..wcs.build import decompose_linear as _decompose_linear
from ..wcs.build import wcs_from_similarity

from .solver import (
    SolveResult,
    _catalog_index,
    _fit_similarity,
    _gnomonic_projection,
    _miss,
)

try:  # pragma: no cover - optional dependency
    from scipy.spatial import cKDTree
except Exception:  # pragma: no cover
    from ..match.triangles import cKDTree

LOGGER = logging.getLogger(__name__)
ARCSEC_TO_RAD = np.deg2rad(1.0 / 3600.0)


def _known_cd_rad_per_pix(scale_arcsec: float, rotation_deg: float, parity_sign: int) -> np.ndarray:
    """Compose the locked linear map (pixel -> tangent radians).

    CD = scale * R(theta) @ diag([parity, 1]).  Decompose/compose are inverse:
    parity = sign(det(CD_ref)); CD_ref @ diag([parity,1]) = scale*R(theta).
    """
    s = scale_arcsec * ARCSEC_TO_RAD
    th = np.deg2rad(rotation_deg)
    r = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    flip = np.array([[1.0 if parity_sign >= 0 else -1.0, 0.0], [0.0, 1.0]])
    return s * (r @ flip)


def _greedy_match(
    pred_tp: np.ndarray, cat_tree: "cKDTree", tol_rad: float
) -> Tuple[np.ndarray, np.ndarray]:
    """One-to-one nearest-neighbour match; returns (obs_idx, cat_idx)."""
    dist, idx = cat_tree.query(pred_tp)
    within = np.where(dist <= tol_rad)[0]
    if within.size == 0:
        return np.empty(0, int), np.empty(0, int)
    order = within[np.argsort(dist[within])]
    seen_cat: set[int] = set()
    obs_keep, cat_keep = [], []
    for oi in order:
        cj = int(idx[oi])
        if cj in seen_cat:
            continue
        seen_cat.add(cj)
        obs_keep.append(int(oi))
        cat_keep.append(cj)
    return np.array(obs_keep, int), np.array(cat_keep, int)


def solve_oriented(
    fits_path: Path,
    config: AtlasConfig,
    *,
    ra0_deg: float,
    dec0_deg: float,
    scale_arcsec_per_pix: float,
    rotation_deg: float,
    parity_sign: int,
    pointing_radius_deg: float,
) -> SolveResult:
    start = time.perf_counter()
    dbg = config.debug

    sources = extract_sources(
        fits_path,
        max_sources=config.oriented_max_image_stars,
        crop_fraction=1.0,
        downsample=1,
        edge_margin=8,
        sn_thresh=2.0,
        peak_sn_thresh=2.0,
        min_area=5,
        # Reject satellite trails / cosmic streaks. Real stars sit at p90 elong
        # ~1.5 across 150 real frames, so this spares every star while dropping
        # the genuine non-star elongated tail (unlike the old permissive 50).
        max_elong=4.0,
        matched_filter_fwhm_pix=(
            config.extract_matched_filter_fwhm_pix if config.use_matched_extraction else 0.0
        ),
        detect_nsig=config.extract_detect_nsig,
    )
    obs_xy = np.asarray(sources.xy, float)
    height, width = sources.shape
    # What extraction found, before the brightness cap below. Reported on every
    # exit path as `n_sources_extracted`. The separate `n_sources` key keeps its
    # original per-branch meaning (pre-cap here, post-cap on the late misses,
    # absent on some) because SkyNode's blind-fallback gate reads it and is
    # sensitive to both the value and its absence.
    n_sources = int(obs_xy.shape[0])
    if n_sources < 4:
        return _miss("too_few_sources", start=start, n_extracted=n_sources,
                     n_sources=n_sources)

    # Keep the brightest sources (fewer = faster; bright = reliably matched).
    if getattr(sources, "flux", None) is not None and sources.flux.size == obs_xy.shape[0]:
        keep = np.argsort(sources.flux)[::-1][: config.oriented_max_image_stars]
        obs_xy = obs_xy[keep]

    # Known pixel->tangent map; reference pixel = image center so the shift ~ the
    # pointing error.
    cd = _known_cd_rad_per_pix(scale_arcsec_per_pix, rotation_deg, parity_sign)
    center_pix = np.array([(width - 1) / 2.0, (height - 1) / 2.0])
    obs_tp = (obs_xy - center_pix) @ cd.T

    # Catalog box: pointing uncertainty + half the field diagonal.
    fov_w = scale_arcsec_per_pix * width / 3600.0
    fov_h = scale_arcsec_per_pix * height / 3600.0
    half_deg = float(pointing_radius_deg) + 0.5 * float(np.hypot(fov_w, fov_h))
    cos_dec = max(0.2, float(abs(np.cos(np.deg2rad(dec0_deg)))))
    catalog_name, catalog_root = config.resolve_catalog()
    cat = _catalog_index(catalog_name, catalog_root).query_box(
        ra0_deg - half_deg / cos_dec,
        ra0_deg + half_deg / cos_dec,
        dec0_deg - half_deg,
        dec0_deg + half_deg,
        thin=config.thin,
    )
    if cat.ra_deg.size < 4:
        return _miss(
            "empty_catalog",
            start=start,
            n_extracted=n_sources,
            n_cat=int(cat.ra_deg.size),
        )

    cat_tp = _gnomonic_projection(cat.ra_deg, cat.dec_deg, ra0_deg, dec0_deg)
    # Cap catalog size by uniform subsample (preserve coverage across the box —
    # the true field can be anywhere within the pointing uncertainty).
    if cat_tp.shape[0] > config.oriented_max_catalog_stars:
        sub = np.random.default_rng(0).choice(
            cat_tp.shape[0], config.oriented_max_catalog_stars, replace=False
        )
        cat_tp = cat_tp[sub]

    # Radius-aware acceptance floor: a wider search offers more chances for a
    # coincidental match, so require more inliers/votes as the pointing radius
    # grows. The configured floors are the tight-search base (validated at ~10'
    # on 150 real frames: 100% solve, 0 false); scale up toward a 1-deg
    # cold-start search where a few-inlier coincidence becomes possible.
    rad_frac = min(1.0, max(0.0, (float(pointing_radius_deg) - 0.15) / 0.85))
    min_votes_eff = config.oriented_min_votes + int(round(rad_frac * 2))
    min_inliers_eff = config.oriented_min_inliers + int(round(rad_frac * 4))
    # The inlier *fraction* is the decisive false-positive rejector (a true solve
    # matches the large majority of sources; a coincidental match only ~20%).
    # Tighten it with the search radius too: a wider search has more chances for
    # a spurious alignment, so demand a higher matched fraction to accept.
    min_fraction_eff = config.oriented_min_fraction + rad_frac * 0.15

    # ---- Hough vote over offsets (catalog - source) within the uncertainty ----
    bin_rad = config.oriented_offset_bin_arcsec * ARCSEC_TO_RAD
    lim = (float(pointing_radius_deg) * np.pi / 180.0) + 2.0 * bin_rad
    offs = (cat_tp[:, None, :] - obs_tp[None, :, :]).reshape(-1, 2)
    inb = (np.abs(offs[:, 0]) <= lim) & (np.abs(offs[:, 1]) <= lim)
    offs = offs[inb]
    if offs.shape[0] < min_votes_eff:
        return _miss(
            "no_offset_votes",
            start=start,
            n_extracted=n_sources,
            n_offsets=int(offs.shape[0]),
            min_votes=int(min_votes_eff),
        )

    nbins = max(4, int(np.ceil(2 * lim / bin_rad)))
    edges = np.linspace(-lim, lim, nbins + 1)
    hist, xe, ye = np.histogram2d(offs[:, 0], offs[:, 1], bins=[edges, edges])

    cat_tree = cKDTree(cat_tp)
    match_tol_rad = config.oriented_match_tol_arcsec * ARCSEC_TO_RAD

    # Evaluate the top-K vote peaks. For each: (1) translation-only match under
    # the locked orientation to seed correspondences, then (2) a free similarity
    # fit CLAMPED to the prior — it corrects the real rotation/scale drift of an
    # imperfect lock (restoring accuracy), while refusing the large warp a wrong
    # asterism would require (rejecting false positives). The true peak wins on
    # verified inlier count even when it isn't the tallest raw vote bin.
    prior_scale, prior_angle, prior_parity = _decompose_linear(cd)
    flat = hist.ravel()
    kk = min(config.oriented_n_peaks, flat.size)
    top_bins = np.argpartition(flat, -kk)[-kk:]
    best = None  # (inliers, scale, rot, trans, peak_votes)
    for fb in top_bins:
        votes = int(flat[fb])
        if votes < min_votes_eff:
            continue
        bi, bj = np.unravel_index(int(fb), hist.shape)
        cx = 0.5 * (xe[bi] + xe[bi + 1])
        cy = 0.5 * (ye[bj] + ye[bj + 1])
        near = (np.abs(offs[:, 0] - cx) <= 1.5 * bin_rad) & (np.abs(offs[:, 1] - cy) <= 1.5 * bin_rad)
        if int(near.sum()) < min_votes_eff:
            continue
        shift = np.median(offs[near], axis=0)
        obs_i = cat_i = None
        for _ in range(3):  # translation-only seed (orientation fixed)
            obs_i, cat_i = _greedy_match(obs_tp + shift, cat_tree, match_tol_rad)
            if obs_i.size < 3:
                break
            shift = np.median(cat_tp[cat_i] - obs_tp[obs_i], axis=0)
        if obs_i is None or obs_i.size < 4:
            continue

        # Free similarity fit, then clamp to the prior (false-positive gate).
        scale_f, rot_f, trans_f = _fit_similarity(obs_xy[obs_i], cat_tp[cat_i])
        fscale, fangle, fparity = _decompose_linear(scale_f * rot_f)
        dang = (fangle - prior_angle + 180.0) % 360.0 - 180.0
        if (
            fparity != prior_parity
            or abs(fscale / prior_scale - 1.0) > config.oriented_scale_dev
            or abs(dang) > config.oriented_rot_tol_deg
        ):
            continue  # warp too large -> reject this candidate

        # Re-match with the corrected transform (recovers edge stars) and refit.
        pred = (obs_xy @ rot_f.T) * scale_f + trans_f
        obs_i, cat_i = _greedy_match(pred, cat_tree, match_tol_rad)
        if obs_i.size < 4:
            continue
        scale_f, rot_f, trans_f = _fit_similarity(obs_xy[obs_i], cat_tp[cat_i])
        if best is None or obs_i.size > best[0]:
            best = (int(obs_i.size), scale_f, rot_f, trans_f, votes)

    if best is None or best[0] < min_inliers_eff:
        return _miss(
            "insufficient_inliers",
            start=start,
            n_extracted=n_sources,
            inliers=0 if best is None else int(best[0]),
            min_inliers=int(min_inliers_eff),
        )

    inliers, scale_f, rot_f, trans_f, peak_votes = best

    # Inlier-fraction gate (the decisive false-positive rejector). A TRUE solve
    # matches the large majority of the *matchable* sources; a coincidental match
    # — e.g. the WRONG parity, or a spurious offset in a dense field over a wide
    # search — matches only a small fraction (~20%) even when it clears the
    # absolute inlier floor. Requiring a minimum matched fraction cleanly
    # separates them and is what lets the parity try-both pick the right flip.
    #
    # The matchable count is bounded by BOTH the detected sources AND the catalog
    # stars that actually cover the image footprint. When an exposure goes deeper
    # than the catalog (few catalog stars, many faint detections), normalizing by
    # the raw source count understates a perfect solve (e.g. 8/79 = 10%). The fair
    # denominator is min(n_sources, n_catalog_in_fov): clip to a comparable count
    # so the fraction reads "of the stars we *could* match, how many did we." A
    # wrong solve stays low under either denominator — in a dense field (where
    # coincidental matches actually arise) the catalog count exceeds the source
    # count, so min() picks the source count and the spurious fraction is unmoved.
    n_obs = int(obs_xy.shape[0])
    # Catalog stars inside the image footprint under the solved transform. Invert
    # the similarity to pixel space: rot_f is orthonormal (incl. parity flips), so
    # (rot_f.T)^-1 applied on the right is just @ rot_f.
    cat_pix = ((cat_tp - trans_f) @ rot_f) / scale_f
    n_cat_fov = int(
        (
            (cat_pix[:, 0] >= 0) & (cat_pix[:, 0] <= width)
            & (cat_pix[:, 1] >= 0) & (cat_pix[:, 1] <= height)
        ).sum()
    )
    denom = min(n_obs, n_cat_fov) if n_cat_fov > 0 else n_obs
    frac = inliers / max(1, denom)
    if frac < min_fraction_eff:
        return _miss(
            "insufficient_fraction",
            start=start,
            n_extracted=n_sources,
            n_sources=n_obs,
            inliers=int(inliers),
            n_catalog_fov=n_cat_fov,
            fraction=float(frac),
            min_fraction=float(min_fraction_eff),
        )
    pred = (obs_xy @ rot_f.T) * scale_f + trans_f
    obs_i, cat_i = _greedy_match(pred, cat_tree, match_tol_rad)
    resid = np.linalg.norm(((obs_xy[obs_i] @ rot_f.T) * scale_f + trans_f) - cat_tp[cat_i], axis=1)
    resid_arcsec = resid / ARCSEC_TO_RAD
    rms_arcsec = float(np.sqrt(np.mean(resid ** 2)) / ARCSEC_TO_RAD)

    # Tight-core verification — the decisive false-positive rejector in CROWDED
    # fields, where the loose inlier-fraction gate is defeated. When the match
    # tolerance saturates (a globular cluster: almost every source has SOME catalog
    # neighbour within tol), a wrong-orientation alignment racks up a high loose
    # fraction at ~tol/2 RMS and passes. A TRUE solve differs by having a dense
    # CORE of sub-arcsec matches; a spurious one has almost none. Require both a
    # minimum count and a minimum fraction of the matched inliers inside the tight
    # tolerance. (Confirmed on a real M22 frame: the true rot solve had ~0.2"
    # median residual / a large tight core; three spurious candidates at the wrong
    # orientation each sat at ~4-5" with an empty core, all clearing the old gates.)
    n_tight = int((resid_arcsec <= config.oriented_tight_tol_arcsec).sum())
    tight_frac = n_tight / max(1, obs_i.size)
    if (
        n_tight < config.oriented_min_tight_inliers
        or tight_frac < config.oriented_min_tight_fraction
    ):
        return _miss(
            "loose_match",
            start=start,
            n_extracted=n_sources,
            n_sources=n_obs,
            inliers=int(obs_i.size),
            n_tight=n_tight,
            tight_fraction=float(tight_frac),
            tight_tol_arcsec=float(config.oriented_tight_tol_arcsec),
            rms_arcsec=rms_arcsec,
        )

    scale_rad = scale_f
    wcs = wcs_from_similarity(scale_f, rot_f, trans_f, ra0_deg, dec0_deg)

    elapsed = time.perf_counter() - start
    if dbg:
        LOGGER.info(
            "oriented solve: peak_votes=%s inliers=%s/%s rms=%.3f\" tight=%s/%s t=%.2fs",
            peak_votes, inliers, obs_xy.shape[0], rms_arcsec, n_tight, obs_i.size, elapsed,
        )
    return SolveResult(
        True,
        wcs,
        {
            "method": "oriented_offset_vote",
            "inliers": int(inliers),
            "n_sources_extracted": n_sources,
            "n_sources": int(obs_xy.shape[0]),
            "peak_votes": int(peak_votes),
            "rms_arcsec": rms_arcsec,
            "n_tight": int(n_tight),
            "tight_fraction": float(tight_frac),
            "scale_arcsec_per_pix": float(scale_rad / ARCSEC_TO_RAD),
            "elapsed_s": float(elapsed),
            "catalog": catalog_name,
        },
    )


__all__ = ["solve_oriented"]
