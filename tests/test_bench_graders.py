"""Each grader against synthetic manifests, including adversarial ones.

docs/working/benchmark.md section 13. The adversarial cases are the point: a
v1 manifest, a manifest with no usage_totals, a max_turns outcome, and a
fabricated artifact path.
"""

from __future__ import annotations

import pytest

from tests.conftest_bench import (
    ANSWER_STANZA,
    BARE_TASK,
    MINIMAL_TASK,
    call,
    finished,
    manifest,
    run_directory,
    write_task,
)
from tools.bench.graders import load_evidence
from tools.bench.graders import protocol as protocol_grader
from tools.bench.graders import trajectory as trajectory_grader
from tools.bench.graders import answer as answer_grader
from tools.bench.graders import efficiency as efficiency_grader


def evidence_for(tmp_path, **kwargs):
    return load_evidence(run_directory(tmp_path, **kwargs))


# --- trajectory -----------------------------------------------------------


TRAJECTORY_TASK = BARE_TASK + ANSWER_STANZA + (
    "  trajectory:\n"
    "    must_call: [search_simbad]\n"
    "    must_not_call: [list_vizier_catalogs]\n"
    "    order: [search_simbad, search_ned]\n"
)


def test_must_not_call_is_a_hard_failure_naming_the_sequence(tmp_path):
    task = write_task(tmp_path, TRAJECTORY_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(tool_calls=[call("list_vizier_catalogs", sequence=3)]),
    )
    result = trajectory_grader.grade(task, evidence)
    assert result.passed is False
    assert "sequence 3" in result.failures[0].detail


def test_must_call_is_a_deviation_not_a_failure(tmp_path):
    """It encodes one good route among several. Punishing an alternative
    correct route would make the suite age badly as strategies change."""

    task = write_task(tmp_path, TRAJECTORY_TASK)
    evidence = evidence_for(tmp_path, manifest_body=manifest(tool_calls=[]))
    result = trajectory_grader.grade(task, evidence)
    assert result.passed is True
    assert [d.check for d in result.deviations] == ["must_call", "order"]


def test_order_is_an_ordered_subsequence_not_an_exact_sequence(tmp_path):
    task = write_task(tmp_path, TRAJECTORY_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(
            tool_calls=[
                call("search_simbad", sequence=1),
                call("resolve_target", sequence=2),
                call("search_ned", sequence=3),
            ]
        ),
    )
    result = trajectory_grader.grade(task, evidence)
    assert result.passed is True
    assert result.deviations == []


ARGUMENT_TASK = BARE_TASK + ANSWER_STANZA + (
    "  trajectory:\n"
    "    arguments:\n"
    "      - tool: search_ned\n"
    "        quantifier: all\n"
    '        where:\n          name: {matches: "^(NGC|IC|M)\\\\s*\\\\d+"}\n'
    "        because: NED's resolver is unreliable with colloquial names.\n"
)


def test_an_argument_rule_is_a_hard_failure_carrying_its_because(tmp_path):
    task = write_task(tmp_path, ARGUMENT_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(
            tool_calls=[call("search_ned", {"name": "Cat's Paw Nebula"})]
        ),
    )
    result = trajectory_grader.grade(task, evidence)
    assert result.passed is False
    failure = result.failures[0]
    assert "Cat's Paw" in failure.detail
    assert failure.because.startswith("NED's resolver")


def test_quantifier_all_fails_on_one_bad_call_among_good_ones(tmp_path):
    task = write_task(tmp_path, ARGUMENT_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(
            tool_calls=[
                call("search_ned", {"name": "NGC 6334"}, sequence=1),
                call("search_ned", {"name": "the Cat's Paw"}, sequence=2),
            ]
        ),
    )
    assert trajectory_grader.grade(task, evidence).passed is False


def test_quantifier_any_passes_when_one_call_satisfies_it(tmp_path):
    task = write_task(
        tmp_path, ARGUMENT_TASK.replace("quantifier: all", "quantifier: any")
    )
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(
            tool_calls=[
                call("search_ned", {"name": "the Cat's Paw"}, sequence=1),
                call("search_ned", {"name": "NGC 6334"}, sequence=2),
            ]
        ),
    )
    assert trajectory_grader.grade(task, evidence).passed is True


def test_an_argument_rule_says_nothing_when_the_tool_was_never_called(tmp_path):
    """must_not_call is the check for "do not call it"; this one passing
    vacuously keeps the two from being confused."""

    task = write_task(tmp_path, ARGUMENT_TASK)
    evidence = evidence_for(tmp_path, manifest_body=manifest(tool_calls=[]))
    result = trajectory_grader.grade(task, evidence)
    assert result.passed is True
    assert result.checks_passed == result.checks_total == 1


# --- protocol -------------------------------------------------------------


def test_the_seven_fault_types_are_always_reported_even_at_zero(tmp_path):
    from tools.llm.types import FAULT_TYPES

    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = evidence_for(tmp_path, manifest_body=manifest())
    counts = protocol_grader.grade(task, evidence).metrics["fault_counts"]
    assert set(counts) == set(FAULT_TYPES)
    assert all(value == 0 for value in counts.values())


def test_faults_are_counted_by_type(tmp_path):
    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(
            protocol_faults=[
                {"turn": 1, "type": "stringified_null", "detail": "d"},
                {"turn": 2, "type": "stringified_null", "detail": "d"},
                {"turn": 3, "type": "schema_violation", "detail": "d"},
            ]
        ),
    )
    metrics = protocol_grader.grade(task, evidence).metrics
    assert metrics["fault_counts"]["stringified_null"] == 2
    assert metrics["fault_total"] == 3


NULL_TASK = BARE_TASK + ANSWER_STANZA + (
    "  protocol:\n"
    "    null_argument_fidelity:\n"
    "      - tool: search_vizier\n        property: max_catalogs\n"
    "        because: JSON null is the only way to ask for everything.\n"
)


@pytest.mark.parametrize(
    "arguments, verdict",
    [
        ({"max_catalogs": None}, "pass"),
        ({}, "partial"),
        ({"max_catalogs": "None"}, "fail"),
        ({"max_catalogs": "null"}, "fail"),
        ({"max_catalogs": 5}, "fail"),
    ],
)
def test_null_argument_fidelity_distinguishes_the_four_observed_shapes(
    tmp_path, arguments, verdict
):
    """JSON null is the only way to request uncapped results; an omitted
    property is a *different* semantic (capped at the default), and a string
    or a literal is capped at something."""

    task = write_task(tmp_path, NULL_TASK)
    evidence = evidence_for(
        tmp_path, manifest_body=manifest(tool_calls=[call("search_vizier", arguments)])
    )
    metrics = protocol_grader.grade(task, evidence).metrics
    assert metrics["null_argument_fidelity"]["search_vizier.max_catalogs"]["verdict"] == verdict


def test_the_worst_verdict_across_calls_is_the_one_reported(tmp_path):
    """A model that got it right once and wrong twice has not demonstrated it
    understands the union."""

    task = write_task(tmp_path, NULL_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(
            tool_calls=[
                call("search_vizier", {"max_catalogs": None}, sequence=1),
                call("search_vizier", {"max_catalogs": "None"}, sequence=2),
            ]
        ),
    )
    fidelity = protocol_grader.grade(task, evidence).metrics["null_argument_fidelity"]
    assert fidelity["search_vizier.max_catalogs"]["verdict"] == "fail"


def test_the_protocol_axis_is_diagnostic_and_never_fails_a_run(tmp_path):
    """It explains a headline number rather than competing with it: a capped
    result reported as exhaustive fails the *answer* axis."""

    task = write_task(tmp_path, NULL_TASK)
    evidence = evidence_for(
        tmp_path,
        manifest_body=manifest(tool_calls=[call("search_vizier", {"max_catalogs": "None"})]),
    )
    result = protocol_grader.grade(task, evidence)
    assert result.passed is True
    assert result.deviations


# --- adversarial manifests ------------------------------------------------


def test_a_v1_manifest_grades_without_crashing(tmp_path):
    """A recorded run predates the v2 payload. Every added key must read as
    None, and the graders must still produce a verdict."""

    task = write_task(tmp_path, TRAJECTORY_TASK)
    v1 = manifest(
        schema_version=1,
        tool_calls=[call("search_simbad"), call("search_ned", sequence=2)],
        turns=[{"turn": 1, "stop_reason": "end_turn", "assistant_text": "done"}],
    )
    evidence = evidence_for(tmp_path, manifest_body=v1, answer="done")
    assert trajectory_grader.grade(task, evidence).passed is True
    metrics = efficiency_grader.grade(task, evidence).metrics
    assert metrics["tokens"]["input_tokens"] is None
    assert metrics["model_time_ms"] is None
    assert metrics["tokens_per_second"] is None
    assert metrics["tokens_per_second_kind"] == "unknown"


def test_a_manifest_with_no_usage_totals_reports_none_not_zero(tmp_path):
    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = evidence_for(
        tmp_path, manifest_body=manifest(usage_totals=None), answer="x"
    )
    tokens = efficiency_grader.grade(task, evidence).metrics["tokens"]
    assert all(value is None for value in tokens.values())


def test_a_max_turns_outcome_is_incomplete_and_neither_pass_nor_fail(tmp_path):
    """A model that ran out of turns did not answer badly, it did not
    answer."""

    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = evidence_for(
        tmp_path, manifest_body=manifest(outcome="max_turns"), answer=""
    )
    result = answer_grader.grade(task, evidence)
    assert result.metrics["incomplete"] is True
    assert result.passed is False
    assert result.failures[0].check == "incomplete"
    # And nothing else was graded: there is no answer to grade.
    assert result.checks_total == 0


def test_a_fabricated_artifact_path_fails(tmp_path):
    """Checked against the manifest, not against a regex: a model that
    invents a plausible-looking path fails, which /artifacts/.*\\.ecsv would
    not catch."""

    task = write_task(
        tmp_path,
        BARE_TASK + "expect:\n  answer:\n    must_report_artifact_path: true\n",
    )
    evidence = evidence_for(
        tmp_path,
        answer="The full table is at /artifacts/bench/vizier_casa_radio.ecsv.",
        manifest_body=manifest(
            tool_calls=[
                call(
                    "search_vizier",
                    artifacts=[{"path": "/artifacts/bench/run/search_vizier_1.ecsv"}],
                )
            ]
        ),
    )
    result = answer_grader.grade(task, evidence)
    assert result.passed is False
    assert "identifies no artifact this session actually wrote" in result.failures[0].detail


def test_a_quoted_real_artifact_path_passes(tmp_path):
    task = write_task(
        tmp_path,
        BARE_TASK + "expect:\n  answer:\n    must_report_artifact_path: true\n",
    )
    real = "/artifacts/bench/run/search_vizier_1.ecsv"
    evidence = evidence_for(
        tmp_path,
        answer=f"The complete table is at {real} (4127 rows).",
        manifest_body=manifest(
            tool_calls=[call("search_vizier", artifacts=[{"path": real}])]
        ),
    )
    assert answer_grader.grade(task, evidence).passed is True


def test_a_run_with_no_manifest_at_all_grades_as_an_error(tmp_path):
    """Grading a failed run must report the failure, not raise on it."""

    task = write_task(tmp_path, MINIMAL_TASK)
    evidence = evidence_for(tmp_path, error="TranscriptExhausted: ...")
    assert evidence.outcome == "error"
    assert evidence.incomplete is True
    assert answer_grader.grade(task, evidence).passed is False


def test_an_elided_path_with_the_right_filename_passes(tmp_path):
    """A live run had a model write the path with the middle elided for
    readability while quoting the exact filename. That is a display
    convention, not a fabrication: the basename is synthesized from the task
    id and the tool name, so it is unguessable in advance and verifiable
    after. The check exists to catch invented paths, and this is not one."""

    task = write_task(
        tmp_path,
        BARE_TASK + "expect:\n  answer:\n    must_report_artifact_path: true\n",
    )
    real = "/home/claude/Kepler/artifacts/bench/run/r1/preview_search_vizier.ecsv"
    evidence = evidence_for(
        tmp_path,
        answer="The full table is at /home/claude/Kepler/artifacts/.../preview_search_vizier.ecsv.",
        manifest_body=manifest(
            tool_calls=[call("search_vizier", artifacts=[{"path": real}])]
        ),
    )
    assert answer_grader.grade(task, evidence).passed is True


def test_a_full_path_still_passes_so_the_rule_stays_symmetric(tmp_path):
    """A model that quotes the whole path is unaffected by the basename rule,
    which is what keeps it fair between providers that format differently."""

    task = write_task(
        tmp_path,
        BARE_TASK + "expect:\n  answer:\n    must_report_artifact_path: true\n",
    )
    real = "/home/claude/Kepler/artifacts/bench/run/r1/preview_search_vizier.ecsv"
    evidence = evidence_for(
        tmp_path,
        answer=f"Written to {real} (4,127 rows).",
        manifest_body=manifest(
            tool_calls=[call("search_vizier", artifacts=[{"path": real}])]
        ),
    )
    assert answer_grader.grade(task, evidence).passed is True


def test_an_invented_filename_still_fails(tmp_path):
    """The anti-fabrication purpose has to survive the loosening."""

    task = write_task(
        tmp_path,
        BARE_TASK + "expect:\n  answer:\n    must_report_artifact_path: true\n",
    )
    evidence = evidence_for(
        tmp_path,
        answer="The full table is at /artifacts/casa_radio_photometry.ecsv.",
        manifest_body=manifest(
            tool_calls=[
                call(
                    "search_vizier",
                    artifacts=[{"path": "/artifacts/bench/run/r1/t_search_vizier.ecsv"}],
                )
            ]
        ),
    )
    result = answer_grader.grade(task, evidence)
    assert result.passed is False
    assert "identifies no artifact" in result.failures[0].detail
