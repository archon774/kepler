"""``grade`` -- turn a run directory into verdicts.

``docs/working/benchmark.md`` section 5.1. A separate verb from ``run``,
because the first version of any grader is wrong and re-grading four paid
backends must not cost a re-spend. ``run`` produces evidence; ``grade``
produces verdicts; ``compare`` produces the matrix.

It reads only the run directory and the corpus, so it is offline, free, and
repeatable -- including against a run recorded before the grader was fixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.bench.graders import grade_run_directory

__all__ = ["grade_run", "GRADES_NAME"]

GRADES_NAME = "grades.json"


def grade_run(
    run_dir: str | Path,
    *,
    suite_root: str | Path = "benchmarks/suites",
    fixture_root: str | Path = "benchmarks/fixtures",
    judge: Any = None,
) -> dict[str, Any]:
    """Grade every ``(backend, task, repeat)`` in ``run_dir`` and write
    ``grades.json`` beside ``run.json``."""

    from tools.bench.harness import RUN_RECORD_NAME
    from tools.bench.tasks import load_suite

    run_dir = Path(run_dir)
    record = json.loads((run_dir / RUN_RECORD_NAME).read_text(encoding="utf-8"))
    suite = load_suite(
        Path(suite_root) / record["config"]["suite_id"], fixture_root=fixture_root
    )
    tasks = {task.id: task for task in suite}

    graded: list[dict[str, Any]] = []
    for entry in record["runs"]:
        task = tasks.get(entry["task_id"])
        if task is None:
            # The corpus moved under a recorded run. Reported rather than
            # raised: the other tasks still grade, and a run.json that no
            # longer matches its suite is itself a finding.
            graded.append(
                {
                    "backend": entry["backend"],
                    "task_id": entry["task_id"],
                    "repeat": entry["repeat"],
                    "error": "this task is no longer a member of the suite",
                }
            )
            continue
        result = grade_run_directory(entry["directory"], task, judge=judge)
        result["backend"] = entry["backend"]
        result["repeat"] = entry["repeat"]
        result["directory"] = entry["directory"]
        result["tags"] = list(task.tags)
        # Wall clock belongs to the run, not the session: it is what a user
        # waits for, and it is the one clock the manifest cannot know.
        result["efficiency"]["metrics"]["wall_ms"] = entry.get("wall_ms")
        graded.append(result)

    grades = {
        "run_id": record["run_id"],
        "suite_id": record["config"]["suite_id"],
        "graded_at_corpus": record["corpus"],
        "corpus_dirty": record.get("corpus_dirty"),
        "judge": getattr(judge, "spec", None),
        "grades": graded,
    }
    (run_dir / GRADES_NAME).write_text(
        json.dumps(grades, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return grades


def _is_flaky(results: Sequence[bool | None]) -> bool:
    """A task that did not give the same verdict every repeat.

    ``None`` (incomplete) counts as its own outcome: a task that answered twice
    and ran out of turns once is not stable, and averaging it into a pass rate
    would hide that.
    """

    return len(set(results)) > 1


def _stability(outcomes: Mapping[str, Sequence[bool | None]]) -> float | None:
    """The share of tasks that gave the same verdict on every repeat.

    Section 17 question 2, answered: variance gets its own column rather than
    being folded into the axes. A model that passes a check two runs in three
    is a different finding from one that passes it always, and a matrix showing
    both as "2/3" loses exactly the distinction a ranking needs -- especially
    for a backend whose provider refuses `temperature`, where nothing else
    bounds run-to-run drift.

    ``None`` when there is only one repeat: with n=1 nothing about stability
    has been measured, and reporting 100% would be a lie of omission.
    """

    repeated = [r for r in outcomes.values() if len(r) > 1]
    if not repeated:
        return None
    return sum(1 for r in repeated if not _is_flaky(r)) / len(repeated)


def summarize(grades: Mapping[str, Any]) -> dict[str, Any]:
    """Per-backend roll-up: the two headline axes first, then the diagnostics.

    ``tokens_to_an_answer`` is the one cross-axis figure reported by default,
    because it *is* the question rather than a summary of it: total tokens
    spent on runs that passed 7.1. Runs that failed the answer axis are
    reported separately as tokens spent without result, never averaged in.
    """

    rows: dict[str, dict[str, Any]] = {}
    # (backend, task) -> the pass/fail of each repeat, for the stability column.
    per_task: dict[tuple[str, str], list[bool | None]] = {}
    for entry in grades.get("grades", ()):
        if "answer" not in entry:
            continue
        # Stability needs a task identity to group repeats by. An entry
        # without one contributes nothing rather than collapsing every task
        # into a single bucket and inventing a spread.
        task_id = entry.get("task_id")
        if task_id is not None:
            per_task.setdefault((entry["backend"], task_id), []).append(
                None if entry["incomplete"] else bool(entry["answer"]["passed"])
            )
        row = rows.setdefault(
            entry["backend"],
            {
                "runs": 0,
                "passed": 0,
                "incomplete": 0,
                "tokens_to_an_answer": 0,
                "tokens_without_result": 0,
                "turns": 0,
                "tool_calls": 0,
                "duplicate_calls": 0,
                "fault_total": 0,
                "trajectory_failures": 0,
                "model_time_ms": 0.0,
                "output_tokens": 0,
            },
        )
        row["runs"] += 1
        metrics = entry["efficiency"]["metrics"]
        tokens = metrics.get("tokens") or {}
        spent = (tokens.get("input_tokens") or 0) + (tokens.get("output_tokens") or 0)

        if entry["incomplete"]:
            row["incomplete"] += 1
            row["tokens_without_result"] += spent
            continue
        if entry["answer"]["passed"]:
            row["passed"] += 1
            row["tokens_to_an_answer"] += spent
        else:
            row["tokens_without_result"] += spent

        row["turns"] += metrics.get("turns") or 0
        row["tool_calls"] += metrics.get("tool_calls") or 0
        row["duplicate_calls"] += metrics.get("duplicate_calls") or 0
        row["model_time_ms"] += metrics.get("model_time_ms") or 0.0
        row["output_tokens"] += tokens.get("output_tokens") or 0
        row["fault_total"] += entry["protocol"]["metrics"].get("fault_total") or 0
        row["trajectory_failures"] += len(entry["trajectory"]["failures"])

    for backend, row in rows.items():
        outcomes = {
            task: results
            for (b, task), results in per_task.items()
            if b == backend
        }
        row["stability"] = _stability(outcomes)
        row["flaky_tasks"] = sorted(
            task for task, results in outcomes.items() if _is_flaky(results)
        )
        scored = row["runs"] - row["incomplete"]
        row["pass_rate"] = row["passed"] / scored if scored else None
        row["tokens_per_answer"] = (
            row["tokens_to_an_answer"] / row["passed"] if row["passed"] else None
        )
        row["tokens_per_second"] = (
            row["output_tokens"] / (row["model_time_ms"] / 1000.0)
            if row["model_time_ms"]
            else None
        )
    return rows
