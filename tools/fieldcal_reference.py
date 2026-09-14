"""The recorded field-calibration ground truth, reachable as a tool result.

BL-4: ``data/fieldcal/`` and ``data/afterglow/`` carry a complete
cross-implementation parity chain -- Skynet's own ``calc_solution`` output,
Afterglow's API response, and Afterglow's published web-table value -- and
before this module nothing outside ``tests/`` could read any of it.

Everything here is offline. ``data/README.md`` spells out the chain for
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

``ngc5128_b_002`` additionally carries the recorded VizieR responses the
run's catalog selection consumed -- ``apass_response.json`` (the full APASS
cone, 132 rows) and ``vsx_response.json`` (the variables the run filtered
against, 12 rows) -- so :func:`replay_field_calibration` can re-run the
whole selection offline and :func:`replay_catalog_sources` can hand either
the selected rows or the full response to a from-pixels solve.

Only ``KEPLER_FIELDCAL_DATA_DIR`` relocates the ``zp_solutions/`` search;
the bundled-frame and Afterglow web-table lookups always read the repo's own
``data/`` because they only make sense against the shipped fixtures.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from tools.calibration import solve_zeropoint_from_measurements
from tools.models import (
    CatalogResponseReference,
    FieldCalMatch,
    FieldCalReplay,
    ToolError,
    ToolWarning,
    ZeropointComparison,
    ZeropointReference,
    ZeropointSolution,
)

__all__ = [
    "FIELDCAL_DATA_DIR_ENV",
    "PARITY_ZP_TOLERANCE",
    "CATALOG_FIXTURES",
    "list_zeropoint_references",
    "load_zeropoint_reference",
    "solve_zeropoint_from_reference",
    "compare_zeropoint_to_reference",
    "load_catalog_response",
    "replay_catalog_sources",
    "replay_variable_sources",
    "replay_field_calibration",
    "load_ocl_reference",
]

#: Where the recorded solves are looked for. Overridable so a caller with
#: their own set of recorded solves does not have to move files into the repo.
FIELDCAL_DATA_DIR_ENV = "KEPLER_FIELDCAL_DATA_DIR"

#: The upstream diagnostic's own declared agreement threshold, in magnitudes.
#: Used when a recorded solve does not carry its own ``parity_zp_tolerance``.
PARITY_ZP_TOLERANCE = 0.0005

#: The two inputs an offline replay can be asked for, by name. ``selected_rows``
#: is the small bit-exact regression case: the rows ``fit_data.csv`` marks
#: ``used_for_calibration``, i.e. the catalog rows that are already known to
#: match. ``full_response`` is the end-to-end selection replay: the recorded
#: VizieR response for the whole field, from which the matches still have to
#: be chosen. Only ``ngc5128_b_002`` has the latter.
CATALOG_FIXTURES = ("selected_rows", "full_response")

#: A recorded VizieR response lives next to the solve it fed, one file per
#: catalog: ``<field>/apass_response.json``, ``<field>/vsx_response.json``.
_RESPONSE_FILENAME = "{catalog}_response.json"

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: The bundled frame each recorded solve describes. The solve-directory name
#: (``ngc5128_b_002``) and the frame filename (``ngc5128_galaxy_b_001.fits``)
#: do not match: upstream's ``(1)``/``(2)`` directory suffixes were flattened
#: separately from the frame rename. Only ``ngc5128_b_002`` has a bundled
#: frame; the three NGC 5286 B solves describe ``ngc5286_globular_b_00N.fits``,
#: which are not in ``data/optical/``.
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

    default = _REPO_ROOT / "data" / "fieldcal"
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
    path = _REPO_ROOT / "data" / "afterglow" / "afterglow_web_values_master.csv"
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

    candidate = _REPO_ROOT / "data" / "optical" / bundled
    if candidate.is_file():
        return str(candidate), []
    return None, [
        ToolWarning(
            code="frame_not_bundled",
            message=f"{bundled} is not present in data/optical/.",
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
    ``data/fieldcal/zp_solutions/``). Returns an empty list -- not an
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


def load_ocl_reference(frame_stem: str) -> dict:
    """The recorded Open/Clear/Lum filter-substitution sweep for a bundled frame.

    BL-6: ``data/fieldcal/ocl_filter_report.json`` records a full
    wcs -> photometry -> field-calibration sweep over ten M15 frames, keyed by
    upstream filename. The rename to ``m15_globular_lum_000.fits`` stranded it;
    ``data/frame_provenance.json`` restores the join.

    Takes a bundled frame stem (``"m15_globular_open_000"``) and returns the
    matching ``results`` entry from the report -- ``input_file``,
    ``best_filter``, ``winning_trial``, ``trials``. A stem with no recorded row
    (only the ten M15 OCL frames were swept) comes back as a ``dict`` carrying
    a ``not_found`` entry under ``errors``, never raised.

    Reads the bundled fixtures directly; ``KEPLER_FIELDCAL_DATA_DIR`` does not
    relocate them.
    """
    data_root = _REPO_ROOT / "data"
    provenance_path = data_root / "frame_provenance.json"
    report_path = data_root / "fieldcal" / "ocl_filter_report.json"

    if not provenance_path.is_file() or not report_path.is_file():
        return {
            "frame_stem": frame_stem,
            "errors": [
                {
                    "code": "fixture_missing",
                    "message": "frame_provenance.json or fieldcal/ocl_filter_report.json "
                    "is not present in data/.",
                }
            ],
        }

    frames = json.loads(provenance_path.read_text()).get("frames", {})
    upstream = frames.get(frame_stem)
    if upstream is None:
        return {
            "frame_stem": frame_stem,
            "errors": [
                {
                    "code": "not_found",
                    "message": f"No upstream filename is recorded for {frame_stem!r} in "
                    "frame_provenance.json.",
                }
            ],
        }

    report = json.loads(report_path.read_text())
    for row in report.get("results", []):
        if row.get("input_file") == upstream:
            return row

    return {
        "frame_stem": frame_stem,
        "upstream_file": upstream,
        "errors": [
            {
                "code": "not_found",
                "message": f"{frame_stem!r} maps to {upstream!r}, which has no row in "
                "ocl_filter_report.json -- only the ten M15 Open/Lum frames were swept.",
            }
        ],
    }


def _response_path(field_dir: Path, catalog: str) -> Path:
    return field_dir / _RESPONSE_FILENAME.format(catalog=catalog.lower())


def _read_response(field_dir: Path, catalog: str):
    """The parsed response fixture and the astropy table rebuilt from it, or
    ``None`` when the file is absent or not a recorded response -- a file
    that does not parse, or whose cells numpy or astropy reject, is treated
    like one that is not there, as ``_read_summary`` does, so a hand-made
    fixture never turns into a traceback out of a registered tool. The table
    is built once here and handed on, since building it is the validation.
    """
    path = _response_path(field_dir, catalog)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    columns, rows = loaded.get("columns"), loaded.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    if not all(isinstance(spec, dict) and "name" in spec and "dtype" in spec for spec in columns):
        return None
    if not all(isinstance(row, list) and len(row) == len(columns) for row in rows):
        return None
    try:
        table = _response_table(loaded)
    except Exception:  # noqa: BLE001 -- a dtype numpy does not know, a cell a column
        # cannot hold (OverflowError), a nested cell (numpy.ma.MaskError): whatever
        # the rebuild rejects makes the file not a recorded response.
        return None
    return loaded, table


def _response_table(payload: dict):
    """Rebuild the astropy table astroquery returned, column dtypes and masks
    included, so the catalog plugin's own ``table_to_sources`` sees exactly
    what the live path saw. A JSON ``null`` is a masked cell; a float32
    magnitude column stays float32, which is what keeps the reference
    magnitudes bit-exact against ``fit_data.csv``. The recorded dtype fixes
    a string column's *kind*, not its width -- the width is whatever the
    values need, so nothing is silently truncated.
    """
    import numpy as np
    from astropy.table import MaskedColumn, Table

    columns = []
    rows = payload["rows"]
    for index, spec in enumerate(payload["columns"]):
        dtype = np.dtype(spec["dtype"])
        cells = [row[index] for row in rows]
        mask = [cell is None for cell in cells]
        if dtype.kind in "US":
            data = np.array(["" if cell is None else cell for cell in cells], dtype=str)
        else:
            data = np.array([0 if cell is None else cell for cell in cells], dtype=dtype)
        if data.ndim != 1:
            raise ValueError(f"column {spec['name']!r} has non-scalar cells")
        columns.append(
            MaskedColumn(
                data,
                mask=mask,
                name=spec["name"],
                unit=spec.get("unit"),
                description=spec.get("description"),
            )
        )
    return Table(columns, masked=True)


def _recorded_catalog(field_dir: Path) -> str:
    """The catalog the recorded solve queried, per its ``fit_summary.json``;
    APASS when the summary does not say. One name drives the response file,
    the plugin mapping and the calibration settings."""
    return _catalog_name(_read_summary(field_dir)) or "APASS"


def load_catalog_response(
    field: str, catalog: str | None = None, directory: str | Path | None = None
) -> CatalogResponseReference:
    """The provenance of a recorded VizieR response, without its rows.

    Reads ``<field>/<catalog>_response.json`` -- ``catalog`` defaulting to
    the one the recorded solve queried -- and reports what was asked
    (``query``), of what release, when, with which columns and under what
    licence (``provenance``). A field that has no recorded response for
    ``catalog`` comes back with a ``fixture_missing`` error naming the file,
    never raised; only ``ngc5128_b_002`` ships one.
    """
    field_dir = _solutions_dir(directory) / field
    catalog = catalog or _recorded_catalog(field_dir)
    loaded = _read_response(field_dir, catalog)
    if loaded is None:
        return CatalogResponseReference(
            field=field,
            catalog=catalog,
            errors=[
                ToolError(
                    code="fixture_missing",
                    message=f"No recorded {catalog} response for {field!r}: "
                    f"{_response_path(field_dir, catalog).name} is not present in "
                    f"{field_dir}, or is not readable as a recorded response.",
                )
            ],
        )
    payload, _table = loaded

    # The rows were validated by _read_response; the descriptive blocks are
    # taken as they are when they have the expected shape and left empty
    # otherwise, so a hand-edited fixture degrades rather than raises.
    def _block(key: str) -> dict:
        value = payload.get(key)
        return dict(value) if isinstance(value, dict) else {}

    def _text(key: str) -> str | None:
        value = payload.get(key)
        return None if value is None else str(value)

    return CatalogResponseReference(
        field=field,
        catalog=_text("catalog") or catalog,
        path=str(_response_path(field_dir, catalog)),
        vizier_catalog=_text("vizier_catalog"),
        vizier_table=_text("vizier_table"),
        query=_block("query"),
        provenance=_block("provenance"),
        columns=[str(spec["name"]) for spec in payload["columns"]],
        row_count=len(payload["rows"]),
    )


def _sources_from_response(field: str, catalog: str, directory: str | Path | None) -> list:
    """The recorded response as ``CatalogSource`` rows, through the same
    plugin mapping the live query uses. ``[]`` when nothing was recorded."""
    loaded = _read_response(_solutions_dir(directory) / field, catalog)
    if loaded is None:
        return []
    _payload, table = loaded

    # The bound plugin (declaration + VizieR backend) supplies the column
    # mapping; nothing here issues a query.
    from algorithms.query.registry import CATALOGS

    try:
        return list(CATALOGS[catalog].table_to_sources(table))
    except (KeyError, TypeError, ValueError):
        # The plugin's mapping needs columns the fixture does not carry: not a
        # recorded response for this catalog, reported by the callers as absent.
        return []


def _selected_row_sources(field: str, directory: str | Path | None) -> list:
    from algorithms.fieldcal.schemas import CatalogSource, Mag

    field_dir = _solutions_dir(directory) / field
    csv_path = field_dir / "fit_data.csv"
    if not csv_path.is_file():
        return []

    sources: list[CatalogSource] = []
    with csv_path.open(newline="") as handle:
        for record in csv.DictReader(handle):
            flag = str(record.get("used_for_calibration", "")).strip().lower()
            if flag not in ("true", "1"):
                continue
            ra_hours = _f(record.get("local_catalog_ra"))
            dec_degs = _f(record.get("local_catalog_dec"))
            ref_mag = _f(record.get("local_ref_mag"))
            if ra_hours is None or dec_degs is None or ref_mag is None:
                continue
            ref_mag_error = _f(record.get("local_ref_mag_error"))
            catalog_name = (record.get("local_catalog_name") or "").strip() or None
            band = (record.get("filter") or "").strip() or None
            source_id = (record.get("id") or "").strip() or None
            sources.append(
                CatalogSource(
                    id=source_id,
                    catalog_name=catalog_name,
                    ra_hours=ra_hours,
                    dec_degs=dec_degs,
                    ref_mag=ref_mag,
                    ref_mag_error=ref_mag_error,
                    mags={band: Mag(value=ref_mag, error=ref_mag_error)} if band else {},
                )
            )
    return sources


def replay_catalog_sources(
    field: str,
    directory: str | Path | None = None,
    *,
    fixture: str = "selected_rows",
    catalog: str | None = None,
) -> list:
    """Rebuild the catalog rows for an offline solve, from one of two fixtures.

    Returns ``list[algorithms.fieldcal.schemas.CatalogSource]`` for
    ``tools.photometry.calibrate_zeropoint``, so the real extract -> measure
    -> match -> solve chain runs against real catalog values with no network.
    ``fixture`` names which recorded input, and is one of
    :data:`CATALOG_FIXTURES`:

    ``"selected_rows"`` (default) -- the rows Skynet actually matched: the
    ``used_for_calibration`` rows of ``fit_data.csv``, with position and
    reference magnitude. This is the small, bit-exact regression case. It
    exercises photometry -> matching -> ref-mag -> solve, but not selection:
    every row it carries is already known to match, and the rows that failed
    to match were never written down, so ``fit_summary.json``'s
    ``num_not_selected_by_field_cal`` cannot be reproduced from it. Only
    ``ngc5128_b_002`` carries these columns; every other field returns ``[]``.

    ``"full_response"`` -- the end-to-end selection replay: the recorded
    response for the whole field (``<catalog>_response.json`` -- ``catalog``
    defaulting to the one the recorded solve queried -- a 10-arcmin cone
    that contains the frame's footprint), rebuilt as an astropy table and
    mapped through the catalog plugin's own ``table_to_sources``, so the rows
    are what the live query returned before its footprint clipping -- ids
    included, which is to say none: VizieR did not return the requested
    ``recno``. Only ``ngc5128_b_002`` has a recorded response. A solve over
    these rows must *choose* its matches; clip them to the frame first, as
    the live path does (``algorithms.query.geometry.clip_sources_to_wcs``),
    and pair them with :func:`replay_variable_sources`, because the recorded
    run filtered VSX variables out before matching and does not reproduce
    without them. ``replay_field_calibration`` and
    ``tools.photometry.calibrate_zeropoint(catalog_fixture=...)`` do both.

    Neither path opens a socket. An unrecognised ``fixture`` is a caller
    error and raises ``ValueError``.
    """
    if fixture not in CATALOG_FIXTURES:
        raise ValueError(
            f"fixture must be one of {', '.join(CATALOG_FIXTURES)}; got {fixture!r}"
        )
    if fixture == "full_response":
        field_dir = _solutions_dir(directory) / field
        return _sources_from_response(field, catalog or _recorded_catalog(field_dir), directory)
    return _selected_row_sources(field, directory)


def replay_variable_sources(field: str, directory: str | Path | None = None) -> list:
    """The recorded VSX rows for a field, for ``perform_field_calibration``'s
    ``variable_sources`` -- the variables the recorded run filtered its catalog
    candidates against before matching. ``[]`` where none were recorded, which
    ``perform_field_calibration`` treats as "nothing to filter". No socket.
    """
    return _sources_from_response(field, "VSX", directory)


def _recorded_detections(field_dir: Path) -> tuple[list, list[str]]:
    """The photometered sources the recorded run selected from, and the ids
    it selected, both in ``fit_data.csv`` order.

    Mirrors upstream's diagnostic exactly: a row is a detection when its
    ``mag`` and ``flux`` are finite and non-zero; null uncertainties are kept
    as ``None`` (``calc_solution`` distinguishes "no error" from "zero
    error"). ``mag`` is on the recorded ``fit_data.csv`` scale, so the solve
    lands on ``production_calc_solution`` rather than on Afterglow's base-20
    correction.
    """
    from algorithms.fieldcal.schemas import PhotometryData

    detections: list[PhotometryData] = []
    selected_ids: list[str] = []
    path = field_dir / "fit_data.csv"
    if not path.is_file():
        return detections, selected_ids
    with path.open(newline="") as handle:
        for record in csv.DictReader(handle):
            source_id = (record.get("id") or "").strip() or None
            if str(record.get("used_for_calibration", "")).strip().lower() in ("true", "1"):
                selected_ids.append(source_id)
            mag, flux = _f(record.get("mag")), _f(record.get("flux"))
            if not mag or not flux:
                continue
            detections.append(
                PhotometryData(
                    id=source_id,
                    x=_f(record.get("x")),
                    y=_f(record.get("y")),
                    ra_hours=_f(record.get("ra_hours")),
                    dec_degs=_f(record.get("dec_degs")),
                    mag=mag,
                    mag_error=_f(record.get("mag_error")),
                    flux=flux,
                    flux_error=_f(record.get("flux_error")),
                    filter=(record.get("filter") or "").strip() or None,
                )
            )
    return detections, selected_ids


def _variable_sources_warning(field: str, response: CatalogResponseReference) -> ToolWarning:
    """Why a replay is running without the variable-star filter: the VSX
    response is not there, or it is there and yields no usable row. Shared by
    the selection replay and the from-pixels fixture path."""
    if response.errors:
        what = f"No recorded VSX response for {field!r}"
    else:
        what = (
            f"The recorded VSX response for {field!r} ({response.row_count} rows) "
            "has no row the VSX mapping can use"
        )
    return ToolWarning(
        code="variable_sources_not_recorded",
        message=f"{what}; the variable-star filter the recorded run applied before "
        "matching is skipped, so the selection may differ from the recorded one.",
    )


def _detection_indices(positions: list[tuple], detections: list) -> list[int | None]:
    """Which detection each matched source came from, by pixel position.

    A matched source keeps its detection's ``x``/``y`` exactly, and matches
    come out in detection order -- so the first detection at or after the
    last one attributed is the answer. That is what makes a recorded list
    with exact-duplicate rows (``fit_data.csv`` has SRC317/SRC319)
    unambiguous: mutual nearest-neighbour matching keeps the lower index of
    identical points, and so does this. A position not found ahead of the
    cursor is looked for from the start, so a re-ordered result still
    resolves; one found nowhere is ``None``.
    """
    indices: list[int | None] = []
    cursor = 0
    for position in positions:
        found = next(
            (i for i in range(cursor, len(detections)) if (detections[i].x, detections[i].y) == position),
            None,
        )
        if found is None:
            found = next(
                (i for i in range(0, cursor) if (detections[i].x, detections[i].y) == position),
                None,
            )
        indices.append(found)
        if found is not None:
            cursor = found + 1
    return indices


def replay_field_calibration(
    field: str, directory: str | Path | None = None
) -> FieldCalReplay:
    """Re-run a recorded field calibration end to end, catalog selection included.

    This is the full-response replay. The recorded detections (``fit_data.csv``)
    and the recorded APASS and VSX responses go through
    ``perform_field_calibration`` the way upstream's diagnostic drove it --
    ``use_provided_photometry``, so the recorded instrumental magnitudes are
    consumed rather than re-measured -- with the bundled frame's header
    supplying the WCS, the epoch and the filter. So, unlike
    :func:`solve_zeropoint_from_reference`, the 35 calibration sources are
    *chosen* here: from the 132 candidates in the cone, after the VSX filter,
    by mutual nearest-neighbour matching against 298 detections. The result
    reports the counts, each match, the solve, and the comparison to the
    recorded numbers; ``selection_matches_recorded`` says whether the replay
    chose exactly the recorded rows in the recorded order.

    Needs the recorded response and the bundled frame, so only
    ``ngc5128_b_002`` can run; any other field returns the errors that stop
    it. No socket is opened on any path.
    """
    reference = load_zeropoint_reference(field, directory)
    if reference.errors:
        return FieldCalReplay(field=field, errors=list(reference.errors))

    field_dir = _solutions_dir(directory) / field
    summary = _read_summary(field_dir)
    catalog = reference.catalog or "APASS"
    errors: list[ToolError] = []
    warnings: list[ToolWarning] = list(reference.warnings)

    response = load_catalog_response(field, catalog, directory)
    cone = replay_catalog_sources(field, directory, fixture="full_response", catalog=catalog)
    if response.errors:
        errors.extend(response.errors)
    elif not cone:
        errors.append(
            ToolError(
                code="fixture_empty",
                message=f"The recorded {catalog} response for {field!r} "
                f"({response.row_count} rows) has no row the {catalog} mapping can "
                "use, so there is nothing to select from.",
            )
        )
    if reference.frame_path is None:
        errors.append(
            ToolError(
                code="frame_not_bundled",
                message=f"No bundled frame for {field!r}; the replay takes its WCS, "
                "epoch and filter from the frame header.",
            )
        )
    if errors:
        return FieldCalReplay(field=field, catalog=catalog, errors=errors, warnings=warnings)

    variable_response = load_catalog_response(field, "VSX", directory)
    variables = replay_variable_sources(field, directory)
    if not variables:
        warnings.append(_variable_sources_warning(field, variable_response))

    detections, selected_ids = _recorded_detections(field_dir)
    if not detections:
        return FieldCalReplay(
            field=field,
            catalog=catalog,
            frame_path=reference.frame_path,
            errors=[ToolError(code="missing_fit_data", message=f"No detections in {field_dir.name}/fit_data.csv.")],
            warnings=warnings,
        )

    import numpy as np
    from astropy.io import fits

    from algorithms.fieldcal.field_cal import perform_field_calibration
    from algorithms.fieldcal.schemas import PhotometricCalibrationSettings
    from algorithms.photometry.source_extraction import build_wcs_from_header
    from algorithms.query.geometry import clip_sources_to_wcs
    from algorithms.skylib_lite.util.angle import angdist

    inputs = dict(
        field=field,
        catalog=catalog,
        frame_path=reference.frame_path,
        num_catalog_rows=response.row_count,
        num_variable_rows=variable_response.row_count,
        num_detected_sources=len(detections),
    )
    try:
        header = fits.getheader(reference.frame_path)
        wcs = build_wcs_from_header(header)
        if wcs is None:
            raise ValueError("Missing WCS needed for calibration")
    except Exception as exc:  # noqa: BLE001 -- unreadable frame, no WCS
        return FieldCalReplay(
            **inputs,
            errors=[ToolError(code="field_calibration_failed", message=str(exc))],
            warnings=warnings,
        )

    # The live query path clips a response to the detector before the solve
    # sees a row (algorithms.query.runner, WCS mode); the recorded cone goes
    # through the same stage. The clipped objects are the cone's own, so a
    # candidate maps back to its position in the recorded response.
    cone_index = {id(source): index for index, source in enumerate(cone)}
    candidates = clip_sources_to_wcs(cone, [wcs])
    variables = clip_sources_to_wcs(variables, [wcs])
    inputs.update(num_catalog_candidates=len(candidates), num_variable_sources=len(variables))

    try:
        # The recorded run's settings: the defaults (min_snr 10, source_match_tol
        # 5 px, variable_check_tol 5 arcsec) plus its own strict_filter_parity
        # flag. With use_provided_photometry no pixel is read, so the image
        # array is a placeholder, as it was upstream.
        settings = PhotometricCalibrationSettings(
            catalogs=[catalog],
            strict_filter_parity=bool(summary.get("strict_filter_parity", False)),
        )
        outcome = perform_field_calibration(
            header.copy(),
            np.zeros((2, 2), dtype=float),
            wcs=wcs,
            field_cal_settings=settings,
            catalog_sources=candidates,
            variable_sources=variables,
            detected_sources=detections,
            use_provided_photometry=True,
        )
    except Exception as exc:  # noqa: BLE001 -- no match, no convergence
        return FieldCalReplay(
            **inputs,
            errors=[ToolError(code="field_calibration_failed", message=str(exc))],
            warnings=warnings,
        )
    if outcome is None or outcome[0] is None:
        return FieldCalReplay(
            **inputs,
            errors=[ToolError(code="no_solution", message="field calibration did not converge")],
            warnings=warnings,
        )
    zero_point, result = outcome

    # A matched source keeps its detection's position and carries the id its
    # candidate went in with -- the recorded response has none, so that is the
    # positional fieldcal_source_<n> perform_field_calibration assigns.
    handed_ids = {
        (str(source.id) if source.id is not None else f"fieldcal_source_{index + 1}"): source
        for index, source in enumerate(candidates)
    }
    detection_indices = _detection_indices([(s.x, s.y) for s in result.phot_results], detections)
    matches: list[FieldCalMatch] = []
    for source, detection_index in zip(result.phot_results, detection_indices):
        detection = detections[detection_index] if detection_index is not None else None
        candidate = handed_ids.get(str(source.id))
        separation = None
        if detection is not None and candidate is not None:
            separation = float(
                angdist(detection.ra_hours, detection.dec_degs, candidate.ra_hours, candidate.dec_degs)
                * 3600.0
            )
        matches.append(
            FieldCalMatch(
                detected_id=detection.id if detection is not None else None,
                catalog_index=cone_index.get(id(candidate)) if candidate is not None else None,
                catalog_id=str(source.id) if source.id is not None else None,
                catalog_ra_deg=candidate.ra_hours * 15.0 if candidate is not None else None,
                catalog_dec_deg=candidate.dec_degs if candidate is not None else None,
                separation_arcsec=separation,
                mag=_f(source.mag),
                mag_error=_f(source.mag_error),
                ref_mag=_f(source.ref_mag),
                ref_mag_error=_f(source.ref_mag_error),
            )
        )

    solution = ZeropointSolution(
        zero_point=_f(zero_point),
        zero_point_error_mag=_f(result.zero_point_error_mag),
        zero_point_slop=_f(result.zero_point_slop),
        limmag5=_f(result.limmag5),
        rej_percent=_f(result.rej_percent),
        source_count=len(result.phot_results),
    )
    comparison = _compare_to_reference(float(zero_point), reference)

    # fit_summary.json's own counts; the matched count falls back to the rows
    # the CSV flags, which is the same number for every recorded solve.
    recorded_matched = summary.get("num_catalog_matched")
    if not isinstance(recorded_matched, int):
        recorded_matched = len(selected_ids) or None
    recorded_not_selected = summary.get("num_not_selected_by_field_cal")
    if not isinstance(recorded_not_selected, int):
        recorded_not_selected = None

    return FieldCalReplay(
        **inputs,
        fixture="full_response",
        num_matched=len(matches),
        num_catalog_not_selected=len(candidates) - len(matches),
        num_detections_not_selected=len(detections) - len(matches),
        recorded_num_matched=recorded_matched,
        recorded_num_not_selected=recorded_not_selected,
        selection_matches_recorded=[m.detected_id for m in matches] == selected_ids,
        matches=matches,
        solution=solution,
        comparison=comparison,
        warnings=warnings + list(comparison.warnings),
    )


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
    return _compare_to_reference(zero_point, reference)


def _compare_to_reference(zero_point: float, reference: ZeropointReference) -> ZeropointComparison:
    """:func:`compare_zeropoint_to_reference` over a reference already loaded."""
    field = reference.field
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
