"""Seam module: cross-domain callables that field calibration needs but does not own.

EXTRACTION SEAM.  In Skynet these were plain sibling-module imports inside
``skynet_db/runners/observation_asset_processing/optical_data_processing/``:

    from .photometry import run_photometry
    from .source_extraction import get_source_radec, run_source_extraction
    from .wcs import build_wcs_for_processing_run, solve_wcs

None of those are field-calibration algorithms — they are aperture/PSF
photometry, SEP source extraction, and plate solving, which live in Kepler's
own ``photometry/`` and ``wcs/`` folders.  They are re-exposed here as
overridable module-level names so that:

  * ``fieldcal`` imports cleanly with nothing else installed, and
  * a host application wires the real implementations in with one assignment,
    e.g. ``fieldcal.deps.run_photometry = my_photometry_runner``.

Call sites in ``field_cal.py`` use ``deps.<name>(...)`` (rather than a
``from .deps import <name>`` binding) precisely so that late injection works.

Nothing in this module performs or alters any calibration math.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "FieldCalDependencyError",
    "build_wcs_for_processing_run",
    "get_source_radec",
    "run_photometry",
    "run_source_extraction",
    "solve_wcs",
]


class FieldCalDependencyError(NotImplementedError):
    """Raised when a severed cross-domain dependency has not been provided."""


def _missing(name: str, original: str, home: str):
    def _stub(*_args: Any, **_kwargs: Any):
        raise FieldCalDependencyError(
            f"fieldcal.deps.{name} has not been provided. "
            f"EXTRACTED: was `{original}` in Skynet; belongs in Kepler/{home}/. "
            f"Assign an implementation: `fieldcal.deps.{name} = <callable>`."
        )

    _stub.__name__ = name
    return _stub


# EXTRACTED: was `from .photometry import run_photometry`
# (skynet_db/runners/observation_asset_processing/optical_data_processing/photometry.py).
# Signature: run_photometry(data, header, sources, settings, wcs=None,
#                           background=None, background_rms=None)
#            -> list[PhotometryData]
run_photometry = _missing(
    "run_photometry", "from .photometry import run_photometry", "photometry"
)

# EXTRACTED: was `from .source_extraction import run_source_extraction`.
# Signature: run_source_extraction(data, header, settings, file_id=None)
#            -> (list[SourceExtractionData], background, background_rms)
run_source_extraction = _missing(
    "run_source_extraction",
    "from .source_extraction import run_source_extraction",
    "photometry",
)

# EXTRACTED: was `from .source_extraction import get_source_radec`.
# Proper-motion-corrected sky position of a detected source.
# Signature: get_source_radec(source, epoch, wcs) -> (ra_hours, dec_degs)
get_source_radec = _missing(
    "get_source_radec", "from .source_extraction import get_source_radec", "photometry"
)

# EXTRACTED: was `from .wcs import build_wcs_for_processing_run`.
# The Skynet implementation is:
#     build_wcs_from_header(header) or build_wcs_from_processing_run_solution(processing_run)
# i.e. FITS-header WCS first, then a fallback that reconstructs the WCS from
# persisted processing-run DB rows.  The DB fallback is ORM persistence and is
# dropped by this extraction; a header-only implementation reproduces the
# behaviour field calibration actually depends on.
# Signature: build_wcs_for_processing_run(processing_run, header) -> WCS | None
build_wcs_for_processing_run = _missing(
    "build_wcs_for_processing_run",
    "from .wcs import build_wcs_for_processing_run",
    "wcs",
)

# EXTRACTED: was `from .wcs import solve_wcs`; used only by the batch
# zero-point export driver, never by the calibration algorithm itself.
# Signature: solve_wcs(processing_run, header, data, tmpdir, extraction_settings=None)
#            -> (WCS | None, solution)
solve_wcs = _missing("solve_wcs", "from .wcs import solve_wcs", "wcs")
