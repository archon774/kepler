"""The recorded field-calibration ground truth, reachable as a tool result.

BL-4: ``test_data/fieldcal/`` and ``test_data/afterglow/`` carry a complete
cross-implementation parity chain -- Skynet's own ``calc_solution`` output,
Afterglow's API response, and Afterglow's published web-table value -- and
before this module nothing outside ``tests/`` could read any of it.

Everything here is offline. ``test_data/README.md`` spells out the chain for
NGC 5128 B::

    Kepler calc_solution        21.147659857998637   (bit-exact)
    Skynet recorded local fit   21.147659857998637
    Afterglow API              (21.14747923526837)   = 20.0 + 1.1474792352683736
    Afterglow web table         21.147                (3 dp, recorded by hand)

Two fixture families live under ``zp_solutions/``. ``ngc5128_b_002`` is the
full Afterglow-parity record and is the only one with a bundled frame
(``ngc5128_galaxy_b_001.fits``). ``ngc5286_b_{000,001,002}`` are the leaner
"bad values" fixture: ``calc_solution`` output and matched catalog rows, but no
Afterglow numbers and no bundled B frame (only ``ngc5286_globular_v_000.fits``
ships). ``skynet_zero_point`` -- ``calc_solution``'s
``catalog_mag = instrumental_mag + zero_point`` offset -- is recorded for all
four and reproduced bit-for-bit by :func:`solve_zeropoint_from_reference`.

Only ``KEPLER_FIELDCAL_DATA_DIR`` relocates the ``zp_solutions/`` search;
the bundled-frame and Afterglow web-table lookups always read the repo's own
``test_data/`` because they only make sense against the shipped fixtures.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from tools.calibration import solve_zeropoint_from_measurements
from tools.models import (
    ToolError,
    ToolWarning,
    ZeropointComparison,
    ZeropointReference,
    ZeropointSolution,
)

__all__ = [
    "FIELDCAL_DATA_DIR_ENV",
    "PARITY_ZP_TOLERANCE",
    "list_zeropoint_references",
    "load_zeropoint_reference",
    "solve_zeropoint_from_reference",
    "compare_zeropoint_to_reference",
]

#: Where the recorded solves are looked for. Overridable so a caller with
#: their own set of recorded solves does not have to move files into the repo.
FIELDCAL_DATA_DIR_ENV = "KEPLER_FIELDCAL_DATA_DIR"

#: The upstream diagnostic's own declared agreement threshold, in magnitudes.
#: Used when a recorded solve does not carry its own ``parity_zp_tolerance``.
PARITY_ZP_TOLERANCE = 0.0005

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: The bundled frame each recorded solve describes. The solve-directory name
#: (``ngc5128_b_002``) and the frame filename (``ngc5128_galaxy_b_001.fits``)
#: do not match: upstream's ``(1)``/``(2)`` directory suffixes were flattened
#: separately from the frame rename. Only ``ngc5128_b_002`` has a bundled
#: frame; the three NGC 5286 B solves describe ``ngc5286_globular_b_00N.fits``,
#: which are not in ``test_data/optical/``.
_BUNDLED_FRAME_BY_FIELD: dict[str, str | None] = {
    "ngc5128_b_002": "ngc5128_galaxy_b_001.fits",
    "ngc5286_b_000": None,
    "ngc5286_b_001": None,
    "ngc5286_b_002": None,
}


def _f(value: object) -> float | None:
    """Parse a possibly-empty CSV/JSON cell to a finite float or ``None``."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_not_none(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _fieldcal_data_dir(directory: str | Path | None = None) -> Path:
    if directory is not None:
        return Path(directory).expanduser()

    from tools.config import env_path

    default = _REPO_ROOT / "test_data" / "fieldcal"
    return env_path(FIELDCAL_DATA_DIR_ENV, default) or default


def _solutions_dir(directory: str | Path | None = None) -> Path:
    return _fieldcal_data_dir(directory) / "zp_solutions"


def _is_field_dir(path: Path) -> bool:
    return path.is_dir() and (
        (path / "fit_summary.json").is_file() or (path / "fit_data.csv").is_file()
    )


def _field_names(solutions_dir: Path) -> list[str]:
    if not solutions_dir.is_dir():
        return []
    return sorted(p.name for p in solutions_dir.iterdir() if _is_field_dir(p))


def _read_summary(field_dir: Path) -> dict:
    path = field_dir / "fit_summary.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _calibration_rows(field_dir: Path) -> tuple[list[dict[str, float | None]], list[ToolWarning]]:
    """The rows upstream marked ``used_for_calibration`` -- the exact input to
    ``calc_solution`` -- as ``{mag, mag_error, ref_mag, ref_mag_error}`` dicts.

    Both fixture families carry these four columns. Many cells are empty
    strings, so every read goes through :func:`_f`.
    """
    path = field_dir / "fit_data.csv"
    if not path.is_file():
        return [], [ToolWarning(code="missing_fit_data", message=f"No fit_data.csv in {field_dir.name}.")]

    rows: list[dict[str, float | None]] = []
    with path.open(newline="") as handle:
        for record in csv.DictReader(handle):
            flag = str(record.get("used_for_calibration", "")).strip().lower()
            if flag not in ("true", "1"):
                continue
            rows.append(
                {
                    "mag": _f(record.get("mag")),
                    "mag_error": _f(record.get("mag_error")),
                    "ref_mag": _f(record.get("ref_mag")),
                    "ref_mag_error": _f(record.get("ref_mag_error")),
                }
            )
    return rows, []


def _catalog_name(summary: dict) -> str | None:
    for key in ("catalog_queried", "catalogs", "catalogs_used"):
        value = summary.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
    return None


def _web_table_zero_point(frame_filename: str) -> float | None:
    """Afterglow's published web-table zero point for a bundled frame, if recorded."""
    path = _REPO_ROOT / "test_data" / "afterglow" / "afterglow_web_values_master.csv"
    if not path.is_file():
        return None
    with path.open(newline="") as handle:
        for record in csv.DictReader(handle):
            if (record.get("file") or "").strip() == frame_filename:
                return _f(record.get("Afterglow web zero_point"))
    return None


def _frame_path(field: str) -> tuple[str | None, list[ToolWarning]]:
    if field not in _BUNDLED_FRAME_BY_FIELD:
        return None, [
            ToolWarning(
                code="frame_not_bundled",
                message=f"No bundled-frame mapping is recorded for {field!r}; "
                "the solve is checked at the calc_solution level only.",
            )
        ]

    bundled = _BUNDLED_FRAME_BY_FIELD[field]
    if bundled is None:
        return None, [
            ToolWarning(
                code="frame_not_bundled",
                message=f"The frame for {field!r} (an NGC 5286 B exposure) is not "
                "bundled -- only ngc5286_globular_v_000.fits ships. The solve is "
                "checked at the calc_solution level only, not end to end from pixels.",
            )
        ]

    candidate = _REPO_ROOT / "test_data" / "optical" / bundled
    if candidate.is_file():
        return str(candidate), []
    return None, [
        ToolWarning(
            code="frame_not_bundled",
            message=f"{bundled} is not present in test_data/optical/.",
        )
    ]


def _load_reference(field: str, field_dir: Path) -> ZeropointReference:
    summary = _read_summary(field_dir)
    production = summary.get("production_calc_solution")
    production = production if isinstance(production, dict) else {}

    skynet_zp = _first_not_none(
        _f(production.get("zero_point")),
        _f(summary.get("local_zero_point")),
        _f(summary.get("zero_point")),
    )

    afterglow_base = _f(summary.get("afterglow_zero_point"))
    afterglow_correction = _f(summary.get("afterglow_zero_point_correction"))
    afterglow_zp = _f(summary.get("afterglow_calibrated_zero_point"))
    if afterglow_zp is None and afterglow_base is not None and afterglow_correction is not None:
        afterglow_zp = afterglow_base + afterglow_correction

    frame_path, warnings = _frame_path(field)
    rows, row_warnings = _calibration_rows(field_dir)
    warnings = warnings + row_warnings

    web_zp = _web_table_zero_point(Path(frame_path).name) if frame_path else None

    return ZeropointReference(
        field=field,
        frame_path=frame_path,
        catalog=_catalog_name(summary),
        num_calibration_sources=len(rows),
        skynet_zero_point=skynet_zp,
        afterglow_zero_point=afterglow_zp,
        afterglow_base=afterglow_base,
        afterglow_correction=afterglow_correction,
        web_table_zero_point=web_zp,
        parity_tolerance_mag=_f(summary.get("parity_zp_tolerance")),
        measurements=[dict(row) for row in rows],
        warnings=warnings,
    )


def list_zeropoint_references(
    directory: str | Path | None = None,
) -> list[ZeropointReference]:
    """Every recorded zero-point solve on local disk.

    Reads ``<KEPLER_FIELDCAL_DATA_DIR>/zp_solutions/*/`` (default
    ``test_data/fieldcal/zp_solutions/``). Returns an empty list -- not an
    error -- when the directory is absent.
    """
    solutions_dir = _solutions_dir(directory)
    return [
        _load_reference(name, solutions_dir / name)
        for name in _field_names(solutions_dir)
    ]


def load_zeropoint_reference(
    field: str, directory: str | Path | None = None
) -> ZeropointReference:
    """Load one recorded zero-point solve by field name (e.g. ``"ngc5128_b_002"``).

    A missing data directory or an unknown field is returned as an
    ``errors``-populated :class:`~tools.models.ZeropointReference`, never
    raised; the error message names the candidates or the
    ``KEPLER_FIELDCAL_DATA_DIR`` override.
    """
    solutions_dir = _solutions_dir(directory)
    if not solutions_dir.is_dir():
        return ZeropointReference(
            field=field,
            errors=[
                ToolError(
                    code="directory_not_found",
                    message=f"No recorded solves at {solutions_dir}. Set "
                    f"{FIELDCAL_DATA_DIR_ENV} to a directory containing a "
                    "zp_solutions/ folder.",
                )
            ],
        )

    field_dir = solutions_dir / field
    if not _is_field_dir(field_dir):
        available = _field_names(solutions_dir)
        return ZeropointReference(
            field=field,
            errors=[
                ToolError(
                    code="not_found",
                    message=f"No recorded solve named {field!r}. "
                    f"Available: {', '.join(available) or '(none)'}.",
                )
            ],
        )

    return _load_reference(field, field_dir)


def solve_zeropoint_from_reference(
    field: str, directory: str | Path | None = None
) -> ZeropointSolution:
    """Re-solve the zero point from a recorded solve's own calibration rows.

    This replays ``calc_solution`` over the exact ``(instrumental, reference)``
    magnitude pairs upstream fed it, so the result is bit-exact against
    ``skynet_zero_point``. It is *not* a pixel-level check -- nothing is
    re-measured from a frame here; see ``tools.photometry.calibrate_zeropoint``
    for that.
    """
    reference = load_zeropoint_reference(field, directory)
    if reference.errors:
        return ZeropointSolution(
            errors=list(reference.errors), warnings=list(reference.warnings)
        )
    return solve_zeropoint_from_measurements(reference.measurements, [])


def compare_zeropoint_to_reference(
    zero_point: float, field: str, directory: str | Path | None = None
) -> ZeropointComparison:
    """Place a computed zero point against a recorded solve.

    ``zero_point`` must be an ABSOLUTE zero point in magnitudes, as
    ``tools.calibration.solve_zeropoint_from_measurements`` and
    ``calc_solution`` return it. Afterglow's API instead reports ``20.0`` plus
    a correction; hand in the bare correction and this returns
    ``within_tolerance = False`` with an ``afterglow_base_convention`` warning
    rather than a silent 20-magnitude miss.
    """
    reference = load_zeropoint_reference(field, directory)
    if reference.errors:
        return ZeropointComparison(
            zero_point=zero_point,
            errors=list(reference.errors),
            warnings=list(reference.warnings),
        )

    tolerance = (
        reference.parity_tolerance_mag
        if reference.parity_tolerance_mag is not None
        else PARITY_ZP_TOLERANCE
    )
    warnings: list[ToolWarning] = []

    delta_vs_skynet = (
        zero_point - reference.skynet_zero_point
        if reference.skynet_zero_point is not None
        else None
    )

    delta_vs_afterglow = None
    if reference.afterglow_zero_point is not None:
        delta_vs_afterglow = zero_point - reference.afterglow_zero_point
        implied_correction = reference.afterglow_zero_point - 20.0
        if abs(zero_point - implied_correction) <= tolerance:
            warnings.append(
                ToolWarning(
                    code="afterglow_base_convention",
                    message=f"{zero_point} matches Afterglow's base-20 correction for "
                    f"{field!r}, not an absolute zero point. Add 20.0 before comparing: "
                    f"the absolute value is {reference.afterglow_zero_point}.",
                )
            )

    within_tolerance = (
        abs(delta_vs_skynet) <= tolerance if delta_vs_skynet is not None else None
    )

    return ZeropointComparison(
        zero_point=zero_point,
        reference=reference,
        delta_vs_skynet=delta_vs_skynet,
        delta_vs_afterglow=delta_vs_afterglow,
        within_tolerance=within_tolerance,
        tolerance_mag=tolerance,
        warnings=warnings,
    )
