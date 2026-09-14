"""Approval policy for the headless agent loop.

The engine receives an approver callable and has no UI dependency. This module
classifies the relatively costly, keyed, and artifact-writing tools so a caller
can decide which calls need an explicit confirmation. ``SessionPolicy`` keeps
an ``ALLOW_ALWAYS`` decision for the chosen tool only, and only for the current
session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

from tools.agent.approval import Approver, Decision, auto_approve

if TYPE_CHECKING:
    from tools.agent.events import ToolCallProposed

__all__ = [
    "Decision",
    "RiskTag",
    "TOOL_RISK",
    "Approver",
    "auto_approve",
    "risk_tags",
    "needs_confirmation",
    "SessionPolicy",
    "policy_approver",
]

RiskTag = Literal["slow", "keyed", "writes"]

TOOL_RISK: dict[str, frozenset[RiskTag]] = {
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


def risk_tags(name: str) -> frozenset[RiskTag]:
    """Return the declared risk tags for one registered tool name."""

    return TOOL_RISK.get(name, frozenset())


def needs_confirmation(name: str) -> bool:
    """Whether a tool's declared risk requires a caller to ask."""

    return bool(risk_tags(name))


@dataclass
class SessionPolicy:
    """Apply risk defaults and remember per-tool allow-always decisions."""

    ask: Approver
    _always_allowed: set[str] = field(default_factory=set, init=False)

    def approve(self, proposed: "ToolCallProposed") -> Decision:
        """Return the decision for one proposed tool call."""

        if not needs_confirmation(proposed.name):
            return Decision.ALLOW
        if proposed.name in self._always_allowed:
            return Decision.ALLOW

        decision = self.ask(proposed)
        if decision is Decision.ALLOW_ALWAYS:
            self._always_allowed.add(proposed.name)
            return Decision.ALLOW
        return decision


def policy_approver(policy: SessionPolicy) -> Approver:
    """Adapt a session policy to the engine's approver callable contract."""

    return policy.approve
