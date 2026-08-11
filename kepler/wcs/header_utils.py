"""FITS-header hint helpers used to seed the astrometric solve.

EXTRACTED from ``skynet_db/runners/utils.py`` (lines 159-441 of the original,
verbatim). That module is a grab-bag of runner utilities — S3 downloads, worker
temp paths, Vizier cache pruning, compressed-FITS product writing, photometric
zero-point fitting, catalog queries. Only the two header-parsing helpers the WCS
solve imports (``estimate_pixel_scale_arcsec_per_pix`` and
``guess_icrs_radec_from_header``) and their private helpers were extracted; the
rest is infrastructure or belongs to other pipelines.

NOTE on ``calc_solution``: it was named as a candidate for this extraction, but
it is the photometric zero-point / limiting-magnitude solver (it takes
``list[PhotometryData]`` and returns ``m0, m0_error, sigma, limmag,
rej_percent``). ``wcs.py`` does not import it and it performs no astrometry, so
it is deliberately left behind for the photometry / field-calibration
extraction. See EXTRACTION.md.
"""

from __future__ import annotations

import astropy.units as u
from astropy.coordinates import SkyCoord, FK5, FK4, ICRS, Angle
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales


def _get_any(header, keys: list[str], default=None):
    for k in keys:
        if k in header:
            return header[k]
    return default

def _binning_from_header(header):
    # Common binning keywords
    xb = _get_any(header, ["XBINNING", "XBIN", "CCDXBIN", "BINX"], 1)
    yb = _get_any(header, ["YBINNING", "YBIN", "CCDYBIN", "BINY"], 1)
    try:
        xb = int(xb)
        yb = int(yb)
    except Exception:
        xb = yb = 1
    # Some cameras store a single BINNING like "2 2" or "2x2"
    single = header.get("BINNING")
    if single and (isinstance(single, str)):
        s = single.lower().replace("x", " ").split()
        if len(s) == 2:
            try:
                xb, yb = int(s[0]), int(s[1])
            except Exception:
                pass
    return max(1, xb), max(1, yb)

def _arcsec_from_wcs(header):
    try:
        w = WCS(header)
        # proj_plane_pixel_scales returns degrees/pixel
        scales_deg = proj_plane_pixel_scales(w)  # np.array([dx_deg, dy_deg]) or length-2/3
        if scales_deg is None:
            return None
        scales_arcsec = (scales_deg * u.deg).to(u.arcsec).value
        # prefer first two axes
        if len(scales_arcsec) >= 2:
            sx, sy = float(scales_arcsec[0]), float(scales_arcsec[1])
            if sx > 0 and sy > 0:
                return (sx, sy, 0.5 * (sx + sy))
    except Exception:
        pass
    # Manual CD/CDELT fallback if WCS init fails
    try:
        cd11 = float(header.get("CD1_1"))
        cd12 = float(header.get("CD1_2"))
        cd21 = float(header.get("CD2_1"))
        cd22 = float(header.get("CD2_2"))
        sx = (cd11**2 + cd12**2) ** 0.5 * 3600.0  # arcsec/pix
        sy = (cd21**2 + cd22**2) ** 0.5 * 3600.0
        if sx > 0 and sy > 0:
            return (sx, sy, 0.5 * (sx + sy))
    except Exception:
        pass
    try:
        # CDELT + PC case (rotation ignored for scale)
        cdelt1 = float(header.get("CDELT1"))
        cdelt2 = float(header.get("CDELT2"))
        sx = abs(cdelt1) * 3600.0
        sy = abs(cdelt2) * 3600.0
        if sx > 0 and sy > 0:
            return (sx, sy, 0.5 * (sx + sy))
    except Exception:
        pass
    return None

def _arcsec_from_direct_keywords(header, xbin: int, ybin: int):
    """
    Look for arcsec/pixel keywords; apply binning if they are *unbinned* values.
    Conventions vary—many headers already include binning; we try to be conservative:
    - If a single keyword (PIXSCALE/SECPIX) exists, return it as-is.
    - If per-axis exist, return their mean.
    """
    # Common arcsec/pixel keywords (already arcsec/pixel)
    single = _get_any(header, ["PIXSCALE", "SECPIX", "SECPIXEL"], None)
    if single is not None:
        try:
            val = float(single)
            if val > 0:
                return (val, val, val)
        except Exception:
            pass

    xk = _get_any(header, ["PIXSCALE1", "SECPIX1", "CDELT1A"], None)
    yk = _get_any(header, ["PIXSCALE2", "SECPIX2", "CDELT2A"], None)
    try:
        if xk is not None and yk is not None:
            sx = abs(float(xk))
            sy = abs(float(yk))
            if sx > 0 and sy > 0:
                return (sx, sy, 0.5 * (sx + sy))
    except Exception:
        pass

    return None

def _arcsec_from_optics(header, xbin: int, ybin: int):
    """
    Plate scale = 206.264806 * (pixel_um * bin) / focal_mm  [arcsec/pixel]
    """
    # Pixel size (microns): commonly XPIXSZ/YPIXSZ, PIXSIZE1/2 (µm, ESO), or PIXSIZE (µm)
    # Use X/Y separately if available; else single; else None
    xpix_um = _get_any(header, ["XPIXSZ", "PIXSIZE1", "PIXSIZE"], None)
    ypix_um = _get_any(header, ["YPIXSZ", "PIXSIZE2", "PIXSIZE"], None)

    # Some headers store mm—very rare. If > 1000, likely nm; if > 100, likely µm is fine.
    def _as_um(v):
        try:
            v = float(v)
        except Exception:
            return None
        # Heuristic sanity: 2–30 µm typical. Leave as-is; user headers usually µm.
        return v

    xpix_um = _as_um(xpix_um)
    ypix_um = _as_um(ypix_um)

    # Focal length in mm: FOCALLEN, FOCAL, FOCALLENGTH
    f_mm = _get_any(header, ["FOCALLEN", "FOCALLENGTH", "FOCAL"], None)
    try:
        f_mm = float(f_mm) if f_mm is not None else None
    except Exception:
        f_mm = None

    if f_mm and (xpix_um or ypix_um):
        K = 206.264806
        if xpix_um:
            sx = K * (xpix_um * xbin) / f_mm
        else:
            sx = None
        if ypix_um:
            sy = K * (ypix_um * ybin) / f_mm
        else:
            sy = None
        # Make a reasonable single value
        if sx and sy:
            return (sx, sy, 0.5 * (sx + sy))
        if sx and not sy:
            return (sx, sx, sx)
        if sy and not sx:
            return (sy, sy, sy)
    return None

def estimate_pixel_scale_arcsec_per_pix(header) -> float | None:
    """
    Best-effort guess of pixel scale (arcsec/pixel). Returns a single representative mean value.
    Preference order:
      1) WCS-based (CD/CDELT/PC) via astropy.wcs
      2) Direct arcsec/pixel keywords
      3) Optics formula (focal length + pixel size + binning)
    """
    xb, yb = _binning_from_header(header)

    # # 1) WCS-based (already accounts for binning implicitly in WCS)
    # wcs_scales = _arcsec_from_wcs(header)
    # if wcs_scales:
    #     return wcs_scales[2]

    # 2) Direct arcsec/pixel keywords (likely already with binning; don't reapply)
    direct = _arcsec_from_direct_keywords(header, xb, yb)
    if direct:
        return direct[2]

    # 3) Optics formula (needs binning applied)
    # optics = _arcsec_from_optics(header, xb, yb)
    # if optics:
    #     return optics[2]

    return None

def _first_present(header, candidates: list[tuple[str, str]]):
    """Return the first (ra_key, dec_key) pair that both exist in header."""
    for ra_k, dec_k in candidates:
        if ra_k in header and dec_k in header:
            return ra_k, dec_k
    return None, None

def _parse_ra_dec_values(ra_val, dec_val):
    """
    Parse RA/Dec that may be sexagesimal strings or floats.
    Returns (ra_deg, dec_deg) in ICRS-equivalent numeric degrees (no frame transform here).
    Heuristic: if RA is numeric and <= 24, treat as hours; else degrees.
    """
    # Normalize unicode minus, stray spaces
    def _norm(x):
        if isinstance(x, str):
            return x.replace("−", "-").strip()
        return x

    ra_val, dec_val = _norm(ra_val), _norm(dec_val)

    # If strings, let Angle parse with appropriate units
    if isinstance(ra_val, str) or isinstance(dec_val, str):
        ra = Angle(ra_val, unit=u.hourangle) if isinstance(ra_val, str) else Angle(float(ra_val), unit=u.deg)
        dec = Angle(dec_val, unit=u.deg) if isinstance(dec_val, str) else Angle(float(dec_val), unit=u.deg)
        return ra.to(u.deg).value, dec.to(u.deg).value

    # Both numeric
    try:
        ra_f = float(ra_val)
        dec_f = float(dec_val)
    except Exception:
        return None, None

    # If RA likely in hours (≤ 24), convert; DEC is degrees
    if 0.0 <= abs(ra_f) <= 24.0:
        ra_deg = (ra_f * 15.0)
    else:
        ra_deg = ra_f
    return ra_deg, dec_f

def _frame_from_header(header):
    """
    Return an astropy coordinates frame callable for the given header,
    defaulting to ICRS when ambiguous.
    """
    # Common aliases
    radesys = (header.get("RADESYS") or header.get("RADECSYS") or "").strip().upper()
    equinox = header.get("EQUINOX", None)

    # If explicitly ICRS, we're done
    if radesys == "ICRS":
        return ICRS()

    # FK5 / J2000 (typical)
    if radesys == "FK5" or (equinox and float(equinox) >= 1980.0):
        return FK5(equinox=f"J{float(equinox) if equinox else 2000.0}")

    # FK4 / B1950
    if radesys == "FK4" or (equinox and float(equinox) < 1980.0):
        return FK4(equinox=f"B{float(equinox) if equinox else 1950.0}")

    # If RADESYS missing but EQUINOX present, assume FK5 for J*, FK4 for B*
    if equinox is not None:
        eq = float(equinox)
        return FK5(equinox=f"J{eq}") if eq >= 1980.0 else FK4(equinox=f"B{eq}")

    # Fallback
    return ICRS()

def guess_icrs_radec_from_header(header) -> tuple[float | None, float | None]:
    """
    Best-effort guess of center RA/Dec (degrees, ICRS) from FITS header.
    1) If CTYPE* looks like RA/DEC and CRVAL* exist → use CRVAL1/2 (assumed in degrees).
    2) Else fallback to several common pointing/target keys, parse units, and transform to ICRS.
    """
    # 1) WCS present?
    ctype1 = str(header.get("CTYPE1", "")).upper()
    ctype2 = str(header.get("CTYPE2", "")).upper()
    if ("RA" in ctype1 and "DEC" in ctype2) or ("DEC" in ctype1 and "RA" in ctype2):
        crval1 = header.get("CRVAL1", None)
        crval2 = header.get("CRVAL2", None)
        if crval1 is not None and crval2 is not None:
            # Assume degrees already in celestial frame indicated by RADESYS/EQUINOX; normalize to ICRS
            frame = _frame_from_header(header)
            try:
                sc = SkyCoord(float(crval1) * u.deg, float(crval2) * u.deg, frame=frame)
                sc_icrs = sc.icrs
                return sc_icrs.ra.deg, sc_icrs.dec.deg
            except Exception:
                pass  # fallthrough to non-WCS hints

    # 2) Fallback candidates (first present wins)
    candidates = [
        ("TELRA", "TELDEC"),
        ("RA_PNT", "DEC_PNT"),
        ("OBJCTRA", "OBJCTDEC"),
        ("TARGRA", "TARGDEC"),
        ("RA", "DEC"),
    ]
    ra_k, dec_k = _first_present(header, candidates)
    if ra_k and dec_k:
        ra_deg, dec_deg = _parse_ra_dec_values(header.get(ra_k), header.get(dec_k))
        if ra_deg is not None and dec_deg is not None:
            frame = _frame_from_header(header)
            try:
                sc = SkyCoord(ra_deg * u.deg, dec_deg * u.deg, frame=frame)
                sc_icrs = sc.icrs
                return sc_icrs.ra.deg, sc_icrs.dec.deg
            except Exception:
                # If frame transform fails, just return raw degrees
                return ra_deg, dec_deg

    return None, None


__all__ = [
    "estimate_pixel_scale_arcsec_per_pix",
    "guess_icrs_radec_from_header",
]
