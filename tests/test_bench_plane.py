"""The tool plane: closure, signature preservation, and per-call routing.

docs/working/benchmark.md section 3 and requirement B1. The registry went from
49 tools to 55 in four days while the model port was being written. Without a
closed plane, the first new remote tool added after the harness lands would run
live, against a real service, inside a benchmark run that believes it is
offline -- silently, with the resulting latency and failure folded into
someone's scoreboard.
"""

from __future__ import annotations

import inspect

import pytest

from tools.bench import plane
from tools.bench.plane import (
    DEFAULT_BLOCKED,
    OFFLINE_PREDICATES,
    TOOL_CLASSES,
    build_tool_plane,
    classify_call,
)
from tools.models import ToolResult
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS


def _replay(name, arguments):
    return ToolResult(status="ok", count=0, preview=[{"replayed": name}])


# --- B1: the plane is closed ---------------------------------------------


def test_every_registered_tool_is_classified():
    """The requirement itself. A new registry tool fails this until someone
    decides, per tool, whether it opens a socket."""

    assert set(TOOL_CLASSES) == set(TOOL_FUNCTIONS)


def test_the_classification_names_only_the_three_classes():
    assert set(TOOL_CLASSES.values()) == {"local", "remote", "mixed"}


def test_every_mixed_tool_has_an_offline_predicate_and_no_other_tool_does():
    mixed = {name for name, kind in TOOL_CLASSES.items() if kind == "mixed"}
    assert set(OFFLINE_PREDICATES) == mixed


def test_an_unclassified_tool_raises_rather_than_defaulting():
    """Every default here is wrong: defaulting to live opens a socket mid-run,
    and defaulting to replay measures a fixture miss instead of the tool."""

    with pytest.raises(KeyError, match="no benchmark classification"):
        classify_call("a_tool_nobody_classified", {})

    with pytest.raises(KeyError, match="no benchmark classification"):
        build_tool_plane(
            replay=_replay, functions={"brand_new_tool": lambda: None}
        )


def test_building_the_plane_covers_every_name_in_the_registry():
    """Not a subset. engine.py passes ``functions.get(call.name)`` into
    validate_tool_call as the signature fallback, and a missing name would
    turn a schema-valid call into a spurious unknown_tool fault -- inflating
    the protocol axis with the harness's own omission."""

    built = build_tool_plane(replay=_replay)
    assert set(built) == set(TOOL_FUNCTIONS)


def test_the_local_class_holds_no_tool_from_a_remote_module():
    """A per-module guess is what this classification exists to avoid."""

    remote_modules = {"tools.ads", "tools.simbad", "tools.vizier", "tools.ned"}
    for name, kind in TOOL_CLASSES.items():
        if TOOL_FUNCTIONS[name].__module__ in remote_modules:
            assert kind == "remote", name


def test_get_literature_cluster_params_is_remote_despite_looking_local():
    """It returns Cantat-Gaudin & Anders (2020) parameters, but
    algorithms/hrdiagram_py/literature.py fetches them through search_vizier."""

    assert TOOL_CLASSES["get_literature_cluster_params"] == "remote"


def test_tools_hr_diagram_spans_all_three_classes():
    """Which is why the classification is per tool rather than per module."""

    kinds = {
        TOOL_CLASSES[name]
        for name, func in TOOL_FUNCTIONS.items()
        if func.__module__ == "tools.hr_diagram"
    }
    assert kinds == {"local", "remote", "mixed"}


# --- routing --------------------------------------------------------------


def test_a_local_tool_runs_live():
    assert classify_call("compute_pulsar_periodogram", {"path": "x"}) == "live"


def test_a_remote_tool_is_always_replayed_whatever_its_arguments():
    assert classify_call("search_ned", {"name": "NGC 6334"}) == "replay"
    assert classify_call("search_ned", {}) == "replay"


def test_run_photometry_runs_live_only_when_the_model_pins_the_offline_path():
    """Choosing to turn field calibration off is itself a graded behaviour:
    it costs 30-90 s of network time, and the system prompt tells the model to
    skip it when the user only wants source counts."""

    live = {"target": "carina", "use_field_cal": False}
    assert classify_call("run_photometry_on_target", live) == "live"
    # The default is true, so an omitted argument is the *online* path.
    assert classify_call("run_photometry_on_target", {"target": "carina"}) == "replay"
    assert (
        classify_call("run_photometry_on_target", {"target": "c", "use_field_cal": True})
        == "replay"
    )


def test_calibrate_zeropoint_needs_the_fixture_and_the_reference_together():
    both = {"path": "f.fits", "catalog_fixture": "full_response", "compare_to": "ngc5128_b_002"}
    assert classify_call("calibrate_zeropoint", both) == "live"
    assert (
        classify_call("calibrate_zeropoint", {"path": "f.fits", "catalog_fixture": "full_response"})
        == "replay"
    )
    assert (
        classify_call("calibrate_zeropoint", {"path": "f.fits", "compare_to": "ngc5128_b_002"})
        == "replay"
    )


def test_the_calibrate_zeropoint_predicate_is_checked_against_the_registry_schema():
    """Section 17 question 1. The offline contract lives in
    tools/photometry.py and is declared in the tool's own schema; asserting
    the predicate against that schema is how the rule stays one rule. If the
    contract changes, this fails rather than the tool quietly starting to be
    replayed when it could have run live."""

    schema = next(
        s["input_schema"] for s in TOOL_SCHEMAS if s["name"] == "calibrate_zeropoint"
    )
    properties = schema["properties"]
    assert "compare_to" in properties
    enum = properties["catalog_fixture"]["enum"]
    # Every declared enum value must satisfy the predicate when paired with a
    # reference, and none of them without one.
    for value in enum:
        args = {"path": "f.fits", "catalog_fixture": value}
        assert classify_call("calibrate_zeropoint", args) == "replay"
        assert classify_call("calibrate_zeropoint", {**args, "compare_to": "r"}) == "live"
    # And the schema still says the two go together.
    assert "required with this" in properties["catalog_fixture"]["description"]


def test_the_two_full_pipeline_tools_have_no_offline_path():
    """Each wraps a Gaia crossmatch; no argument makes them offline."""

    for name in ("run_full_hr_pipeline", "run_full_hr_pipeline_from_catalog"):
        assert classify_call(name, {"cluster_name": "NGC 2168"}) == "replay"


def test_solve_astrometry_is_blocked_by_default_and_opted_in_explicitly():
    assert "solve_astrometry" in DEFAULT_BLOCKED
    assert classify_call("solve_astrometry", {"path": "f.fits"}) == "blocked"
    assert (
        classify_call("solve_astrometry", {"path": "f.fits"}, blocked=frozenset())
        == "live"
    )


# --- the shims ------------------------------------------------------------


def test_functools_wraps_keeps_every_empty_properties_tool_faulting_as_it_does():
    """Not a nicety. engine.py falls back to the callable's signature for a
    schema with no ``properties``; without __wrapped__, list_pulsar_scans and
    the four other such tools would stop faulting on junk arguments under
    replay and the protocol grader would report a model as cleaner than it
    is."""

    built = build_tool_plane(replay=_replay)
    empty = [
        s["name"]
        for s in TOOL_SCHEMAS
        if not s["input_schema"].get("properties")
    ]
    assert empty, "the repository has empty-properties schemas; this guards them"
    for name in empty:
        assert inspect.signature(built[name]) == inspect.signature(
            TOOL_FUNCTIONS[name]
        ), name


def test_the_signature_fallback_still_faults_through_the_shim():
    """The end-to-end form of the check above, through the real validator."""

    from tools.llm.validation import index_schemas, validate_tool_call

    built = build_tool_plane(replay=_replay)
    index = index_schemas(TOOL_SCHEMAS)
    fault = validate_tool_call(
        "list_pulsar_scans",
        {"nonsense": 1},
        index,
        func=built["list_pulsar_scans"],
    )
    assert fault is not None and fault.type == "schema_violation"


def test_a_replayed_call_reaches_the_replay_callable_and_the_real_one_never_runs():
    calls = []

    def replay(name, arguments):
        calls.append((name, dict(arguments)))
        return ToolResult(status="ok", count=1)

    def boom(**kwargs):
        raise AssertionError("a class-R tool must never execute in a run")

    built = build_tool_plane(
        replay=replay, functions={**TOOL_FUNCTIONS, "search_ned": boom}
    )
    result = built["search_ned"](name="NGC 6334", table="photometry")
    assert result.status == "ok"
    assert calls == [("search_ned", {"name": "NGC 6334", "table": "photometry"})]


def test_a_live_call_reaches_the_real_function():
    seen = []

    def real(**kwargs):
        seen.append(kwargs)
        return ToolResult(status="ok", count=7)

    built = build_tool_plane(
        replay=_replay, functions={**TOOL_FUNCTIONS, "list_pulsar_scans": real}
    )
    assert built["list_pulsar_scans"]().count == 7
    assert seen == [{}]


def test_a_blocked_tool_returns_a_schema_valid_error_rather_than_raising():
    built = build_tool_plane(replay=_replay)
    result = built["solve_astrometry"](path="frame.fits")
    dumped = result.model_dump()
    assert dumped["status"] == "error"
    assert dumped["errors"][0]["code"] == "tool_disabled"
    assert "--enable" in dumped["errors"][0]["message"]


def test_enable_lifts_the_block():
    live = []
    built = build_tool_plane(
        replay=_replay,
        functions={
            **TOOL_FUNCTIONS,
            "solve_astrometry": lambda **kw: live.append(kw) or ToolResult(status="ok"),
        },
        enabled=frozenset({"solve_astrometry"}),
    )
    built["solve_astrometry"](path="frame.fits")
    assert live == [{"path": "frame.fits"}]


def test_a_shim_keeps_the_real_functions_identity_for_reflection():
    built = build_tool_plane(replay=_replay)
    shim = built["search_ned"]
    assert shim.__wrapped__ is TOOL_FUNCTIONS["search_ned"]
    assert shim.__doc__ == TOOL_FUNCTIONS["search_ned"].__doc__


def test_the_class_counts_match_the_document():
    """Section 3.1 states 26 local, 22 remote, 7 mixed. Drift in either
    direction is a decision someone should have written down."""

    counts = {kind: 0 for kind in ("local", "remote", "mixed")}
    for kind in TOOL_CLASSES.values():
        counts[kind] += 1
    assert counts == {"local": 26, "remote": 22, "mixed": 7}
    assert sum(counts.values()) == 55
