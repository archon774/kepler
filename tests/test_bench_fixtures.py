"""The fixture store: matching, miss policies, revalidation (B3), and the
artifact rules (S7/S6/S5).

docs/working/benchmark.md section 5.3. Fixture files are reviewed as
adversarial input, not as test data: they are committed, replayed, and are the
archive as far as a benchmarked model is concerned.
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from tools import artifacts
from tools.bench.fixtures import (
    FixtureError,
    FixtureStore,
    build_error_result,
    load_fixture_file,
    resolve_fixture_path,
    return_models,
)
from tools.models import PulsarScan, PulsarScanList, ToolResult
from tools.registry import TOOL_FUNCTIONS


@pytest.fixture()
def fixture_root(tmp_path, monkeypatch):
    root = tmp_path / "fixtures"
    (root / "content").mkdir(parents=True)
    monkeypatch.setattr(artifacts, "ARTIFACT_DIR", tmp_path / "artifacts")
    return root


def write(root, name, body):
    path = root / f"{name}.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


NED_OK = """
    tool: search_ned
    recorded_on: 2026-09-13
    entries:
      - id: ngc6334-photometry
        match:
          name: {matches: "^NGC\\\\s*6334"}
          table: {equals: photometry}
        response:
          status: ok
          count: 214
      - id: colloquial-name-fails
        match:
          name: {contains: "cat"}
        response:
          status: error
          errors:
            - code: provider_unavailable
              message: NED's resolver returned nothing for that name.
      - id: default
        match: {}
        response:
          status: not_found
          count: 0
    """


# --- S5: safe YAML --------------------------------------------------------


def test_a_python_object_tag_raises(fixture_root):
    path = write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: x
            match: {}
            response: !!python/object/apply:os.system ["echo pwned"]
        """,
    )
    with pytest.raises((FixtureError, yaml.YAMLError)):
        load_fixture_file(path)


# --- S6: containment ------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["../secrets", "/etc/passwd", "a/b", "..", "sub\\evil", ""]
)
def test_a_fixture_reference_that_is_not_a_bare_name_is_rejected(fixture_root, name):
    with pytest.raises(FixtureError, match="bare name|outside"):
        resolve_fixture_path(name, fixture_root)


def test_a_missing_fixture_is_named_rather_than_silently_empty(fixture_root):
    with pytest.raises(FixtureError, match="does not exist"):
        resolve_fixture_path("search_ned", fixture_root)


@pytest.mark.parametrize("ref", ["../../etc/passwd", "/etc/passwd", "sub/x.ecsv"])
def test_a_content_ref_that_leaves_the_content_directory_is_rejected(
    fixture_root, ref
):
    path = write(
        fixture_root,
        "search_ned",
        f"""
        tool: search_ned
        entries:
          - id: x
            match: {{}}
            response:
              status: ok
              count: 1
              artifact:
                format: ecsv
                content_ref: "{ref}"
        """,
    )
    with pytest.raises(FixtureError, match="bare filename|outside"):
        load_fixture_file(path)


# --- S7: content, never a path -------------------------------------------


@pytest.mark.parametrize("key", ["path", "subdir", "ext"])
def test_a_fixture_may_not_choose_where_a_byte_lands(fixture_root, key):
    """The whole of S7. Rejecting these keeps _write_directory()'s
    unvalidated subdir join and reserve_artifact_path()'s loosely-stripped ext
    unreachable from recorded data."""

    path = write(
        fixture_root,
        "search_ned",
        f"""
        tool: search_ned
        entries:
          - id: x
            match: {{}}
            response:
              status: ok
              count: 1
              artifact:
                format: ecsv
                {key}: "../../../escape.ecsv"
        """,
    )
    with pytest.raises(FixtureError, match="carries content, never a path"):
        load_fixture_file(path)


def test_the_shim_reserves_its_own_path_and_copies_the_recorded_body(fixture_root):
    (fixture_root / "content" / "ned_rows.ecsv").write_text(
        "# recorded rows\nra,dec\n1.0,2.0\n", encoding="utf-8"
    )
    write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: x
            match: {}
            response:
              status: ok
              count: 214
              artifact:
                format: ecsv
                row_count: 214
                columns: [ra, dec]
                content_ref: ned_rows.ecsv
        """,
    )
    store = FixtureStore.load(["search_ned"], root=fixture_root, task_id="ned-task")
    with artifacts.scoped_artifacts("bench/run/ned-task/r1"):
        result = store.replay("search_ned", {"name": "NGC 6334"})

    written = result.artifact.path
    assert "bench/run/ned-task/r1" in written
    assert written.endswith(".ecsv")
    assert "recorded rows" in open(written).read()
    # The recorded metadata survives; only the path is the harness's.
    assert result.artifact.row_count == 214
    assert result.artifact.columns == ["ra", "dec"]


def test_an_artifact_with_no_recorded_body_still_exists_on_disk(fixture_root):
    """must_report_artifact_path checks the quoted path against the manifest,
    and a path to nothing would pass it. An empty file is honest; a dangling
    one is not."""

    write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: x
            match: {}
            response:
              status: ok
              count: 3
              artifact: {format: ecsv, row_count: 3}
        """,
    )
    store = FixtureStore.load(["search_ned"], root=fixture_root)
    with artifacts.scoped_artifacts("bench/run/t/r1"):
        result = store.replay("search_ned", {})
    from pathlib import Path

    assert Path(result.artifact.path).exists()


# --- B3: revalidation through the tool's own return model ----------------


def test_a_drifted_fixture_fails_at_load_before_a_token_is_spent(fixture_root):
    path = write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: x
            match: {}
            response:
              status: definitely-not-a-status
              count: 1
        """,
    )
    with pytest.raises(FixtureError, match="return model"):
        load_fixture_file(path)


def test_a_union_return_validates_if_any_member_accepts_the_body(fixture_root):
    """resolve_pulsar_scan returns PulsarScan | PulsarScanList, and a fixture
    may legitimately record either."""

    assert set(return_models(TOOL_FUNCTIONS["resolve_pulsar_scan"])) == {
        PulsarScan,
        PulsarScanList,
    }


def test_an_unregistered_tool_is_rejected(fixture_root):
    path = write(
        fixture_root,
        "not_a_tool",
        """
        tool: not_a_tool
        entries: []
        """,
    )
    with pytest.raises(FixtureError, match="not a registered tool"):
        load_fixture_file(path)


def test_an_unknown_top_level_key_is_an_error(fixture_root):
    path = write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        mis_policy: error
        entries: []
        """,
    )
    with pytest.raises(FixtureError, match="unknown top-level"):
        load_fixture_file(path)


def test_an_unknown_predicate_is_an_error(fixture_root):
    path = write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: x
            match:
              name: {startswith: NGC}
            response: {status: ok, count: 0}
        """,
    )
    with pytest.raises(FixtureError, match="unknown predicate"):
        load_fixture_file(path)


def test_a_default_entry_that_is_not_last_is_an_error(fixture_root):
    path = write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: catch-all
            match: {}
            response: {status: not_found, count: 0}
          - id: shadowed
            match: {name: {equals: "NGC 6334"}}
            response: {status: ok, count: 1}
        """,
    )
    with pytest.raises(FixtureError, match="shadow"):
        load_fixture_file(path)


# --- matching -------------------------------------------------------------


@pytest.fixture()
def ned_store(fixture_root):
    write(fixture_root, "search_ned", NED_OK)
    return FixtureStore.load(["search_ned"], root=fixture_root)


def test_first_match_wins_in_file_order(ned_store):
    result = ned_store.replay(
        "search_ned", {"name": "NGC 6334", "table": "photometry"}
    )
    assert result.count == 214


def test_contains_is_case_folded(ned_store):
    """Different models spell the same target differently; exact-argument
    keying would miss constantly and measure argument formatting."""

    for spelling in ("Cat's Paw Nebula", "cat's paw", "CAT'S PAW"):
        result = ned_store.replay("search_ned", {"name": spelling})
        assert result.status == "error"
        assert result.errors[0].code == "provider_unavailable"


def test_matches_is_anchored(ned_store):
    """An unanchored regex would let 'PGC NGC 6334' through as a formal
    designation, which is the failure the core suite grades."""

    assert (
        ned_store.replay(
            "search_ned", {"name": "the NGC 6334 region", "table": "photometry"}
        ).status
        == "not_found"
    )


def test_the_trailing_empty_match_is_the_per_tool_default(ned_store):
    assert ned_store.replay("search_ned", {"name": "M31"}).status == "not_found"


def test_present_absent_and_is_null_are_three_different_questions(fixture_root):
    """JSON null is how an uncapped result is requested and an omitted
    argument means the default cap; a fixture conflating them answers the
    wrong call."""

    write(
        fixture_root,
        "search_vizier",
        """
        tool: search_vizier
        entries:
          - id: uncapped
            match: {max_catalogs: {is_null: true}}
            response: {status: ok, count: 4127}
          - id: omitted
            match: {max_catalogs: {absent: true}}
            response: {status: partial, count: 20}
          - id: capped
            match: {max_catalogs: {present: true}}
            response: {status: partial, count: 5}
        """,
    )
    store = FixtureStore.load(["search_vizier"], root=fixture_root)
    assert store.replay("search_vizier", {"max_catalogs": None}).count == 4127
    assert store.replay("search_vizier", {}).count == 20
    assert store.replay("search_vizier", {"max_catalogs": 5}).count == 5


def test_one_of_matches_any_listed_value(fixture_root):
    write(
        fixture_root,
        "search_atnf",
        """
        tool: search_atnf
        entries:
          - id: crab
            match: {name: {one_of: [J0534+2200, B0531+21]}}
            response: {status: ok, count: 1}
          - id: default
            match: {}
            response: {status: not_found, count: 0}
        """,
    )
    store = FixtureStore.load(["search_atnf"], root=fixture_root)
    assert store.replay("search_atnf", {"name": "B0531+21"}).count == 1
    # ATNF does zero name resolution; "Crab" matches nothing, and the fixture
    # reproduces that rather than being helpful about it.
    assert store.replay("search_atnf", {"name": "Crab"}).count == 0


# --- miss policies --------------------------------------------------------


def test_the_default_miss_policy_hands_the_model_an_honest_error(fixture_root):
    write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        entries:
          - id: only-this
            match: {name: {equals: "NGC 6334"}}
            response: {status: ok, count: 1}
        """,
    )
    store = FixtureStore.load(["search_ned"], root=fixture_root)
    result = store.replay("search_ned", {"name": "M31"})
    assert result.status == "error"
    assert result.errors[0].code == "fixture_miss"
    assert "Nothing was queried" in result.errors[0].message
    assert store.misses and store.miss_rate == 1.0


def test_synthesize_returns_a_schema_valid_empty_result(fixture_root):
    write(
        fixture_root,
        "search_ned",
        """
        tool: search_ned
        miss_policy: synthesize
        entries:
          - id: only-this
            match: {name: {equals: "NGC 6334"}}
            response: {status: ok, count: 1}
        """,
    )
    store = FixtureStore.load(["search_ned"], root=fixture_root)
    result = store.replay("search_ned", {"name": "M31"})
    assert result.status == "not_found"
    assert result.count == 0


def test_a_task_can_override_the_files_policy(fixture_root):
    write(fixture_root, "search_ned", NED_OK)
    store = FixtureStore.load(
        ["search_ned"], root=fixture_root, miss_policy="synthesize"
    )
    # The file's own default entry answers everything, so force a real miss by
    # asking for a tool the task did not declare.
    result = store.replay("search_mpc", {"designation": "1P"})
    assert result.status == "not_found"


def test_a_tool_with_no_declared_fixture_file_misses_and_says_which(fixture_root):
    write(fixture_root, "search_ned", NED_OK)
    store = FixtureStore.load(["search_ned"], root=fixture_root)
    result = store.replay("search_mpc", {"designation": "1P"})
    assert result.errors[0].code == "fixture_miss"
    assert "no fixture file is declared" in result.errors[0].message


def test_an_invalid_miss_policy_is_rejected(fixture_root):
    write(fixture_root, "search_ned", NED_OK)
    with pytest.raises(FixtureError, match="miss_policy"):
        FixtureStore.load(["search_ned"], root=fixture_root, miss_policy="ignore")


def test_the_miss_rate_is_tracked_per_run(fixture_root):
    """A suite with a high miss rate is measuring its own coverage rather than
    the model, and the report says so in those words."""

    write(fixture_root, "search_ned", NED_OK)
    store = FixtureStore.load(["search_ned"], root=fixture_root)
    store.replay("search_ned", {"name": "NGC 6334", "table": "photometry"})
    store.replay("search_ned", {"name": "NGC 6334", "table": "photometry"})
    store.replay("search_mpc", {"designation": "Halley"})
    assert store.hits == 2
    assert store.miss_rate == pytest.approx(1 / 3)


# --- error results --------------------------------------------------------


def test_an_error_result_uses_the_tools_own_return_model():
    result = build_error_result(
        TOOL_FUNCTIONS["search_ned"], code="fixture_miss", message="nope"
    )
    assert isinstance(result, ToolResult)
    assert result.model_dump()["errors"][0]["code"] == "fixture_miss"
