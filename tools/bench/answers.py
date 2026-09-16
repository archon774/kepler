"""``answers`` -- put the question and the model's reply side by side.

``docs/working/benchmark.md`` section 11. Every other verb reduces a session
to a verdict; this one does the opposite, because **a scoreboard cannot be
audited against nothing**. A check that fires is a claim about a piece of
prose, and the only way to tell a real failure from a regex artefact is to
read the prose. That is how the ``must_source_value`` false positive was
found, and reading 144 answers by hand through ``find`` is how it was nearly
missed.

Offline, free, and repeatable: it reads the run directory and the corpus, and
consults no model. There is no automated second reading and deliberately so:
an extra diagnostic layer over a broken check leaves the check broken. Five
checks in this suite were found firing on correct answers by reading the prose,
and each was fixed where it was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

__all__ = ["sessions", "render"]


def sessions(
    run_dirs: Sequence[str | Path],
    *,
    suite_root: str | Path = "benchmarks/suites",
    fixture_root: str | Path = "benchmarks/fixtures",
) -> Iterator[dict[str, Any]]:
    """Yield one record per session: the prompt, the reply, and the verdict.

    The verdict comes from ``grades.json`` when it is beside ``run.json`` and
    is simply absent when it is not. An ungraded run still has answers worth
    reading, and grading here would make a read-only verb write.
    """

    from tools.bench.grade import GRADES_NAME
    from tools.bench.graders import load_evidence
    from tools.bench.harness import RUN_RECORD_NAME
    from tools.bench.tasks import load_suite

    for run_dir in run_dirs:
        run_dir = Path(run_dir)
        record = json.loads((run_dir / RUN_RECORD_NAME).read_text(encoding="utf-8"))
        suite = load_suite(
            Path(suite_root) / record["config"]["suite_id"],
            fixture_root=fixture_root,
        )
        tasks = {task.id: task for task in suite}

        graded: dict[tuple[str, str, int], Mapping[str, Any]] = {}
        grades_path = run_dir / GRADES_NAME
        if grades_path.exists():
            payload = json.loads(grades_path.read_text(encoding="utf-8"))
            for entry in payload.get("grades", ()):
                graded[
                    (entry["backend"], entry["task_id"], entry["repeat"])
                ] = entry

        for entry in record["runs"]:
            task = tasks.get(entry["task_id"])
            if task is None:
                continue
            evidence = load_evidence(entry["directory"])
            grade = graded.get(
                (entry["backend"], entry["task_id"], entry["repeat"])
            )
            yield {
                "backend": entry["backend"],
                "task_id": entry["task_id"],
                "repeat": entry["repeat"],
                "prompt": task.prompt,
                "answer": evidence.answer,
                "outcome": evidence.outcome,
                "correct": None if grade is None else grade["answer"]["passed"],
                "failed_checks": _failed_checks(grade),
                "calls": [
                    call.get("tool_name") for call in evidence.tool_calls()
                ],
            }


def _failed_checks(grade: Mapping[str, Any] | None) -> list[str]:
    if grade is None:
        return []
    return sorted(
        {
            failure["check"]
            for axis in ("answer", "trajectory", "protocol")
            for failure in grade.get(axis, {}).get("failures", ())
        }
    )


def render(
    records: Sequence[Mapping[str, Any]], *, verbose: bool = False
) -> list[str]:
    """Render the records as Markdown, grouped by task then backend."""

    lines: list[str] = []
    by_task: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        by_task.setdefault(record["task_id"], []).append(record)

    for task_id in sorted(by_task):
        group = sorted(by_task[task_id], key=lambda r: (r["backend"], r["repeat"]))
        lines += [f"## `{task_id}`", "", "> " + group[0]["prompt"].strip(), ""]
        for record in group:
            verdict = {True: "correct", False: "wrong", None: "ungraded"}[
                record["correct"]
            ]
            head = (
                f"### `{record['backend'].split('/')[-1]}` r{record['repeat']} "
                f"— {verdict}"
            )
            if record["failed_checks"]:
                head += " (" + ", ".join(record["failed_checks"]) + ")"
            lines += [head, ""]
            if verbose and record["calls"]:
                lines += ["`" + " -> ".join(record["calls"]) + "`", ""]
            body = record["answer"].strip()
            if not body:
                body = f"*(no answer; the session ended `{record['outcome']}`)*"
            lines += [body, ""]
    return lines
