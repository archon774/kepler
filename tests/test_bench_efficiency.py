"""The efficiency axis: three clocks kept apart, four token classes kept apart.

docs/working/benchmark.md section 7.2. Pure reporting -- no pass/fail, and no
money. There is no cost axis and no price table: tokens are the measurement,
and converting them to money is the reader's job against their own current
pricing page.
"""

from __future__ import annotations

from tests.conftest_bench import (
    MINIMAL_TASK,
    call,
    finished,
    manifest,
    run_directory,
    write_task,
)
from tools.bench.graders import load_evidence
from tools.bench.graders import efficiency as efficiency_grader


def metrics_for(tmp_path, **kwargs):
    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = load_evidence(run_directory(tmp_path, **kwargs))
    return efficiency_grader.grade(task, evidence).metrics


def _capabilities(streaming: bool):
    return {
        "spec": "x/y",
        "capabilities": {
            "streaming": streaming,
            "parallel_tool_calls": True,
            "native_tool_call_ids": True,
            "schema_dialect": "json_schema",
            "supports_union_types": True,
            "max_output_tokens": 4096,
        },
    }


# --- the three clocks -----------------------------------------------------


def test_model_time_and_tool_time_are_reported_separately(tmp_path):
    """Tool execution dominates wall clock on this surface: field calibration
    is a 30-90 s network round trip and an all-sky solve_astrometry is ~285 s.
    A model that answers by calling one looks an order of magnitude slower and
    that says nothing about tokens per second."""

    metrics = metrics_for(
        tmp_path,
        answer="done",
        manifest_body=manifest(
            tool_calls=[call("run_photometry_on_target")],
            turns=[
                {"turn": 1, "latency_ms": 400.0, "usage": {"output_tokens": 20}},
                {"turn": 2, "latency_ms": 600.0, "usage": {"output_tokens": 30}},
            ],
        ),
        events=[finished("run_photometry_on_target", {"status": "ok"}, duration_ms=62000.0)],
    )
    assert metrics["model_time_ms"] == 1000.0
    assert metrics["tool_time_ms"] == 62000.0


def test_tool_time_never_enters_the_timing_per_token_rate(tmp_path):
    """The rate is derived from the model clock alone."""

    metrics = metrics_for(
        tmp_path,
        answer="done",
        manifest_body=manifest(
            turns=[{"turn": 1, "latency_ms": 1000.0, "usage": {"output_tokens": 50}}],
            usage_totals={
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": None,
                "cache_write_tokens": None,
                "reasoning_tokens": None,
            },
        ),
        events=[finished("compute_pulsar_periodogram", {"status": "ok"}, duration_ms=90000.0)],
    )
    # 50 output tokens over one second of *model* time.
    assert metrics["tokens_per_second"] == 50.0


def test_wall_clock_is_left_for_the_run_record_to_fill_in(tmp_path):
    """It is the one clock the manifest cannot know: it is what a user waits
    for, not what the session measured."""

    assert metrics_for(tmp_path, manifest_body=manifest())["wall_ms"] is None


def test_a_missing_latency_reads_as_none_rather_than_zero(tmp_path):
    """A run whose adapter did not report latency did not take no time."""

    metrics = metrics_for(
        tmp_path,
        manifest_body=manifest(turns=[{"turn": 1, "stop_reason": "end_turn"}]),
    )
    assert metrics["model_time_ms"] is None
    assert metrics["tokens_per_second"] is None


# --- the four token classes ----------------------------------------------


def test_the_four_token_classes_stay_separate_with_a_cache_share(tmp_path):
    """SYSTEM_PROMPT plus 55 tool schemas is a large fixed prefix resent every
    turn, so a backend that caches it and one that does not are doing visibly
    different amounts of work at identical behaviour."""

    metrics = metrics_for(
        tmp_path,
        manifest_body=manifest(
            usage_totals={
                "input_tokens": 40000,
                "output_tokens": 300,
                "cache_read_tokens": 36000,
                "cache_write_tokens": 1200,
                "reasoning_tokens": None,
            }
        ),
    )
    tokens = metrics["tokens"]
    assert tokens["input_tokens"] == 40000
    assert tokens["cache_read_tokens"] == 36000
    assert tokens["cache_write_tokens"] == 1200
    assert tokens["reasoning_tokens"] is None
    assert metrics["cache_share_of_input"] == 0.9


def test_a_class_nobody_reported_stays_none(tmp_path):
    metrics = metrics_for(tmp_path, manifest_body=manifest(usage_totals=None))
    assert all(value is None for value in metrics["tokens"].values())
    assert metrics["cache_share_of_input"] is None


def test_totals_are_rebuilt_from_the_turns_when_the_roll_up_is_absent(tmp_path):
    """A manifest written before the roll-up existed still grades."""

    metrics = metrics_for(
        tmp_path,
        manifest_body=manifest(
            schema_version=1,
            turns=[
                {"turn": 1, "usage": {"input_tokens": 10, "output_tokens": 2}},
                {"turn": 2, "usage": {"input_tokens": 12, "output_tokens": 3}},
            ],
        ),
    )
    assert metrics["tokens"]["input_tokens"] == 22
    assert metrics["tokens"]["output_tokens"] == 5


# --- the rate is labelled -------------------------------------------------


def test_a_non_streaming_backends_rate_is_labelled_as_averaged(tmp_path):
    """Only the Anthropic adapter streams natively; the other three call
    on_text once with the finished text, so their latency is a whole round
    trip. Printing both in one column would compare two different
    quantities."""

    metrics = metrics_for(
        tmp_path, manifest_body=manifest(backend=_capabilities(streaming=False))
    )
    assert metrics["tokens_per_second_kind"] == "averaged"


def test_a_streaming_backends_rate_is_labelled_as_streaming(tmp_path):
    metrics = metrics_for(
        tmp_path, manifest_body=manifest(backend=_capabilities(streaming=True))
    )
    assert metrics["tokens_per_second_kind"] == "streaming"


def test_a_manifest_with_no_backend_record_says_unknown_not_averaged(tmp_path):
    metrics = metrics_for(tmp_path, manifest_body=manifest(schema_version=1))
    assert metrics["tokens_per_second_kind"] == "unknown"


# --- the duplicate rate ---------------------------------------------------


def test_the_duplicate_rate_is_reported_under_tokens_used(tmp_path):
    """A re-issued identical call is tokens spent for nothing. It is a
    confirmed-live failure mode and already recorded per call, so reporting it
    costs nothing."""

    metrics = metrics_for(
        tmp_path,
        manifest_body=manifest(
            tool_calls=[
                call("search_ned", sequence=1),
                call("search_ned", sequence=2, cache_hit=True),
                call("search_ned", sequence=3, cache_hit=True),
            ]
        ),
    )
    assert metrics["tool_calls"] == 3
    assert metrics["duplicate_calls"] == 2
    assert metrics["duplicate_rate"] == 2 / 3


def test_no_calls_means_no_duplicate_rate_rather_than_zero(tmp_path):
    assert metrics_for(tmp_path, manifest_body=manifest())["duplicate_rate"] is None


# --- the axis never fails a run ------------------------------------------


def test_the_efficiency_axis_reports_and_never_judges(tmp_path):
    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = load_evidence(
        run_directory(tmp_path, manifest_body=manifest(outcome="max_turns"))
    )
    result = efficiency_grader.grade(task, evidence)
    assert result.passed is True
    assert result.checks_total == 0
    # The incompleteness is still surfaced, so a reader is not told a run that
    # never answered spent its tokens well.
    assert result.metrics["incomplete"] is True
    assert result.metrics["outcome"] == "max_turns"


# --- tokens to an answer --------------------------------------------------


def test_tokens_to_an_answer_counts_only_runs_that_passed(tmp_path):
    """The headline cross-axis figure: not who emits tokens fastest, but who
    gets there with least work. Runs that failed the answer axis are reported
    separately as tokens spent without result, never averaged in."""

    from tools.bench.grade import summarize

    def entry(passed, incomplete, tokens):
        return {
            "backend": "openai/x",
            "incomplete": incomplete,
            "answer": {"passed": passed, "failures": []},
            "trajectory": {"failures": []},
            "protocol": {"metrics": {"fault_total": 0}},
            "efficiency": {
                "metrics": {
                    "turns": 2,
                    "tool_calls": 1,
                    "duplicate_calls": 0,
                    "model_time_ms": 1000.0,
                    "tokens": {"input_tokens": tokens, "output_tokens": 0},
                }
            },
        }

    rows = summarize(
        {
            "grades": [
                entry(True, False, 1000),
                entry(True, False, 2000),
                entry(False, False, 9000),
                entry(False, True, 500),
            ]
        }
    )
    row = rows["openai/x"]
    assert row["passed"] == 2
    assert row["incomplete"] == 1
    assert row["tokens_to_an_answer"] == 3000
    assert row["tokens_per_answer"] == 1500
    # 9000 from the failed run and 500 from the incomplete one.
    assert row["tokens_without_result"] == 9500
    # The incomplete run is excluded from the denominator: it did not answer.
    assert row["pass_rate"] == 2 / 3
