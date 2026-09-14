"""The matrix: column order, the header's contents, and the failure list.

docs/working/benchmark.md sections 7.6 and 12. A reader who has never opened
the suite should be able to tell what went wrong and why it counts.
"""

from __future__ import annotations

import json

import pytest

from tools.bench.report import (
    SCORE_BOARDS,
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
    repeat=1,
    wall_ms=70000.0,
):
    return {
        "backend": backend,
        "task_id": task_id,
        "repeat": repeat,
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
                "wall_ms": wall_ms,
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
    assert columns[:6] == [
        "backend",
        "correctness",
        # Immediately beside the rate it qualifies, so a reader subtracting two
        # rates sees what the subtraction is worth before doing it.
        "95% interval",
        "stability",
        # The two costs of an answer, in the order a user meets them.
        "seconds to an answer",
        "tokens to an answer",
    ]
    assert columns.index("trajectory failures") > columns.index("tokens to an answer")
    assert columns.index("protocol faults") > columns.index("trajectory failures")


def test_the_three_measurements_get_three_boards_and_no_blend():
    """Correct, how long, how many tokens -- scored separately.

    Correctness has a baseline and the other two do not, so a weighted sum
    would move whenever the field of compared backends changed while reading
    like a property of the model.
    """

    report = build_report([_pair()])
    assert set(SCORE_BOARDS) == {"correctness", "speed", "cost"}
    assert set(report["boards"]) >= set(SCORE_BOARDS)
    for row in report["matrix"].values():
        assert "score" not in row
        assert "composite" not in row


def test_each_board_is_ordered_on_its_own_measurement():
    slow = _entry(backend="slow/model", task_id="t1", wall_ms=200_000)
    fast = _entry(backend="fast/model", task_id="t1", wall_ms=10_000)
    fast["efficiency"]["metrics"]["tokens"] = {
        "input_tokens": 84000,
        "output_tokens": 1600,
    }
    boards = build_report([_pair(entries=[slow, fast])])["boards"]
    assert [e["backend"] for e in boards["speed"]] == ["fast/model", "slow/model"]
    assert [e["backend"] for e in boards["cost"]] == ["slow/model", "fast/model"]


def test_a_relative_board_reports_its_ratio_to_the_best():
    """"1.8x the fastest" is a comparison. A normalised 0.55 would read as a
    score on a scale that does not exist."""

    quick = _entry(backend="quick/model", task_id="t1", wall_ms=50_000)
    slow = _entry(backend="slow/model", task_id="t1", wall_ms=100_000)
    boards = build_report([_pair(entries=[quick, slow])])["boards"]
    assert boards["speed"][0]["times_best"] == pytest.approx(1.0)
    assert boards["speed"][1]["times_best"] == pytest.approx(2.0)
    assert "times_best" not in boards["correctness"][0]
    assert "interval" in boards["correctness"][0]


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


# --- stability and the ranking composite ---------------------------------


def _repeat_entries(backend, task_outcomes):
    """One entry per (task, repeat). `task_outcomes` maps task -> [pass|None]."""

    out = []
    for task, results in task_outcomes.items():
        for n, passed in enumerate(results, start=1):
            e = _entry(backend=backend, task_id=task, passed=bool(passed))
            e["repeat"] = n
            e["incomplete"] = passed is None
            out.append(e)
    return out


def test_stability_reports_the_share_of_tasks_that_agreed_across_repeats():
    """Section 17 question 2, answered: variance gets its own column rather
    than being folded into the axes. A model passing a check two runs in three
    is a different finding from one that passes it always, and a matrix showing
    both as "2/3" loses the distinction a ranking needs."""

    from tools.bench.grade import summarize

    rows = summarize(
        {
            "grades": _repeat_entries(
                "a/b",
                {
                    "steady": [True, True, True],
                    "also-steady": [False, False, False],
                    "flaky": [True, False, True],
                },
            )
        }
    )
    assert rows["a/b"]["stability"] == pytest.approx(2 / 3)
    assert rows["a/b"]["flaky_tasks"] == ["flaky"]


def test_an_incomplete_repeat_counts_as_its_own_outcome():
    """A task that answered twice and ran out of turns once is not stable, and
    averaging it into a pass rate would hide that."""

    from tools.bench.grade import summarize

    rows = summarize(
        {"grades": _repeat_entries("a/b", {"sometimes": [True, True, None]})}
    )
    assert rows["a/b"]["stability"] == 0.0
    assert rows["a/b"]["flaky_tasks"] == ["sometimes"]


def test_a_single_repeat_reports_no_stability_rather_than_a_perfect_one():
    """With n=1 nothing about stability has been measured, and reporting 100%
    would be a lie of omission -- especially for a backend whose provider
    refuses `temperature`, where nothing else bounds run-to-run drift."""

    from tools.bench.grade import summarize

    rows = summarize({"grades": _repeat_entries("a/b", {"once": [True]})})
    assert rows["a/b"]["stability"] is None
    text = render_markdown(build_report([_pair(entries=[_entry()])]))
    assert "| -- |" in text


def test_correctness_does_not_move_when_a_slower_backend_joins():
    """The distinction the split exists for. Adding a backend changes every
    speed standing and no correctness figure."""

    base = [_entry(backend="a/model", task_id="t1", wall_ms=50_000)]
    with_slow = base + [_entry(backend="b/model", task_id="t1", wall_ms=500_000)]

    before = build_report([_pair(entries=base)])["boards"]
    after = build_report([_pair(entries=with_slow)])["boards"]

    def correctness(boards, backend):
        return next(e["value"] for e in boards["correctness"] if e["backend"] == backend)

    assert correctness(before, "a/model") == correctness(after, "a/model")
    # ... while its speed standing is now a comparison against a second model.
    assert len(after["speed"]) == 2


def test_a_backend_that_answered_nothing_is_unmeasured_not_zero():
    """It has no cost *per answer*, and ranking it as infinitely slow would
    invent a measurement it never made."""

    entry = _entry(incomplete=True, passed=False)
    report = build_report([_pair(entries=[entry])])
    boards = report["boards"]
    assert boards["speed"] == []
    assert boards["speed_unmeasured"] == [{"backend": "anthropic/claude-opus-5"}]
    assert "Not measured" in render_markdown(report)


def test_the_board_names_the_backends_the_measurements_disagree_on():
    """A model first for correctness and last for speed has not been beaten --
    it bought accuracy with time, and no weight can adjudicate that."""

    right_slow = _entry(backend="careful/model", task_id="t1", passed=True,
                        wall_ms=500_000)
    wrong_fast = _entry(backend="hasty/model", task_id="t1", passed=False,
                        wall_ms=5_000)
    wrong_fast2 = _entry(backend="hasty/model", task_id="t2", passed=True,
                         wall_ms=5_000)
    text = render_markdown(
        build_report([_pair(entries=[right_slow, wrong_fast, wrong_fast2])])
    )
    assert "### The board" in text
    assert "No single order over these backends exists." in text


# --- what the trial count will and will not support ------------------------


def test_a_two_item_gap_at_this_trial_count_is_not_a_separation():
    """The correction that motivated the interval column.

    23/24 and 21/24 look like a ranking and are not one: two items across
    twenty-four trials carry intervals several times the gap's own width.
    """

    from tools.bench.report import separated, wilson_interval

    top = {"pass_interval": list(wilson_interval(23, 24))}
    second = {"pass_interval": list(wilson_interval(21, 24))}
    assert not separated(top, second)


def test_a_wide_gap_is_separated():
    from tools.bench.report import separated, wilson_interval

    top = {"pass_interval": list(wilson_interval(23, 24))}
    bottom = {"pass_interval": list(wilson_interval(10, 24))}
    assert separated(top, bottom)


def test_a_perfect_score_still_has_a_lower_bound():
    """Wilson rather than the normal interval: 24/24 does not collapse to a
    zero-width interval claiming certainty from twenty-four trials."""

    from tools.bench.report import wilson_interval

    low, high = wilson_interval(24, 24)
    assert 0.0 < low < 1.0
    assert high == 1.0


def test_the_report_names_the_pairs_it_could_not_separate():
    """Two backends one item apart over four trials: the table must say so
    rather than leave an ordered column implying a ranking."""

    entries = [_entry(task_id=f"t{i}", passed=i < 4) for i in range(4)]
    entries += [
        _entry(backend="ollama/local", task_id=f"t{i}", passed=i < 3)
        for i in range(4)
    ]
    text = render_markdown(build_report([_pair(entries=entries)]))
    assert "95% interval" in text
    assert "Not separated by this suite" in text
    assert "`anthropic/claude-opus-5` vs `ollama/local`" in text


def test_stability_is_recomputed_across_merged_suites():
    """A report merging several suites must recompute stability over every
    task in all of them. Overwriting per suite reported whichever suite merged
    last as the backend's variance."""

    steady = _pair(entries=[_entry(task_id="a", passed=True, repeat=r) for r in (1, 2)])
    flaky = _pair(
        _record(run_id="2026-09-14-pulsar"),
        entries=[
            _entry(task_id="b", passed=True, repeat=1),
            _entry(task_id="b", passed=False, repeat=2),
        ],
    )
    row = build_report([steady, flaky])["matrix"]["anthropic/claude-opus-5"]
    assert row["tasks"] == 2
    assert row["flaky_tasks"] == ["b"]
    assert row["stability"] == 0.5


def test_time_to_an_answer_counts_only_runs_that_answered():
    """A fast wrong answer is not a fast answer -- the same rule tokens follow."""

    report = build_report(
        [
            _pair(
                entries=[
                    _entry(task_id="a", passed=True, wall_ms=10_000),
                    _entry(task_id="b", passed=False, wall_ms=90_000),
                ]
            )
        ]
    )
    row = report["matrix"]["anthropic/claude-opus-5"]
    assert row["seconds_per_answer"] == 10.0
    assert "seconds to an answer" in render_markdown(report)
