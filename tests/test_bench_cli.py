"""``kepler-bench`` argument handling, chiefly the required token budget.

docs/benchmarking/harness.md sections 5.7 and 11.
"""

from __future__ import annotations

import json

import pytest

from tools import artifacts, config
from tools.bench.cli import build_parser, main


@pytest.fixture(autouse=True)
def artifact_root(monkeypatch, tmp_path):
    root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    return root


def test_max_tokens_is_required_for_a_live_backend(capsys):
    """Four backends x a suite x repeats against metered APIs is a
    self-inflicted billing risk, and there is no default because a default
    budget is a number nobody thinks about."""

    assert main(["run", "smoke", "--backend", "anthropic/claude-opus-5"]) == 2
    assert "--max-tokens is required" in capsys.readouterr().err


def test_a_replay_only_run_needs_no_budget(tmp_path, capsys):
    out = tmp_path / "run"
    assert main(["run", "smoke", "--backend", "replay/smoke", "--out", str(out)]) == 0
    record = json.loads((out / "run.json").read_text())
    assert record["runs"][0]["outcome"] == "end_turn"


def test_a_run_with_no_backend_is_refused(capsys):
    assert main(["run", "smoke"]) == 2
    assert "at least one --backend" in capsys.readouterr().err


def test_dry_run_prints_the_ceiling_without_spending_anything(capsys):
    assert main(["run", "smoke", "--backend", "replay/smoke", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "upper bound on tokens" in out
    assert "1 task(s) x 1 repeat(s)" in out


def test_a_replay_only_run_refuses_sockets_without_being_asked(tmp_path, monkeypatch):
    """A run with no live backend has nothing to talk to; `--offline` is
    implied rather than something an operator has to remember."""

    import socket

    # `_run` imports no_sockets from the harness at call time (the CLI
    # stays import-light), so the harness module is where to patch it.
    from tools.bench import harness

    inside: list[bool] = []
    real_guard = harness.no_sockets

    def recording_guard():
        guard = real_guard()

        class _Watched:
            def __enter__(self):
                guard.__enter__()
                # Inside the guard, constructing a socket must refuse.
                try:
                    socket.socket()
                except AssertionError:
                    inside.append(True)
                else:  # pragma: no cover - the guard failed to engage
                    inside.append(False)
                return None

            def __exit__(self, *exc):
                return guard.__exit__(*exc)

        return _Watched()

    monkeypatch.setattr(harness, "no_sockets", recording_guard)
    out = tmp_path / "run"
    assert main(["run", "smoke", "--backend", "replay/smoke", "--out", str(out)]) == 0
    assert inside == [True]


def test_offline_can_be_asked_for_explicitly_alongside_a_live_backend(tmp_path):
    """The flag exists for a mixed run: a replayed model beside a live one,
    where the operator wants the whole thing refused a socket anyway."""

    parser = build_parser()
    args = parser.parse_args(
        ["run", "core", "--backend", "ollama/x", "--max-tokens", "1", "--offline"]
    )
    assert args.offline is True


def test_repeated_backends_are_deduplicated(tmp_path):
    out = tmp_path / "run"
    main(
        [
            "run",
            "smoke",
            "--backend",
            "replay/smoke",
            "--backend",
            "replay/smoke",
            "--out",
            str(out),
        ]
    )
    record = json.loads((out / "run.json").read_text())
    assert record["config"]["backends"] == ["replay/smoke"]


def test_the_parser_exposes_the_four_verbs_documented_in_section_11():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(["run", "core", "--backend", "ollama/qwen3.8:27b-mlx"])
    assert args.verb == "run"
    assert args.backend == ["ollama/qwen3.8:27b-mlx"]


# --- compare --------------------------------------------------------------


def test_compare_renders_the_matrix_over_a_run_directory(tmp_path, capsys):
    out = tmp_path / "run"
    main(["run", "smoke", "--backend", "replay/smoke", "--out", str(out)])
    capsys.readouterr()
    assert main(["compare", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "# Kepler model benchmark" in printed
    assert "## Scores" in printed
    assert "## Diagnostics" in printed
    assert (out / "report.md").exists()
    assert (out / "report.json").exists()


def test_compare_grades_an_ungraded_run_rather_than_telling_you_to(tmp_path):
    """Grading is free and repeatable; a compare over an ungraded run should
    produce the matrix, not another command to type."""

    out = tmp_path / "run"
    main(
        [
            "run",
            "smoke",
            "--backend",
            "replay/smoke",
            "--out",
            str(out),
            "--no-grade",
        ]
    )
    assert not (out / "grades.json").exists()
    assert main(["compare", str(out)]) == 0
    assert (out / "grades.json").exists()


def test_run_implies_grade_unless_told_otherwise(tmp_path):
    out = tmp_path / "run"
    main(["run", "smoke", "--backend", "replay/smoke", "--out", str(out)])
    grades = json.loads((out / "grades.json").read_text())
    assert grades["grades"][0]["answer"]["passed"] is True


# --- record ---------------------------------------------------------------


def test_an_argument_value_is_parsed_as_json_where_it_parses():
    """`null`, numbers and booleans must reach the tool as themselves rather
    than as strings: that distinction is the whole of the
    null-argument-fidelity check."""

    from tools.bench.cli import _coerce

    assert _coerce("null") is None
    assert _coerce("5") == 5
    assert _coerce("true") is True
    assert _coerce("NGC 6334") == "NGC 6334"


def test_a_malformed_record_argument_is_refused(capsys):
    assert main(["record", "core/x", "--tool", "search_ned", "--argument", "name"]) == 2
    assert "NAME=VALUE" in capsys.readouterr().err


def test_record_refuses_a_class_l_tool(capsys):
    """Replaying compute_pulsar_periodogram would replace the measurement
    with a guess about the measurement."""

    with pytest.raises(ValueError, match="class-L"):
        main(
            [
                "record",
                "pulsar/x",
                "--tool",
                "compute_pulsar_periodogram",
                "--argument",
                "path=x",
            ]
        )


# --- answers: reading what the model actually said ------------------------


def _replay_run(tmp_path):
    out = tmp_path / "run"
    assert main(["run", "smoke", "--backend", "replay/smoke", "--out", str(out)]) == 0
    return out


def test_answers_prints_the_question_beside_the_reply(tmp_path, capsys):
    """Every other verb reduces a session to a verdict. A check that fires is
    a claim about a piece of prose, and the only way to tell a real failure
    from a regex artefact is to read the prose."""

    out = _replay_run(tmp_path)
    assert main(["answers", str(out)]) == 0
    printed = capsys.readouterr().out
    record = json.loads((out / "run.json").read_text())
    task_id = record["runs"][0]["task_id"]
    assert f"## `{task_id}`" in printed
    assert "replay/smoke" in printed or "smoke" in printed


def test_answers_needs_no_grades_file(tmp_path, capsys):
    """An ungraded run still has answers worth reading, and grading here would
    make a read-only verb write."""

    out = _replay_run(tmp_path)
    (out / "grades.json").unlink(missing_ok=True)
    assert main(["answers", str(out)]) == 0
    assert "ungraded" in capsys.readouterr().out


def test_answers_filters_to_nothing_without_failing(tmp_path, capsys):
    out = _replay_run(tmp_path)
    assert main(["answers", str(out), "--task", "no-such-task"]) == 0
    assert "No sessions matched." in capsys.readouterr().err
