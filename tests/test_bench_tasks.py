"""The task loader: safe YAML (S5), containment (S6), env (B7), and the
required ``because``.

docs/working/benchmark.md section 6.1. The loader is strict in one specific
way that matters: unknown keys are an error. A typo in ``must_not_call`` that
silently grades nothing is worse than a load failure, because the suite keeps
reporting a pass that was never checked.

YAML bodies below are written flush-left rather than dedented, so a test can
append an ``expect:`` stanza to ``MINIMAL`` without the two fighting over a
common indent prefix.
"""

from __future__ import annotations

import pytest

from tools.bench.tasks import TaskError, load_suite, load_task

FIXTURE_ROOT = "benchmarks/fixtures"
SMOKE_SUITE = "benchmarks/suites/smoke"

MINIMAL = "id: a-task\ntitle: A task\nprompt: Do the thing.\n"


def write(tmp_path, body, name="t.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# --- S5 -------------------------------------------------------------------


def test_a_python_object_tag_raises(tmp_path):
    path = write(
        tmp_path,
        'id: a-task\nprompt: !!python/object/apply:os.system ["echo pwned"]\n',
    )
    with pytest.raises(TaskError):
        load_task(path)


# --- ids ------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["A-Task", "../escape", "a task", "-leading", "", "x" * 65, "a/b"]
)
def test_an_id_that_could_not_be_an_artifact_subdirectory_is_rejected(tmp_path, bad):
    """It becomes an artifact subdirectory name and scoped_artifacts would
    reject it anyway; rejecting here gives a better message, before a run."""

    path = write(tmp_path, f"id: {bad!r}\nprompt: go\n")
    with pytest.raises(TaskError, match="id must match"):
        load_task(path)


def test_a_minimal_task_loads(tmp_path):
    task = load_task(write(tmp_path, MINIMAL))
    assert task.id == "a-task"
    assert task.prompt == "Do the thing."
    assert task.max_turns == 12


def test_an_empty_prompt_is_rejected(tmp_path):
    with pytest.raises(TaskError, match="non-empty prompt"):
        load_task(write(tmp_path, "id: a-task\nprompt: '   '\n"))


def test_max_turns_must_be_a_positive_integer(tmp_path):
    with pytest.raises(TaskError, match="max_turns"):
        load_task(write(tmp_path, MINIMAL + "max_turns: 0\n"))


# --- unknown keys ---------------------------------------------------------


def test_an_unknown_top_level_key_is_an_error(tmp_path):
    with pytest.raises(TaskError, match="unknown top-level"):
        load_task(write(tmp_path, MINIMAL + "max_tokens: 100\n"))


def test_a_misspelled_check_name_is_an_error_rather_than_grading_nothing(tmp_path):
    """The reason unknown keys are rejected at all: a check that silently
    grades nothing keeps reporting a pass that was never checked."""

    path = write(
        tmp_path,
        MINIMAL + "expect:\n  trajectory:\n    must_not_calls: [search_ned]\n",
    )
    with pytest.raises(TaskError, match="expect.trajectory has unknown"):
        load_task(path)


def test_an_unknown_answer_check_is_an_error(tmp_path):
    path = write(tmp_path, MINIMAL + "expect:\n  answer:\n    must_mention: ['x']\n")
    with pytest.raises(TaskError, match="expect.answer has unknown"):
        load_task(path)


def test_an_unknown_expect_section_is_an_error(tmp_path):
    path = write(tmp_path, MINIMAL + "expect:\n  efficiency:\n    max_turns: 3\n")
    with pytest.raises(TaskError, match="expect has unknown"):
        load_task(path)


# --- B7: env --------------------------------------------------------------


def test_a_task_may_shape_keplers_own_configuration(tmp_path):
    task = load_task(write(tmp_path, MINIMAL + "env:\n  KEPLER_MAX_FRAMES: '5'\n"))
    assert task.env == {"KEPLER_MAX_FRAMES": "5"}


@pytest.mark.parametrize(
    "key",
    [
        "ANTHROPIC_API_KEY",
        "OPENAI_BASE_URL",
        "PATH",
        "LD_PRELOAD",
        "kepler_max_frames",
        "KEPLERISH",
    ],
)
def test_a_task_may_not_set_anything_else(tmp_path, key):
    """It cannot set a credential, a provider base URL, or PATH."""

    with pytest.raises(TaskError, match="is not allowed"):
        load_task(write(tmp_path, MINIMAL + f"env:\n  {key}: 'x'\n"))


# --- S6: containment ------------------------------------------------------


@pytest.mark.parametrize("name", ["../../etc/passwd", "/etc/passwd", "a/b"])
def test_a_fixture_reference_that_is_not_a_bare_name_is_rejected(tmp_path, name):
    path = write(tmp_path, MINIMAL + f"fixtures: ['{name}']\n")
    with pytest.raises(TaskError, match="bare name|outside"):
        load_task(path, fixture_root=FIXTURE_ROOT)


@pytest.mark.parametrize("member", ["../../../etc/passwd", "/etc/passwd", "sub/x"])
def test_a_suite_member_that_is_not_a_bare_filename_is_rejected(tmp_path, member):
    path = write(
        tmp_path, f"id: s\ndescription: d\ntasks: ['{member}']\n", name="suite.yaml"
    )
    with pytest.raises(TaskError, match="bare filename|outside"):
        load_suite(path)


# --- the required `because` ----------------------------------------------


ARGUMENT_RULE = (
    "expect:\n"
    "  trajectory:\n"
    "    arguments:\n"
    "      - tool: search_ned\n"
    '        where:\n          name: {matches: "^NGC"}\n'
)


def test_an_argument_rule_without_a_because_is_rejected(tmp_path):
    """It is printed verbatim in the report beside the failure, so a
    scoreboard entry explains itself without anyone opening the suite file.
    An untested convention elsewhere; here the loader enforces it."""

    with pytest.raises(TaskError, match="needs a non-empty `because`"):
        load_task(write(tmp_path, MINIMAL + ARGUMENT_RULE))


HARD_CHECK_BODIES = {
    "must_reach_verdict": (
        "      - tool: compare_zeropoint_to_reference\n"
        "        field: within_tolerance\n"
        "        equals: true\n"
    ),
    "must_disclose": (
        "      - when_warning: listing_truncated\n"
        '        must_match: "truncat"\n'
    ),
    "must_label": (
        '      - value_pattern: "-?\\\\d+\\\\.\\\\d+"\n'
        '        near: "spectral index"\n'
    ),
    "must_state_uncertainty": (
        "      - field: zero_point_error_mag\n"
        '        must_not_match: "accurate to"\n'
    ),
    "must_source_value": '      - pattern: "%/yr"\n',
    "conditional": (
        "      - when_not_called: [search_ads]\n"
        '        answer_must_not_match: "[0-9]+%"\n'
    ),
}


@pytest.mark.parametrize("kind", sorted(HARD_CHECK_BODIES))
def test_every_hard_answer_check_requires_a_because(tmp_path, kind):
    body = MINIMAL + f"expect:\n  answer:\n    {kind}:\n" + HARD_CHECK_BODIES[kind]
    with pytest.raises(TaskError, match="because"):
        load_task(write(tmp_path, body, name=f"{kind}.yaml"))


@pytest.mark.parametrize("kind", sorted(HARD_CHECK_BODIES))
def test_every_hard_answer_check_loads_with_one(tmp_path, kind):
    body = (
        MINIMAL
        + f"expect:\n  answer:\n    {kind}:\n"
        + HARD_CHECK_BODIES[kind]
        + "        because: it matters\n"
    )
    task = load_task(write(tmp_path, body, name=f"{kind}-ok.yaml"))
    assert task.answer[kind][0]["because"] == "it matters"


def test_a_because_survives_as_one_line_for_the_report(tmp_path):
    body = (
        MINIMAL
        + ARGUMENT_RULE
        + "        because: >\n"
        "          NED's resolver is unreliable with colloquial names; the\n"
        "          system prompt requires a formal designation first.\n"
    )
    because = load_task(write(tmp_path, body)).trajectory["arguments"][0]["because"]
    assert "\n" not in because
    assert because.startswith("NED's resolver")


# --- validation against the registry --------------------------------------


def test_an_unregistered_tool_in_a_trajectory_check_is_rejected(tmp_path):
    path = write(
        tmp_path, MINIMAL + "expect:\n  trajectory:\n    must_call: [search_gaia]\n"
    )
    with pytest.raises(TaskError, match="unregistered tool"):
        load_task(path)


def test_an_unknown_argument_predicate_is_rejected(tmp_path):
    body = (
        MINIMAL
        + "expect:\n  trajectory:\n    arguments:\n      - tool: search_ned\n"
        "        where:\n          name: {startswith: NGC}\n"
        "        because: x\n"
    )
    with pytest.raises(TaskError, match="unknown predicate"):
        load_task(write(tmp_path, body))


def test_an_argument_rule_with_no_predicate_is_rejected(tmp_path):
    body = (
        MINIMAL
        + "expect:\n  trajectory:\n    arguments:\n      - tool: search_ned\n"
        "        where: {}\n        because: x\n"
    )
    with pytest.raises(TaskError, match="at least one predicate"):
        load_task(write(tmp_path, body))


def test_an_invalid_regex_is_rejected_at_load(tmp_path):
    path = write(tmp_path, MINIMAL + 'expect:\n  answer:\n    must_match: ["[unclosed"]\n')
    with pytest.raises(TaskError, match="valid regular expression"):
        load_task(path)


def test_null_argument_fidelity_only_applies_to_a_null_accepting_property(tmp_path):
    """On a property that never accepts null the check would grade nothing, so
    the suite says so at load rather than reporting a free pass."""

    body = (
        MINIMAL
        + "expect:\n  protocol:\n    null_argument_fidelity:\n"
        "      - tool: search_ned\n        property: name\n"
    )
    with pytest.raises(TaskError, match="does not accept null"):
        load_task(write(tmp_path, body))


def test_null_argument_fidelity_accepts_one_of_the_eight_union_properties(tmp_path):
    body = (
        MINIMAL
        + "expect:\n  protocol:\n    null_argument_fidelity:\n"
        "      - tool: search_vizier\n        property: max_catalogs\n"
    )
    rules = load_task(write(tmp_path, body)).protocol["null_argument_fidelity"]
    assert rules[0]["tool"] == "search_vizier"
    assert rules[0]["property"] == "max_catalogs"


def test_enable_may_only_name_a_tool_that_is_blocked_by_default(tmp_path):
    with pytest.raises(TaskError, match="not blocked by default"):
        load_task(write(tmp_path, MINIMAL + "enable: [search_ned]\n"))
    task = load_task(write(tmp_path, MINIMAL + "enable: [solve_astrometry]\n"))
    assert task.enable == ("solve_astrometry",)


def test_a_task_cannot_ask_for_record_mode(tmp_path):
    """It is capture mode only, and would make a benchmark run perform live
    remote calls."""

    with pytest.raises(TaskError, match="capture mode only"):
        load_task(write(tmp_path, MINIMAL + "miss_policy: record\n"))


def test_a_conditional_needs_exactly_one_guard_and_one_assertion(tmp_path):
    body = (
        MINIMAL
        + "expect:\n  answer:\n    conditional:\n"
        "      - when_not_called: [search_ads]\n"
        "        when_called: [search_ned]\n"
        '        answer_must_not_match: "x"\n'
        "        because: y\n"
    )
    with pytest.raises(TaskError, match="exactly one of when_not_called"):
        load_task(write(tmp_path, body))


def test_must_report_value_requires_a_number(tmp_path):
    body = (
        MINIMAL
        + "expect:\n  answer:\n    must_report_value:\n"
        "      - name: period_s\n        expected: fast\n"
    )
    with pytest.raises(TaskError, match="expected must be a number"):
        load_task(write(tmp_path, body))


def test_must_report_value_loads_with_a_tolerance_and_a_unit(tmp_path):
    body = (
        MINIMAL
        + "expect:\n  answer:\n    must_report_value:\n"
        "      - name: period_s\n        expected: 0.7145197\n"
        "        rel_tol: 0.02\n        unit: s\n"
    )
    check = load_task(write(tmp_path, body)).answer["must_report_value"][0]
    assert check == {
        "name": "period_s",
        "expected": 0.7145197,
        "rel_tol": 0.02,
        "unit": "s",
        "because": None,
    }


# --- suites ---------------------------------------------------------------


def test_the_committed_smoke_suite_loads():
    suite = load_suite(SMOKE_SUITE, fixture_root=FIXTURE_ROOT)
    assert suite.id == "smoke"
    assert [task.id for task in suite] == ["pulsar-scan-inventory"]
    assert suite.tagged("smoke")


def test_the_smoke_suite_needs_no_fixture_and_touches_no_remote_tool():
    """It is the harness's own regression test: both sides replayed, header
    reads only, under a second, inside a plain `uv run pytest`."""

    from tools.bench.plane import TOOL_CLASSES

    suite = load_suite(SMOKE_SUITE, fixture_root=FIXTURE_ROOT)
    for task in suite:
        assert task.fixtures == ()
        named = set(task.trajectory["must_call"]) | set(task.trajectory["order"])
        assert all(TOOL_CLASSES[name] == "local" for name in named)


def test_a_suite_with_a_duplicate_task_id_is_rejected(tmp_path):
    write(tmp_path, MINIMAL, name="one.yaml")
    write(tmp_path, MINIMAL, name="two.yaml")
    path = write(
        tmp_path, "id: s\ndescription: d\ntasks: [one, two]\n", name="suite.yaml"
    )
    with pytest.raises(TaskError, match="more than once"):
        load_suite(path)


def test_a_suite_that_lists_no_tasks_is_rejected(tmp_path):
    path = write(tmp_path, "id: s\ndescription: d\ntasks: []\n", name="suite.yaml")
    with pytest.raises(TaskError, match="lists no tasks"):
        load_suite(path)


def test_a_missing_member_is_named(tmp_path):
    path = write(tmp_path, "id: s\ndescription: d\ntasks: [absent]\n", name="suite.yaml")
    with pytest.raises(TaskError, match="does not exist"):
        load_suite(path)


def test_a_suite_directory_resolves_to_its_suite_yaml(tmp_path):
    write(tmp_path, MINIMAL, name="one.yaml")
    write(tmp_path, "id: s\ndescription: d\ntasks: [one]\n", name="suite.yaml")
    assert load_suite(tmp_path).id == "s"
