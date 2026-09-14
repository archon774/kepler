"""``falsify`` -- attack the answer keys with the evidence already recorded.

A benchmark's keys are the part nobody grades. ``run`` measures models against
them and ``grade`` applies them, but nothing asks whether a check that fired
was *right* to fire. Every false positive in a key is a model penalised for
being correct, and it is invisible in a scoreboard: it looks exactly like a
model being wrong.

This is the sanctioned use of an adversary, and the asymmetry is the whole
design. Evidence can demonstrate that a key is **invalid** -- it fired on an
answer that agrees with the archive. Nothing can demonstrate that a key is
valid. So this verb only ever *accuses*, and a human decides.

It consults no model. Each probe compares a recorded failure against the
mechanical source the key itself cites, which is available offline because
``run`` and ``grade`` are separate verbs and the evidence is on disk:

``tolerance``
    A ``must_report_value`` failure whose answer does contain the right number
    at a slightly wider tolerance. The key is tight, not the model wrong.
``off_subject``
    A ``must_not_match`` failure whose matched span never names the task's
    subject. This is the shape that failed a model for writing "NED has no
    band filter of its own" -- a correct statement about a service's
    limitations, matched by a pattern meant to catch "the object is not in
    NED".
``sourced_after_all``
    A ``must_source_value`` failure over a number the event stream does
    contain. That is a grader defect, not a fabrication.
``named_the_artifact``
    A ``must_report_artifact_path`` failure whose answer names the file by
    basename. Found and fixed once; kept because it is the class of defect
    that re-enters whenever the check is touched.

Every probe is a heuristic and says so. The output is a list of things to look
at, ranked by how many backends hit the same one -- a check that fires on
several unrelated backends' answers is far more likely to be a bad check than
four models being wrong the same way.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = ["falsify_run", "PROBES"]

#: How much wider a tolerance has to be before a near miss counts as a
#: candidate. Ten times: a key an order of magnitude tighter than the answer's
#: precision is a key about formatting, not about correctness.
TOLERANCE_SLACK = 10.0

PROBES = ("tolerance", "off_subject", "sourced_after_all", "named_the_artifact")


def falsify_run(
    run_dir: str | Path,
    *,
    suite_root: str | Path = "benchmarks/suites",
    fixture_root: str | Path = "benchmarks/fixtures",
) -> dict[str, Any]:
    """Every candidate false positive in one graded run directory."""

    from tools.bench.grade import GRADES_NAME
    from tools.bench.graders import load_evidence
    from tools.bench.harness import RUN_RECORD_NAME
    from tools.bench.tasks import load_suite

    run_dir = Path(run_dir)
    record = json.loads((run_dir / RUN_RECORD_NAME).read_text(encoding="utf-8"))
    grades = json.loads((run_dir / GRADES_NAME).read_text(encoding="utf-8"))
    suite = load_suite(
        Path(suite_root) / record["config"]["suite_id"], fixture_root=fixture_root
    )
    tasks = {task.id: task for task in suite}

    findings: list[dict[str, Any]] = []
    for entry in grades.get("grades", ()):
        task = tasks.get(entry.get("task_id"))
        if task is None or "answer" not in entry:
            continue
        failures = entry["answer"].get("failures") or []
        if not failures:
            continue
        try:
            evidence = load_evidence(Path(entry["directory"]))
        except (OSError, ValueError):
            continue
        for failure in failures:
            findings.extend(
                _probe(failure, task=task, evidence=evidence, entry=entry)
            )
    return {
        "run_id": record["run_id"],
        "suite_id": record["config"]["suite_id"],
        "findings": findings,
    }


def _probe(
    failure: Mapping[str, Any], *, task: Any, evidence: Any, entry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    check = failure.get("check")
    answer = evidence.answer or ""
    out: list[dict[str, Any]] = []
    context = {
        "backend": entry.get("backend"),
        "task_id": entry.get("task_id"),
        "repeat": entry.get("repeat"),
        "check": check,
        "directory": entry.get("directory"),
    }

    if check == "must_report_value":
        out += _tolerance(task, answer, context)
    elif check == "must_not_match":
        out += _off_subject(task, answer, failure, context)
    elif check == "must_source_value":
        out += _sourced_after_all(answer, evidence, failure, context)
    elif check == "must_report_artifact_path":
        out += _named_the_artifact(answer, evidence, context)
    return out


def _tolerance(task: Any, answer: str, context: Mapping[str, Any]):
    from tools.bench.graders.answer import numbers_in

    for check in task.answer.get("must_report_value", ()):
        expected = check.get("expected")
        if expected is None:
            continue
        tol = check["rel_tol"] or 0.0
        wide = max(tol * TOLERANCE_SLACK, 1e-6)
        near = [
            value
            for value in numbers_in(answer)
            if math.isclose(value, expected, rel_tol=wide, abs_tol=0.0)
            and not math.isclose(value, expected, rel_tol=tol, abs_tol=0.0)
        ]
        if near:
            yield {
                **context,
                "probe": "tolerance",
                "detail": (
                    f"the answer carries {near[0]!r} against an expected "
                    f"{expected!r} at rel_tol {tol:g}. Within {wide:g} it "
                    "passes -- the key may be graded on precision the task "
                    "never asked for."
                ),
            }


def _off_subject(task: Any, answer: str, failure: Mapping[str, Any], context):
    """A forbidden pattern that matched without naming what the task is about.

    The subject is taken from the task's own prompt -- its capitalised and
    designation-shaped tokens -- so nothing here is tuned to a model's phrasing.
    """

    detail = failure.get("detail") or ""
    span = _quoted_span(detail)
    if span is None:
        return
    # A token the forbidden pattern already names is no evidence the span is
    # on subject. The pattern that failed a model for "NED has no band filter
    # of its own" named NED itself; what it never named was the object.
    pattern = _pattern_of(detail)
    subjects = {
        word
        for word in _subjects(task.prompt)
        if not re.search(re.escape(word), pattern, re.IGNORECASE)
    }
    if not subjects:
        return
    if not any(re.search(re.escape(word), span, re.IGNORECASE) for word in subjects):
        yield {
            **context,
            "probe": "off_subject",
            "detail": (
                f"the forbidden pattern matched {span!r}, which names none of "
                f"the task's subjects {sorted(subjects)}. A negation check has "
                "to name what is being denied or it fires on any sentence "
                "about what a service cannot do."
            ),
        }


def _sourced_after_all(answer: str, evidence: Any, failure: Mapping[str, Any], context):
    from tools.bench.graders.answer import unsourced_numbers

    unsourced = unsourced_numbers(answer, evidence)
    flagged = {
        token
        for token in re.findall(r"'([^']*)'", failure.get("detail") or "")
        if _NUMERIC_TOKEN.fullmatch(token)
    }
    recovered = sorted(flagged - set(unsourced))
    if flagged and recovered:
        yield {
            **context,
            "probe": "sourced_after_all",
            "detail": (
                f"the check failed over {recovered}, which the event stream "
                "does contain. That is a grader defect, not a fabrication."
            ),
        }


def _named_the_artifact(answer: str, evidence: Any, context):
    paths = list(evidence.artifact_paths())
    named = [path for path in paths if Path(path).name and Path(path).name in answer]
    if named:
        yield {
            **context,
            "probe": "named_the_artifact",
            "detail": (
                f"the answer names {Path(named[0]).name!r}, the real file, "
                "without quoting the full path. Citing a file by name is a "
                "citation."
            ),
        }


_SUBJECT_RE = re.compile(r"\b(?:[A-Z][A-Za-z]{2,}|[A-Z]?\d{2,}[+\-]?\d*)\b")
_STOPWORDS = frozenset(
    {
        "The", "This", "That", "What", "Which", "How", "Give", "Get", "Pull",
        "Find", "Report", "Use", "For", "And", "All", "Every", "None", "JSON",
        "Kepler", "NASA",
    }
)


def _subjects(prompt: str) -> set[str]:
    """The task's own subject words, read off its prompt."""

    return {
        token
        for token in _SUBJECT_RE.findall(prompt)
        if token not in _STOPWORDS and len(token) > 2
    }


#: A grader's detail reads ``the answer matched '<pattern>': <excerpt>``. The
#: pattern may itself contain ``": "``, so the split is on the closing quote.
_DETAIL_SPLIT = re.compile(r"': ")

_NUMERIC_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _pattern_of(detail: str) -> str:
    """The forbidden pattern a grader quoted in its failure detail."""

    match = re.search(r"'(.*)': ", detail)
    return match.group(1) if match else ""


def _quoted_span(detail: str) -> str | None:
    """The excerpt a grader put after the pattern in its failure detail."""

    parts = _DETAIL_SPLIT.split(detail, maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None
