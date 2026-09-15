"""The trajectory axis -- *diagnostic*.

``docs/working/benchmark.md`` section 7.3. Reads the manifest's ordered
``tool_calls``.

The asymmetry here is the point, and it is deliberate:

* **``must_not_call``** and **``arguments``** encode documented failure modes
  -- things a model should *not* do -- and are **hard failures**.
* **``must_call``** and **``order``** encode one good route among several, and
  punishing an alternative correct route would make the suite age badly as
  model strategies change. They are **deviations**.

It is diagnostic because a trajectory is only interesting through its effect
on an answer. A model that took an odd route to a correct, honestly-reported
result has not done anything wrong; what this axis buys is the explanation.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from tools.bench.graders import Evidence, Failure, GradeResult

__all__ = ["grade", "matches_predicates"]


def matches_predicates(
    arguments: Mapping[str, Any], predicates: Mapping[str, Mapping[str, Any]]
) -> bool:
    """Apply the shared fixture predicate vocabulary to a call's arguments."""

    from tools.bench.fixtures import _match_one

    return all(
        _match_one(rule, key in arguments, arguments.get(key), f"argument {key!r}")
        for key, rule in predicates.items()
    )


def grade(task: Any, evidence: Evidence) -> GradeResult:
    result = GradeResult(axis="trajectory")
    expected = task.trajectory or {}
    called = evidence.called()

    sequences = {
        index: call.get("sequence", index + 1)
        for index, call in enumerate(evidence.tool_calls())
    }
    for rule in expected.get("must_not_call", ()):
        name, because = rule["tool"], rule.get("because")
        offending = [
            sequences[index] for index, tool in enumerate(called) if tool == name
        ]
        result.record(
            not offending,
            Failure(
                check="must_not_call",
                detail=(
                    f"{name} was called at sequence "
                    f"{', '.join(str(i) for i in offending)}"
                ),
                because=because,
            ),
        )

    for rule in expected.get("arguments", ()):
        result.record(*_argument_verdict(rule, evidence))

    for name in expected.get("must_call", ()):
        result.record(
            name in called,
            Failure(check="must_call", detail=f"{name} was never called"),
            hard=False,
        )

    order = list(expected.get("order", ()))
    if order:
        result.record(
            _is_subsequence(order, called),
            Failure(
                check="order",
                detail=(
                    f"expected {' -> '.join(order)} as an ordered subsequence of "
                    f"{' -> '.join(called) or '(no calls)'}"
                ),
            ),
            hard=False,
        )

    result.metrics = {
        "tool_calls": len(called),
        "distinct_tools": len(set(called)),
        "sequence": called,
    }
    return result


def _argument_verdict(rule: Mapping[str, Any], evidence: Evidence):
    """Select the calls to the rule's tool, apply its predicates under its
    quantifier, and report the offending argument value if it fails."""

    tool = rule["tool"]
    predicates = rule["where"]
    quantifier = rule.get("quantifier", "all")
    calls = [
        call for call in evidence.tool_calls() if call.get("tool_name") == tool
    ]

    if not calls:
        # A rule about how a tool must be *called* says nothing when it was
        # never called. must_not_call is the check for "do not call it"; this
        # one passing vacuously keeps the two from being confused.
        return True, Failure(check="arguments", detail="", because=rule["because"])

    verdicts = [
        matches_predicates(call.get("arguments") or {}, predicates) for call in calls
    ]
    ok = all(verdicts) if quantifier == "all" else any(verdicts)
    offending = [
        call.get("arguments")
        for call, verdict in zip(calls, verdicts)
        if not verdict
    ]
    return ok, Failure(
        check="arguments",
        detail=(
            f"{tool} ({quantifier}) violated {dict(predicates)}; offending "
            f"call(s): {offending if quantifier == 'all' else [c.get('arguments') for c in calls]}"
        ),
        because=rule["because"],
    )


def _is_subsequence(needle: Sequence[str], haystack: Sequence[str]) -> bool:
    iterator = iter(haystack)
    return all(item in iterator for item in needle)
