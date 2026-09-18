"""Approval-policy behavior for the headless agent loop."""

from __future__ import annotations

from tools.agent.approval import Decision
from tools.agent.events import ToolCallProposed
from tools.agent.policy import (
    TOOL_RISK,
    SessionPolicy,
    needs_confirmation,
    policy_approver,
    risk_tags,
)
from tools.registry import TOOL_FUNCTIONS


def test_risk_tags_match_the_declared_approval_table():
    assert risk_tags("run_photometry_on_target") == frozenset({"slow"})
    assert risk_tags("search_ads") == frozenset({"keyed"})
    assert risk_tags("sonify_pulsar") == frozenset({"writes"})
    assert risk_tags("resolve_target") == frozenset()
    assert needs_confirmation("run_photometry_on_target") is True
    assert needs_confirmation("resolve_target") is False


def test_risk_table_covers_exactly_the_approved_tools():
    assert TOOL_RISK == {
        "run_full_hr_pipeline": frozenset({"slow"}),
        "run_full_hr_pipeline_from_catalog": frozenset({"slow"}),
        "extract_photometry_from_fits": frozenset({"slow"}),
        "run_photometry_on_target": frozenset({"slow"}),
        "search_ads": frozenset({"keyed"}),
        "get_paper_abstract": frozenset({"keyed"}),
        "get_citing_papers": frozenset({"keyed"}),
        "get_referenced_papers": frozenset({"keyed"}),
        "build_literature_review": frozenset({"keyed"}),
        "sonify_pulsar": frozenset({"writes"}),
        "plot_pulsar": frozenset({"writes"}),
        "plot_field_sed": frozenset({"writes"}),
    }


def test_every_risky_tool_is_registered():
    assert set(TOOL_RISK) <= set(TOOL_FUNCTIONS)


def test_untagged_tools_do_not_ask_for_confirmation():
    asked: list[str] = []
    policy = SessionPolicy(
        ask=lambda proposed: asked.append(proposed.name) or Decision.DENY
    )

    decision = policy_approver(policy)(
        ToolCallProposed(call_id="call-1", name="resolve_target", arguments={})
    )

    assert decision is Decision.ALLOW
    assert asked == []


def test_allow_always_skips_later_calls_to_the_same_tool_only():
    asked: list[str] = []
    policy = SessionPolicy(
        ask=lambda proposed: asked.append(proposed.name) or Decision.ALLOW_ALWAYS
    )
    approver = policy_approver(policy)

    first = approver(
        ToolCallProposed(call_id="call-1", name="search_ads", arguments={})
    )
    repeated = approver(
        ToolCallProposed(call_id="call-2", name="search_ads", arguments={})
    )
    different = approver(
        ToolCallProposed(
            call_id="call-3", name="get_paper_abstract", arguments={}
        )
    )

    assert first is Decision.ALLOW
    assert repeated is Decision.ALLOW
    assert different is Decision.ALLOW
    assert asked == ["search_ads", "get_paper_abstract"]


def test_allow_once_asks_again_for_the_next_risky_call():
    asked: list[str] = []
    policy = SessionPolicy(
        ask=lambda proposed: asked.append(proposed.name) or Decision.ALLOW
    )
    approver = policy_approver(policy)

    approver(ToolCallProposed(call_id="call-1", name="plot_pulsar", arguments={}))
    approver(ToolCallProposed(call_id="call-2", name="plot_pulsar", arguments={}))

    assert asked == ["plot_pulsar", "plot_pulsar"]


def test_an_archive_search_asks_only_when_it_would_actually_download():
    """A plain archive query returns a table; the same call with the flag set
    pulls the matched products into the data tree over the network -- 121,515
    of them for Cassiopeia A, by `search_mast`'s own measured docstring."""

    from tools.agent.policy import DOWNLOAD_FLAGS, needs_confirmation, risk_tags

    assert set(DOWNLOAD_FLAGS) == {"search_mast", "search_casda"}

    assert needs_confirmation("search_mast", {"name": "Cas A"}) is False
    assert needs_confirmation("search_mast", {"name": "Cas A", "download": True}) is True
    assert risk_tags("search_casda", {"download": True}) == frozenset(
        {"writes", "slow"}
    )
    # The table is still readable by name alone.
    assert risk_tags("search_ads") == frozenset({"keyed"})


def test_a_downloading_call_reaches_the_approver():
    from tools.agent.events import ToolCallProposed
    from tools.agent.policy import Decision, SessionPolicy

    asked: list[str] = []

    def ask(proposed):
        asked.append(proposed.name)
        return Decision.DENY

    policy = SessionPolicy(ask)

    assert policy.approve(ToolCallProposed("c0", "search_mast", {})) is Decision.ALLOW
    assert asked == []

    decision = policy.approve(
        ToolCallProposed("c1", "search_mast", {"download": True})
    )

    assert decision is Decision.DENY
    assert asked == ["search_mast"]
