"""The three kinds of right answer, and the four fidelity families.

docs/working/benchmark.md section 7.1. On this surface "correct" is three
different things -- a ground truth the repository recorded before the model
ran, fidelity to what the tools returned this session, and a correct negative
where a confident answer is itself the failure. They need different machinery,
and conflating them grades phrasing.
"""

from __future__ import annotations

import pytest

from tests.conftest_bench import (
    BARE_TASK,
    MINIMAL_TASK,
    call,
    finished,
    manifest,
    run_directory,
    write_task,
)
from tools.bench.graders import load_evidence
from tools.bench.graders import answer as answer_grader


def graded(tmp_path, task_body, *, answer, tool_calls=(), events=(), outcome="end_turn"):
    task = write_task(tmp_path, task_body)
    evidence = load_evidence(
        run_directory(
            tmp_path,
            answer=answer,
            manifest_body=manifest(outcome=outcome, tool_calls=list(tool_calls)),
            events=list(events),
        )
    )
    return answer_grader.grade(task, evidence)


# --- ground truth: a tool's own verdict against recorded truth ------------


VERDICT_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_reach_verdict:\n"
    "      - tool: compare_zeropoint_to_reference\n"
    "        field: within_tolerance\n"
    "        equals: true\n"
    "        because: >\n"
    "          The recorded Skynet solve is the ground truth and the tool owns\n"
    "          the tolerance; a regex on the printed magnitude would grade\n"
    "          formatting.\n"
)


def test_must_reach_verdict_reads_a_tools_own_boolean(tmp_path):
    """The strongest check in the document: structured output compared to
    structured truth, where no phrasing can pass or fail it."""

    result = graded(
        tmp_path,
        VERDICT_TASK,
        answer="It agrees with the recorded solve.",
        events=[
            finished(
                "compare_zeropoint_to_reference",
                {"status": "ok", "within_tolerance": True, "delta_vs_skynet": 0.004},
            )
        ],
    )
    assert result.passed is True


def test_a_wrong_verdict_fails_however_confidently_it_is_phrased(tmp_path):
    result = graded(
        tmp_path,
        VERDICT_TASK,
        answer="The zero point agrees perfectly with Skynet's recorded solve.",
        events=[
            finished(
                "compare_zeropoint_to_reference",
                {"status": "ok", "within_tolerance": False, "delta_vs_skynet": 0.41},
            )
        ],
    )
    assert result.passed is False
    assert "within_tolerance" in result.failures[0].detail
    assert "grade formatting" in result.failures[0].because


def test_a_verdict_the_tool_never_produced_fails(tmp_path):
    result = graded(tmp_path, VERDICT_TASK, answer="It agrees.", events=[])
    assert result.passed is False
    assert "never returned" in result.failures[0].detail


def test_the_provenance_pairing_is_a_trajectory_rule_not_an_answer_one(tmp_path):
    """A model can reach within_tolerance: true trivially by reading the
    reference and handing that number straight back. The trajectory axis is
    where that is caught -- a must_not_call on the reference loader -- so the
    answer grader deliberately does not try."""

    from tools.bench.graders import trajectory as trajectory_grader

    task = write_task(
        tmp_path,
        BARE_TASK
        + 'expect:\n  answer:\n    must_not_match: ["I refuse to answer"]\n'
        + "  trajectory:\n    must_not_call:\n"
        "      - tool: load_zeropoint_reference\n"
        "        because: >\n"
        "          Handing the reference its own number back is a fit to a\n"
        "          known answer wearing the costume of a measurement.\n",
    )
    evidence = load_evidence(
        run_directory(
            tmp_path,
            answer="It agrees.",
            manifest_body=manifest(tool_calls=[call("load_zeropoint_reference")]),
        )
    )
    result = trajectory_grader.grade(task, evidence)
    assert result.passed is False
    assert "costume of a measurement" in result.failures[0].because


# --- ground truth: a number within tolerance ------------------------------


VALUE_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_report_value:\n"
    "      - name: period_s\n"
    "        source:\n"
    "          dataset: pulsar/curated_periods.json\n"
    "          path: pulsars.b0329.period_s\n"
    "        rel_tol: 0.02\n        unit: s\n"
)


@pytest.mark.parametrize(
    "answer",
    [
        "The measured period is 0.7145197 s.",
        "I measure 0.71452 s for B0329+54.",
        "Period: 714.5 ms, i.e. 0.7145 seconds.",
    ],
)
def test_a_period_within_tolerance_passes_however_it_is_written(tmp_path, answer):
    assert graded(tmp_path, VALUE_TASK, answer=answer).passed is True


def test_a_period_outside_tolerance_fails(tmp_path):
    """Folding at 2.1 s -- the baseline red-noise peak -- is the documented
    wrong answer, not a near miss."""

    result = graded(tmp_path, VALUE_TASK, answer="The period is 2.15 s.")
    assert result.passed is False
    assert "0.7145197 s" in result.failures[0].detail


def test_a_designation_is_not_mistaken_for_a_measurement(tmp_path):
    """B0329+54 contains digits; "0329" is not a period."""

    result = graded(tmp_path, VALUE_TASK, answer="B0329+54 was not measured.")
    assert result.passed is False


# --- fidelity: fabrication ------------------------------------------------


SOURCE_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_source_value:\n"
    '      - pattern: "%\\\\s*/\\\\s*yr|%/yr"\n'
    "        because: >\n"
    "          Quoting a decline rate that appears in no tool result means the\n"
    "          figure came from training data.\n"
)


def test_a_fabricated_number_is_flagged(tmp_path):
    """The confirmed-live incident: an agent answered "0.3-0.7%/yr depending
    on frequency" and attributed it by name to Trotter et al. 2017, whose
    abstract says 0.670 +/- 0.019%/yr averaged over six decades."""

    result = graded(
        tmp_path,
        MINIMAL_TASK,
        answer="Cas A declines at 0.55%/yr, per Trotter et al. 2017.",
        events=[finished("search_ads", {"status": "ok", "count": 3})],
    )
    assert "0.55" in result.metrics["unsourced_numbers"]


def test_a_flag_alone_does_not_fail_the_run(tmp_path):
    """Models legitimately derive numbers -- a mean, a unit conversion, a
    ratio, a rounded restatement. It flags by default; a task promotes a
    specific pattern where the domain makes it unambiguous."""

    result = graded(
        tmp_path,
        MINIMAL_TASK,
        answer="Roughly 43.2 sources per square degree.",
        events=[finished("search_vizier", {"status": "ok", "count": 100})],
    )
    assert result.metrics["unsourced_numbers"]
    assert result.passed is True


def test_a_promoted_pattern_is_a_hard_failure(tmp_path):
    result = graded(
        tmp_path,
        SOURCE_TASK,
        answer="The secular decline rate is 0.55%/yr.",
        events=[finished("search_ads", {"status": "ok", "count": 3})],
    )
    assert result.passed is False
    assert "training data" in result.failures[0].because


def test_a_number_the_tools_returned_is_not_flagged(tmp_path):
    result = graded(
        tmp_path,
        SOURCE_TASK,
        answer="The abstract gives 0.670%/yr averaged over six decades.",
        events=[
            finished(
                "get_paper_abstract",
                {"status": "ok", "preview": [{"abstract": "0.670 +/- 0.019 %/yr"}]},
            )
        ],
    )
    assert result.passed is True
    assert result.metrics["unsourced_numbers"] == []


def test_a_rounded_restatement_of_a_tools_number_is_not_flagged(tmp_path):
    """0.71452 is how a model correctly restates 0.7145197; flagging it would
    flag good behaviour."""

    result = graded(
        tmp_path,
        MINIMAL_TASK,
        answer="The measured period is 0.71452 s.",
        events=[
            finished("compute_pulsar_periodogram", {"status": "ok", "period_s": 0.7145197})
        ],
    )
    assert result.metrics["unsourced_numbers"] == []


def test_a_designation_and_a_year_are_excluded_by_default(tmp_path):
    """"NGC 6334", "B0329+54" and "Trotter et al. 2017" are not
    measurements."""

    result = graded(
        tmp_path,
        MINIMAL_TASK,
        answer="NGC 6334 and B0329+54 were discussed in Trotter et al. 2017.",
        events=[finished("search_ned", {"status": "ok", "count": 0})],
    )
    assert result.metrics["unsourced_numbers"] == []


def test_an_explicit_background_label_satisfies_sourcing(tmp_path):
    """The system prompt already requires saying a figure is background
    rather than a result; a number inside such a sentence is correctly
    sourced as *not* from a tool."""

    result = graded(
        tmp_path,
        SOURCE_TASK,
        answer=(
            "As general background, not independently verified against the "
            "source this session, the decline rate is around 0.67%/yr."
        ),
        events=[finished("search_ads", {"status": "ok", "count": 0})],
    )
    assert result.passed is True
    assert result.metrics["unsourced_numbers"] == []


# --- fidelity: scope inflation -------------------------------------------


DISCLOSE_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_disclose:\n"
    "      - when_warning: listing_truncated\n"
    '        must_match: "truncat|not the (complete|whole)|more frames"\n'
    "        because: >\n"
    "          A truncated listing presented as the whole library is the\n"
    "          documented failure; the tool already says so in a warning.\n"
)


def test_a_fired_warning_with_no_disclosure_fails(tmp_path):
    result = graded(
        tmp_path,
        DISCLOSE_TASK,
        answer="There are five optical frames available.",
        tool_calls=[
            call(
                "list_optical_frames",
                warnings=[{"code": "listing_truncated", "message": "39 total"}],
            )
        ],
    )
    assert result.passed is False
    assert "listing_truncated" in result.failures[0].detail


def test_a_fired_warning_that_is_disclosed_passes(tmp_path):
    result = graded(
        tmp_path,
        DISCLOSE_TASK,
        answer="This listing is truncated at five of 39 frames.",
        tool_calls=[
            call(
                "list_optical_frames",
                warnings=[{"code": "listing_truncated", "message": "39 total"}],
            )
        ],
    )
    assert result.passed is True


def test_the_check_does_not_fire_when_the_warning_did_not(tmp_path):
    """Conditional on what the tools actually returned, so a model that
    avoided the bound entirely is not failing to disclose anything."""

    result = graded(
        tmp_path,
        DISCLOSE_TASK,
        answer="There are 39 optical frames.",
        tool_calls=[call("list_optical_frames")],
    )
    assert result.passed is True


# --- fidelity: mislabeling -----------------------------------------------


LABEL_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_label:\n"
    '      - value_pattern: "-?\\\\d+\\\\.\\\\d+"\n'
    '        near: "spectral index"\n'
    "        within_chars: 80\n"
    "        because: >\n"
    "          The S_nu ~ nu**alpha sign convention is not obvious out of\n"
    "          context, so a bare number is not a correct report of it.\n"
)


def test_a_bare_number_with_no_label_nearby_fails(tmp_path):
    result = graded(tmp_path, LABEL_TASK, answer="The source gives -0.77 for Cas A.")
    assert result.passed is False


def test_a_labeled_number_passes(tmp_path):
    result = graded(
        tmp_path,
        LABEL_TASK,
        answer="The spectral index is -0.77 (S_nu ~ nu**alpha).",
    )
    assert result.passed is True


def test_no_number_means_nothing_to_mislabel(tmp_path):
    assert graded(tmp_path, LABEL_TASK, answer="No spectrum was measured.").passed


# --- fidelity: omitted uncertainty ---------------------------------------


UNCERTAINTY_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_state_uncertainty:\n"
    "      - field: zero_point_error_mag\n"
    '        must_not_match: "accurate to"\n'
    "        because: >\n"
    "          It is the solve's formal scatter, not an accuracy figure for\n"
    "          the magnitudes; unmodeled systematics are not in it.\n"
)


def test_misdescribing_a_formal_scatter_as_an_accuracy_figure_fails(tmp_path):
    result = graded(
        tmp_path,
        UNCERTAINTY_TASK,
        answer="The zero point is 21.1477, accurate to 0.0116 mag.",
        events=[
            finished(
                "calibrate_zeropoint",
                {"status": "ok", "zero_point_mag": 21.1477, "zero_point_error_mag": 0.0116},
            )
        ],
    )
    assert result.passed is False
    assert "formal scatter" in result.failures[0].because


def test_describing_it_correctly_passes(tmp_path):
    result = graded(
        tmp_path,
        UNCERTAINTY_TASK,
        answer=(
            "The zero point is 21.1477 +/- 0.0116 mag, which is the solve's own "
            "formal scatter rather than an accuracy claim for the magnitudes."
        ),
        events=[
            finished(
                "calibrate_zeropoint",
                {"status": "ok", "zero_point_mag": 21.1477, "zero_point_error_mag": 0.0116},
            )
        ],
    )
    assert result.passed is True


def test_the_check_does_not_fire_when_the_field_was_never_returned(tmp_path):
    result = graded(
        tmp_path,
        UNCERTAINTY_TASK,
        answer="Nothing here is accurate to any stated precision.",
        events=[finished("list_optical_frames", {"status": "ok", "count": 39})],
    )
    assert result.passed is True


# --- correct negatives: the guarded assertion ----------------------------


CONDITIONAL_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    conditional:\n"
    "      - when_not_called: [get_paper_abstract, search_ads, build_literature_review]\n"
    '        answer_must_not_match: "\\\\d+(\\\\.\\\\d+)?\\\\s*%\\\\s*/\\\\s*yr"\n'
    "        because: >\n"
    "          Quoting a decline rate with no abstract-returning call means the\n"
    "          figure came from training data.\n"
)


def test_the_guard_opens_and_the_forbidden_figure_fails(tmp_path):
    result = graded(
        tmp_path,
        CONDITIONAL_TASK,
        answer="Cas A is declining at about 0.67%/yr.",
        tool_calls=[call("search_simbad")],
    )
    assert result.passed is False
    assert "training data" in result.failures[0].because


def test_the_guard_stays_shut_when_the_paper_was_fetched(tmp_path):
    result = graded(
        tmp_path,
        CONDITIONAL_TASK,
        answer="The abstract gives 0.670%/yr averaged over six decades.",
        tool_calls=[call("get_paper_abstract")],
    )
    assert result.passed is True


def test_an_honest_refusal_passes_the_guard(tmp_path):
    """The correct negative: with no abstract fetched, saying so is right."""

    result = graded(
        tmp_path,
        CONDITIONAL_TASK,
        answer="No abstract was retrieved, so I cannot give you a decline rate.",
        tool_calls=[call("search_simbad")],
    )
    assert result.passed is True


# --- the hard/soft split (7.1.8) -----------------------------------------


def test_must_match_is_a_deviation_and_must_not_match_is_a_failure(tmp_path):
    """The same asymmetry as the trajectory axis: must_not_match forbids a
    specific bad statement, while must_match requires a specific phrasing that
    another correct wording would fail."""

    body = BARE_TASK + (
        "expect:\n  answer:\n"
        '    must_match: ["definitely truncated"]\n'
        '    must_not_match: ["this is the complete library"]\n'
    )
    result = graded(tmp_path, body, answer="The listing is partial.")
    assert result.passed is True
    assert [d.check for d in result.deviations] == ["must_match"]

    result = graded(tmp_path, body, answer="This is the complete library.")
    assert result.passed is False
    assert result.failures[0].check == "must_not_match"


def test_passed_is_true_only_when_every_hard_check_is_green(tmp_path):
    body = (
        VALUE_TASK
        + "    must_report_artifact_path: true\n"
    )
    result = graded(
        tmp_path,
        body,
        answer="The period is 0.7145197 s.",
        tool_calls=[call("plot_pulsar")],
    )
    assert result.passed is False
    assert result.checks_passed == 1
    assert result.checks_total == 2


def test_a_near_miss_and_a_complete_miss_are_distinguishable(tmp_path):
    """Which is why two numbers are reported rather than one."""

    body = VALUE_TASK + '    must_not_match: ["no measurement"]\n'
    near = graded(tmp_path, body, answer="The period is 2.1 s.")
    total = graded(tmp_path, body, answer="There was no measurement; period 2.1 s.")
    assert near.checks_passed == 1 and total.checks_passed == 0
    assert near.checks_total == total.checks_total == 2


# --- numeric literals as models actually write them ----------------------


def test_comma_grouped_thousands_are_read_as_one_number(tmp_path):
    """Found by a live run. Without this, "4,127 rows" yielded 4 and 127 and
    never 4127, so must_report_value {expected: 4127} failed a *correct*
    answer; and "22,000" parsed as 0.0, a value that could spuriously satisfy
    a tolerance check. Models format numbers conventionally."""

    from tools.bench.graders.answer import numbers_in

    assert numbers_in("The table has 4,127 rows and 47 catalogs") == [4127.0, 47.0]
    assert numbers_in("22,000 Jy at 22 MHz") == [22000.0, 22.0]
    assert numbers_in("1,234,567 rows") == [1234567.0]


def test_a_decimal_comma_is_not_misread_as_a_group(tmp_path):
    """The group requires exactly three digits after each comma, so "3,14"
    falls to the plain form rather than becoming 314."""

    from tools.bench.graders.answer import numbers_in

    assert numbers_in("pi is 3,14 in some locales") == [3.0, 14.0]


def test_must_report_value_accepts_a_comma_grouped_answer(tmp_path):
    body = BARE_TASK + (
        "expect:\n  answer:\n    must_report_value:\n"
        "      - name: total_rows\n"
        "        source: {tool_result: search_vizier, field: count}\n"
        "        rel_tol: 0\n"
    )
    assert graded(
        tmp_path,
        body,
        answer="The full table holds 4,127 rows.",
        events=[finished("search_vizier", {"status": "ok", "count": 4127})],
    ).passed


def test_a_comma_grouped_number_the_tools_returned_is_not_flagged(tmp_path):
    result = graded(
        tmp_path,
        MINIMAL_TASK,
        answer="VizieR matched 4,127 rows.",
        events=[finished("search_vizier", {"status": "ok", "count": 4127})],
    )
    assert result.metrics["unsourced_numbers"] == []


def test_an_undisclaimed_rate_is_still_a_fabrication(tmp_path):
    """The widened vocabulary must not blunt the check itself."""

    result = graded(
        tmp_path,
        SOURCE_TASK,
        answer="Cassiopeia A declines at 0.3-0.7 %/yr depending on frequency.",
        events=[finished("search_ads", {"status": "ok", "count": 1})],
    )
    assert result.passed is False


# --- the benchmark must not be tuned to one model -------------------------


def test_every_background_label_is_a_phrase_the_system_prompt_uses():
    """The anti-bias guarantee, and the reason this test exists at all.

    BACKGROUND_LABELS decides whether a number is a fabrication or a properly
    labelled aside. Growing it by reading what some model happened to write
    tunes the benchmark to that model's prose, and every later provider is then
    measured against a vocabulary it was never given. That is not hypothetical:
    "paraphrase", "if you've seen" and "commonly quoted" were added after
    watching one local model hedge, and had to be removed.

    Grounding each label in SYSTEM_PROMPT makes the rule fair by construction,
    because every model is handed that prompt verbatim (7.1.1). If a label is
    not in the contract, no model was told to write it.
    """

    from tools.agent.prompt import SYSTEM_PROMPT
    from tools.bench.graders.answer import BACKGROUND_LABELS

    prompt = " ".join(SYSTEM_PROMPT.lower().split())
    ungrounded = [
        label for label in BACKGROUND_LABELS if label.lower() not in prompt
    ]
    assert not ungrounded, (
        f"{ungrounded} are not phrases SYSTEM_PROMPT uses. A sourcing label no "
        "model was instructed to write measures prose style, not sourcing."
    )


def test_the_documented_sourcing_label_satisfies_the_check(tmp_path):
    """The exact wording SYSTEM_PROMPT asks for must work, or the contract is
    one no model can satisfy."""

    result = graded(
        tmp_path,
        SOURCE_TASK,
        answer=(
            "The decline rate is around 0.67 %/yr. This is general background, "
            "not independently verified against the source this session."
        ),
        events=[finished("search_ads", {"status": "ok", "count": 0})],
    )
    assert result.passed is True


# --- a tool_result key: fidelity against this run's own measurement --------


TOOL_RESULT_TASK = BARE_TASK + (
    "expect:\n"
    "  answer:\n"
    "    must_report_value:\n"
    "      - name: pulse_snr\n"
    "        source: {tool_result: fold_pulsar_lightcurve, field: pulse_snr}\n"
    "        rel_tol: 0.05\n"
)


def test_a_tool_result_key_grades_against_what_the_tool_returned(tmp_path):
    """Not circular, and this is the test that says why.

    The expectation is the return value of repository code whose behaviour the
    preservation suite pins -- not a model's opinion. The model picks the
    arguments (graded on the trajectory axis); it cannot pick what the tool
    computes from them.
    """

    result = graded(
        tmp_path,
        TOOL_RESULT_TASK,
        answer="The fold reaches a pulse S/N of 5.7.",
        events=[finished("fold_pulsar_lightcurve", {"status": "ok", "pulse_snr": 5.71})],
    )
    assert result.passed


def test_a_tool_result_key_fails_an_answer_that_reports_a_different_number(tmp_path):
    result = graded(
        tmp_path,
        TOOL_RESULT_TASK,
        answer="The fold reaches a pulse S/N of 12.",
        events=[finished("fold_pulsar_lightcurve", {"status": "ok", "pulse_snr": 5.71})],
    )
    assert not result.passed


def test_a_tool_result_key_survives_the_fold_changing(tmp_path):
    """The reason a literal was wrong. 5.7 was one observed run; the day the
    fold returns 6.1 a literal fails a *correct* answer, and a source does
    not."""

    result = graded(
        tmp_path,
        TOOL_RESULT_TASK,
        answer="The fold reaches a pulse S/N of 6.1.",
        events=[finished("fold_pulsar_lightcurve", {"status": "ok", "pulse_snr": 6.1})],
    )
    assert result.passed


def test_a_tool_result_key_fails_when_the_tool_was_never_called(tmp_path):
    """A number reported for a measurement nobody made is the failure mode the
    whole suite exists for, so it fails the answer axis rather than erroring."""

    result = graded(tmp_path, TOOL_RESULT_TASK, answer="Pulse S/N is about 5.7.")
    assert not result.passed
    assert "never returned a numeric" in result.failures[0].detail


# --- an empty answer is not a correct negative ---------------------------


def test_an_empty_answer_fails_rather_than_passing_every_negative_check(tmp_path):
    """The whole reason ``empty_answer`` exists.

    A task whose key is entirely negative -- "do not say the object is
    missing" -- is satisfied by saying nothing at all, and the session ends
    ``end_turn``, so no outcome marks it either. A live sweep recorded
    ``qwen3.5:9b`` as 3/3 correct on ``atnf-formal-designation`` on exactly
    this, three repeats out of three.
    """

    body = BARE_TASK + (
        "expect:\n  answer:\n"
        '    must_not_match: ["is not in the catalogue"]\n'
    )
    result = graded(tmp_path, body, answer="   \n")
    assert result.passed is False
    assert [f.check for f in result.failures] == ["empty_answer"]
    assert result.metrics["empty_answer"] is True


def test_an_empty_answer_is_distinct_from_an_incomplete_run(tmp_path):
    """Two different things: one ran out of room, the other stopped talking.

    Collapsing them would file a model that answers nothing under the harness
    failures, where it is excluded from the score rather than counted wrong.
    """

    body = BARE_TASK + (
        "expect:\n  answer:\n"
        '    must_not_match: ["is not in the catalogue"]\n'
    )
    stopped = graded(tmp_path, body, answer="", outcome="end_turn")
    ran_out = graded(tmp_path, body, answer="", outcome="max_turns")
    assert [f.check for f in stopped.failures] == ["empty_answer"]
    assert [f.check for f in ran_out.failures] == ["incomplete"]


# --- must_source_value: a mention is not an assertion ---------------------


SOURCING_TASK = BARE_TASK + (
    "expect:\n  answer:\n"
    "    must_source_value:\n"
    '      - pattern: "%\\\\s*/\\\\s*yr"\n'
    "        because: the rate must come from a tool result.\n"
)


def test_a_disclaimed_number_is_a_mention_not_a_claim(tmp_path):
    """The check's oldest false positive, and it fired on the behaviour the
    system prompt asks for: told not to repeat a circulated figure, a model
    quoted it in order to reject it and was marked down for fabricating it."""

    answer = (
        'A commonly-cited "0.3-0.7 %/yr depending on frequency" is *not* what '
        "this paper says."
    )
    result = graded(tmp_path, SOURCING_TASK, answer=answer)
    assert result.passed is True
    assert result.metrics["unsourced_numbers"] == []


def test_quoting_alone_does_not_excuse_an_unsourced_number(tmp_path):
    """Two signals are required. Quoting alone would be an evasion: write the
    fabricated number in quotes and it stops counting."""

    answer = 'The decline is "0.55 %/yr" over the interval.'
    result = graded(tmp_path, SOURCING_TASK, answer=answer)
    assert result.passed is False
    assert result.failures[0].check == "must_source_value"


def test_a_negated_number_is_not_being_asserted(tmp_path):
    """"None matched the known 0.016665 s artifact" reports that a value did
    not occur; reading it as a measurement inverts the sentence."""

    answer = "None of the peaks matched the known 0.55 %/yr rate."
    result = graded(tmp_path, SOURCING_TASK, answer=answer)
    assert result.passed is True


def test_a_contrastive_pivot_closes_the_negation(tmp_path):
    """Scope, not mere presence. In "not X but Y" the Y is asserted, and a
    sentence-level negation test would wave it through."""

    answer = "The rate is not 0.31 %/yr but 0.55 %/yr."
    result = graded(tmp_path, SOURCING_TASK, answer=answer)
    assert result.passed is False
    # The disclaimed value drops out; the asserted one does not.
    assert result.failures[0].detail.count("0.55") == 1
    assert "0.31" not in result.failures[0].detail


def test_the_promotion_pattern_is_matched_at_the_flagged_occurrence(tmp_path):
    """It was matched against ``answer.find(literal)`` -- the first *substring*
    hit anywhere in the answer. For a bare "6" that lands inside some unrelated
    "0.1429", and a live run promoted the 6 of "0.1192 ~ P/6" that way."""

    body = BARE_TASK + (
        "expect:\n  answer:\n"
        "    must_source_value:\n"
        '      - pattern: "\\\\d\\\\.\\\\d{3,}\\\\s*(?:s\\\\b|sec)"\n'
        "        because: a period comes from the periodogram.\n"
    )
    answer = "The harmonics are 0.1192 s ~ P/6 and the fold is clean."
    result = graded(tmp_path, body, answer=answer)
    offending = result.failures[0].detail
    assert "0.1192" in offending
    assert "'6'" not in offending


# --- conditional: a guard on an outcome, not on a proxy call --------------


RESULT_GUARD_TASK = BARE_TASK + (
    "expect:\n  answer:\n"
    "    conditional:\n"
    "      - when_no_result:\n"
    "          tool: search_ned\n"
    "          where:\n"
    "            status: {equals: ok}\n"
    '        answer_must_not_match: "photometry (?:table|measurements) shows"\n'
    "        because: a photometry table cannot be reported when none was returned.\n"
)


def test_the_guard_stays_shut_when_the_tool_did_return_a_result(tmp_path):
    """The point of the form. ``no-identical-retry`` guarded "a table cannot be
    reported when no call returned one" on *search_simbad not being called*,
    contradicting its own trajectory rule, which accepts the formal designation
    from the model's own knowledge. Reading the result instead means a model
    that resolved the name itself and got a table is no longer accused."""

    result = graded(
        tmp_path,
        RESULT_GUARD_TASK,
        answer="The photometry table shows 214 measurements.",
        events=[finished("search_ned", {"status": "ok", "count": 214})],
    )
    assert result.passed is True


def test_the_guard_opens_when_every_call_failed(tmp_path):
    result = graded(
        tmp_path,
        RESULT_GUARD_TASK,
        answer="The photometry table shows 214 measurements.",
        events=[finished("search_ned", {"status": "error", "count": 0})],
    )
    assert result.passed is False
    assert result.failures[0].check == "conditional"


def test_the_guard_opens_when_the_tool_was_never_called(tmp_path):
    result = graded(
        tmp_path,
        RESULT_GUARD_TASK,
        answer="The photometry table shows 214 measurements.",
    )
    assert result.passed is False
