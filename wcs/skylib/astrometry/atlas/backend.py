"""Atlas backend integration."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

# EXTRACTED: was `from skylib.astrometry.types import ...` — import made relative.
from ..types import (
    SolveAttempt,
    SolveFailure,
    SolveMethod,
    SolveRequest,
    SolveSolution,
)

from .config import AtlasConfig
from .solve.solver import solve as atlas_solve
from .solve.oriented import solve_oriented

#: Maps each solver's own miss reason onto the normalized public vocabulary.
#: The raw reason stays in ``metadata["reason"]`` — this is the value callers
#: persist and group by, so it is deliberately coarse and stable.
_FAILURE_REASONS = {
    # blind (triangle) solver
    "missing_fov": SolveFailure.BAD_INPUT,
    "bad_fov_or_scale": SolveFailure.BAD_INPUT,
    "empty_catalog": SolveFailure.NO_CATALOG,
    "insufficient_catalog": SolveFailure.NO_CATALOG,
    "no_sources": SolveFailure.NO_SOURCES,
    "no_triangles": SolveFailure.NO_MATCH,
    "no_match": SolveFailure.NO_MATCH,
    "timeout": SolveFailure.TIMEOUT,
    "no_confident_match_coarse": SolveFailure.VERIFICATION_FAILED,
    "verification_failed": SolveFailure.VERIFICATION_FAILED,
    # oriented (offset-vote) solver
    "too_few_sources": SolveFailure.NO_SOURCES,
    "no_offset_votes": SolveFailure.NO_MATCH,
    "insufficient_inliers": SolveFailure.VERIFICATION_FAILED,
    "insufficient_fraction": SolveFailure.VERIFICATION_FAILED,
    "loose_match": SolveFailure.VERIFICATION_FAILED,
}


def _normalize_failure(metadata: dict) -> Optional[str]:
    """Map a solver's raw miss reason onto the public vocabulary.

    An unrecognized reason falls back to NO_MATCH rather than None so a miss is
    never recorded as reasonless; the raw string remains in the metadata.
    """
    reason = (metadata or {}).get("reason")
    if reason is None:
        return None
    return _FAILURE_REASONS.get(str(reason), SolveFailure.NO_MATCH)


class AtlasBackend:
    name = "atlas"

    def is_available(self) -> bool:
        return True

    def solve(self, request: SolveRequest, config: Optional[AtlasConfig]) -> SolveSolution:
        if not isinstance(config, AtlasConfig):
            raise ValueError("Atlas config is required")
        if request.image_path is None:
            raise ValueError("image_path must be provided for Atlas backend")

        catalog_roots = dict(config.catalog_roots) if config.catalog_roots else {}

        if not catalog_roots.get("ucac5"):
            ucac5_root = os.getenv("SKYLIB_UCAC5_ROOT")
            if ucac5_root and Path(ucac5_root).exists():
                catalog_roots["ucac5"] = Path(ucac5_root)

        config.catalog_roots = catalog_roots

        # Fast "on-the-fly" path: orientation (rotation/parity) and scale are
        # known (locked by a prior calibration); only the pointing offset is
        # unknown. Dispatch to the offset-voting solver.
        if request.rotation_deg is not None:
            parity_sign = -1 if request.parity is False else 1

            def _oriented(cfg: AtlasConfig) -> SolveSolution:
                result = solve_oriented(
                    request.image_path,
                    cfg,
                    ra0_deg=float(request.ra_hours) * 15.0,
                    dec0_deg=float(request.dec_degs),
                    scale_arcsec_per_pix=0.5 * (float(request.min_scale) + float(request.max_scale)),
                    rotation_deg=float(request.rotation_deg),
                    parity_sign=parity_sign,
                    pointing_radius_deg=float(request.radius),
                )
                sol = SolveSolution(backend=self.name)
                sol.wcs = result.wcs
                sol.metadata = result.metadata
                return sol

            return self._run(request, config, _oriented, SolveMethod.ORIENTED)

        fov_guess = None
        if request.fov is not None:
            fov_guess = (float(request.fov), float(request.fov))

        def _blind(cfg: AtlasConfig) -> SolveSolution:
            result = atlas_solve(
                request.image_path,
                cfg,
                ra0_deg=float(request.ra_hours) * 15.0,
                dec0_deg=float(request.dec_degs),
                scale_range_arcsec_per_pix=(float(request.min_scale), float(request.max_scale)),
                fov_guess_deg=fov_guess,
            )
            sol = SolveSolution(backend=self.name)
            sol.wcs = result.wcs
            sol.metadata = result.metadata
            return sol

        return self._run(request, config, _blind, SolveMethod.BLIND)

    @classmethod
    def _run(
        cls,
        request: SolveRequest,
        config: AtlasConfig,
        run,
        method: str,
    ) -> SolveSolution:
        """Run a solve and attach the diagnostics every attempt must carry.

        Written once, before any hit/miss branch, so the fields cannot be
        populated on success and forgotten on failure.
        """
        started = time.perf_counter()
        solution = cls._with_matched_fallback(config, run)
        duration_sec = time.perf_counter() - started

        metadata = solution.metadata or {}
        solution.attempt = SolveAttempt.from_request(request, method)
        # Wall clock spans extraction and any matched-extraction retry, so it is
        # what the caller waited for — not the inner solver's own elapsed_s.
        solution.duration_sec = float(duration_sec)
        # `n_sources_extracted` is the consistent pre-cap count added for this
        # contract; `n_sources` is the older per-branch key kept for SkyNode's
        # gate, and is the fallback for any path that only sets that one.
        source_count = metadata.get("n_sources_extracted")
        if source_count is None:
            source_count = metadata.get("n_sources")
        solution.source_count = (
            int(source_count) if isinstance(source_count, (int, float)) else None
        )
        solution.failure_reason = (
            None if solution.solved else _normalize_failure(metadata)
        )
        return solution

    @staticmethod
    def _with_matched_fallback(config: AtlasConfig, run) -> SolveSolution:
        """Run a solve; on failure retry once with the matched-filter extractor.

        The legacy raw-threshold detector is primary (it solves the well-exposed
        fleet with no regressions). When it yields too few stars to solve — shallow
        or partly-clouded frames — the PSF-matched peak detector recovers the faint
        stars the legacy path erodes away, so the retry rescues frames that would
        otherwise miss. The fallback only runs after a genuine miss, so it can
        neither regress nor false-positive a frame the primary path already solved.
        """
        sol = run(config)
        if sol.wcs is not None or config.use_matched_extraction:
            return sol
        retry_cfg = replace(config, use_matched_extraction=True)
        retry = run(retry_cfg)
        if retry.wcs is not None:
            retry.metadata = {**(retry.metadata or {}), "matched_fallback": True}
            return retry
        # Both extractors missed. Keep the primary result — it is the canonical
        # path, and its source count is the one callers gate on — but record that
        # the retry ran and what it saw, so a double miss is not reported as a
        # single one.
        sol.metadata = {
            **(sol.metadata or {}),
            "matched_fallback_attempted": True,
            "matched_fallback_reason": (retry.metadata or {}).get("reason"),
            "matched_fallback_n_sources": (retry.metadata or {}).get("n_sources"),
        }
        return sol


__all__ = ["AtlasBackend"]
