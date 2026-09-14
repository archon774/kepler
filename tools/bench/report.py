"""The matrix: ``report.md`` and ``report.json``, same content.

``docs/working/benchmark.md`` sections 7.6 and 12.

**Column order is load-bearing.** The two questions this harness exists to
answer are read left to right -- correctness, then efficiency -- and the two
diagnostic axes sit beside them to explain a number rather than competing with
it for attention.

**The score is three measurements and nothing else.** A model is asked a
question about Kepler's tool surface, and only three things about its reply are
scored: **is it correct**, **how long did it take**, and **how many tokens did
it cost**. Everything else the harness records -- trajectory, protocol, fixture
misses, duplicate calls -- is diagnosis for reading *why* a score came out as it
did, and never enters the score.

Correctness is a rate and already lives in [0, 1]. Time and tokens have no
natural ceiling, so each is scored as a ratio against the best row: the fastest
backend scores 1.0 on time, one taking twice as long scores 0.5. Both are
measured over runs that reached a passing answer, because a fast wrong answer is
not a fast answer.

The older text below is kept because its warning still holds --
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

import math
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "render_markdown",
    "build_report",
    "write_report",
    "SCORE_WEIGHTS",
    "COMPOSITE_WEIGHTS",
    "REPORT_MD_NAME",
    "REPORT_JSON_NAME",
]

REPORT_MD_NAME = "report.md"
REPORT_JSON_NAME = "report.json"

#: The three measurements, and what each is worth. Printed above every ranking
#: so a reader can disagree with the weights rather than guess at them.
#:
#: Correctness dominates on purpose: an answer delivered instantly and cheaply
#: is worth nothing if it is wrong, so no amount of speed or thrift lifts a
#: model past one that is right by a wide margin. Time and tokens are weighted
#: equally -- they are two prices for the same answer, one paid in waiting and
#: one in spend, and nothing here knows which a given caller minds more.
SCORE_WEIGHTS: Mapping[str, float] = {
    "correctness": 0.6,
    "time": 0.2,
    "tokens": 0.2,
}

#: Superseded name, kept so an older report payload still reads.
COMPOSITE_WEIGHTS = SCORE_WEIGHTS

#: A fixture miss rate above this is called out in the header in the
#: document's own words rather than left for a reader to notice in a column.
_MISS_RATE_NOTICE = 0.05

#: Past this, a recorded fixture is grading a model against an archive that
#: may no longer exist (section 17 question 3).
_FIXTURE_AGE_WARNING_DAYS = 180


def build_report(
    runs: Sequence[Mapping[str, Any]],
    *,
    composite: bool = True,
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
        best_tokens = _best(matrix, "tokens_per_answer")
        best_seconds = _best(matrix, "seconds_per_answer")
        for row in matrix.values():
            row["score"] = _score(row, best_seconds, best_tokens)
            row["composite"] = row["score"]

    return {
        "header": header,
        "weights": dict(SCORE_WEIGHTS) if composite else None,
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
        "wall_ms_to_answer": 0.0,
        "wall_ms_without_result": 0.0,
        "task_outcomes": {},
    }


def _merge(into: dict[str, Any], row: Mapping[str, Any]) -> None:
    for key, value in row.items():
        if isinstance(value, (int, float)) and key in into:
            into[key] += value
    # Stability is not summable and not overwritable either. A report merging
    # five suites has to recompute it over every task in all of them; taking
    # the last suite's figure -- which is what an overwrite did -- reported one
    # suite's variance as the backend's.
    for task, results in (row.get("task_outcomes") or {}).items():
        into["task_outcomes"].setdefault(task, []).extend(results)


def _finalize(row: dict[str, Any]) -> None:
    from tools.bench.grade import _is_flaky, _stability

    outcomes = row.get("task_outcomes") or {}
    row["stability"] = _stability(outcomes)
    row["flaky_tasks"] = sorted(
        task for task, results in outcomes.items() if _is_flaky(results)
    )
    row["tasks"] = len(outcomes)

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
    row["scored"] = scored
    interval = wilson_interval(row["passed"], scored)
    # A list, not a tuple: the JSON and Markdown reports are written from the
    # same object and a test holds them to the same content.
    row["pass_interval"] = list(interval) if interval else None
    # Time to an answer, on the runs that reached one. The question a user
    # actually asks of a model is how long they wait for a usable answer, and
    # that is comparable across every backend however it is served.
    row["seconds_per_answer"] = (
        row["wall_ms_to_answer"] / 1000.0 / row["passed"] if row["passed"] else None
    )
    row["turns_per_run"] = row["turns"] / row["runs"] if row["runs"] else None
    row["duplicate_rate"] = (
        row["duplicate_calls"] / row["tool_calls"] if row["tool_calls"] else None
    )


#: 95%, the conventional two-sided normal quantile.
WILSON_Z = 1.959963984540054


def wilson_interval(passed: int, trials: int, *, z: float = WILSON_Z):
    """A Wilson score interval on a pass rate.

    The suite reports rates like 23/24 and 21/24 side by side, and a reader
    will subtract them. This is the mechanical answer to whether that
    subtraction means anything: at these trial counts a two-item gap has a
    confidence interval several times its own width, so two backends whose
    intervals overlap have not been separated *by this suite* however
    confidently the table is read.

    Wilson rather than the textbook normal interval because it stays inside
    [0, 1] and does not collapse to zero width at 24/24 -- both of which
    matter at exactly the counts a benchmark of this size produces.
    """

    if trials <= 0:
        return None
    p = passed / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = (
        z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
    ) / denominator
    return (max(0.0, center - half), min(1.0, center + half))


def separated(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether two backends' correctness intervals fail to overlap.

    Reported rather than enforced: a suite that cannot separate two models is
    making a statement about the suite, and hiding it behind an ordered table
    would be the whole failure this benchmark is meant to avoid.
    """

    first, second = a.get("pass_interval"), b.get("pass_interval")
    if not first or not second:
        return False
    return first[1] < second[0] or second[1] < first[0]


def _best(matrix: Mapping[str, Mapping[str, Any]], key: str) -> float | None:
    """The best (lowest) value of a cost column across the compared backends."""

    values = [row[key] for row in matrix.values() if row.get(key)]
    return min(values) if values else None


def _score(
    row: Mapping[str, Any],
    best_seconds: float | None,
    best_tokens: float | None,
) -> float | None:
    """The benchmark score: correctness, time and tokens, and nothing else.

    Correctness is already a rate in [0, 1]. Time and tokens are normalised
    against the best row, because neither has a natural ceiling to divide by:
    the fastest backend scores 1.0 on time and one taking twice as long scores
    0.5. Both costs count only the runs that reached a passing answer.

    ``None`` when a backend answered nothing, rather than substituting a zero:
    a model with no passing run has no time or token cost per answer, and
    scoring it as infinitely slow would invent a measurement it never made.
    """

    correctness = row.get("pass_rate")
    seconds = row.get("seconds_per_answer")
    tokens = row.get("tokens_per_answer")
    if correctness is None or not seconds or not tokens:
        return None
    if not best_seconds or not best_tokens:
        return None
    return round(
        correctness * SCORE_WEIGHTS["correctness"]
        + (best_seconds / seconds) * SCORE_WEIGHTS["time"]
        + (best_tokens / tokens) * SCORE_WEIGHTS["tokens"],
        4,
    )


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
        "corpus_conflicts": _corpus_conflicts(runs),
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


def _corpus_conflicts(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Where merged runs were measured with different instruments.

    Two runs of the same task are only poolable if the task file, the fixtures
    behind it and the system prompt were byte-identical. Merging runs that
    differ produces one confident-looking rate over two different experiments,
    and nothing in the output would have said so.

    Reported per artefact rather than as a single flag, because *what* differs
    decides whether a reader can salvage anything: a changed fixture invalidates
    the tasks that read it, a changed prompt invalidates everything.
    """

    tasks: dict[str, set[str]] = {}
    fixtures: dict[str, set[str]] = {}
    prompts: set[str] = set()
    suites: set[str] = set()
    for pair in runs:
        record = pair["record"]
        corpus = record.get("corpus") or {}
        for task_id, digest in (corpus.get("tasks") or {}).items():
            tasks.setdefault(task_id, set()).add(digest)
        for name, digest in (corpus.get("fixtures") or {}).items():
            fixtures.setdefault(name, set()).add(digest)
        prompt = (record.get("config") or {}).get("system_prompt_sha256")
        if prompt:
            prompts.add(prompt)
        if corpus.get("suite"):
            suites.add(corpus["suite"])
    return {
        "tasks": sorted(t for t, digests in tasks.items() if len(digests) > 1),
        "fixtures": sorted(f for f, digests in fixtures.items() if len(digests) > 1),
        "system_prompts": sorted(prompts) if len(prompts) > 1 else [],
    }


def has_corpus_conflict(report: Mapping[str, Any]) -> bool:
    conflicts = report["header"].get("corpus_conflicts") or {}
    return any(conflicts.get(key) for key in ("tasks", "fixtures", "system_prompts"))


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

    conflicts = header.get("corpus_conflicts") or {}
    if any(conflicts.get(key) for key in ("tasks", "fixtures", "system_prompts")):
        lines.append("> **These runs were not measured with the same instrument.**")
        lines.append(">")
        lines.append(
            "> Pooling them produces one confident-looking rate over two "
            "different experiments. Re-run the older backends against the "
            "current corpus instead of merging."
        )
        if conflicts.get("system_prompts"):
            lines.append("> - **system prompt differs** — nothing here is poolable.")
        if conflicts.get("tasks"):
            lines.append(
                "> - task files differ: "
                + ", ".join(f"`{t}`" for t in conflicts["tasks"])
            )
        if conflicts.get("fixtures"):
            lines.append(
                "> - fixtures differ: "
                + ", ".join(f"`{f}`" for f in conflicts["fixtures"])
            )
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

    lines.extend(_ranking_table(report))
    lines.extend(_matrix_table(report))
    lines.extend(_grid_table(report))
    lines.extend(_failure_list(report))
    return "\n".join(lines) + "\n"


def _ranking_table(report: Mapping[str, Any]) -> list[str]:
    """The scoreboard: three measurements, one score, one order.

    Ranked because that is what a scoreboard is for. The 95% interval stays in
    the row so the precision of the correctness term is visible beside it --
    a reader ordering two backends whose intervals overlap should be able to
    see that from the same table.
    """

    weights = report.get("weights")
    if not weights:
        return []
    rows = [
        (backend, row)
        for backend, row in report["matrix"].items()
        if row.get("score") is not None
    ]
    unscored = sorted(set(report["matrix"]) - {backend for backend, _ in rows})
    rows.sort(key=lambda item: item[1]["score"], reverse=True)

    lines = [
        "## Ranking",
        "",
        "Three measurements and nothing else: **is the answer correct**, **how "
        "long did it take**, **how many tokens did it cost**. Time and tokens "
        "are scored against the best row and counted only over runs that "
        "reached a passing answer.",
        "",
        "Weights: " + ", ".join(f"**{k}** {v}" for k, v in weights.items()) + ".",
        "",
        "| # | backend | score | correct | 95% interval | seconds/answer | "
        "tokens/answer |",
        "| --: | --- | --: | --- | --- | --: | --: |",
    ]
    for rank, (backend, row) in enumerate(rows, start=1):
        lines.append(
            "| {rank} | `{backend}` | **{score:.3f}** | {passed}/{scored} "
            "({rate}) | {interval} | {spa} | {tpa} |".format(
                rank=rank,
                backend=backend,
                score=row["score"],
                passed=row["passed"],
                scored=row["runs"] - row["incomplete"],
                rate=_pct(row["pass_rate"]),
                interval=_interval(row.get("pass_interval")),
                spa=_num(row.get("seconds_per_answer"), "{:,.0f}"),
                tpa=_num(row.get("tokens_per_answer"), "{:,.0f}"),
            )
        )
    lines.append("")
    if unscored:
        lines.append(
            "Unscored (no passing run, so no cost per answer to measure): "
            + ", ".join(f"`{backend}`" for backend in unscored)
            + "."
        )
        lines.append("")
    return lines


def _matrix_table(report: Mapping[str, Any]) -> list[str]:
    lines = [
        "## Diagnostics",
        "",
        "Not scored. These explain *why* a score came out as it did.",
        "",
        "| backend | correctness | 95% interval | stability | seconds to an "
        "answer | tokens to an answer | turns/run | tok/s | duplicate rate | "
        "trajectory failures | protocol faults |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for backend, row in sorted(report["matrix"].items()):
        lines.append(
            "| `{backend}` | {passed}/{scored} ({rate}) | {interval} | "
            "{stability} | {spa} | {tpa} | "
            "{tpr} | {tps} | {dup} | {traj} | {faults} |".format(
                backend=backend,
                passed=row["passed"],
                scored=row["runs"] - row["incomplete"],
                rate=_pct(row["pass_rate"]),
                interval=_interval(row.get("pass_interval")),
                stability=_pct(row.get("stability")),
                spa=_num(row.get("seconds_per_answer"), "{:,.0f}"),
                tpa=_num(row["tokens_per_answer"], "{:,.0f}"),
                tpr=_num(row["turns_per_run"], "{:.1f}"),
                tps=_num(row["tokens_per_second"], "{:.1f}"),
                dup=_pct(row["duplicate_rate"]),
                traj=row["trajectory_failures"],
                faults=row["fault_total"],
            )
        )
    lines.extend(_separation_note(report))
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
    return lines


def _interval(interval: Any) -> str:
    if not interval:
        return "--"
    return f"{interval[0]:.0%}-{interval[1]:.0%}"


def _separation_note(report: Mapping[str, Any]) -> list[str]:
    """Say which pairs this suite actually separated, and which it did not.

    A table of rates invites subtraction. At 24 trials a two-item gap carries
    an interval several times its own width, so the honest report names the
    pairs whose intervals overlap rather than leaving an ordered column to
    imply a ranking the evidence does not carry.
    """

    rows = sorted(report["matrix"].items())
    if len(rows) < 2:
        return [""]
    overlapping = [
        f"`{a}` vs `{b}`"
        for index, (a, row_a) in enumerate(rows)
        for b, row_b in rows[index + 1 :]
        if not separated(row_a, row_b)
    ]
    lines = [""]
    if overlapping:
        lines.append(
            "**Not separated by this suite** (95% correctness intervals "
            "overlap): " + ", ".join(overlapping) + ". Ordering these pairs on "
            "correctness reads a difference the trial count does not support."
        )
    else:
        lines.append(
            "Every pair of backends is separated at 95% on correctness."
        )
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
