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
    "SCORE_BOARDS",
    "boards",
    "REPORT_MD_NAME",
    "REPORT_JSON_NAME",
]

REPORT_MD_NAME = "report.md"
REPORT_JSON_NAME = "report.json"

#: The three measurements, each scored on its own board. **Never blended.**
#:
#: They are not the same kind of quantity, and a weighted sum of them would
#: hide that. Correctness is *absolute*: it is a rate in [0, 1], 1.0 means the
#: model answered every question correctly, and the figure means the same thing
#: whether it was measured against one other backend or ten.
#:
#: Speed and cost have no such baseline. Seconds and tokens are unbounded below
#: by anything this harness knows -- there is no "perfectly fast" -- so the only
#: honest comparison is against the other backends on the board. That makes them
#: *relative*: add a slower model and every other model's speed standing moves,
#: while nobody's correctness does. Folding a floating quantity into a fixed one
#: produces a number that changes when the field changes and looks like it
#: measured the model.
#:
#: So three boards, three orders, and a summary that shows where they disagree.
#: A model that is right most often and slowest is a real result, not a tie to
#: be broken by a weight nobody can justify.
SCORE_BOARDS: tuple[str, ...] = ("correctness", "speed", "cost")

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
        _rank_boards(matrix)

    return {
        "by_task": _by_task(grid),
        "header": header,
        "boards": boards(matrix) if composite else None,
        "matrix": matrix,
        "per_task": grid,
        "failures": failures,
    }


def _by_task(grid: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """One cell per ``(task, backend)``: what the benchmark is actually for.

    Did the model reach a correct answer on this prompt, were its tool calls
    the ones the task requires, were those calls well formed, and what did it
    cost. Repeats are a count -- ``2/3`` is the finding -- and nothing here is
    inferred beyond what the sessions recorded.
    """

    cells: dict[str, dict[str, Any]] = {}
    for row in grid:
        cell = cells.setdefault(
            f"{row['task_id']}\x00{row['backend']}",
            {
                "task_id": row["task_id"],
                "backend": row["backend"],
                "repeats": 0,
                "correct": 0,
                "incomplete": 0,
                "trajectory_failures": 0,
                "trajectory_deviations": 0,
                "faults": 0,
                "wall_ms": 0.0,
                "tokens": 0,
                "checks": [],
            },
        )
        cell["repeats"] += 1
        if row["incomplete"]:
            cell["incomplete"] += 1
        elif row["passed"]:
            cell["correct"] += 1
        cell["trajectory_failures"] += row["trajectory_failures"] or 0
        cell["trajectory_deviations"] += row["trajectory_deviations"] or 0
        cell["faults"] += row["faults"] or 0
        cell["wall_ms"] += row["wall_ms"] or 0.0
        cell["tokens"] += (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
        cell["checks"].extend(row["answer_failures"])
    return cells


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
        "wall_ms_cold": 0.0,
        "cold_answers": 0,
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
    # Clustered, not naive: repeats of one task are one question asked twice.
    interval, rho, effective = clustered_interval(row["passed"], scored, outcomes)
    # A list, not a tuple: the JSON and Markdown reports are written from the
    # same object and a test holds them to the same content.
    row["pass_interval"] = list(interval) if interval else None
    row["intra_cluster_correlation"] = round(rho, 3)
    row["effective_trials"] = round(effective, 1)
    naive = wilson_interval(row["passed"], scored)
    row["pass_interval_naive"] = list(naive) if naive else None
    # Time to an answer, on the runs that reached one. The question a user
    # actually asks of a model is how long they wait for a usable answer, and
    # that is comparable across every backend however it is served.
    #
    # Scored on *first* repeats. A repeat of the same task reuses the
    # provider's prefix cache and runs artificially fast -- measured at a
    # median 1.33x on sessions doing byte-identical work -- and the size of
    # that discount differs by provider, so averaging it in would rank
    # backends partly on whose caching this harness happened to exercise.
    row["seconds_per_answer_warm"] = (
        row["wall_ms_to_answer"] / 1000.0 / row["passed"] if row["passed"] else None
    )
    row["seconds_per_answer"] = (
        row["wall_ms_cold"] / 1000.0 / row["cold_answers"]
        if row["cold_answers"]
        else row["seconds_per_answer_warm"]
    )
    row["cold_latency"] = bool(row["cold_answers"])
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
    if passed < 0 or passed > trials:
        # p outside [0, 1] drives p(1-p) negative and the square root raises a
        # bare ValueError from inside the arithmetic. That is a caller error --
        # a count larger than the number of trials -- and it should say so
        # rather than surface as a domain error in a formula.
        raise ValueError(
            f"wilson_interval: passed={passed} is not in [0, {trials}]"
        )
    p = passed / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = (
        z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
    ) / denominator
    return (max(0.0, center - half), min(1.0, center + half))


def design_effect(outcomes: Mapping[str, Sequence[Any]]) -> tuple[float, float]:
    """Intra-cluster correlation and design effect for a backend's sessions.

    A suite of ``t`` tasks run ``m`` times each yields ``t*m`` sessions, and a
    binomial interval over them assumes ``t*m`` *independent* trials. They are
    not independent: three repeats of one question are one question asked three
    times. Treating them as independent understates the interval -- it reports
    more precision than the design bought.

    The correlation is estimated the standard way, from the split between
    between-task and within-task variance, and turned into a design effect
    ``1 + (m-1) * rho``. The effective sample size is ``t*m / deff``.

    The two ends are worth stating because the useful one is the bad one. A
    model whose answers vary freely within a task has ``rho = 0``, nothing is
    lost, and the effective size is the session count. A model that answers each
    task the same way every time has ``rho = 1``, a design effect of ``m``, and
    an effective size of ``t`` -- **repeats buy it nothing at all**. The more
    deterministic the backend, the more a naive interval flatters it.
    """

    clusters = [list(v) for v in outcomes.values() if v]
    if len(clusters) < 2:
        return 0.0, 1.0
    sizes = [len(c) for c in clusters]
    total = sum(sizes)
    k = len(clusters)
    if total <= k:  # every cluster of size 1: no repeats to be correlated
        return 0.0, 1.0

    # m0, the unbalanced-design cluster size (Donner 1986). It reduces to the
    # common cluster size when the design is balanced, which ours is whenever a
    # run completes -- but a partial run has ragged clusters and the mean would
    # be the wrong constant.
    m0 = (total - sum(size * size for size in sizes) / total) / (k - 1)
    if m0 <= 1:
        return 0.0, 1.0

    props = [sum(1 for x in c if x) / len(c) for c in clusters]
    grand = sum(sum(1 for x in c if x) for c in clusters) / total

    # One-way random-effects ANOVA on binary data. For a cluster of size n and
    # proportion p, the within-cluster sum of squares is exactly n*p*(1-p).
    between = sum(
        size * (prop - grand) ** 2 for size, prop in zip(sizes, props)
    ) / (k - 1)
    within = sum(
        size * prop * (1.0 - prop) for size, prop in zip(sizes, props)
    ) / (total - k)

    denominator = between + (m0 - 1) * within
    if denominator <= 0:
        # No variance anywhere: every session agreed. Nothing here distinguishes
        # a deterministic model from a lucky one, so assume full clustering
        # rather than claim the repeats were independent evidence.
        rho = 1.0
    else:
        rho = (between - within) / denominator
    # A negative estimate means less between-cluster than within-cluster
    # variance -- real, but it would push the effective size *above* the
    # session count and claim more independence than sessions exist.
    rho = min(1.0, max(0.0, rho))
    return rho, 1.0 + (m0 - 1) * rho


def clustered_interval(
    passed: int, trials: int, outcomes: Mapping[str, Sequence[Any]]
):
    """A Wilson interval on the effective sample size, not the session count.

    **Where this interval comes from.** Each task is treated as a draw from the
    population of questions one could ask about this tool surface, and each
    repeat as a Bernoulli draw within that task. Two levels of randomness, so
    the variance has two terms, and the design effect is what folds the second
    into an effective sample size.

    So it answers *"how would this model do on other questions like these?"* --
    which is what a reader meeting a benchmark number wants to know. It does
    **not** answer "re-run this same suite, what would it score?". Those are
    different questions with different answers, and for a model that answers
    each task the same way every repeat they are as far apart as they get: its
    re-run score is perfectly reproducible, a point, while its score on a fresh
    set of eight questions is barely pinned down at all.

    Simulated rather than argued, in ``tests/test_bench_report.py``: against a
    population where each task is reliably passed or reliably failed, a naive
    Wilson interval over the session count covers the population mean about 74%
    of the time at a nominal 95%. This one covers it about 94%.

    The assumption it rests on is the one worth stating: that these tasks are
    exchangeable with the questions a reader cares about. They are hand-picked
    from documented failure modes, not drawn at random, so that is a judgement
    about the corpus and not something the arithmetic establishes.
    """

    if trials <= 0:
        return None, 0.0, 0.0
    rho, deff = design_effect(outcomes)
    effective = trials / deff if deff else trials
    rate = passed / trials
    interval = wilson_interval(round(rate * effective), max(1, round(effective)))
    return interval, rho, effective


def difference_interval(
    passed_a: int,
    trials_a: int,
    passed_b: int,
    trials_b: int,
):
    """A 95% interval on the *difference* of two pass rates.

    Newcombe (1998) method 10, the square-and-add hybrid score interval, built
    from the two Wilson intervals this module already computes.

    This replaced an overlap test, which was wrong in a way that is easy to
    miss because it errs toward modesty. Two 95% intervals can overlap while
    the difference between them is significant: the overlap test is
    substantially more conservative than its nominal level, so "their intervals
    overlap" is a weaker statement than "no difference was shown" and must not
    be reported as the latter. The question "are these two backends different?"
    is a question about the difference, so it is asked about the difference.
    """

    if trials_a <= 0 or trials_b <= 0:
        return None
    first = wilson_interval(passed_a, trials_a)
    second = wilson_interval(passed_b, trials_b)
    if first is None or second is None:
        return None
    rate_a, rate_b = passed_a / trials_a, passed_b / trials_b
    delta = rate_a - rate_b
    lower = delta - math.sqrt((rate_a - first[0]) ** 2 + (second[1] - rate_b) ** 2)
    upper = delta + math.sqrt((first[1] - rate_a) ** 2 + (rate_b - second[0]) ** 2)
    return max(-1.0, lower), min(1.0, upper)


def _effective_counts(row: Mapping[str, Any]) -> tuple[int, int] | None:
    """A row's pass count and trial count on its *effective* sample size.

    The clustering correction has to survive into the comparison. Testing a
    difference on raw session counts would re-assume the independence the
    interval already established is not there.
    """

    effective = row.get("effective_trials")
    rate = row.get("pass_rate")
    if not effective or rate is None:
        return None
    trials = max(1, round(effective))
    return round(rate * trials), trials


def separated(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether the difference between two backends excludes zero at 95%.

    Reported rather than enforced: a suite that cannot separate two models is
    making a statement about the suite, and hiding it behind an ordered table
    would be the failure this benchmark exists to catch.
    """

    first, second = _effective_counts(a), _effective_counts(b)
    if first is None or second is None:
        return False
    interval = difference_interval(*first, *second)
    if interval is None:
        return False
    return interval[0] > 0.0 or interval[1] < 0.0


#: How each board is read off a matrix row: the column, and whether a bigger
#: number is better.
_BOARD_COLUMN: Mapping[str, tuple[str, bool]] = {
    "correctness": ("pass_rate", True),
    "speed": ("seconds_per_answer", False),
    "cost": ("tokens_per_answer", False),
}


def boards(matrix: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Three independent orders, one per measurement.

    Each row carries the raw measurement and -- for the two relative boards --
    its ratio to the best entry, so "1.8x the fastest" is visible as a
    comparison rather than disguised as a score. Correctness carries its 95%
    interval instead, because it has an absolute scale on which an interval
    means something.
    """

    out: dict[str, list[dict[str, Any]]] = {}
    for board in SCORE_BOARDS:
        column, higher_is_better = _BOARD_COLUMN[board]
        entries = [
            {"backend": backend, "value": row[column]}
            for backend, row in matrix.items()
            if row.get(column) is not None
        ]
        entries.sort(key=lambda e: e["value"], reverse=higher_is_better)
        best = entries[0]["value"] if entries else None
        for rank, entry in enumerate(entries, start=1):
            entry["rank"] = rank
            if board == "correctness":
                entry["interval"] = matrix[entry["backend"]].get("pass_interval")
            elif best:
                # Relative to the best on this board, and only ever that: there
                # is no absolute scale for a second or a token here.
                entry["times_best"] = entry["value"] / best
        entries_missing = sorted(
            backend
            for backend, row in matrix.items()
            if row.get(column) is None
        )
        out[board] = entries
        out[f"{board}_unmeasured"] = [
            {"backend": backend} for backend in entries_missing
        ]
    return out


def _rank_boards(matrix: dict[str, dict[str, Any]]) -> None:
    """Write each backend's rank on each board back onto its matrix row."""

    for board, entries in boards(matrix).items():
        if board.endswith("_unmeasured"):
            continue
        for entry in entries:
            matrix[entry["backend"]][f"rank_{board}"] = entry["rank"]


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
    # Harness errors, counted apart from the other incomplete outcomes. A model
    # running out of turns is a result about the model; an API outage is not a
    # result at all, and recording them the same way is how a sweep of 47 failed
    # sessions renders as a scoreboard with a quiet column nobody reads first.
    errored: list[str] = []
    sessions = 0
    for pair in runs:
        record = pair["record"]
        for entry in record.get("runs", ()):
            sessions += 1
            if entry.get("outcome") == "error" or entry.get("error"):
                errored.append(f"{entry['task_id']}@{entry['backend']}")
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
        "errored": errored,
        "sessions": sessions,
        "error_rate": len(errored) / sessions if sessions else 0.0,
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


#: Above this share of sessions failing inside the harness, a run is not a
#: measurement of anything. Set where it is because a handful of transient API
#: errors across a long sweep is survivable -- those sessions are excluded and
#: the rest still measured -- while a quarter of them means the thing being
#: reported is the network.
MAX_ERROR_RATE = 0.20


def has_broken_run(report: Mapping[str, Any]) -> bool:
    """Whether so many sessions failed inside the harness that the run is not
    a result.

    The failure this exists for: a live sweep lost its API connection after two
    sessions, errored the remaining 47, and reported ``DONE`` on all five
    suites in under twenty seconds. Errored sessions are recorded
    ``incomplete``, which the grader rightly excludes from the pass rate rather
    than counting as failures -- so the run rendered as a scoreboard over the
    two sessions that survived, with the wreckage in a column beside it. The
    only reason it was caught is that seven seconds for nine live-API sessions
    is impossible on its face, and that is not a check.
    """

    return report["header"].get("error_rate", 0.0) > MAX_ERROR_RATE


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
        "trajectory_deviations": len(entry["trajectory"]["deviations"]),
        "answer_failures": [f["check"] for f in entry["answer"]["failures"]],
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
    if header.get("errored"):
        rate = header.get("error_rate", 0.0)
        lines.append(
            f"> **{len(header['errored'])} of {header['sessions']} sessions "
            f"failed inside the harness** ({rate:.0%}). These are not model "
            "results -- an API outage and a model running out of turns are not "
            "the same event, and only the second belongs in a score."
        )
        if rate > MAX_ERROR_RATE:
            lines.append(">")
            lines.append(
                "> **This run is not a measurement.** Re-run it; do not read "
                "the tables below."
            )
        lines.append("")

    if header["incomplete"]:
        lines.append(
            "**Incomplete** (did not answer; never scored as a low pass rate): "
            + ", ".join(f"`{item}`" for item in header["incomplete"])
        )
        lines.append("")

    lines.extend(_task_matrix(report))
    lines.extend(_ranking_table(report))
    lines.extend(_matrix_table(report))
    lines.extend(_grid_table(report))
    lines.extend(_failure_list(report))
    return "\n".join(lines) + "\n"


#: What each board measures, in the report's own words.
_BOARD_BLURB: Mapping[str, str] = {
    "correctness": (
        "**Absolute.** Share of sessions whose answer passed every hard check. "
        "1.0 means every question answered correctly, and the figure means the "
        "same whoever else was measured.\n\n"
        "The interval is computed on the **effective** sample size, not the "
        "session count. Repeats of one task are one question asked several "
        "times, so they are not independent trials; `n_eff` is the session "
        "count divided by the design effect. A backend that answers each task "
        "identically every repeat has `n_eff` equal to the *task* count -- for "
        "it, repeats bought nothing.\n\n"
        "It answers **\"how would this model do on other questions like "
        "these?\"** -- each task a draw from the population of questions one "
        "could ask about this tool surface, each repeat a draw within it. It "
        "does *not* answer \"re-run this same suite, what would it score?\"; "
        "a deterministic backend re-runs to the same number exactly, and this "
        "interval is deliberately far wider than that. The assumption is that "
        "these tasks are exchangeable with the questions you care about -- "
        "they are hand-picked from documented failure modes, so that is a "
        "judgement about the corpus, not a result of the arithmetic."
    ),
    "speed": (
        "**Relative.** Wall-clock seconds to a passing answer, measured on "
        "**first repeats only**. Repeating a task back to back reuses the "
        "provider's prefix cache: sessions doing byte-identical work -- same "
        "turns, same calls, same input tokens -- ran a median 1.33x and up to "
        "2.43x slower on their first repeat than their later ones. A caller "
        "asks each question once, cold, and the size of that discount differs "
        "by provider, so averaging it in would rank backends partly on whose "
        "caching this harness happened to exercise.\n\n"
        "There is no \"perfectly fast\", so the only comparison available is "
        "against the other backends here -- add a slower model and these "
        "standings move."
    ),
    "cost": (
        "**Relative.** Tokens spent per passing answer, on the same footing as "
        "speed: a ranking among these backends, not a score on a fixed scale."
    ),
}

_BOARD_UNIT: Mapping[str, str] = {
    "correctness": "",
    "speed": "s",
    "cost": " tokens",
}


def _task_matrix(report: Mapping[str, Any]) -> list[str]:
    """One cell per task per model: the result this benchmark exists to give.

    Whether a model used these tools well on a given prompt is a direct
    observation. The session ran; the checks passed or they did not. So the
    cell is a count, and ``2/3`` is reported as ``2/3`` rather than averaged
    into a rate and wrapped in an interval -- that would answer a question
    about tasks nobody ran.
    """

    cells = report.get("by_task") or {}
    if not cells:
        return []
    tasks = sorted({c["task_id"] for c in cells.values()})
    backends = sorted({c["backend"] for c in cells.values()})

    lines = [
        "## Per task",
        "",
        "Correct answers out of repeats. A mark means the *route* was wrong "
        "even where the answer was not -- `T` a forbidden call made or an "
        "argument rule broken, `d` a declared call skipped or taken out of "
        "order, `P` a protocol fault, `!` a run that never answered.",
        "",
        "| task | " + " | ".join(f"`{b.split('/')[-1]}`" for b in backends) + " |",
        "| --- | " + " | ".join(":-:" for _ in backends) + " |",
    ]
    for task in tasks:
        row = [f"`{task}`"]
        for backend in backends:
            cell = cells.get(f"{task}\x00{backend}")
            if cell is None:
                row.append("--")
                continue
            marks = "".join(
                mark
                for mark, present in (
                    ("T", cell["trajectory_failures"]),
                    ("d", cell["trajectory_deviations"]),
                    ("P", cell["faults"]),
                    ("!", cell["incomplete"]),
                )
                if present
            )
            count = f"{cell['correct']}/{cell['repeats']}"
            if cell["correct"] == cell["repeats"] and not marks:
                count = f"**{count}**"
            row.append(f"{count} {marks}".strip())
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.extend(_tool_use_summary(cells, backends))
    return lines


def _tool_use_summary(
    cells: Mapping[str, Mapping[str, Any]], backends: Sequence[str]
) -> list[str]:
    """Per model: which tasks it cannot do, and how its tool use went wrong.

    Half the question is whether the calls and the reasoning were acceptable,
    which is the trajectory and protocol axes. They belong here, not filed
    under diagnostics beneath a percentage.
    """

    lines = [
        "### Per model",
        "",
        "| model | always correct | never correct | inconsistent | "
        "forbidden routes | skipped/out-of-order calls | protocol faults |",
        "| --- | :-: | :-: | :-: | :-: | :-: | :-: |",
    ]
    for backend in backends:
        mine = [c for c in cells.values() if c["backend"] == backend]
        lines.append(
            "| `{backend}` | {always} of {total} | {never} | {mixed} | "
            "{traj} | {dev} | {faults} |".format(
                backend=backend,
                always=sum(1 for c in mine if c["correct"] == c["repeats"]),
                total=len(mine),
                never=sum(1 for c in mine if c["correct"] == 0),
                mixed=sum(1 for c in mine if 0 < c["correct"] < c["repeats"]),
                traj=sum(c["trajectory_failures"] for c in mine),
                dev=sum(c["trajectory_deviations"] for c in mine),
                faults=sum(c["faults"] for c in mine),
            )
        )
    lines.append("")

    never: list[str] = []
    for backend in backends:
        failed = sorted(
            c["task_id"]
            for c in cells.values()
            if c["backend"] == backend and c["correct"] == 0
        )
        if failed:
            never.append(
                f"- `{backend}` never answered: "
                + ", ".join(f"`{t}`" for t in failed)
            )
    if never:
        lines.append("Tasks a model never got right, which is the sharper result:")
        lines.append("")
        lines.extend(never)
        lines.append("")

    lines.append("Which answer checks each model failed, and how often:")
    lines.append("")
    for backend in backends:
        checks: list[str] = []
        for cell in cells.values():
            if cell["backend"] == backend:
                checks.extend(cell["checks"])
        if not checks:
            lines.append(f"- `{backend}`: none")
            continue
        counted = sorted(((checks.count(c), c) for c in set(checks)), reverse=True)
        lines.append(
            f"- `{backend}`: "
            + ", ".join(f"`{name}` x{count}" for count, name in counted)
        )
    lines.append("")
    return lines


def _ranking_table(report: Mapping[str, Any]) -> list[str]:
    """Three boards, never one number.

    Correctness, speed and cost are not the same kind of quantity, and a
    weighted sum of them would read as a measurement of the model while
    actually moving whenever the field of compared backends changes. They get
    an order each, and the summary shows where those orders disagree -- which
    is the finding, not a tie to be broken.
    """

    data = report.get("boards")
    if not data:
        return []

    lines = [
        "## Scores",
        "",
        "Three measurements, three boards, **never blended**. Only correctness "
        "has a baseline; a second and a token do not, so those two are "
        "rankings among the backends compared here and nothing more.",
        "",
    ]

    for board in SCORE_BOARDS:
        entries = data.get(board) or []
        lines.append(f"### {board.capitalize()}")
        lines.append("")
        lines.append(_BOARD_BLURB[board])
        lines.append("")
        if not entries:
            lines.append("Nothing measured on this board.")
            lines.append("")
        elif board == "correctness":
            lines.append(
                "| # | backend | correct | 95% interval | n_eff | rho |"
            )
            lines.append("| --: | --- | --- | --- | --: | --: |")
            for entry in entries:
                row = report["matrix"][entry["backend"]]
                lines.append(
                    "| {rank} | `{backend}` | **{rate}** ({passed}/{scored}) | "
                    "{interval} | {neff} of {scored} | {rho} |".format(
                        rank=entry["rank"],
                        backend=entry["backend"],
                        rate=_pct(entry["value"]),
                        passed=row["passed"],
                        scored=row["runs"] - row["incomplete"],
                        interval=_interval(entry.get("interval")),
                        neff=_num(row.get("effective_trials"), "{:.1f}"),
                        rho=_num(row.get("intra_cluster_correlation"), "{:.2f}"),
                    )
                )
        else:
            unit = _BOARD_UNIT[board]
            lines.append(f"| # | backend | per answer | vs best |")
            lines.append("| --: | --- | --: | --: |")
            for entry in entries:
                times = entry.get("times_best")
                lines.append(
                    "| {rank} | `{backend}` | **{value:,.0f}**{unit} | "
                    "{times} |".format(
                        rank=entry["rank"],
                        backend=entry["backend"],
                        value=entry["value"],
                        unit=unit,
                        times="best" if times == 1 else f"{times:.2f}x",
                    )
                )
        lines.append("")
        missing = data.get(f"{board}_unmeasured") or []
        if missing:
            lines.append(
                "Not measured (no passing run to cost): "
                + ", ".join(f"`{m['backend']}`" for m in missing)
                + "."
            )
            lines.append("")

    lines.extend(_board_summary(report, data))
    return lines


def _board_summary(report: Mapping[str, Any], data: Mapping[str, Any]) -> list[str]:
    """One row per backend, its place on each board.

    The point of the table is the rows that disagree with themselves. A model
    ranked first for correctness and last for speed has not been beaten by a
    faster one -- it has bought accuracy with time, and which of those a caller
    wants is not something this harness can decide for them.
    """

    backends = sorted(report["matrix"])
    if len(backends) < 2:
        return []
    place: dict[str, dict[str, Any]] = {b: {} for b in backends}
    for board in SCORE_BOARDS:
        for entry in data.get(board) or []:
            place[entry["backend"]][board] = entry["rank"]

    lines = [
        "### The board",
        "",
        "Where these three disagree is the result, not a tie to break.",
        "",
        "| backend | correctness | speed | cost |",
        "| --- | :-: | :-: | :-: |",
    ]
    for backend in backends:
        cells = " | ".join(
            str(place[backend].get(board, "--")) for board in SCORE_BOARDS
        )
        lines.append(f"| `{backend}` | {cells} |")
    lines.append("")

    disagreeing = [
        backend
        for backend in backends
        if len({place[backend][b] for b in SCORE_BOARDS if b in place[backend]}) > 1
    ]
    if disagreeing:
        lines.append(
            "Ranked differently by different measurements: "
            + ", ".join(f"`{b}`" for b in disagreeing)
            + ". No single order over these backends exists."
        )
    else:
        lines.append(
            "Every backend holds the same place on all three boards, so one "
            "order does describe them."
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
            "**Not separated by this suite**: " + ", ".join(overlapping) + ". "
            "A 95% interval on the *difference* in correctness (Newcombe 1998, "
            "method 10, on effective sample sizes) includes zero for these "
            "pairs -- ordering them reads a difference the trial count does "
            "not support."
        )
    else:
        lines.append(
            "Every pair of backends is separated at 95% on correctness: each "
            "pairwise difference interval excludes zero."
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
