"""The four grading axes, and the run-directory reader they share.

``docs/working/benchmark.md`` section 7. Each grader is a pure function from
``(task, manifest, answer_text, events)`` to a result record: no I/O beyond
reading the run directory, and no model calls at all. **Nothing in this
package asks a model whether an answer is correct**; every verdict is a
deterministic assertion against recorded evidence, and the one component that
did ask a model was removed rather than kept as a second opinion over checks
that could be fixed instead.

Two of the four answer a question and two explain one:

* **answer** (7.1) -- Q1, is it right? Headline.
* **efficiency** (7.2) -- Q2, at what cost in work? Headline.
* **trajectory** (7.3) -- *diagnostic*. A trajectory is only interesting
  through its effect on an answer; a model that took an odd route to a
  correct, honestly-reported result has not done anything wrong. What this
  buys is the explanation: when the answer axis fails, the trajectory usually
  says why.
* **protocol** (7.4) -- *diagnostic*, and it feeds Q1 directly. A
  ``max_catalogs`` sent as the string ``"None"`` produces a capped result, and
  a capped result reported as exhaustive is a scope-inflation failure on 7.1.
  The protocol axis is where that failure's cause is legible.

Grading is a separate verb from running because the first version of any
grader is wrong, and re-grading must not cost a re-spend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

__all__ = [
    "Evidence",
    "GradeResult",
    "Failure",
    "load_evidence",
    "grade_run_directory",
]


@dataclass(frozen=True)
class Failure:
    """One failed check, carrying the task's own explanation.

    ``because`` is printed verbatim in the report, so a reader who has never
    opened the suite file can tell what went wrong and why it counts.
    """

    check: str
    detail: str
    because: str | None = None


@dataclass
class GradeResult:
    """One axis's verdict for one ``(backend, task, repeat)``."""

    axis: str
    passed: bool = True
    checks_total: int = 0
    checks_passed: int = 0
    failures: list[Failure] = field(default_factory=list)
    deviations: list[Failure] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def record(self, ok: bool, failure: Failure, *, hard: bool = True) -> None:
        """Count one check and file its failure as hard or as a deviation."""

        self.checks_total += 1
        if ok:
            self.checks_passed += 1
            return
        if hard:
            self.passed = False
            self.failures.append(failure)
        else:
            self.deviations.append(failure)

    def to_json(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "passed": self.passed,
            "checks_total": self.checks_total,
            "checks_passed": self.checks_passed,
            "failures": [
                {"check": f.check, "detail": f.detail, "because": f.because}
                for f in self.failures
            ],
            "deviations": [
                {"check": f.check, "detail": f.detail, "because": f.because}
                for f in self.deviations
            ],
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class Evidence:
    """Everything one graded run left on disk.

    The event stream is loaded alongside the manifest because the manifest
    deliberately omits tool payloads -- its own ``notes`` key says so -- and
    ``ToolCallFinished`` carries the full result dict. That is the only place
    the numbers a model actually saw are recoverable, which is the main reason
    ``events.jsonl`` is written at all.
    """

    directory: Path
    manifest: Mapping[str, Any]
    answer: str
    events: tuple[Mapping[str, Any], ...]
    outcome: str
    error: str | None = None

    @property
    def incomplete(self) -> bool:
        """A session that ran out of turns or budget did not answer badly --
        it did not answer. Reported in its own column, never as a low score."""

        from tools.bench.harness import INCOMPLETE_OUTCOMES

        return self.outcome in INCOMPLETE_OUTCOMES

    def tool_results(self, name: str | None = None) -> Iterator[Mapping[str, Any]]:
        """Every ``ToolCallFinished`` result, in order, optionally one tool's."""

        for event in self.events:
            if event.get("event") != "ToolCallFinished":
                continue
            if name is not None and event.get("name") != name:
                continue
            result = event.get("result")
            if isinstance(result, Mapping):
                yield result

    def tool_calls(self) -> Sequence[Mapping[str, Any]]:
        """The manifest's ordered call records: name, arguments, status,
        cache_hit, artifacts, warnings, errors."""

        calls = self.manifest.get("tool_calls")
        return calls if isinstance(calls, Sequence) else ()

    def called(self) -> list[str]:
        return [str(call.get("tool_name")) for call in self.tool_calls()]

    def artifact_paths(self) -> set[str]:
        paths: set[str] = set()
        for call in self.tool_calls():
            for artifact in call.get("artifacts") or ():
                if isinstance(artifact, Mapping) and artifact.get("path"):
                    paths.add(str(artifact["path"]))
        return paths

    def warnings(self) -> list[Mapping[str, Any]]:
        """Every warning any tool raised this session, as the manifest wrote it.

        The manifest normalizes to ``{code, message}``, but only the half of
        the surface that raises a coded warning gets a ``code``: ``ToolResult``
        -- what every class-R tool returns -- declares ``warnings: list[str]``
        upstream, while ``OpticalFrameList``, ``PulsarScanList`` and the other
        local models declare ``list[ToolWarning]``. That asymmetry is
        extraction-preserved and not ours to fix here, so
        :meth:`raised_warning` matches on either.
        """

        raised: list[Mapping[str, Any]] = []
        for call in self.tool_calls():
            for warning in call.get("warnings") or ():
                if isinstance(warning, Mapping):
                    raised.append(warning)
        return raised

    def warning_codes(self) -> set[str]:
        """The coded warnings only. See :meth:`warnings` for why that is not
        all of them."""

        return {
            str(warning["code"])
            for warning in self.warnings()
            if warning.get("code")
        }

    def errors(self) -> list[Mapping[str, Any]]:
        """Every error any tool returned this session, as the manifest wrote
        it. Always coded: the manifest normalizes ``{code, message}``."""

        raised: list[Mapping[str, Any]] = []
        for call in self.tool_calls():
            for error in call.get("errors") or ():
                if isinstance(error, Mapping):
                    raised.append(error)
        return raised

    def raised_signal(self, name: str) -> bool:
        """Whether a bounding signal identified by ``name`` fired this session.

        Warnings *and* errors, because which of the two a tool uses for the
        same situation is not consistent across this surface and is not the
        model's concern: ``list_optical_frames`` reports a truncated listing as
        a ``listing_truncated`` warning, while ``resolve_optical_frame``
        reports an ambiguous name as an ``ambiguous`` *error*. Both are a
        bound the answer has to acknowledge, and a check that fired for one and
        silently never for the other would grade the tool's choice rather than
        the model's.

        Matched against the ``code`` where there is one, and otherwise
        case-folded against the message -- ``ToolResult``, what every class-R
        tool returns, declares ``warnings: list[str]`` upstream and has nowhere
        to put a code.
        """

        folded = name.casefold()
        for signal in self.warnings() + self.errors():
            if signal.get("code") and str(signal["code"]).casefold() == folded:
                return True
            if folded in str(signal.get("message", "")).casefold():
                return True
        return False


def load_evidence(directory: str | Path) -> Evidence:
    """Read one ``(backend, task, repeat)`` directory.

    Tolerant of a v1 manifest and of a run that crashed before writing one:
    grading a failed run must report the failure, not raise on it.
    """

    from tools.bench.harness import ANSWER_NAME, ERROR_NAME, EVENTS_NAME

    directory = Path(directory)
    manifest_path = directory / "session_manifest.json"
    manifest: Mapping[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    answer_path = directory / ANSWER_NAME
    answer = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""

    events: list[Mapping[str, Any]] = []
    events_path = directory / EVENTS_NAME
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    error_path = directory / ERROR_NAME
    error = error_path.read_text(encoding="utf-8") if error_path.exists() else None

    outcome = str(manifest.get("outcome") or ("error" if error else "unknown"))
    for event in reversed(events):
        if event.get("event") == "SessionFinished":
            outcome = str(event.get("outcome") or outcome)
            break
    if error and "budget" in error.lower():
        outcome = "budget_exceeded"

    return Evidence(
        directory=directory,
        manifest=manifest,
        answer=answer,
        events=tuple(events),
        outcome=outcome,
        error=error,
    )


def grade_run_directory(directory: str | Path, task: Any) -> dict[str, Any]:
    """Grade one run directory on all four axes."""

    from tools.bench.graders import answer as answer_grader
    from tools.bench.graders import efficiency as efficiency_grader
    from tools.bench.graders import protocol as protocol_grader
    from tools.bench.graders import trajectory as trajectory_grader

    evidence = load_evidence(directory)
    graded = {
        "task_id": task.id,
        "outcome": evidence.outcome,
        "incomplete": evidence.incomplete,
        "error": evidence.error,
        "answer": answer_grader.grade(task, evidence).to_json(),
        "efficiency": efficiency_grader.grade(task, evidence).to_json(),
        "trajectory": trajectory_grader.grade(task, evidence).to_json(),
        "protocol": protocol_grader.grade(task, evidence).to_json(),
    }
    return graded
