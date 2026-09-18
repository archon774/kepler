"""Approval vocabulary for the agent loop.

The engine calls an ``Approver`` before dispatching each tool call. Phase 0c
ships only the allow-everything default; ``docs/tool-architecture.md`` 10.2
builds ``tools/agent/policy.py`` -- the risk table, ``SessionPolicy``, and
``policy_approver`` -- on top of the names defined here, so that phase supplies
a policy rather than changing the engine's contract.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tools.agent.events import ToolCallProposed

__all__ = ["Decision", "Approver", "auto_approve"]


class Decision(str, Enum):
    """A string enum: an approver returns one of these for each proposed call.

    ``ALLOW_ALWAYS`` persists for the session -- the *approver* remembers it
    (see ``SessionPolicy``), so the engine treats it exactly like ``ALLOW``.
    """

    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"


#: Any callable taking a proposed call and returning a :class:`Decision`.
Approver = Callable[["ToolCallProposed"], Decision]


def auto_approve(proposed: "ToolCallProposed") -> Decision:
    """The default approver: never blocks. The shim and any plain-Python caller
    behave exactly as they did before the engine existed."""

    return Decision.ALLOW
