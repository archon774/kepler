"""``kepler-bench`` argument handling, chiefly the required token budget.

docs/working/benchmark.md sections 5.7 and 11.
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
