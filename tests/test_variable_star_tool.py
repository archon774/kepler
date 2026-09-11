"""Offline public-pipeline tests for the variable-star port."""

from pathlib import Path
import math

import pytest
from astropy.table import Table

from tools.variable_star import (
    _validate_fold_period,
    _validate_periodogram_range,
    _validated_subdir,
    compute_variable_star_periodogram,
    fold_variable_star_lightcurve,
    list_variable_star_fixtures,
    load_variable_star_lightcurve,
    resolve_variable_star_fixture,
)


def test_bundled_fixture_runs_through_the_offline_variable_pipeline(artifact_dir) -> None:
    """Catches broken stage handoff or a fixture that cannot execute end-to-end."""
    listed = list_variable_star_fixtures()
    assert listed.count == 1
    resolved = resolve_variable_star_fixture("two_source_parity")
    assert resolved.path == listed.fixtures[0].path

    lightcurve = load_variable_star_lightcurve(resolved.path)
    assert lightcurve.errors == []
    assert lightcurve.rows_merged == 4
    assert lightcurve.artifact is not None
    assert Path(lightcurve.artifact.path).parent == artifact_dir / "variable_star"

    periodogram = compute_variable_star_periodogram(
        lightcurve.artifact.path,
        variable_star="source1",
        reference_star_magnitude=12.0,
    )
    assert periodogram.errors == []
    # The fixed TypeScript setting is 2,000, but its accumulating `< stop`
    # loop emits 2,001 rows for the default 0.1--1.0 range.
    assert periodogram.samples == 2001
    assert periodogram.artifact is not None

    folded = fold_variable_star_lightcurve(
        lightcurve.artifact.path,
        variable_star="source1",
        reference_star_magnitude=12.0,
        period=0.4,
    )
    assert folded.errors == []
    assert folded.rows_folded == 8
    assert folded.artifact is not None

    stage1 = Table.read(lightcurve.artifact.path, format="ascii.ecsv")
    assert list(stage1["mjd"]) == [59000.0, 59000.2, 59000.4, 59000.6]
    assert list(stage1["source1"]) == [14.0, 14.12, 14.04, 13.94]
    assert list(stage1["source2"]) == [12.0, 12.01, 12.0, 12.02]

    stage2 = Table.read(periodogram.artifact.path, format="ascii.ecsv")
    assert list(stage2["period"][:3]) == pytest.approx(
        [0.10000000000000002, 0.1001151955538169, 0.10023052380778998]
    )
    assert list(stage2["power"][:3]) == pytest.approx(
        [0.0011733762577678033, 0.03182175083315293, 0.031823436745865116]
    )

    stage3 = Table.read(folded.artifact.path, format="ascii.ecsv")
    assert list(stage3["phase"]) == pytest.approx(
        [0.5999999999985448, 0.5999999999970896, 0.4000000000014552, 0.4,
         0.1999999999985448, 0.19999999999708962, 1.4551693183761927e-12, 0.0]
    )
    assert list(stage3["magnitude"]) == pytest.approx([13.92, 14.11, 14.04, 14.0, 13.92, 14.11, 14.04, 14.0])


def test_variable_tool_reports_an_invalid_schema_without_an_artifact(tmp_path) -> None:
    """Catches accepting malformed raw CSV at the public tool boundary."""
    bad = tmp_path / "bad.csv"
    bad.write_text("id,mjd,mag\nsource,1,12\n", encoding="utf-8")

    result = load_variable_star_lightcurve(bad)

    assert result.artifact is None
    assert [error.code for error in result.errors] == ["invalid_schema"]


def test_registry_exposes_all_variable_star_pipeline_stages() -> None:
    """Catches a public stage that is implemented but unreachable to the agent loop."""
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    names = {
        "list_variable_star_fixtures",
        "resolve_variable_star_fixture",
        "load_variable_star_lightcurve",
        "compute_variable_star_periodogram",
        "fold_variable_star_lightcurve",
    }
    assert names <= TOOL_FUNCTIONS.keys()
    schemas = {schema["name"]: schema for schema in TOOL_SCHEMAS}
    assert schemas["load_variable_star_lightcurve"]["input_schema"]["required"] == ["path"]
    assert schemas["fold_variable_star_lightcurve"]["input_schema"]["required"] == [
        "path", "variable_star", "reference_star_magnitude", "period"
    ]


def test_public_validation_rejects_non_progressing_period_inputs() -> None:
    """Catches subnormal values that would otherwise make the copied loops hang."""
    with pytest.raises(ValueError, match="representable"):
        _validate_periodogram_range(5e-324, 1e-323)
    with pytest.raises(ValueError, match="representably"):
        _validate_fold_period(5e-324, [59000.0, 59000.2])


def test_public_validation_rejects_a_positive_step_that_cannot_advance_start() -> None:
    """Catches a huge adjacent range whose float increment rounds back to start."""
    start = 1e308
    with pytest.raises(ValueError, match="advance"):
        _validate_periodogram_range(start, math.nextafter(start, math.inf))


def test_public_validation_rejects_a_step_that_stalls_at_a_binade_boundary() -> None:
    """Catches a grid that advances once but stops after rounding to the next binade."""
    start = math.nextafter(2.0, 0.0)
    with pytest.raises(ValueError, match="every grid point"):
        _validate_periodogram_range(start, start + 1_000 * math.ulp(start))


def test_fold_validation_bounds_total_repeated_subtraction_work() -> None:
    """Catches allowing the per-row cycle allowance to multiply into a DoS."""
    with pytest.raises(ValueError, match="work limit"):
        _validate_fold_period(1e-7, [0.0] * 2_000 + [0.1])


def test_public_validation_rejects_artifact_directory_escape() -> None:
    """Catches a direct caller escaping the configured artifact directory."""
    with pytest.raises(ValueError, match="relative"):
        _validated_subdir("../../outside")


def test_public_validation_rejects_an_artifact_subdirectory_symlink(artifact_dir, tmp_path) -> None:
    """Catches a symlink below the artifact root redirecting writes outside it."""
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (artifact_dir / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="resolve"):
        _validated_subdir("escape")


def test_load_rejects_non_finite_or_unpaired_source_csv(tmp_path) -> None:
    """Catches accepting values that poison a bounded local pipeline."""
    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "id,mjd,mag,mag_error\nvariable,1,nan,0.1\ncomparison,1,12,0.1\n",
        encoding="utf-8",
    )

    result = load_variable_star_lightcurve(invalid)

    assert [error.code for error in result.errors] == ["invalid_schema"]


def test_fixture_resolution_bounds_untrusted_source_id_output(tmp_path) -> None:
    """Catches returning every user-controlled source ID to the agent loop."""
    source = tmp_path / "many_ids.csv"
    source.write_text(
        "id,mjd,mag,mag_error\na,1,12,0.1\nb,1,13,0.1\nc,1,14,0.1\n",
        encoding="utf-8",
    )

    result = resolve_variable_star_fixture(str(source))

    assert result.source_ids == ["a", "b"]
    assert result.source_count == 3


def test_load_rejects_a_non_regular_csv_path(tmp_path) -> None:
    """Catches blocking on a FIFO or device before the CSV row limit is reached."""
    result = load_variable_star_lightcurve(tmp_path)

    assert [error.code for error in result.errors] == ["not_a_file"]


def test_fixture_listing_has_a_bounded_count(monkeypatch, tmp_path) -> None:
    """Catches enumeration of every CSV in a caller-controlled directory."""
    from tools import variable_star

    monkeypatch.setattr(variable_star, "_MAX_FIXTURES", 1)
    for name in ("one.csv", "two.csv"):
        (tmp_path / name).write_text("id,mjd,mag,mag_error\na,1,12,0.1\nb,1,13,0.1\n", encoding="utf-8")

    result = list_variable_star_fixtures(tmp_path)

    assert [error.code for error in result.errors] == ["too_many_fixtures"]


def test_csv_row_limit_stops_before_materializing_the_remaining_input(monkeypatch, tmp_path) -> None:
    """Catches reading an attacker-controlled CSV to EOF before enforcing its row cap."""
    from tools import variable_star

    class Reader:
        fieldnames = ["id", "mjd", "mag", "mag_error"]

        def __iter__(self):
            for _ in range(variable_star._MAX_ROWS + 1):
                yield {"id": "a", "mjd": "1", "mag": "12", "mag_error": "0.1"}
            raise AssertionError("reader was consumed past the row limit")

    path = tmp_path / "rows.csv"
    path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(variable_star.csv, "DictReader", lambda _: Reader())

    with pytest.raises(ValueError, match="row limit"):
        variable_star._read_csv(path)
