"""The run loop: the smoke suite end to end, the no-socket guard (B2),
run.json completeness (B4), and the token budget (B5).

docs/working/benchmark.md sections 5.5-5.7. Everything here runs under a plain
`uv run pytest`: offline, deterministic, no API keys, no daemon, no new CI job.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.llm_fakes import StubBackend
from tools import artifacts, config
from tools.bench.harness import (
    BudgetExceeded,
    RunConfig,
    corpus_digest,
    no_sockets,
    run_suite,
)
from tools.bench.tasks import load_suite
from tools.llm.replay_backend import ReplayBackend
from tools.llm.types import ModelResponse, ToolCallBlock, Usage

#: Absolute, so a test that chdirs (to exercise a relative --out) still finds
#: the corpus.
_REPO = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = _REPO / "benchmarks/fixtures"
SMOKE_SUITE = _REPO / "benchmarks/suites/smoke"
SMOKE_TRANSCRIPT = _REPO / "benchmarks/transcripts/smoke.json"


@pytest.fixture()
def artifact_root(monkeypatch, tmp_path):
    root = tmp_path / "artifacts"
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", root)
    return root


@pytest.fixture()
def smoke():
    return load_suite(SMOKE_SUITE, fixture_root=FIXTURE_ROOT)


def _config(out, **kwargs):
    return RunConfig(
        suite_id="smoke", backends=("replay/smoke",), out=Path(out), **kwargs
    )


def _replay():
    return {"replay/smoke": ReplayBackend.from_file(SMOKE_TRANSCRIPT)}


# --- end to end -----------------------------------------------------------


def test_the_smoke_suite_runs_end_to_end_offline(artifact_root, smoke, tmp_path):
    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke,
        backends=_replay(),
        config=_config(out),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    assert len(record.runs) == 1
    run = record.runs[0]
    assert run.outcome == "end_turn"
    assert not run.incomplete
    # The whole point of the smoke suite: it is fast enough to live in the
    # default test suite rather than needing a CI job of its own.
    assert run.wall_ms < 2000


def test_the_run_directory_holds_the_four_files_a_grader_reads(
    artifact_root, smoke
):
    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke, backends=_replay(), config=_config(out), fixture_root=FIXTURE_ROOT, out=out
    )
    directory = record.runs[0].directory
    assert (directory / "session_manifest.json").exists()
    assert (directory / "events.jsonl").exists()
    assert (directory / "answer.txt").exists()
    # error.txt exists only when the session raised.
    assert not (directory / "error.txt").exists()


def test_answer_txt_is_the_final_turn_unbounded(artifact_root, smoke):
    """The manifest bounds assistant_text at 4,000 characters, so a
    must_not_match on a long answer would otherwise be graded against a
    truncated one."""

    out = artifact_root / "bench" / "run-1"
    long_answer = "The listing is partial. " * 400
    backend = ReplayBackend(
        [
            ModelResponse(stop_reason="tool_use", text="narrating turn one",
                          tool_calls=(ToolCallBlock(call_id="c1", name="list_pulsar_scans", arguments={}),)),
            ModelResponse(stop_reason="end_turn", text=long_answer),
        ],
        name="long",
    )
    record = run_suite(
        smoke,
        backends={"replay/long": backend},
        config=_config(out),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    answer = (record.runs[0].directory / "answer.txt").read_text()
    assert len(answer) > 4000
    # And it is the *final* turn only: a model that narrates its tool use for
    # six turns and then answers is graded on the answer, not the narration.
    assert "narrating turn one" not in answer

    manifest = json.loads(
        (record.runs[0].directory / "session_manifest.json").read_text()
    )
    assert manifest["turns"][-1]["assistant_text"].endswith("[truncated]")


def test_events_jsonl_carries_the_full_tool_results_the_manifest_omits(
    artifact_root, smoke
):
    """must_source_value has nowhere else to look for the numbers a model
    actually saw: the manifest's own `notes` key says payloads are omitted."""

    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke, backends=_replay(), config=_config(out), fixture_root=FIXTURE_ROOT, out=out
    )
    lines = [
        json.loads(line)
        for line in (record.runs[0].directory / "events.jsonl").read_text().splitlines()
    ]
    finished = [e for e in lines if e["event"] == "ToolCallFinished"]
    assert finished
    assert "scans" in finished[0]["result"]
    assert finished[0]["duration_ms"] is not None


def test_the_sessions_artifacts_land_inside_the_run_directory(artifact_root, smoke):
    """Which is what makes must_report_artifact_path checkable against files
    that are still there when grading runs later."""

    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke, backends=_replay(), config=_config(out), fixture_root=FIXTURE_ROOT, out=out
    )
    directory = record.runs[0].directory
    manifest = json.loads((directory / "session_manifest.json").read_text())
    assert Path(manifest["artifact_directory"]) == directory


def test_repeats_share_nothing(artifact_root, smoke):
    out = artifact_root / "bench" / "run-1"
    backends = {
        "replay/smoke": ReplayBackend(
            load_smoke_responses() * 3, name="smoke"
        )
    }
    record = run_suite(
        smoke,
        backends=backends,
        config=_config(out, repeats=3),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    directories = [run.directory for run in record.runs]
    assert [d.name for d in directories] == ["r1", "r2", "r3"]
    assert len(set(directories)) == 3
    manifests = {
        json.loads((d / "session_manifest.json").read_text())["session_id"]
        for d in directories
    }
    assert len(manifests) == 3


def load_smoke_responses():
    from tools.llm.replay_backend import load_transcript

    return list(load_transcript(SMOKE_TRANSCRIPT))


# --- B2: no socket --------------------------------------------------------


def test_a_replay_run_opens_no_socket(artifact_root, smoke):
    """The requirement. Every class-R tool is replayed and no class-L tool
    queries anything, so a socket construction during a run is a bug that
    would otherwise show up as latency in someone's scoreboard."""

    out = artifact_root / "bench" / "run-1"
    with no_sockets():
        record = run_suite(
            smoke,
            backends=_replay(),
            config=_config(out),
            fixture_root=FIXTURE_ROOT,
            out=out,
        )
    assert record.runs[0].outcome == "end_turn"


def test_the_guard_actually_refuses(artifact_root):
    import socket

    with no_sockets():
        with pytest.raises(AssertionError, match="opened a socket"):
            socket.socket()
    # And it is restored afterwards.
    socket.socket().close()


# --- B4: every run states its inputs -------------------------------------


def test_run_json_carries_every_knob(artifact_root, smoke):
    out = artifact_root / "bench" / "run-1"
    run_suite(
        smoke,
        backends=_replay(),
        config=_config(out, repeats=2, temperature=0.0, seed=7, max_tokens=1_000_000),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    record = json.loads((out / "run.json").read_text())
    for key in (
        "run_id",
        "started_at",
        "finished_at",
        "host",
        "git_head",
        "corpus_dirty",
        "corpus",
        "env_overrides",
        "config",
        "backends",
        "dry_run_ceiling_tokens",
        "tokens_used",
        "runs",
    ):
        assert key in record, key
    assert record["config"]["repeats"] == 2
    assert record["config"]["seed"] == 7
    assert record["config"]["max_tokens"] == 1_000_000
    # The system prompt is ~270 lines; the hash is recorded rather than the
    # text, so two runs can be compared without carrying it twice.
    assert len(record["config"]["system_prompt_sha256"]) == 64
    assert "system_prompt" not in record["config"]
    assert record["backends"]["replay/smoke"]["provider"] == "replay"
    assert record["backends"]["replay/smoke"]["capabilities"]["schema_dialect"]


def test_the_corpus_digest_hashes_every_task_file(smoke):
    digest = corpus_digest(smoke, FIXTURE_ROOT)
    assert len(digest["suite"]) == 64
    assert set(digest["tasks"]) == {task.id for task in smoke}
    assert all(len(value) == 64 for value in digest["tasks"].values())


def test_corpus_dirty_is_surfaced_rather_than_suppressed(artifact_root, smoke):
    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke, backends=_replay(), config=_config(out), fixture_root=FIXTURE_ROOT, out=out
    )
    # True, False, or None when git could not answer -- "we could not tell"
    # and "it was clean" are different statements about a recorded run.
    assert record.corpus_dirty in (True, False, None)
    assert "corpus_dirty" in json.loads((out / "run.json").read_text())


# --- B5: the token budget -------------------------------------------------


def _budget_backend(turns: int, per_turn: int):
    return StubBackend(
        [
            ModelResponse(
                stop_reason="tool_use",
                tool_calls=(
                    ToolCallBlock(call_id=f"c{n}", name="list_pulsar_scans", arguments={}),
                ),
                usage=Usage(input_tokens=per_turn, output_tokens=0),
            )
            for n in range(turns)
        ]
        + [ModelResponse(stop_reason="end_turn", text="done")],
        spec="openai/fake",
    )


def test_a_run_crossing_the_budget_stops_and_keeps_partial_results(
    artifact_root, smoke
):
    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke,
        backends={"openai/fake": _budget_backend(10, 1000)},
        config=_config(out, max_tokens=2500),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    run = record.runs[0]
    assert run.outcome == "budget_exceeded"
    assert run.incomplete
    # Partial results are kept and clearly marked partial.
    assert (run.directory / "events.jsonl").exists()
    assert "token budget" in (run.directory / "error.txt").read_text()


def test_the_budget_is_checked_before_dispatch_not_after(artifact_root, smoke):
    """Checking afterwards means the spend has already happened. With a
    ceiling of 1000 and 1000 tokens per turn, exactly one turn runs."""

    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke,
        backends={"openai/fake": _budget_backend(10, 1000)},
        config=_config(out, max_tokens=1000),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    assert record.usage_total == 1000
    assert record.runs[0].outcome == "budget_exceeded"


def test_a_replay_backend_is_exempt_from_the_budget(artifact_root, smoke):
    """A transcript cannot run away. Ollama is not exempt: a local daemon
    costs no money but a runaway loop still costs hours."""

    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke,
        backends=_replay(),
        config=_config(out, max_tokens=1),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    assert record.runs[0].outcome == "end_turn"


def test_the_dry_run_ceiling_is_an_upper_bound_printed_before_the_first_call(
    artifact_root, smoke
):
    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke,
        backends=_replay(),
        config=_config(out, repeats=2),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    # tasks x repeats x max_turns x the per-turn output ceiling.
    assert record.dry_run_ceiling == 6 * 2 * 1 * 4096


# --- failures are contained ----------------------------------------------


def test_a_task_that_raises_is_recorded_and_the_run_continues(artifact_root, smoke):
    out = artifact_root / "bench" / "run-1"
    record = run_suite(
        smoke,
        backends={"replay/short": ReplayBackend([], name="short")},
        config=_config(out),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    run = record.runs[0]
    assert run.outcome == "error"
    assert "TranscriptExhausted" in (run.directory / "error.txt").read_text()
    assert (out / "run.json").exists()


# --- a task's env override ------------------------------------------------


def test_a_tasks_env_override_is_applied_and_restored(artifact_root, tmp_path):
    """A task can shrink KEPLER_MAX_FRAMES to exercise the truncation
    warning; the override must not leak into the next task."""

    import os

    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "t.yaml").write_text(
        "id: t\nprompt: list the frames\nmax_turns: 3\n"
        "env:\n  KEPLER_MAX_FRAMES: '5'\n"
        'expect:\n  answer:\n    must_not_match: ["I refuse to answer"]\n',
        encoding="utf-8",
    )
    (suite_dir / "suite.yaml").write_text(
        "id: s\ndescription: d\ntasks: [t]\n", encoding="utf-8"
    )
    suite = load_suite(suite_dir, fixture_root=FIXTURE_ROOT)

    seen = []

    class _Probe(ReplayBackend):
        def complete(self, **kwargs):
            seen.append(os.environ.get("KEPLER_MAX_FRAMES"))
            return super().complete(**kwargs)

    before = os.environ.get("KEPLER_MAX_FRAMES")
    out = artifact_root / "bench" / "run-1"
    run_suite(
        suite,
        backends={
            "replay/x": _Probe([ModelResponse(stop_reason="end_turn", text="ok")])
        },
        config=_config(out),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    assert seen == ["5"]
    assert os.environ.get("KEPLER_MAX_FRAMES") == before


# --- path handling --------------------------------------------------------


def test_a_relative_out_path_works(artifact_root, smoke, monkeypatch, tmp_path):
    """The CLI's own default is `--out artifacts/bench/<run-id>`, a relative
    path. Every directory downstream is joined or compared against the
    absolute artifact root, so a relative one means something different to
    each of them -- this crashed the first live calibration run on its first
    task."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")

    record = run_suite(
        smoke,
        backends=_replay(),
        config=_config("artifacts/bench/relative"),
        fixture_root=FIXTURE_ROOT,
        out="artifacts/bench/relative",
    )
    run = record.runs[0]
    assert run.outcome == "end_turn"
    # The session's artifacts landed inside the run directory, which is what
    # keeps a reported artifact path resolvable when grading runs later.
    assert run.directory.is_absolute()
    manifest = json.loads((run.directory / "session_manifest.json").read_text())
    assert Path(manifest["artifact_directory"]) == run.directory


def test_a_run_directory_outside_the_artifact_root_still_grades(
    artifact_root, smoke, tmp_path
):
    """The session keeps its default scope and the manifest is copied in, so
    grading still reads one directory."""

    out = tmp_path / "elsewhere"
    record = run_suite(
        smoke,
        backends=_replay(),
        config=_config(out),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    run = record.runs[0]
    assert run.outcome == "end_turn"
    assert (run.directory / "session_manifest.json").exists()


def test_run_json_records_the_backend_as_it_was_after_being_called(
    artifact_root, smoke
):
    """Some backend properties are only knowable after a request.
    `temperature_supported` starts optimistic and turns False the first time a
    provider refuses the parameter, so a snapshot taken before the run records
    every backend as accepting it -- which is what run.json did for a real
    claude-sonnet-5 run while its own session manifests said otherwise."""

    class _Refusing(ReplayBackend):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.temperature_supported = True

        def complete(self, **kwargs):
            self.temperature_supported = False
            return super().complete(**kwargs)

    out = artifact_root / "bench" / "run-1"
    backend = _Refusing(
        [ModelResponse(stop_reason="end_turn", text="done")], name="refusing"
    )
    run_suite(
        smoke,
        backends={"replay/refusing": backend},
        config=_config(out),
        fixture_root=FIXTURE_ROOT,
        out=out,
    )
    record = json.loads((out / "run.json").read_text())
    assert record["backends"]["replay/refusing"]["temperature_supported"] is False
