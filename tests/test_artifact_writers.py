"""What the artifact writers leave on disk when a step fails or repeats.

A reserved artifact name is an empty file, claimed atomically so two writers
sharing a root never receive one path. That fixed one bug and exposed three:
a writer that failed left the empty file behind, where ``list_artifacts``
reported it as a result; a reservation made outside a writer's ``try`` turned
an unwritable root into an exception out of the tool; and one table kept a
fixed name that a repeated run overwrote. These pin each, by the finding of
the MCP track's second review that named it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.table import Table

from tools import artifacts


def _files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file())


# --- the reservation itself ------------------------------------------------------


def test_discard_placeholder_removes_only_an_empty_file(tmp_path):
    empty = tmp_path / "empty.png"
    empty.touch()
    written = tmp_path / "written.png"
    written.write_bytes(b"\x89PNG")

    artifacts.discard_placeholder(empty)
    artifacts.discard_placeholder(written)
    artifacts.discard_placeholder(tmp_path / "absent.png")
    artifacts.discard_placeholder(None)

    assert _files(tmp_path) == [written]


def test_a_repeated_name_skips_past_the_highest_suffix_in_one_step(tmp_path):
    """Efficiency: probing _1, _2, ... cost one open per earlier file."""
    (tmp_path / "plot.png").touch()
    (tmp_path / "plot_7.png").touch()
    (tmp_path / "plot_x.png").touch()  # not a counter

    assert artifacts.reserve_path_in(tmp_path, "plot", "png") == tmp_path / "plot_8.png"


def test_a_table_is_written_beside_its_claimed_name_never_onto_it(artifact_dir, monkeypatch):
    """astropy's FITS writer, pointed at the reserved path with overwrite=True,
    deleted the placeholder before writing -- releasing the claimed name to
    another writer for the length of the write. The claimed path must exist,
    and not be the write's target, for the whole write."""
    real_write = Table.__dict__["write"]  # a descriptor; bound per instance below
    seen = []

    def watching(self, target, *args, **kwargs):
        claimed = artifact_dir / "s" / "t.fits"
        seen.append((Path(target) != claimed, claimed.is_file()))
        return real_write.__get__(self, Table)(target, *args, **kwargs)

    monkeypatch.setattr(Table, "write", watching)
    ref = artifacts.write_table(Table({"a": [1, 2]}), "t", subdir="s", fmt="fits")

    assert seen == [(True, True)]
    assert Path(ref.path) == artifact_dir / "s" / "t.fits"
    assert len(Table.read(ref.path)) == 2
    assert _files(artifact_dir) == [Path(ref.path)]


@pytest.mark.parametrize("fmt", ["ecsv", "csv", "fits"])
def test_a_table_gets_the_mode_every_other_artifact_gets(artifact_dir, fmt):
    """Third review: staged through mkstemp, tables came out 0600."""
    import os
    import stat

    umask = os.umask(0o022)
    try:
        ref = artifacts.write_table(Table({"a": [1]}), "t", fmt=fmt)
        text = artifacts.write_text("x", "note")
    finally:
        os.umask(umask)

    assert stat.S_IMODE(Path(ref.path).stat().st_mode) == 0o644
    assert stat.S_IMODE(Path(text.path).stat().st_mode) == 0o644


def test_an_interrupted_writes_staging_file_is_not_listed(artifact_dir):
    from tools.artifacts import list_artifact_files

    (artifact_dir / ".t.ecsv.abc123.part").write_text("partial")
    (artifact_dir / "t.ecsv").write_text("x")

    assert [m.file.path for m in list_artifact_files(artifact_dir)] == [str(artifact_dir / "t.ecsv")]


def test_a_failed_table_write_leaves_nothing(artifact_dir, monkeypatch):
    def refuse(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Table, "write", refuse)
    with pytest.raises(OSError):
        artifacts.write_table(Table({"a": [1]}), "t", subdir="s")

    assert _files(artifact_dir) == []


# --- finding 4: the pulsar writers report an unwritable root ----------------------


def test_sonify_reports_an_unwritable_root_as_write_failed(pulsar_path, monkeypatch):
    from tools import pulsar

    def refuse(*args, **kwargs):
        raise PermissionError("read-only artifact root")

    monkeypatch.setattr(pulsar.artifacts, "reserve_artifact_path", refuse)
    result = pulsar.sonify_pulsar(pulsar_path("b0329"), audio_seconds=0.5)

    assert [e.code for e in result.errors] == ["write_failed"]


def test_plot_reports_an_unwritable_root_as_write_failed(pulsar_path, monkeypatch):
    from tools import pulsar

    def refuse(*args, **kwargs):
        raise PermissionError("read-only artifact root")

    monkeypatch.setattr(pulsar.artifacts, "reserve_artifact_path", refuse)
    result = pulsar.plot_pulsar(str(pulsar_path("b0329")))

    assert [e.code for e in result.errors] == ["write_failed"]


def test_a_failed_pulsar_plot_leaves_no_placeholder(pulsar_path, artifact_dir, monkeypatch):
    from tools import pulsar

    def broken(*args, **kwargs):
        raise ValueError("cannot draw")

    monkeypatch.setattr(pulsar, "_render_plot", broken)
    result = pulsar.plot_pulsar(str(pulsar_path("b0329")))

    assert [e.code for e in result.errors] == ["plot_failed"]
    assert [p for p in _files(artifact_dir) if p.suffix == ".png"] == []


# --- finding 7: failed writers leave no 0-byte files ------------------------------


def test_a_failed_isochrone_fit_leaves_no_placeholders(artifact_dir, monkeypatch):
    from tools import hr_diagram

    tmp_path = artifact_dir

    def no_grid(*args, **kwargs):
        raise RuntimeError("no isochrone grid configured")

    monkeypatch.setattr(hr_diagram.isochrones, "fit_and_compare", no_grid)
    with pytest.raises(RuntimeError):
        hr_diagram._fit_and_compare(None, {}, "NGC 2682", "NGC_2682")

    assert _files(tmp_path) == []


def test_a_failed_spectrum_plot_leaves_no_placeholder(tmp_path, monkeypatch):
    from tools import radio_sources

    def broken(*args, **kwargs):
        raise ValueError("cannot draw")

    monkeypatch.setattr(radio_sources, "_plot_spectrum", broken)
    with pytest.raises(ValueError):
        radio_sources.analyze_source_spectrum(
            frequencies_hz=[1e8, 1e9, 1e10],
            fluxes_jy=[10.0, 3.0, 1.0],
            output_dir=str(tmp_path),
        )

    assert _files(tmp_path) == []


# --- findings 2 and 7: photometry's table and its zero-point plot -----------------


@pytest.fixture
def stub_photometry(monkeypatch):
    """run_photometry_on_target with the measurement and drawing stubbed out."""
    from tools import photometry

    zero_point = SimpleNamespace(verified=False, source="instrumental", value=None)
    source = SimpleNamespace(mag=None, exp_length=1.0)
    monkeypatch.setattr(
        photometry, "compute_photometry",
        lambda *args, **kwargs: (np.zeros((2, 2)), [source], zero_point),
    )
    monkeypatch.setattr(photometry, "magnitude_label_for", lambda zp: "instrumental")
    monkeypatch.setattr(
        photometry, "plot_photometry",
        lambda data, results, path, **kwargs: Path(path).write_bytes(b"png"),
    )
    monkeypatch.setattr(
        photometry, "_write_source_table",
        lambda results, path: Path(path).write_text("x,y\n"),
    )
    return photometry


def _bundled_frame() -> str:
    from tools import config

    frame = config.BUNDLED_DATA_DIR / "optical" / "m104_galaxy_v_000.fits"
    if not frame.is_file():
        pytest.skip("the bundled optical frames are not present")
    return str(frame)


def test_a_repeated_photometry_run_never_replaces_its_source_table(stub_photometry, tmp_path):
    """Finding 2: the table kept a fixed name while the plots were reserved."""
    first = stub_photometry.run_photometry_on_target(
        _bundled_frame(), use_field_cal=False, output_dir=str(tmp_path), write_source_table=True
    )
    second = stub_photometry.run_photometry_on_target(
        _bundled_frame(), use_field_cal=False, output_dir=str(tmp_path), write_source_table=True
    )

    tables = [a.path for run in (first, second) for a in run.artifacts if a.format == "csv"]
    assert len(tables) == 2 and tables[0] != tables[1]
    assert all(Path(t).is_file() for t in tables)


def test_a_zero_point_plot_that_draws_nothing_leaves_no_file(stub_photometry, tmp_path, monkeypatch):
    zero_point = SimpleNamespace(verified=True, source="apass", value=21.0, diagnostics={})
    source = SimpleNamespace(mag=None, exp_length=1.0)
    monkeypatch.setattr(
        stub_photometry, "compute_photometry",
        lambda *args, **kwargs: (np.zeros((2, 2)), [source], zero_point),
    )
    monkeypatch.setattr(stub_photometry, "plot_zero_point_solution", lambda zp, path: None)

    result = stub_photometry.run_photometry_on_target(
        _bundled_frame(), use_field_cal=False, output_dir=str(tmp_path)
    )

    assert [Path(a.path).name for a in result.artifacts] == ["m104_galaxy_v_000_photometry.png"]
    assert [p.name for p in _files(tmp_path)] == ["m104_galaxy_v_000_photometry.png"]


# --- finding 5: CASDA never prompts for a password --------------------------------


def test_casda_download_without_a_stored_password_is_refused_not_prompted(artifact_dir, monkeypatch):
    import keyring

    from tools import casda

    table = Table({"obs_publisher_did": ["x"], "dataproduct_type": ["image"]})

    class FakeCasda:
        def query_region(self, *args, **kwargs):
            return table

        def filter_out_unreleased(self, rows):
            return rows

        def login(self, *args, **kwargs):  # would prompt via getpass
            raise AssertionError("login was attempted without a stored password")

    monkeypatch.setattr(casda, "Casda", FakeCasda)
    monkeypatch.setattr(casda, "CASDA_OPAL_USERNAME", "someone@example.org")
    monkeypatch.setattr(keyring, "get_password", lambda service, user: None)

    result = casda.search_casda(ra_deg=83.8, dec_deg=-5.4, download=True)

    assert result.status == "partial"
    assert "keyring" in result.errors[0].message


def test_hr_artifacts_land_in_an_active_session_scope(artifact_dir):
    """Third review: the HR writers ignored scoped_artifacts."""
    from tools import hr_diagram

    with artifacts.scoped_artifacts("sessions/abc"):
        path = hr_diagram._output_path("hr_ngc", ".png")

    assert path == artifact_dir / "sessions" / "abc" / "hrdiagram" / "hr_ngc.png"
