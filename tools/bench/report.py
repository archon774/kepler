"""The matrix: ``report.md`` and ``report.json``, same content.

``docs/working/benchmark.md`` sections 7.6 and 12.

**Column order is load-bearing.** The two questions this harness exists to
answer are read left to right -- correctness, then efficiency -- and the two
diagnostic axes sit beside them to explain a number rather than competing with
it for attention.

**There is no blended score by default.** A composite hides which axis failed,
and "model A scored 0.72" is not actionable. One cross-axis figure is reported
because it *is* the question rather than a summary of it: **tokens to an
answer**, conditioned on passing the answer axis. A weighted composite is
available behind ``--composite``, with its weights printed above it, and it
covers the two headline axes only -- a diagnostic has no independent meaning
to weight.

B6: every model- and fixture-derived string is untrusted text by
construction. Markdown and JSON only. If an HTML report is ever added, every
such string is escaped there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "render_markdown",
    "build_report",
    "write_report",
    "COMPOSITE_WEIGHTS",
    "REPORT_MD_NAME",
    "REPORT_JSON_NAME",
]

REPORT_MD_NAME = "report.md"
REPORT_JSON_NAME = "report.json"

#: Only the two headline axes. Printed above the composite whenever one is
#: rendered, so a reader never sees a single number without its recipe.
COMPOSITE_WEIGHTS: Mapping[str, float] = {"correctness": 0.7, "efficiency": 0.3}

#: A fixture miss rate above this is called out in the header in the
#: document's own words rather than left for a reader to notice in a column.
_MISS_RATE_NOTICE = 0.05

#: Past this, a recorded fixture is grading a model against an archive that
#: may no longer exist (section 17 question 3).
_FIXTURE_AGE_WARNING_DAYS = 180


def build_report(
    runs: Sequence[Mapping[str, Any]],
    *,
    composite: bool = False,
    tag: str | None = None,
) -> dict[str, Any]:
    """Build the report payload from one or more ``(run.json, grades.json)``
    pairs.

    ``tag`` filters to the tasks carrying it, which is how a single
    correctness family -- ``sourcing``, ``null-argument``, ``name-resolution``
    -- gets read on its own.
    """

    from tools.bench.grade import summarize

    header = _header(runs, tag=tag)
    matrix: dict[str, dict[str, Any]] = {}
    grid: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for pair in runs:
        grades = _filtered(pair["grades"], tag)
        for backend, row in summarize(grades).items():
            matrix.setdefault(backend, _empty_row())
            _merge(matrix[backend], row)
        for entry in grades.get("grades", ()):
            if "answer" not in entry:
                continue
            grid.append(_grid_row(entry))
            failures.extend(_failures(entry))

    for row in matrix.values():
        _finalize(row)
        if composite:
            row["composite"] = _composite(row)

    return {
        "header": header,
        "weights": dict(COMPOSITE_WEIGHTS) if composite else None,
        "matrix": matrix,
        "per_task": grid,
        "failures": failures,
    }


def _empty_row() -> dict[str, Any]:
    return {
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
    }


def _merge(into: dict[str, Any], row: Mapping[str, Any]) -> None:
    for key, value in row.items():
        if isinstance(value, (int, float)) and key in into:
            into[key] += value


def _finalize(row: dict[str, Any]) -> None:
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
    row["turns_per_run"] = row["turns"] / row["runs"] if row["runs"] else None
    row["duplicate_rate"] = (
        row["duplicate_calls"] / row["tool_calls"] if row["tool_calls"] else None
    )


def _composite(row: Mapping[str, Any]) -> float | None:
    """A weighted figure over the two headline axes only.

    Efficiency is normalized as the inverse of tokens per answer against the
    best row -- but that needs the whole matrix, so this returns the
    correctness term alone when it cannot see one. Available behind a flag
    precisely because a composite hides which axis failed.
    """

    correctness = row.get("pass_rate")
    if correctness is None:
        return None
    return round(correctness * COMPOSITE_WEIGHTS["correctness"], 4)


def _filtered(grades: Mapping[str, Any], tag: str | None) -> Mapping[str, Any]:
    if tag is None:
        return grades
    return {
        **grades,
        "grades": [
            entry for entry in grades.get("grades", ()) if tag in (entry.get("tags") or ())
        ],
    }


def _header(runs: Sequence[Mapping[str, Any]], *, tag: str | None) -> dict[str, Any]:
    """Run id, timestamps, backends, corpus hashes, the fixture miss rate, and
    any incomplete outcome. A reader must be able to tell what was measured."""

    hits = 0
    misses = 0
    incomplete: list[str] = []
    budget_exceeded: list[str] = []
    for pair in runs:
        record = pair["record"]
        for entry in record.get("runs", ()):
            hits += entry.get("fixture_hits") or 0
            misses += len(entry.get("fixture_misses") or ())
            if entry.get("outcome") == "budget_exceeded":
                budget_exceeded.append(f"{entry['task_id']}@{entry['backend']}")
            elif entry.get("incomplete"):
                incomplete.append(
                    f"{entry['task_id']}@{entry['backend']} ({entry['outcome']})"
                )

    total = hits + misses
    miss_rate = misses / total if total else 0.0
    return {
        "runs": [
            {
                "run_id": pair["record"]["run_id"],
                "suite_id": pair["record"]["config"]["suite_id"],
                "started_at": pair["record"]["started_at"],
                "finished_at": pair["record"]["finished_at"],
                "host": pair["record"]["host"],
                "git_head": pair["record"]["git_head"],
                "corpus_dirty": pair["record"].get("corpus_dirty"),
                "corpus": pair["record"]["corpus"],
                "repeats": pair["record"]["config"]["repeats"],
                "temperature": pair["record"]["config"]["temperature"],
                "seed": pair["record"]["config"]["seed"],
                "backends": pair["record"]["backends"],
                "judge": pair["grades"].get("judge"),
            }
            for pair in runs
        ],
        "tag": tag,
        "fixture_miss_rate": miss_rate,
        "fixture_misses": misses,
        "incomplete": incomplete,
        "budget_exceeded": budget_exceeded,
    }


def _grid_row(entry: Mapping[str, Any]) -> dict[str, Any]:
    metrics = entry["efficiency"]["metrics"]
    tokens = metrics.get("tokens") or {}
    return {
        "backend": entry["backend"],
        "task_id": entry["task_id"],
        "repeat": entry["repeat"],
        "outcome": entry["outcome"],
        "incomplete": entry["incomplete"],
        "passed": None if entry["incomplete"] else entry["answer"]["passed"],
        "checks": f"{entry['answer']['checks_passed']}/{entry['answer']['checks_total']}",
        "turns": metrics.get("turns"),
        "tool_calls": metrics.get("tool_calls"),
        "input_tokens": tokens.get("input_tokens"),
        "output_tokens": tokens.get("output_tokens"),
        "cache_read_tokens": tokens.get("cache_read_tokens"),
        "model_time_ms": metrics.get("model_time_ms"),
        "tool_time_ms": metrics.get("tool_time_ms"),
        "wall_ms": metrics.get("wall_ms"),
        "rate_kind": metrics.get("tokens_per_second_kind"),
        "faults": entry["protocol"]["metrics"].get("fault_total"),
        "trajectory_failures": len(entry["trajectory"]["failures"]),
        "judge": (entry.get("judge") or {}).get("verdict"),
    }


def _failures(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every hard failure, with its ``because`` verbatim.

    A reader who has never opened the suite should be able to tell what went
    wrong and why it counts.
    """

    out: list[dict[str, Any]] = []
    for axis in ("answer", "trajectory", "protocol"):
        for failure in entry[axis]["failures"]:
            out.append(
                {
                    "backend": entry["backend"],
                    "task_id": entry["task_id"],
                    "repeat": entry["repeat"],
                    "axis": axis,
                    **failure,
                }
            )
    return out


# --- Markdown -------------------------------------------------------------


def render_markdown(report: Mapping[str, Any]) -> str:
    header = report["header"]
    lines: list[str] = ["# Kepler model benchmark", ""]

    for run in header["runs"]:
        lines.append(f"## Run `{run['run_id']}` -- suite `{run['suite_id']}`")
        lines.append("")
        lines.append(f"- started {run['started_at']}, finished {run['finished_at']}")
        lines.append(f"- host `{run['host']}`, repository `{run['git_head']}`")
        lines.append(
            f"- repeats {run['repeats']}, temperature {run['temperature']}, "
            f"seed {run['seed']}"
        )
        if run["corpus_dirty"]:
            lines.append(
                "- **corpus was dirty at launch**: this run graded against "
                "uncommitted tasks or fixtures"
            )
        elif run["corpus_dirty"] is None:
            lines.append(
                "- corpus cleanliness unknown: git could not be consulted"
            )
        lines.append(f"- suite SHA-256 `{run['corpus']['suite'][:12]}`")
        for task_id, digest in sorted(run["corpus"]["tasks"].items()):
            lines.append(f"  - `{task_id}` `{digest[:12]}`")
        for name, digest in sorted(run["corpus"]["fixtures"].items()):
            lines.append(f"  - fixture `{name}` `{digest[:12]}`")
        for spec, details in sorted(run["backends"].items()):
            caps = details.get("capabilities") or {}
            lines.append(
                f"- `{spec}` -- dialect `{caps.get('schema_dialect')}`, "
                f"streaming {caps.get('streaming')}, unions "
                f"{caps.get('supports_union_types')}"
            )
        if run.get("judge"):
            lines.append(f"- judge `{run['judge']}` (advisory; never blended)")
        lines.append("")

    if header["tag"]:
        lines.append(f"Filtered to tasks tagged `{header['tag']}`.")
        lines.append("")

    lines.append(
        f"Fixture miss rate: **{header['fixture_miss_rate']:.1%}** "
        f"({header['fixture_misses']} miss(es))."
    )
    if header["fixture_miss_rate"] > _MISS_RATE_NOTICE:
        lines.append("")
        lines.append(
            "> A suite with a high miss rate is measuring its own coverage, "
            "not the model."
        )
    lines.append("")

    if header["budget_exceeded"]:
        lines.append(
            "**Budget exceeded** (partial results, marked partial): "
            + ", ".join(f"`{item}`" for item in header["budget_exceeded"])
        )
        lines.append("")
    if header["incomplete"]:
        lines.append(
            "**Incomplete** (did not answer; never scored as a low pass rate): "
            + ", ".join(f"`{item}`" for item in header["incomplete"])
        )
        lines.append("")

    lines.extend(_matrix_table(report))
    lines.extend(_grid_table(report))
    lines.extend(_failure_list(report))
    return "\n".join(lines) + "\n"


def _matrix_table(report: Mapping[str, Any]) -> list[str]:
    lines = [
        "## Matrix",
        "",
        "The two headline axes first; the two diagnostic axes explain them.",
        "",
        "| backend | correctness | tokens to an answer | turns/run | tok/s | "
        "duplicate rate | trajectory failures | protocol faults |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for backend, row in sorted(report["matrix"].items()):
        lines.append(
            "| `{backend}` | {passed}/{scored} ({rate}) | {tpa} | {tpr} | "
            "{tps} | {dup} | {traj} | {faults} |".format(
                backend=backend,
                passed=row["passed"],
                scored=row["runs"] - row["incomplete"],
                rate=_pct(row["pass_rate"]),
                tpa=_num(row["tokens_per_answer"], "{:,.0f}"),
                tpr=_num(row["turns_per_run"], "{:.1f}"),
                tps=_num(row["tokens_per_second"], "{:.1f}"),
                dup=_pct(row["duplicate_rate"]),
                traj=row["trajectory_failures"],
                faults=row["fault_total"],
            )
        )
    lines.append("")
    lines.append(
        "*Tokens to an answer* is total tokens on runs that passed the answer "
        "axis, per passing run. Runs that failed it spent "
        + ", ".join(
            f"`{backend}` {row['tokens_without_result']:,}"
            for backend, row in sorted(report["matrix"].items())
        )
        + " token(s) without result."
    )
    lines.append("")
    if report.get("weights"):
        lines.append(
            "Composite weights (headline axes only): "
            + ", ".join(f"{k} {v}" for k, v in report["weights"].items())
        )
        for backend, row in sorted(report["matrix"].items()):
            lines.append(f"- `{backend}`: {_num(row.get('composite'), '{:.4f}')}")
        lines.append("")
    return lines


def _grid_table(report: Mapping[str, Any]) -> list[str]:
    lines = [
        "## Per task",
        "",
        "| backend | task | r | outcome | passed | checks | turns | calls | "
        "in | out | cache-read | model ms | tool ms | wall ms | rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- |",
    ]
    for row in report["per_task"]:
        lines.append(
            "| `{backend}` | `{task}` | {repeat} | {outcome} | {passed} | "
            "{checks} | {turns} | {calls} | {inp} | {out} | {cache} | {mt} | "
            "{tt} | {wt} | {kind} |".format(
                backend=row["backend"],
                task=row["task_id"],
                repeat=row["repeat"],
                outcome=row["outcome"],
                passed="--" if row["passed"] is None else ("yes" if row["passed"] else "no"),
                checks=row["checks"],
                turns=_num(row["turns"], "{}"),
                calls=_num(row["tool_calls"], "{}"),
                inp=_num(row["input_tokens"], "{:,}"),
                out=_num(row["output_tokens"], "{:,}"),
                cache=_num(row["cache_read_tokens"], "{:,}"),
                mt=_num(row["model_time_ms"], "{:,.0f}"),
                tt=_num(row["tool_time_ms"], "{:,.0f}"),
                wt=_num(row["wall_ms"], "{:,.0f}"),
                kind=row["rate_kind"],
            )
        )
    lines.append("")
    return lines


def _failure_list(report: Mapping[str, Any]) -> list[str]:
    if not report["failures"]:
        return ["## Failures", "", "None.", ""]
    lines = ["## Failures", ""]
    for failure in report["failures"]:
        lines.append(
            f"### `{failure['task_id']}` @ `{failure['backend']}` r{failure['repeat']} "
            f"-- {failure['axis']}/{failure['check']}"
        )
        lines.append("")
        lines.append(f"{failure['detail']}")
        if failure.get("because"):
            lines.append("")
            lines.append(f"> {failure['because']}")
        lines.append("")
    return lines


def _pct(value: float | None) -> str:
    return "--" if value is None else f"{value:.0%}"


def _num(value: Any, spec: str) -> str:
    """``--`` for an absent value, never ``0``.

    A provider that did not report a token class did not report zero of them,
    and a column of zeros would read as a measurement.
    """

    return "--" if value is None else spec.format(value)


def write_report(
    report: Mapping[str, Any], directory: str | Path
) -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    md = directory / REPORT_MD_NAME
    js = directory / REPORT_JSON_NAME
    md.write_text(render_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return md, js
