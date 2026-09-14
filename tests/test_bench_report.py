"""The matrix: column order, the header's contents, and the failure list.

docs/working/benchmark.md sections 7.6 and 12. A reader who has never opened
the suite should be able to tell what went wrong and why it counts.
"""

from __future__ import annotations

import json

import pytest

from tools.bench.report import (
    COMPOSITE_WEIGHTS,
    build_report,
    render_markdown,
    write_report,
)


def _record(**kwargs):
    base = {
        "run_id": "2026-09-13-core",
        "started_at": "2026-09-13T00:00:00+00:00",
        "finished_at": "2026-09-13T00:10:00+00:00",
        "host": "obs-01",
        "git_head": "abc123",
        "corpus_dirty": False,
        "corpus": {"suite": "s" * 64, "tasks": {"t1": "a" * 64}, "fixtures": {"search_ned": "b" * 64}},
        "config": {"suite_id": "core", "repeats": 1, "temperature": 0.0, "seed": None},
        "backends": {
            "anthropic/claude-opus-5": {
                "spec": "anthropic/claude-opus-5",
                "capabilities": {
                    "schema_dialect": "json_schema",
                    "streaming": True,
                    "supports_union_types": True,
                },
            }
        },
        "runs": [
            {
                "task_id": "t1",
                "backend": "anthropic/claude-opus-5",
                "outcome": "end_turn",
                "incomplete": False,
                "fixture_hits": 4,
                "fixture_misses": [],
            }
        ],
    }
    base.update(kwargs)
    return base


def _entry(
    *,
    backend="anthropic/claude-opus-5",
    task_id="t1",
    passed=True,
    incomplete=False,
    failures=(),
    tags=("core",),
):
    return {
        "backend": backend,
        "task_id": task_id,
        "repeat": 1,
        "outcome": "max_turns" if incomplete else "end_turn",
        "incomplete": incomplete,
        "tags": list(tags),
        "answer": {
            "passed": passed,
            "checks_passed": 3 if passed else 1,
            "checks_total": 3,
            "failures": list(failures),
            "deviations": [],
        },
        "trajectory": {"failures": [], "deviations": []},
        "protocol": {"failures": [], "metrics": {"fault_total": 2}},
        "efficiency": {
            "metrics": {
                "turns": 4,
                "tool_calls": 6,
                "duplicate_calls": 1,
                "model_time_ms": 8000.0,
                "tool_time_ms": 61000.0,
                "wall_ms": 70000.0,
                "tokens_per_second_kind": "streaming",
                "tokens": {
                    "input_tokens": 42000,
                    "output_tokens": 800,
                    "cache_read_tokens": 39000,
                    "cache_write_tokens": None,
                    "reasoning_tokens": None,
                },
            }
        },
    }


def _pair(record=None, entries=(), judge=None):
    return {
        "record": record or _record(),
        "grades": {"grades": list(entries) or [_entry()], "judge": judge},
    }


# --- the header -----------------------------------------------------------


def test_the_header_carries_the_corpus_hashes_the_host_and_the_backends():
    text = render_markdown(build_report([_pair()]))
    assert "host `obs-01`" in text
    assert "suite SHA-256 `ssssssssssss`" in text
    assert "`t1` `aaaaaaaaaaaa`" in text
    assert "fixture `search_ned` `bbbbbbbbbbbb`" in text
    assert "dialect `json_schema`" in text


def test_a_dirty_corpus_is_called_out_in_the_header():
    """Never silently graded against uncommitted tasks."""

    text = render_markdown(build_report([_pair(_record(corpus_dirty=True))]))
    assert "corpus was dirty at launch" in text


def test_an_unknown_corpus_state_is_distinguished_from_a_clean_one():
    """"We could not tell" and "it was clean" are different statements."""

    text = render_markdown(build_report([_pair(_record(corpus_dirty=None))]))
    assert "corpus cleanliness unknown" in text


def test_the_fixture_miss_rate_is_in_the_header():
    report = build_report([_pair()])
    assert report["header"]["fixture_miss_rate"] == 0.0
    assert "Fixture miss rate" in render_markdown(report)


def test_a_high_miss_rate_says_what_it_means_in_the_documents_own_words():
    """A suite with a high miss rate is measuring its own coverage, not the
    model, and the report says so in those words."""

    record = _record()
    record["runs"][0]["fixture_misses"] = [{"tool": "search_ned", "arguments": {}}] * 4
    text = render_markdown(build_report([_pair(record)]))
    assert "measuring its own coverage, not the model" in text


def test_incomplete_and_budget_exceeded_outcomes_are_surfaced_separately():
    record = _record()
    record["runs"] = [
        {
            "task_id": "t1",
            "backend": "anthropic/claude-opus-5",
            "outcome": "budget_exceeded",
            "incomplete": True,
            "fixture_hits": 0,
            "fixture_misses": [],
        },
        {
            "task_id": "t2",
            "backend": "anthropic/claude-opus-5",
            "outcome": "max_turns",
            "incomplete": True,
            "fixture_hits": 0,
            "fixture_misses": [],
        },
    ]
    text = render_markdown(build_report([_pair(record)]))
    assert "**Budget exceeded**" in text and "`t1@anthropic/claude-opus-5`" in text
    assert "**Incomplete**" in text and "max_turns" in text
    assert "never scored as a low pass rate" in text


def test_the_judge_model_is_named_in_the_header_and_marked_advisory():
    text = render_markdown(build_report([_pair(judge="ollama/qwen3.8:27b-mlx")]))
    assert "judge `ollama/qwen3.8:27b-mlx`" in text
    assert "advisory; never blended" in text


# --- the matrix -----------------------------------------------------------


def test_the_column_order_reads_the_two_questions_left_to_right():
    """Load-bearing: the diagnostics sit beside the headline numbers to
    explain them rather than competing for attention."""

    text = render_markdown(build_report([_pair()]))
    header = next(line for line in text.splitlines() if line.startswith("| backend |"))
    columns = [c.strip() for c in header.strip("|").split("|")]
    assert columns[:3] == ["backend", "correctness", "tokens to an answer"]
    assert columns.index("trajectory failures") > columns.index("tokens to an answer")
    assert columns.index("protocol faults") > columns.index("trajectory failures")


def test_there_is_no_blended_score_by_default():
    """A composite hides which axis failed, and "model A scored 0.72" is not
    actionable."""

    report = build_report([_pair()])
    assert report["weights"] is None
    assert "composite" not in render_markdown(report).lower()


def test_the_composite_prints_its_weights_above_it():
    report = build_report([_pair()], composite=True)
    text = render_markdown(report)
    assert report["weights"] == dict(COMPOSITE_WEIGHTS)
    assert "Composite weights (headline axes only)" in text
    # Headline axes only: a diagnostic has no independent meaning to weight.
    assert "trajectory" not in report["weights"]
    assert "protocol" not in report["weights"]


def test_tokens_without_result_are_reported_separately_never_averaged_in():
    report = build_report(
        [_pair(entries=[_entry(passed=True), _entry(task_id="t2", passed=False)])]
    )
    row = report["matrix"]["anthropic/claude-opus-5"]
    assert row["tokens_to_an_answer"] == 42800
    assert row["tokens_without_result"] == 42800
    assert row["tokens_per_answer"] == 42800
    assert "without result" in render_markdown(report)


def test_an_incomplete_run_is_not_a_failed_one_in_the_pass_rate():
    report = build_report(
        [
            _pair(
                entries=[
                    _entry(passed=True),
                    _entry(task_id="t2", incomplete=True, passed=False),
                ]
            )
        ]
    )
    row = report["matrix"]["anthropic/claude-opus-5"]
    assert row["pass_rate"] == 1.0
    assert row["incomplete"] == 1


def test_an_absent_measurement_renders_as_a_dash_not_a_zero():
    """A provider that did not report a token class did not report zero of
    them, and a column of zeros would read as a measurement."""

    entry = _entry()
    entry["efficiency"]["metrics"]["model_time_ms"] = None
    entry["efficiency"]["metrics"]["tokens"]["cache_read_tokens"] = None
    text = render_markdown(build_report([_pair(entries=[entry])]))
    row = next(line for line in text.splitlines() if "`t1`" in line and "| 1 |" in line)
    assert "| -- |" in row


# --- the per-task grid ----------------------------------------------------


def test_the_grid_prints_all_three_clocks_and_the_rate_kind():
    text = render_markdown(build_report([_pair()]))
    header = next(line for line in text.splitlines() if "model ms" in line)
    assert "tool ms" in header and "wall ms" in header
    assert "streaming" in text


def test_a_tag_filter_reads_one_correctness_family_on_its_own():
    report = build_report(
        [
            _pair(
                entries=[
                    _entry(task_id="t1", tags=("core", "sourcing")),
                    _entry(task_id="t2", tags=("core", "null-argument")),
                ]
            )
        ],
        tag="sourcing",
    )
    assert [row["task_id"] for row in report["per_task"]] == ["t1"]
    assert "Filtered to tasks tagged `sourcing`" in render_markdown(report)


# --- the failure list -----------------------------------------------------


def test_every_hard_failure_prints_its_because_verbatim():
    """So a scoreboard entry explains itself without anyone opening the suite
    file."""

    failure = {
        "check": "must_reach_verdict",
        "detail": "compare_zeropoint_to_reference.within_tolerance was [False]",
        "because": (
            "The recorded Skynet solve is the ground truth and the tool owns "
            "the tolerance; a regex on the printed magnitude would grade "
            "formatting."
        ),
    }
    report = build_report([_pair(entries=[_entry(passed=False, failures=[failure])])])
    text = render_markdown(report)
    assert "answer/must_reach_verdict" in text
    assert failure["detail"] in text
    assert f"> {failure['because']}" in text


def test_no_failures_says_so_rather_than_printing_an_empty_section():
    assert "None." in render_markdown(build_report([_pair()]))


# --- output ---------------------------------------------------------------


def test_both_files_are_written_with_the_same_content(tmp_path):
    report = build_report([_pair()])
    md, js = write_report(report, tmp_path)
    assert md.read_text().startswith("# Kepler model benchmark")
    assert json.loads(js.read_text())["matrix"] == report["matrix"]


def test_several_run_directories_merge_into_one_matrix():
    report = build_report(
        [
            _pair(),
            _pair(
                _record(run_id="2026-09-14-core"),
                entries=[_entry(task_id="t2", passed=False)],
            ),
        ]
    )
    assert len(report["header"]["runs"]) == 2
    row = report["matrix"]["anthropic/claude-opus-5"]
    assert row["runs"] == 2 and row["passed"] == 1
