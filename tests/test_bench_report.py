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


def _row(passed, trials):
    """A matrix row carrying only what a separation test reads."""

    return {"pass_rate": passed / trials, "effective_trials": float(trials)}


def test_a_two_item_gap_at_this_trial_count_is_not_a_separation():
    """The correction that motivated the interval column.

    23/24 and 21/24 look like a ranking and are not one.
    """

    from tools.bench.report import separated

    assert not separated(_row(23, 24), _row(21, 24))


def test_a_wide_gap_is_separated():
    from tools.bench.report import separated

    assert separated(_row(23, 24), _row(8, 24))


def test_separation_asks_about_the_difference_not_about_overlap():
    """Two 95% intervals can overlap while their difference excludes zero.

    The overlap test errs toward modesty, which is why the mistake survives
    review: it never claims a difference that is not there, it denies ones that
    are. "Their intervals overlap" is not "no difference was shown".
    """

    from tools.bench.report import difference_interval, separated, wilson_interval

    a, b = _row(45, 60), _row(32, 60)
    first, second = wilson_interval(45, 60), wilson_interval(32, 60)
    # The individual intervals do overlap ...
    assert first[0] < second[1]
    # ... and the difference between them still excludes zero.
    low, high = difference_interval(45, 60, 32, 60)
    assert low > 0
    assert separated(a, b)


def test_the_difference_interval_matches_newcombes_published_examples():
    """Newcombe (1998), Statistics in Medicine 17:873-890, method 10."""

    from tools.bench.report import difference_interval

    low, high = difference_interval(56, 70, 48, 80)
    assert low == pytest.approx(0.0524, abs=5e-5)
    assert high == pytest.approx(0.3339, abs=5e-5)

    low, high = difference_interval(9, 10, 3, 10)
    assert low == pytest.approx(0.1705, abs=5e-5)
    assert high == pytest.approx(0.8090, abs=5e-5)


def test_separation_uses_the_effective_sample_size_not_the_session_count():
    """The clustering correction has to survive into the comparison, or the
    test re-assumes the independence the interval established is absent."""

    from tools.bench.report import separated

    wide = _row(40, 48)
    narrow = _row(28, 48)
    assert separated(wide, narrow)
    # The same rates on the effective size of a fully clustered run are not.
    assert not separated(
        {"pass_rate": 40 / 48, "effective_trials": 16.0},
        {"pass_rate": 28 / 48, "effective_trials": 16.0},
    )


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


# --- repeats are clustered, not independent -------------------------------


def test_a_deterministic_backend_gets_no_credit_for_repeats():
    """The case a naive interval flatters most.

    A model answering each task the same way every repeat has learned nothing
    new on repeats two and three. Its effective sample size is the *task*
    count, and an interval over the session count claims precision the design
    never bought.
    """

    from tools.bench.report import design_effect

    outcomes = {"t1": [True, True, True], "t2": [False, False, False],
                "t3": [True, True, True]}
    rho, deff = design_effect(outcomes)
    assert rho == pytest.approx(1.0)
    assert deff == pytest.approx(3.0)


def test_a_backend_that_varies_within_a_task_keeps_its_trials():
    """The other end: answers varying freely inside a task make the repeats
    genuinely independent evidence, and nothing is lost."""

    from tools.bench.report import design_effect

    outcomes = {"t1": [True, False, True], "t2": [False, True, False],
                "t3": [True, False, False]}
    rho, deff = design_effect(outcomes)
    assert rho == pytest.approx(0.0)
    assert deff == pytest.approx(1.0)


def test_total_agreement_is_treated_as_fully_clustered():
    """Every session passing leaves nothing to tell a deterministic model from
    a lucky one, so assume clustering rather than claim independent evidence."""

    from tools.bench.report import design_effect

    rho, deff = design_effect({"t1": [True] * 3, "t2": [True] * 3})
    assert rho == pytest.approx(1.0)
    assert deff == pytest.approx(3.0)


def test_the_clustered_interval_is_never_narrower_than_the_naive_one():
    from tools.bench.report import clustered_interval, wilson_interval

    outcomes = {f"t{i}": [True, True, True] for i in range(7)}
    outcomes["t7"] = [False, False, False]
    interval, rho, effective = clustered_interval(21, 24, outcomes)
    naive = wilson_interval(21, 24)
    assert effective == pytest.approx(8.0)
    assert (interval[1] - interval[0]) > (naive[1] - naive[0])


def test_the_correctness_board_shows_what_the_repeats_were_worth():
    entries = [
        _entry(task_id=f"t{i}", passed=True, repeat=r)
        for i in range(3)
        for r in (1, 2, 3)
    ]
    text = render_markdown(build_report([_pair(entries=entries)]))
    assert "n_eff" in text and "rho" in text
    assert "other questions like these" in text


def test_wilson_agrees_with_scipy_everywhere_it_is_used():
    """An independent implementation, not a restatement of the same algebra.

    scipy is already a hard dependency of this repository, so the check costs
    nothing and catches the class of error a hand-derived formula invites.
    """

    from scipy.stats import binomtest

    from tools.bench.report import wilson_interval

    for trials in range(2, 60):
        for passed in range(trials + 1):
            mine = wilson_interval(passed, trials)
            reference = binomtest(passed, trials).proportion_ci(
                confidence_level=0.95, method="wilson"
            )
            assert mine[0] == pytest.approx(reference.low, abs=1e-12)
            assert mine[1] == pytest.approx(reference.high, abs=1e-12)


def test_the_icc_reduces_to_the_textbook_form_on_a_balanced_design():
    """m0 is the unbalanced-design cluster size and must collapse to the common
    size when every cluster is the same length -- which ours are, whenever a
    run completes."""

    from tools.bench.report import design_effect

    outcomes = {
        "t1": [True, True, False],
        "t2": [True, False, False],
        "t3": [True, True, True],
        "t4": [False, False, False],
    }
    sizes = [3, 3, 3, 3]
    total, k = sum(sizes), len(sizes)
    m0 = (total - sum(s * s for s in sizes) / total) / (k - 1)
    assert m0 == pytest.approx(3.0)

    props = [sum(1 for x in v if x) / len(v) for v in outcomes.values()]
    grand = sum(sum(1 for x in v if x) for v in outcomes.values()) / total
    msb = sum(s * (p - grand) ** 2 for s, p in zip(sizes, props)) / (k - 1)
    msw = sum(s * p * (1 - p) for s, p in zip(sizes, props)) / (total - k)
    expected = (msb - msw) / (msb + (m0 - 1) * msw)

    rho, deff = design_effect(outcomes)
    assert rho == pytest.approx(expected)
    assert deff == pytest.approx(1 + (m0 - 1) * rho)


def test_a_ragged_design_uses_m0_rather_than_the_mean_cluster_size():
    """A partial run has clusters of different lengths, and the mean is the
    wrong constant for a design effect."""

    from tools.bench.report import design_effect

    outcomes = {"t1": [True] * 8, "t2": [False, True], "t3": [True, False]}
    sizes = [8, 2, 2]
    total, k = sum(sizes), len(sizes)
    m0 = (total - sum(s * s for s in sizes) / total) / (k - 1)
    assert m0 != pytest.approx(total / k)  # the mean would be 4.0
    _, deff = design_effect(outcomes)
    rho, _ = design_effect(outcomes)
    assert deff == pytest.approx(1 + (m0 - 1) * rho)


def test_a_single_session_per_task_leaves_the_trials_alone():
    """--repeats 1 has no clusters to correlate, so nothing is discounted."""

    from tools.bench.report import design_effect

    rho, deff = design_effect({"t1": [True], "t2": [False], "t3": [True]})
    assert rho == 0.0
    assert deff == 1.0


def test_wilson_rejects_a_count_larger_than_its_trials():
    """Outside [0, 1] the variance term goes negative and the square root
    raises from inside the arithmetic. A caller error should say what it is."""

    from tools.bench.report import wilson_interval

    with pytest.raises(ValueError, match=r"not in \[0, 18\]"):
        wilson_interval(20, 18)
    with pytest.raises(ValueError, match=r"not in \[0, 18\]"):
        wilson_interval(-1, 18)
    assert wilson_interval(18, 18) is not None


def test_the_clustered_interval_covers_a_population_the_naive_one_misses():
    """Where the interval comes from, checked by simulation rather than argued.

    Each task is a draw from the population of questions one could ask about
    this surface; each repeat is a draw within that task. Against a population
    where a task is either reliably passed or reliably failed -- the shape a
    deterministic model produces -- a naive interval over the session count
    covers the population mean far below its nominal 95%, because it counts
    three repeats of one question as three questions.
    """

    import random

    from tools.bench.report import design_effect, wilson_interval

    random.seed(23)
    tasks, repeats, trials = 8, 3, 1500
    truth = 0.7
    naive_hits = clustered_hits = 0
    for _ in range(trials):
        rates = [1.0 if random.random() < truth else 0.0 for _ in range(tasks)]
        outcomes = {
            f"t{i}": [random.random() < rate for _ in range(repeats)]
            for i, rate in enumerate(rates)
        }
        passed = sum(sum(1 for x in v if x) for v in outcomes.values())
        sessions = tasks * repeats

        low, high = wilson_interval(passed, sessions)
        naive_hits += low <= truth <= high

        _, deff = design_effect(outcomes)
        effective = max(1, round(sessions / deff))
        low, high = wilson_interval(
            round(passed / sessions * effective), effective
        )
        clustered_hits += low <= truth <= high

    # The naive interval is badly too narrow here; the clustered one is close
    # to nominal. Bounds are loose enough not to be flaky at this trial count.
    assert naive_hits / trials < 0.85
    assert 0.90 < clustered_hits / trials < 0.99


def test_latency_is_scored_on_first_repeats_not_warmed_ones():
    """Repeating a task hits the provider's prefix cache.

    Six tasks in one live sweep did byte-identical work across their three
    repeats -- same turns, same tool calls, same input tokens -- and still ran
    a median 1.33x slower on the first. A caller asks each question once, and
    the discount differs by provider, so averaging warmed repeats in would rank
    backends on whose caching the harness exercised.
    """

    entries = [
        _entry(task_id="t1", repeat=1, passed=True, wall_ms=90_000),
        _entry(task_id="t1", repeat=2, passed=True, wall_ms=30_000),
        _entry(task_id="t1", repeat=3, passed=True, wall_ms=30_000),
    ]
    row = build_report([_pair(entries=entries)])["matrix"]["anthropic/claude-opus-5"]
    assert row["seconds_per_answer"] == pytest.approx(90.0)
    assert row["seconds_per_answer_warm"] == pytest.approx(50.0)
    assert row["cold_latency"] is True


def test_latency_falls_back_when_no_first_repeat_answered():
    """A model whose first attempt never lands has no cold measurement, and
    saying so beats silently scoring it on warmed repeats."""

    entries = [
        _entry(task_id="t1", repeat=1, passed=False, wall_ms=90_000),
        _entry(task_id="t1", repeat=2, passed=True, wall_ms=40_000),
    ]
    row = build_report([_pair(entries=entries)])["matrix"]["anthropic/claude-opus-5"]
    assert row["cold_latency"] is False
    assert row["seconds_per_answer"] == pytest.approx(40.0)
