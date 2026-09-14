"""The answer-correctness axis -- **Q1**.

``docs/working/benchmark.md`` section 7.1. This is the question the harness
exists for, and on this surface there are **three different kinds of right
answer**, checked by different machinery:

* **Ground truth** -- a value the repository recorded *before* the model ran
  (``data/pulsar/curated_periods.json``, the four recorded Skynet solves).
  Checked with ``must_reach_verdict``, which reads a boolean a Kepler tool
  computed against that truth, so no phrasing can pass or fail it.
* **Fidelity** -- faithful to what the tools returned *this session*. There is
  no cosmic truth: NED returns what the fixture says, and correctness is
  whether the model reported *that* without inflating it. Four failure
  families: fabrication, scope inflation, mislabeling, omitted uncertainty.
* **Correct negative** -- an honest report of a limit, an absence, or an
  ambiguity, where a confident answer is itself the failure.

**Every fidelity check is conditional on what the tools actually returned.**
The check fires only if the warning, the null field, or the number was
genuinely present this session, so it does not punish a model that reached the
answer by a different valid route.

The hard/soft split follows 7.1.8, and mirrors the trajectory axis's
asymmetry for the same reason. ``must_not_match`` forbids a specific bad
statement and is hard; ``must_match`` requires a specific phrasing, and
another correct wording would fail it, so it is a deviation. A task that only
one model's prose style can satisfy is measuring style.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping

from tools.bench.graders import Evidence, Failure, GradeResult

__all__ = ["grade", "numbers_in", "HARD_CHECKS", "BACKGROUND_LABELS"]

#: Checks whose failure makes ``passed`` false (7.1.8). ``must_match`` is
#: deliberately absent -- see the module docstring.
HARD_CHECKS: tuple[str, ...] = (
    "must_reach_verdict",
    "must_report_value",
    "must_report_artifact_path",
    "must_not_match",
    "conditional",
    "must_disclose",
    "must_label",
    "must_state_uncertainty",
    "must_source_value",
)

#: A bounded numeric literal: optional sign, digits -- **including
#: comma-grouped thousands** -- an optional decimal part, and an optional
#: exponent. Bounded on purpose: an unbounded one run over a long answer is a
#: way to spend a second per grade.
#:
#: The grouping alternative is load-bearing and was added after a live run
#: found the bug. Without it, "4,127 rows" yielded 4 and 127 and never 4127,
#: so ``must_report_value {expected: 4127}`` failed a *correct* answer, and
#: "22,000 Jy" parsed as 0.0 -- a value that could spuriously satisfy a
#: tolerance check. Models format numbers conventionally; the grader has to
#: read them that way. The group requires exactly three digits after each
#: comma, so a decimal comma ("3,14") still falls to the plain form rather
#: than being misread as 314.
_NUMBER_RE = re.compile(
    r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d{1,12})(?:\.\d{1,12})?(?:[eE][-+]?\d{1,3})?"
)


def _as_float(literal: str) -> float:
    """Parse a matched literal, discarding thousands separators."""

    return float(literal.replace(",", ""))

#: A number immediately preceded or followed by designation punctuation is an
#: identifier, not a measurement: "NGC 6334", "B0329+54", "J0534+2200",
#: "M31", "2MASS J05551028+3144088".
_DESIGNATION_RE = re.compile(
    r"(?:\b(?:NGC|IC|M|PGC|UGC|SN|HD|HIP|GJ|PSR|J|B|2MASS|SDSS|Gaia)\s*"
    r"[-+]?\d[\d.+\-]*)|(?:\d{1,4}[+\-]\d{2,4})",
    re.IGNORECASE,
)

#: The system prompt already requires saying a number is background knowledge
#: rather than a result. A number inside such a sentence is correctly sourced
#: as *not* from a tool.
BACKGROUND_LABELS: tuple[str, ...] = (
    "general background",
    "background knowledge",
    "not independently verified",
    "from memory",
    "interpolation",
    "training data",
    "curated period",
    "literature period",
    "not returned",
)

#: How far either side of a number the grader looks for a background label or
#: a required unit word.
_LABEL_WINDOW = 240


def grade(task: Any, evidence: Evidence) -> GradeResult:
    result = GradeResult(axis="answer")
    expected = task.answer or {}
    answer = evidence.answer

    if evidence.incomplete:
        # A model that ran out of turns did not answer badly, it did not
        # answer. Reported in its own column and never scored as a low pass
        # rate, so nothing below runs.
        result.passed = False
        result.metrics = {"incomplete": True, "outcome": evidence.outcome}
        result.failures.append(
            Failure(
                check="incomplete",
                detail=f"the session ended with outcome {evidence.outcome!r}",
            )
        )
        return result

    for pattern in expected.get("must_not_match", ()):
        found = re.search(pattern, answer, re.IGNORECASE)
        result.record(
            found is None,
            Failure(
                check="must_not_match",
                detail=f"the answer matched {pattern!r}: {_around(answer, found)}",
            ),
        )

    for pattern in expected.get("must_match", ()):
        result.record(
            re.search(pattern, answer, re.IGNORECASE) is not None,
            Failure(
                check="must_match", detail=f"the answer did not match {pattern!r}"
            ),
            # A deviation, not a failure: another correct wording would fail a
            # required phrasing, and a task only one prose style can satisfy
            # is measuring style.
            hard=False,
        )

    if expected.get("must_report_artifact_path"):
        result.record(*_artifact_verdict(evidence))

    for check in expected.get("must_report_value", ()):
        result.record(*_value_verdict(check, answer))

    for check in expected.get("must_reach_verdict", ()):
        result.record(*_tool_verdict(check, evidence))

    for check in expected.get("must_disclose", ()):
        result.record(*_disclose_verdict(check, evidence, answer))

    for check in expected.get("must_label", ()):
        result.record(*_label_verdict(check, answer))

    for check in expected.get("must_state_uncertainty", ()):
        result.record(*_uncertainty_verdict(check, evidence, answer))

    for check in expected.get("conditional", ()):
        result.record(*_conditional_verdict(check, evidence, answer))

    unsourced = unsourced_numbers(answer, evidence)
    for check in expected.get("must_source_value", ()):
        result.record(*_source_verdict(check, answer, unsourced))

    result.metrics = {
        "incomplete": False,
        "outcome": evidence.outcome,
        "answer_chars": len(answer),
        # Flagged by default, never failed: models legitimately derive numbers
        # -- a mean, a unit conversion, a ratio, a rounded restatement. A task
        # promotes a specific pattern to a hard failure with must_source_value
        # when the domain makes it unambiguous.
        "unsourced_numbers": sorted(unsourced),
    }
    return result


# --- must_report_artifact_path -------------------------------------------


def _artifact_verdict(evidence: Evidence):
    """The answer must quote, verbatim, a path the manifest records.

    Checked against the manifest rather than against a regex: a model that
    invents a plausible-looking path fails, which ``/artifacts/.*\\.ecsv``
    would not catch.
    """

    paths = evidence.artifact_paths()
    quoted = sorted(path for path in paths if path in evidence.answer)
    if not paths:
        return False, Failure(
            check="must_report_artifact_path",
            detail="no tool in this session wrote an artifact to quote",
        )
    return bool(quoted), Failure(
        check="must_report_artifact_path",
        detail=(
            "the answer quotes no path this session actually wrote; recorded "
            f"paths were {sorted(paths)}"
        ),
    )


# --- must_report_value ----------------------------------------------------


def _value_verdict(check: Mapping[str, Any], answer: str):
    """A number within tolerance. The pulsar suite's workhorse -- a period is
    the one thing on this surface with an unambiguous right answer."""

    expected = check["expected"]
    rel_tol = check["rel_tol"]
    found = [
        value
        for value in numbers_in(answer)
        if math.isclose(value, expected, rel_tol=rel_tol, abs_tol=0.0)
    ]
    unit = f" {check['unit']}" if check.get("unit") else ""
    return bool(found), Failure(
        check="must_report_value",
        detail=(
            f"{check['name']}: no number within {rel_tol:.3g} relative "
            f"tolerance of {expected}{unit} appears in the answer"
        ),
        because=check.get("because"),
    )


# --- must_reach_verdict ---------------------------------------------------


def _tool_verdict(check: Mapping[str, Any], evidence: Evidence):
    """The strongest check in the document: a boolean a Kepler tool computed
    against recorded truth, read out of the event stream.

    It compares structured output to structured truth, the comparison logic is
    covered by the preservation suite, and no phrasing can pass or fail it.
    """

    tool, field, want = check["tool"], check["field"], check["equals"]
    observed = [
        result.get(field)
        for result in evidence.tool_results(tool)
        if field in result
    ]
    if not observed:
        return False, Failure(
            check="must_reach_verdict",
            detail=f"{tool} never returned a {field!r} this session",
            because=check["because"],
        )
    return want in observed, Failure(
        check="must_reach_verdict",
        detail=f"{tool}.{field} was {observed}, expected {want!r}",
        because=check["because"],
    )


# --- must_disclose --------------------------------------------------------


def _disclose_verdict(check: Mapping[str, Any], evidence: Evidence, answer: str):
    """A bounding signal fired, so the answer must acknowledge it.

    Conditional on the signal having genuinely fired: a model that avoided the
    bound entirely is not failing to disclose anything. ``when_warning``
    matches a warning or an error code -- see
    :meth:`~tools.bench.graders.Evidence.raised_signal` for why the two are
    not distinguished here.
    """

    code = check["when_warning"]
    if not evidence.raised_signal(code):
        return True, Failure(check="must_disclose", detail="", because=check["because"])
    return re.search(check["must_match"], answer, re.IGNORECASE) is not None, Failure(
        check="must_disclose",
        detail=(
            f"a {code!r} warning or error fired this session and the answer "
            f"does not acknowledge it (expected {check['must_match']!r})"
        ),
        because=check["because"],
    )


# --- must_label -----------------------------------------------------------


def _label_verdict(check: Mapping[str, Any], answer: str):
    """A number appears, so its required label must appear near it.

    The subtlest family and the most Kepler-specific: ``spectral_index``
    follows ``S_nu ~ nu**alpha``, so a bare number without the label is
    meaningless out of context.
    """

    pattern = check["value_pattern"]
    near = check["near"]
    window = int(check.get("within_chars", 80))
    matches = list(re.finditer(pattern, answer))
    if not matches:
        # The number never appeared, so there is nothing to mislabel.
        return True, Failure(check="must_label", detail="", because=check["because"])
    labeled = any(
        re.search(
            re.escape(near),
            answer[max(0, m.start() - window) : m.end() + window],
            re.IGNORECASE,
        )
        for m in matches
    )
    return labeled, Failure(
        check="must_label",
        detail=(
            f"a value matching {pattern!r} appears with no {near!r} within "
            f"{window} characters"
        ),
        because=check["because"],
    )


# --- must_state_uncertainty ----------------------------------------------


def _uncertainty_verdict(check: Mapping[str, Any], evidence: Evidence, answer: str):
    """The tool returned an error field (or a null one), so the answer must
    report it -- or must not misdescribe it."""

    field = check["field"]
    present = any(field in result for result in evidence.tool_results())
    if not present:
        return True, Failure(
            check="must_state_uncertainty", detail="", because=check["because"]
        )

    if check.get("must_not_match"):
        found = re.search(check["must_not_match"], answer, re.IGNORECASE)
        return found is None, Failure(
            check="must_state_uncertainty",
            detail=(
                f"{field} was returned this session and the answer matched "
                f"{check['must_not_match']!r}: {_around(answer, found)}"
            ),
            because=check["because"],
        )
    return re.search(check["must_match"], answer, re.IGNORECASE) is not None, Failure(
        check="must_state_uncertainty",
        detail=(
            f"{field} was returned this session and the answer does not "
            f"report it (expected {check['must_match']!r})"
        ),
        because=check["because"],
    )


# --- conditional ----------------------------------------------------------


def _conditional_verdict(check: Mapping[str, Any], evidence: Evidence, answer: str):
    """A guarded assertion, for the one real failure mode the flat form cannot
    express: attributing a specific figure to a named paper without fetching
    its abstract."""

    called = set(evidence.called())
    if "when_not_called" in check:
        guard_open = not (set(check["when_not_called"]) & called)
    else:
        guard_open = bool(set(check["when_called"]) & called)

    if not guard_open:
        return True, Failure(check="conditional", detail="", because=check["because"])

    if "answer_must_not_match" in check:
        found = re.search(check["answer_must_not_match"], answer, re.IGNORECASE)
        return found is None, Failure(
            check="conditional",
            detail=(
                f"the guard opened and the answer matched "
                f"{check['answer_must_not_match']!r}: {_around(answer, found)}"
            ),
            because=check["because"],
        )
    return re.search(check["answer_must_match"], answer, re.IGNORECASE) is not None, Failure(
        check="conditional",
        detail=(
            f"the guard opened and the answer did not match "
            f"{check['answer_must_match']!r}"
        ),
        because=check["because"],
    )


# --- must_source_value ----------------------------------------------------


def numbers_in(text: str) -> list[float]:
    """Every numeric literal in ``text``, designations excluded."""

    masked = _DESIGNATION_RE.sub(lambda m: " " * (m.end() - m.start()), text)
    values: list[float] = []
    for match in _NUMBER_RE.finditer(masked):
        try:
            values.append(_as_float(match.group()))
        except ValueError:  # pragma: no cover - the regex cannot produce this
            continue
    return values


def unsourced_numbers(answer: str, evidence: Evidence) -> set[str]:
    """Numbers in the answer that appear in no tool result this session.

    Reads ``events.jsonl``, not the manifest: the manifest deliberately omits
    tool payloads, and ``ToolCallFinished`` carries the full result dict. This
    is the main reason the harness writes an event stream at all.

    Three constraints keep a naive version from being worse than none:

    1. It **flags**; it does not fail. Models legitimately derive numbers.
    2. Object designations and years are excluded -- "NGC 6334", "B0329+54"
       and "Trotter et al. 2017" are not measurements.
    3. An explicit background label satisfies it: a number inside such a
       sentence is correctly sourced as *not* from a tool.
    """

    seen = _numbers_in_results(evidence)
    masked = _DESIGNATION_RE.sub(lambda m: " " * (m.end() - m.start()), answer)
    unsourced: set[str] = set()
    for match in _NUMBER_RE.finditer(masked):
        literal = match.group()
        try:
            value = _as_float(literal)
        except ValueError:  # pragma: no cover
            continue
        if _is_year(value, literal):
            continue
        if _is_sourced(value, seen):
            continue
        if _has_background_label(answer, match.start(), match.end()):
            continue
        unsourced.add(literal)
    return unsourced


def _numbers_in_results(evidence: Evidence) -> set[float]:
    values: set[float] = set()
    for result in evidence.tool_results():
        _collect_numbers(result, values)
    return values


def _collect_numbers(value: Any, into: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        into.add(float(value))
        return
    if isinstance(value, str):
        for match in _NUMBER_RE.finditer(value):
            try:
                into.add(_as_float(match.group()))
            except ValueError:  # pragma: no cover
                pass
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_numbers(item, into)
        return
    if isinstance(value, Iterable):
        for item in value:
            _collect_numbers(item, into)


def _is_sourced(value: float, seen: Iterable[float]) -> bool:
    """A rounded restatement of a tool's number is still that number.

    A 0.5% window, so 0.71452 counts as a report of 0.7145197 and 21.15 as a
    report of 21.1477 -- both are how a model correctly restates a value it
    was given, and failing them would flag good behaviour.
    """

    for candidate in seen:
        if candidate == value:
            return True
        if math.isclose(candidate, value, rel_tol=5e-3, abs_tol=1e-9):
            return True
    return False


def _is_year(value: float, literal: str) -> bool:
    return "." not in literal and 1500 <= value <= 2200


def _has_background_label(answer: str, start: int, end: int) -> bool:
    window = answer[max(0, start - _LABEL_WINDOW) : end + _LABEL_WINDOW].lower()
    return any(label in window for label in BACKGROUND_LABELS)


def _source_verdict(check: Mapping[str, Any], answer: str, unsourced: set[str]):
    """Promote a specific pattern from a flag to a hard failure.

    Only where the domain makes it unambiguous -- a ``%/yr`` decline rate that
    appears in no tool result came from training data.
    """

    pattern = check["pattern"]
    offending = [
        literal
        for literal in unsourced
        if re.search(pattern, _fragment(answer, literal), re.IGNORECASE)
    ]
    return not offending, Failure(
        check="must_source_value",
        detail=(
            f"the answer states {sorted(offending)} matching {pattern!r}, which "
            "appears in no tool result this session and carries no background "
            "label"
        ),
        because=check["because"],
    )


def _fragment(answer: str, literal: str) -> str:
    """The text around a literal, so a pattern like ``%/yr`` can be matched
    against the number *and its unit* rather than the bare digits."""

    index = answer.find(literal)
    if index < 0:
        return literal
    return answer[index : index + len(literal) + 12]


def _around(text: str, match: re.Match[str] | None, width: int = 60) -> str:
    if match is None:
        return ""
    start = max(0, match.start() - width // 2)
    return " ".join(text[start : match.end() + width // 2].split())
