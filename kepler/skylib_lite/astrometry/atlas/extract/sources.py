from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats

# EXTRACTED: was `from skylib.io.fits_compression import select_image_hdu` —
# vendored under kepler/skylib_lite/io/fits_compression.py, import made relative.
from ....io.fits_compression import select_image_hdu

try:
    from scipy import ndimage as ndi
except Exception:  # pragma: no cover
    ndi = None

# Gaussian sigma -> FWHM.
_FWHM_PER_SIGMA = 2.3548200450309493


def estimate_background_2d(data: np.ndarray, box: int) -> np.ndarray:
    """Spatially-varying background of ``data`` (SExtractor-style mesh of
    sigma-clipped medians, smoothed) at full resolution.

    A single global background + RMS buries stars that sit on a large-scale
    gradient or nebulosity: the structure inflates the global RMS until the
    per-pixel S/N of genuine stars falls below the detection floor, so a rich
    field reads as ``few_sources``. Subtracting this 2-D background first
    flattens that structure and recovers the field. Shared by the QA
    sparse-frame recount and the camera simulator's catalog renderer. Falls
    back to a flat global median on a degenerate frame / missing optional dep.
    """
    data = np.asarray(data, dtype=np.float64)
    box = int(max(8, min(int(box), data.shape[0], data.shape[1])))
    try:
        from photutils.background import Background2D

        return np.asarray(Background2D(data, box_size=box).background, dtype=np.float64)
    except Exception:  # pragma: no cover - degenerate frame / missing optional dep
        return np.full(data.shape, float(np.median(data)), dtype=np.float64)


@dataclass
class ExtractedSources:
    xy: np.ndarray
    shape: Tuple[int, int]
    flux: np.ndarray          # brightness proxy (sum of background-subtracted positive flux)
    peak_sn: np.ndarray       # peak S/N in detection blob
    # Shape metrics (catalog-depth-independent) for artifact vs star discrimination:
    npix: Optional[np.ndarray] = None       # connected-pixel count
    elong: Optional[np.ndarray] = None       # sqrt(major/minor variance)
    sharpness: Optional[np.ndarray] = None   # peak pixel / total flux (concentration)
    theta: Optional[np.ndarray] = None       # major-axis position angle [rad], in (-pi/2, pi/2]
    fwhm_pix: Optional[np.ndarray] = None     # round-equivalent FWHM [full-frame px]
    central_ratio: Optional[np.ndarray] = None  # value at centroid / peak (donut ⇒ low: hole)
    # Background level + per-pixel noise of the (downsampled) frame, for QA sanity.
    background: float = 0.0
    background_rms: float = 0.0


def extract_sources(fits_path: Path, **kwargs) -> ExtractedSources:
    """Extract sources from a FITS file (thin wrapper over :func:`extract_sources_from_array`)."""
    with fits.open(fits_path) as hdul:
        # Compression-aware: picks the CompImageHDU extension for tile-compressed
        # files, the primary otherwise. See skylib.io.fits_compression.
        data = select_image_hdu(hdul).data
    if data is None:
        raise ValueError("FITS image contains no data")
    if data.ndim > 2:
        data = data[0]
    return extract_sources_from_array(np.asarray(data, dtype=np.float64), **kwargs)


def _detect_matched_peaks(
    data: np.ndarray,
    bg_median: float,
    std: float,
    *,
    fwhm_pix: float,
    nsig: float,
    peak_sn_thresh: float,
    min_area: int,
    max_area: int,
    max_elong: float,
) -> list:
    """PSF-matched peak detection (DAOFIND / image2xy style).

    Correlate the background-subtracted image with a Gaussian matched to the PSF,
    then take LOCAL MAXIMA of that response above ``nsig`` times its own noise.
    Versus the legacy raw-threshold + 3x3 ``binary_opening`` path this:

    * recovers faint real stars — the kernel integrates a star's flux over its PSF
      footprint, lifting it above the per-pixel noise floor (the per-pixel cut
      never reaches a star whose individual pixels sit near the noise); and
    * does not erode — the old opening deleted any star whose core was not a solid
      3x3 block above threshold, which starved the solver on shallow frames (only
      ~5 of ~14 catalog stars survived, below the verifier's inlier floor).

    Peaks are required to be separated by ~3 FWHM, which deblends close pairs and
    avoids the dense forest of noise peaks a bare threshold would yield. Each peak
    is measured in a window on the original residual and returned in the same tuple
    format / coordinate frame as the legacy path, so all downstream post-processing
    is shared. Single hot pixels are dropped by the ``min_area`` footprint gate (a
    lone spike has too few pixels above 1 sigma); brighter cosmic-ray clusters that
    survive are harmless — the geometric verifier discards unmatched detections.
    """
    resid = data - bg_median
    sigma_psf = max(float(fwhm_pix) / _FWHM_PER_SIGMA, 1e-3)
    matched = ndi.gaussian_filter(resid, sigma_psf, mode="nearest")
    # Response noise of a unit-sum Gaussian kernel: var = std^2 * sum(k^2) with
    # sum(k^2) = 1/(4*pi*sigma^2). So detect_sn is a true PSF detection significance.
    response_noise = std * np.sqrt(1.0 / (4.0 * np.pi * sigma_psf * sigma_psf))
    detect_sn = matched / max(response_noise, 1e-12)

    sep = max(3, int(round(float(fwhm_pix) * 3.0)) | 1)  # odd; min-separation ~3 FWHM
    peaks = (matched == ndi.maximum_filter(matched, size=sep)) & (detect_sn > float(nsig))
    ys, xs = np.where(peaks)
    if ys.size == 0:
        return []

    # On deep frames the peak list can run to tens of thousands (real faint stars
    # plus noise). Measuring every one in Python is wasteful, and the caller keeps
    # only max_sources of them anyway. Pre-trim to the strongest by matched
    # response (≈ integrated flux for a PSF source), which never drops a real star
    # — they have the highest response — while bounding the measurement loop.
    _PEAK_CAP = 4000
    if ys.size > _PEAK_CAP:
        strongest = np.argpartition(matched[ys, xs], -_PEAK_CAP)[-_PEAK_CAP:]
        ys, xs = ys[strongest], xs[strongest]

    h, w = data.shape
    r = max(3, int(round(float(fwhm_pix) * 1.5)))
    detections = []
    for py, px in zip(ys.tolist(), xs.tolist()):
        y0, y1 = max(0, py - r), min(h, py + r + 1)
        x0, x1 = max(0, px - r), min(w, px + r + 1)
        win = resid[y0:y1, x0:x1]
        wpos = np.clip(win, 0.0, None)
        flux_sum = float(wpos.sum())
        if flux_sum <= 0:
            continue

        peak_val = float(resid[py, px])
        peak_sn = peak_val / std
        if peak_sn < float(peak_sn_thresh):
            continue

        # Footprint above 1 sigma: large enough that a faint but real PSF survives,
        # small (1-3 px) for a lone hot pixel -> the min_area gate drops it.
        npix = int(np.count_nonzero((win / std) > 1.0))
        if npix < int(min_area) or npix > int(max_area):
            continue

        yy, xx = np.mgrid[y0:y1, x0:x1]
        cy = float((yy * wpos).sum() / flux_sum)
        cx = float((xx * wpos).sum() / flux_sum)
        dy = yy - cy
        dx = xx - cx
        mxx = float((wpos * dx * dx).sum() / flux_sum)
        myy = float((wpos * dy * dy).sum() / flux_sum)
        mxy = float((wpos * dx * dy).sum() / flux_sum)
        tr = mxx + myy
        det = mxx * myy - mxy * mxy
        disc = max(tr * tr / 4.0 - det, 0.0)
        l1 = tr / 2.0 + np.sqrt(disc)
        l2 = tr / 2.0 - np.sqrt(disc)
        elong = float("inf") if l2 <= 1e-12 else float(np.sqrt(l1 / l2))
        if elong > float(max_elong):
            continue

        theta = 0.5 * float(np.arctan2(2.0 * mxy, mxx - myy))
        sigma_geom = (max(l1, 0.0) * max(l2, 0.0)) ** 0.25 if l2 > 1e-12 else np.sqrt(max(l1, 0.0))
        fwhm = _FWHM_PER_SIGMA * float(sigma_geom)
        sharpness = peak_val / flux_sum if flux_sum > 0 else 0.0
        cyi = int(round(cy))
        cxi = int(round(cx))
        central_val = float(resid[cyi, cxi]) if (0 <= cyi < h and 0 <= cxi < w) else peak_val
        central_ratio = (central_val / peak_val) if peak_val > 0 else 0.0
        detections.append(
            (peak_sn, flux_sum, cx, cy, elong, npix, sharpness, theta, fwhm, central_ratio)
        )
    return detections


def extract_sources_from_array(
    data: np.ndarray,
    *,
    max_sources: int = 500,
    crop_fraction: float = 1.0,
    downsample: int = 1,
    edge_margin: int = 8,
    sn_thresh: float = 5.0,          # detection threshold in S/N
    peak_sn_thresh: float = 8.0,     # require at least this peak S/N in a blob
    min_area: int = 5,               # min connected pixels
    max_area: int = 10_000,          # reject huge blobs (saturation blooms, etc)
    max_elong: float = 20.0,         # allow trails; lower if you want
    matched_filter_fwhm_pix: float = 0.0,  # >0 = PSF-matched peak detection; 0 = legacy raw threshold
    detect_nsig: float = 3.5,              # matched-filter detection significance (only used when matched)
    local_background_box: Optional[int] = None,  # >0 = subtract a 2-D background (legacy path); None = global
    debug_overlay_path: Optional[Path] = None,
) -> ExtractedSources:
    """Single-pass source extraction over an in-memory image array.

    Shared by the oriented plate solver and the per-exposure QA core (the node
    passes its readout array, the server passes the FITS data array — same code).
    Returns centroids plus catalog-depth-independent shape metrics (elongation,
    sharpness, position angle, FWHM) and the frame background/noise.
    """
    if ndi is None:
        raise ImportError("scipy is required for extract_sources_from_array")

    data = np.asarray(data, dtype=np.float64)
    full_shape = data.shape

    crop_fraction = max(0.1, min(1.0, float(crop_fraction)))
    downsample = max(1, int(downsample))

    def _empty() -> ExtractedSources:
        return ExtractedSources(
            xy=np.empty((0, 2)),
            shape=full_shape,
            flux=np.empty((0,), dtype=np.float64),
            peak_sn=np.empty((0,), dtype=np.float64),
            npix=np.empty((0,), dtype=np.float64),
            elong=np.empty((0,), dtype=np.float64),
            sharpness=np.empty((0,), dtype=np.float64),
            theta=np.empty((0,), dtype=np.float64),
            fwhm_pix=np.empty((0,), dtype=np.float64),
            central_ratio=np.empty((0,), dtype=np.float64),
            background=float(bg_median),
            background_rms=float(bg_std),
        )

    y0, x0 = 0, 0
    if crop_fraction < 1.0:
        h, w = data.shape
        ch = int(h * crop_fraction)
        cw = int(w * crop_fraction)
        y0 = (h - ch) // 2
        x0 = (w - cw) // 2
        data = data[y0 : y0 + ch, x0 : x0 + cw]

    if downsample > 1:
        data = data[::downsample, ::downsample]

    # Local 2-D background recovers stars buried under large-scale structure
    # (gradient / nebulosity) that inflates a single global RMS. Opt-in — QA's
    # sparse recount enables it; the matched-filter solver path keeps the
    # validated global background untouched.
    use_local_bg = (
        local_background_box is not None
        and int(local_background_box) > 0
        and not (matched_filter_fwhm_pix and matched_filter_fwhm_pix > 0)
    )
    if use_local_bg:
        bg_field = estimate_background_2d(data, int(local_background_box))
        data_bs = data - bg_field
        _, _, std = sigma_clipped_stats(data_bs, sigma=3.0)
        bg_std = max(float(std), 1e-12)
        std = bg_std
        bg_median = float(np.median(bg_field))
    else:
        mean, median, std = sigma_clipped_stats(data, sigma=3.0)
        bg_median = float(median)
        bg_std = max(float(std), 1e-12)
        std = bg_std
        data_bs = data - bg_median

    # ``data_bs`` is the background-subtracted frame (scalar bg globally, the
    # 2-D field locally); detection + flux/peak/centroid measurements all read
    # from it so both paths share one code path below.
    sn = data_bs / std

    # --- Detection ---------------------------------------------------------
    structure = np.ones((3, 3), dtype=bool)
    if matched_filter_fwhm_pix and matched_filter_fwhm_pix > 0:
        # PSF-matched peak detection (opt-in; see _detect_matched_peaks). The
        # plate-solver paths enable this to recover faint stars on shallow frames;
        # all other callers keep the legacy raw-threshold path below unchanged.
        detections = _detect_matched_peaks(
            data, bg_median, std,
            fwhm_pix=float(matched_filter_fwhm_pix), nsig=float(detect_nsig),
            peak_sn_thresh=float(peak_sn_thresh), min_area=int(min_area),
            max_area=int(max_area), max_elong=float(max_elong),
        )
        slices = []  # matched path filled `detections`; skip the legacy loop
    else:
        # Legacy: raw per-pixel S/N threshold with morphological open+close.
        mask = sn > float(sn_thresh)
        mask = ndi.binary_opening(mask, structure=structure)
        mask = ndi.binary_closing(mask, structure=structure)
        labeled, nlab = ndi.label(mask, structure=structure)
        if nlab == 0:
            return _empty()
        slices = ndi.find_objects(labeled)
        detections = []

    # Measure each component (legacy threshold path only; matched path already
    # populated `detections` above and leaves `slices` empty).
    for lab, slc in enumerate(slices, start=1):
        if slc is None:
            continue
        region = (labeled[slc] == lab)
        npix = int(region.sum())
        if npix < int(min_area) or npix > int(max_area):
            continue

        sn_reg = sn[slc][region]
        peak_sn = float(sn_reg.max())
        if peak_sn < float(peak_sn_thresh):
            continue

        # intensity-weighted centroid on background-subtracted flux
        flux_reg = data_bs[slc][region]
        flux_reg = np.clip(flux_reg, 0.0, None)
        flux_sum = float(flux_reg.sum())
        if flux_sum <= 0:
            continue

        # Pixel coordinates within slice
        yy, xx = np.nonzero(region)
        # Convert to full-image coords in the downsampled/cropped space
        yy = yy + slc[0].start
        xx = xx + slc[1].start

        # Weighted centroid
        w = flux_reg
        cy = float((yy * w).sum() / flux_sum)
        cx = float((xx * w).sum() / flux_sum)

        # 2nd moments for elongation estimate
        dy = yy - cy
        dx = xx - cx
        mxx = float((w * dx * dx).sum() / flux_sum)
        myy = float((w * dy * dy).sum() / flux_sum)
        mxy = float((w * dx * dy).sum() / flux_sum)

        # Eigenvalues of covariance (principal axis variances)
        tr = mxx + myy
        det = mxx * myy - mxy * mxy
        disc = max(tr * tr / 4.0 - det, 0.0)
        l1 = tr / 2.0 + np.sqrt(disc)
        l2 = tr / 2.0 - np.sqrt(disc)
        # elongation as sqrt(var_major/var_minor)
        if l2 <= 1e-12:
            elong = float("inf")
        else:
            elong = float(np.sqrt(l1 / l2))

        if elong > float(max_elong):
            continue

        # Major-axis position angle (mod pi) and round-equivalent FWHM, both from
        # the same second moments. theta feeds the trailing detector; fwhm the
        # focus detector. fwhm is in DOWNSAMPLED px here; scaled back below.
        theta = 0.5 * float(np.arctan2(2.0 * mxy, mxx - myy))
        sigma_geom = (max(l1, 0.0) * max(l2, 0.0)) ** 0.25 if l2 > 1e-12 else np.sqrt(max(l1, 0.0))
        fwhm = _FWHM_PER_SIGMA * float(sigma_geom)

        # Concentration: peak background-subtracted pixel / total flux. Near 1 for
        # a hot pixel (all flux in one pixel), low for a PSF-spread star.
        peak_val = float(data_bs[slc][region].max())
        sharpness = peak_val / flux_sum if flux_sum > 0 else 0.0

        # Central-dip ratio: background-subtracted value AT the centroid / peak.
        # ~1 for a star (centroid = peak), low for a defocused donut whose centre
        # is the hole — the discriminator between a focus fault and poor seeing.
        cyi = int(round(cy))
        cxi = int(round(cx))
        if 0 <= cyi < data.shape[0] and 0 <= cxi < data.shape[1]:
            central_val = float(data_bs[cyi, cxi])
        else:
            central_val = peak_val
        central_ratio = (central_val / peak_val) if peak_val > 0 else 0.0
        detections.append(
            (peak_sn, flux_sum, cx, cy, elong, npix, sharpness, theta, fwhm, central_ratio)
        )

    if not detections:
        return _empty()

    if matched_filter_fwhm_pix and matched_filter_fwhm_pix > 0:
        # Matched path: sort brightest-first by integrated flux (peak S/N tiebreak).
        # Flux favours real PSF-spread stars over single-pixel noise/hot-pixel
        # spikes, so the max_sources cut keeps the stars the matcher needs rather
        # than noise — the ordering astrometry.net's pipeline also uses.
        detections.sort(key=lambda t: (t[1], t[0]), reverse=True)
    else:
        # Legacy path: unchanged — sort by peak S/N then flux.
        detections.sort(key=lambda t: (t[0], t[1]), reverse=True)
    detections = detections[: max_sources if max_sources > 0 else len(detections)]

    peak_sn_arr = np.array([d[0] for d in detections], dtype=np.float64)
    flux_arr = np.array([d[1] for d in detections], dtype=np.float64)
    x = np.array([d[2] for d in detections], dtype=np.float64)
    y = np.array([d[3] for d in detections], dtype=np.float64)
    elong_arr = np.array([d[4] for d in detections], dtype=np.float64)
    npix_arr = np.array([d[5] for d in detections], dtype=np.float64)
    sharp_arr = np.array([d[6] for d in detections], dtype=np.float64)
    theta_arr = np.array([d[7] for d in detections], dtype=np.float64)
    fwhm_arr = np.array([d[8] for d in detections], dtype=np.float64)
    central_arr = np.array([d[9] for d in detections], dtype=np.float64)

    # Edge margin (in the downsampled/cropped image coords)
    if edge_margin > 0:
        h, w = data.shape
        m = int(edge_margin)
        keep = (x > m) & (y > m) & (x < (w - m)) & (y < (h - m))
        x = x[keep]
        y = y[keep]
        peak_sn_arr = peak_sn_arr[keep]
        flux_arr = flux_arr[keep]
        elong_arr = elong_arr[keep]
        npix_arr = npix_arr[keep]
        sharp_arr = sharp_arr[keep]
        theta_arr = theta_arr[keep]
        fwhm_arr = fwhm_arr[keep]
        central_arr = central_arr[keep]

    if x.size == 0:
        return _empty()

    # Debug overlay
    if debug_overlay_path is not None:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.imshow(data, origin="lower", cmap="gray", vmin=bg_median - 2 * std, vmax=bg_median + 10 * std)
            ax.scatter(x, y, s=18, facecolors="none", edgecolors="lime", linewidths=0.9)
            ax.set_title(f"detections={len(x)} (sn>{sn_thresh}, peak>{peak_sn_thresh})")
            fig.tight_layout()
            fig.savefig(debug_overlay_path, dpi=160)
            plt.close(fig)
        except Exception:
            pass

    # Back to FITS pixel coords (1-based) and undo crop/downsample
    x = (x * downsample) + x0 + 1.0
    y = (y * downsample) + y0 + 1.0
    fwhm_arr = fwhm_arr * downsample  # downsampled px -> full-frame px
    xy = np.stack([x, y], axis=1)
    return ExtractedSources(
        xy=xy,
        shape=full_shape,
        flux=flux_arr,
        peak_sn=peak_sn_arr,
        npix=npix_arr,
        elong=elong_arr,
        sharpness=sharp_arr,
        theta=theta_arr,
        fwhm_pix=fwhm_arr,
        central_ratio=central_arr,
        background=bg_median,
        background_rms=bg_std,
    )
