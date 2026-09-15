"""The protocol axis -- *diagnostic*.

``docs/working/benchmark.md`` section 7.4. Counts each of the seven
``FAULT_TYPES`` from the manifest's ``protocol_faults``, and evaluates
``null_argument_fidelity`` for each declared ``(tool, property)``:

======================  ==========  ===================================
Observed                Verdict     Why
======================  ==========  ===================================
JSON ``null``           **pass**    the only way to request uncapped results
property absent         **partial** a *different* semantic -- capped at the
                                    default, not uncapped
a string (``"None"``)   **fail**    also raises ``stringified_null``
a plain integer         **fail**    capped at the model's number
======================  ==========  ===================================

This is the single most discriminating check in the suite for small local
models. It exists because of eight union-typed registry properties that
Gemini's OpenAPI subset cannot express natively and that ``schema.py``
rewrites to a nullable scalar rather than downgrade. **The schema stays
faithful; a model's failure to use it is a result.**
"""

from __future__ import annotations

from typing import Any

from tools.bench.graders import Evidence, Failure, GradeResult
from tools.llm.types import FAULT_TYPES

__all__ = ["grade", "NULL_FIDELITY_VERDICTS"]

#: Ordered worst-to-best, so a report can sort by it.
NULL_FIDELITY_VERDICTS: tuple[str, ...] = ("fail", "partial", "pass", "not_called")


def grade(task: Any, evidence: Evidence) -> GradeResult:
    result = GradeResult(axis="protocol")

    faults = evidence.manifest.get("protocol_faults") or []
    counts = {kind: 0 for kind in FAULT_TYPES}
    for fault in faults:
        kind = str(fault.get("type"))
        counts[kind] = counts.get(kind, 0) + 1

    fidelity: dict[str, dict[str, Any]] = {}
    for rule in (task.protocol or {}).get("null_argument_fidelity", ()):
        key = f"{rule['tool']}.{rule['property']}"
        verdict, observed = _fidelity(evidence, rule["tool"], rule["property"])
        fidelity[key] = {"verdict": verdict, "observed": observed}
        result.record(
            verdict in ("pass", "not_called"),
            Failure(
                check="null_argument_fidelity",
                detail=(
                    f"{key} was {observed}; JSON null is the only way to "
                    "request an uncapped result"
                ),
                because=rule.get("because"),
            ),
            # Diagnostic, like the whole axis: it feeds Q1 rather than
            # competing with it. A capped result reported as exhaustive fails
            # the answer axis, and this is where that failure's cause is
            # legible.
            hard=False,
        )

    result.metrics = {
        "fault_counts": counts,
        "fault_total": sum(counts.values()),
        "null_argument_fidelity": fidelity,
    }
    return result


def _fidelity(evidence: Evidence, tool: str, prop: str) -> tuple[str, str]:
    """The worst verdict across every call this session made to ``tool``.

    Worst rather than best: a model that got it right once and wrong twice has
    not demonstrated it understands the union.
    """

    calls = [c for c in evidence.tool_calls() if c.get("tool_name") == tool]
    if not calls:
        return "not_called", "the tool was never called"

    worst = "pass"
    observed = "JSON null"
    for call in calls:
        arguments = call.get("arguments") or {}
        if prop not in arguments:
            verdict, seen = "partial", "the property was omitted (capped at the default)"
        else:
            value = arguments[prop]
            if value is None:
                verdict, seen = "pass", "JSON null"
            elif isinstance(value, str):
                verdict, seen = "fail", f"the string {value!r}"
            else:
                verdict, seen = "fail", f"the literal {value!r} (capped at that number)"
        if NULL_FIDELITY_VERDICTS.index(verdict) < NULL_FIDELITY_VERDICTS.index(worst):
            worst, observed = verdict, seen
    return worst, observed
