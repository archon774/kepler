"""Configuration for the Atlas plate solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional


@dataclass
class AtlasConfig:
    catalog: str = "ucac5"
    catalog_roots: Mapping[str, Path] = field(default_factory=dict)
    # Deadline for the blind triangle matcher, measured from the start of each
    # attempt. None = unbounded; pass a number to bound it.
    #
    # Scope is the matcher loop only: not extraction, not the catalog query, not
    # the oriented path, and the matched-extraction retry gets its own fresh
    # allowance. Callers that need a bound on the whole solve own that wall
    # clock themselves — SkyNode does exactly this, wrapping the call at 90 s
    # and setting this field a margin below so the uncancellable executor thread
    # self-aborts first.
    timeout_s: Optional[float] = None
    max_catalog_stars: int = 10000
    max_image_stars: int = 500
    # Source extraction: PSF-matched peak detector (see extract.sources). The
    # legacy raw-threshold detector is the PRIMARY path (it already solves the
    # full well-exposed fleet); the matched detector recovers faint stars on
    # shallow/star-starved frames and is invoked by the backend only as a FALLBACK
    # after a primary-extraction solve fails — so it never regresses or
    # false-positives a frame the primary path already handles. These knobs are
    # the matched detector's parameters when that fallback runs.
    use_matched_extraction: bool = False          # primary-path toggle (backend flips on for retry)
    extract_matched_filter_fwhm_pix: float = 2.5  # PSF-match kernel FWHM [px]
    extract_detect_nsig: float = 3.5              # matched-filter detection significance
    n_tri_obs: int = 15000
    n_tri_cat: int = 50000
    invariant_tol: float = 0.006
    match_tol_arcsec: float = 5.0
    refine_center: bool = True
    thin: int = 1
    debug: bool = False
    catalog_pad_frac = 1.0  # +50% radius
    catalog_max_radius_deg = None  # or e.g. 2.0

    # ---- Oriented ("on-the-fly check") fast path knobs ----
    # Used only when a rotation prior is supplied (rotation/parity/scale known).
    oriented_max_image_stars: int = 80       # brightest detected sources to use
    oriented_max_catalog_stars: int = 40000  # cap before subsample (voting is cheap;
                                             # keep stars so sparse fields aren't
                                             # diluted out of the vote even at 1° boxes)
    oriented_offset_bin_arcsec: float = 8.0  # Hough vote bin (≈ a few pixels)
    oriented_match_tol_arcsec: float = 6.0   # NN match tol (covers TAN-vs-SIP scatter)
    # Acceptance floors for a TIGHT search; the solver scales them UP with the
    # pointing radius (a wider search has more chances for a coincidental match).
    # Validated on 150 real frames at ~10' radius: 100% solve, 0 false positives.
    oriented_min_inliers: int = 6            # accept: min verified matches (tight base)
    oriented_min_votes: int = 4              # min stars supporting a shift peak (tight base)
    oriented_n_peaks: int = 12               # top vote peaks to verify (reject false peaks)
    oriented_min_fraction: float = 0.30      # accept: min frac of sources verified
                                             # (true solves ~0.6-0.95; false ~0.2)
    # Bounded refinement: a candidate's free-fit similarity must stay within these
    # of the locked prior (set ≥ the operator's pointing-calibration uncertainty +
    # margin). Corrects real drift AND rejects false matches (which need a big warp).
    oriented_rot_tol_deg: float = 2.0        # max |rotation - prior|
    oriented_scale_dev: float = 0.015        # max |scale/prior - 1|
    # Tight-core verification (dense-field false-positive rejector). The loose
    # inlier-fraction gate is defeated in crowded fields (e.g. globular clusters):
    # the match tolerance saturates, so a WRONG-orientation alignment still finds a
    # neighbour for most sources (~70% fraction, ~tol/2 RMS) and passes. A TRUE
    # solve additionally has a dense CORE of sub-arcsec matches; a spurious one has
    # almost none in that core. So require a minimum count AND fraction of the
    # matched inliers to fall within a tight tolerance. Validated: true M22 solve
    # ~0.2" median residual vs spurious ~4-5".
    oriented_tight_tol_arcsec: float = 1.5   # "tight core" residual tolerance
    oriented_min_tight_inliers: int = 6      # min matches inside the tight core
    oriented_min_tight_fraction: float = 0.25  # min frac of loose inliers in the core

    def resolve_catalog(self) -> tuple[str, Path]:
        catalog = self.catalog.strip().lower()
        if catalog in self.catalog_roots:
            return catalog, self.catalog_roots[catalog]
        raise ValueError(f"Unsupported catalog: {self.catalog}")
