"""WCS construction helpers for assisted plate solving."""

from __future__ import annotations

from typing import Tuple

import numpy as np
from astropy.wcs import WCS


def decompose_linear(m: np.ndarray) -> Tuple[float, float, int]:
    """Decompose a 2x2 linear map ``scale * R(theta) * flip`` -> (scale, angle_deg, parity).

    Inverse of the oriented solver's ``scale * R(theta) @ diag([parity, 1])``
    composition. ``parity = sign(det(m))``; the first column is un-flipped before
    the angle is read, so ``angle_deg`` is the on-sky rotation in the SAME
    convention the oriented fast path uses for its ``rotation_deg`` prior. The
    angle is in ``(-180, 180]`` (``atan2``).

    This is the canonical bridge from a solved pixel->tangent map (e.g. a blind
    triangle solve's ``scale * rotation``, or a WCS ``CD`` converted to rad/pix)
    back to the (rotation, parity) the oriented solver consumes.
    """
    det = float(np.linalg.det(m))
    parity = 1 if det >= 0 else -1
    mu = m @ np.array([[parity, 0.0], [0.0, 1.0]])  # un-flip -> det>0
    scale = float(np.sqrt(abs(det)))
    angle = float(np.degrees(np.arctan2(mu[1, 0], mu[0, 0])))
    return scale, angle, parity


def wcs_from_similarity(
    scale_rad_per_pix: float,
    rotation: np.ndarray,
    translation: np.ndarray,
    ra0_deg: float,
    dec0_deg: float,
) -> WCS:
    cd_rad_per_pix = scale_rad_per_pix * rotation
    cd_deg_per_pix = cd_rad_per_pix * (180.0 / np.pi)

    crpix = -np.linalg.solve(cd_rad_per_pix, translation)

    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ("RA---TAN", "DEC--TAN")
    wcs.wcs.crval = [float(ra0_deg), float(dec0_deg)]
    wcs.wcs.crpix = [float(crpix[0]), float(crpix[1])]
    wcs.wcs.cd = cd_deg_per_pix
    return wcs
