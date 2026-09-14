"""``kepler-bench`` -- the benchmark CLI.

``docs/working/benchmark.md`` section 11. Six verbs over a directory on disk:

* ``run`` -- live model, replayed remote tools, live local tools.
* ``grade`` -- offline, free, and repeatable after a grader fix.
* ``falsify`` -- the adversarial pass over the keys. Offline, consults no model.
* ``answers`` -- the question beside the reply, for a reader. Offline.
* ``compare`` -- the matrix.
* ``record`` -- live capture of one class-R tool, for human review.

``run`` implies ``grade`` unless ``--no-grade``; ``grade`` is separately
invocable so a grader's first version being wrong never costs a re-spend
against four paid backends.

``--max-tokens`` is **required** for any non-replay backend, and there is no
default: a default budget is a number nobody thinks about.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

__all__ = ["main", "build_parser"]

DEFAULT_SUITE_ROOT = Path("benchmarks/suites")
DEFAULT_FIXTURE_ROOT = Path("benchmarks/fixtures")
DEFAULT_OUT_ROOT = Path("artifacts/bench")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kepler-bench",
        description="Benchmark models on Kepler's tool surface.",
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    run = sub.add_parser("run", help="run a suite against one or more backends")
    run.add_argument("suite", help="suite id under benchmarks/suites/")
    run.add_argument(
        "--backend",
        action="append",
        default=[],
        metavar="PROVIDER/MODEL",
        help="a backend spec; repeat for several. 'replay/<name>' replays a "
        "recorded transcript from benchmarks/transcripts/.",
    )
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="hard token ceiling for the whole run. Required for any live "
        "backend; there is no default, because a default budget is a number "
        "nobody thinks about.",
    )
    run.add_argument("--max-turns", type=int, default=None)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--seed", type=int, default=None)
    run.add_argument(
        "--enable",
        action="append",
        default=[],
        metavar="TOOL",
        help="opt a blocked tool in (solve_astrometry).",
    )
    run.add_argument("--out", type=Path, default=None)
    run.add_argument("--suite-root", type=Path, default=DEFAULT_SUITE_ROOT)
    run.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    run.add_argument(
        "--offline",
        action="store_true",
        help="refuse any socket for the duration of the run (B2). Implied for "
        "a replay-only run.",
    )
    run.add_argument("--no-grade", action="store_true")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print the token ceiling and the plan, then stop.",
    )

    grade = sub.add_parser(
        "grade",
        help="grade a run directory offline. Free and repeatable, so a "
        "grader fix never costs a re-spend.",
    )
    grade.add_argument("run_dir", type=Path)
    grade.add_argument("--suite-root", type=Path, default=DEFAULT_SUITE_ROOT)
    grade.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    grade.add_argument(
        "--judge",
        default=None,
        metavar="PROVIDER/MODEL",
        help="turn on the advisory judge column. Off by default; it is the "
        "least trustworthy instrument here.",
    )
    falsify = sub.add_parser(
        "falsify",
        help="attack the answer keys with recorded evidence. Offline, free, "
        "and it consults no model: it can only accuse a key of being wrong.",
    )
    falsify.add_argument("run_dir", type=Path, nargs="+")
    falsify.add_argument("--suite-root", type=Path, default=DEFAULT_SUITE_ROOT)
    falsify.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)

    answers = sub.add_parser(
        "answers",
        help="print the question and the model's reply for each session. "
        "Offline, free, and the only way to audit a check against the prose "
        "it fired on.",
    )
    answers.add_argument("run_dir", type=Path, nargs="+")
    answers.add_argument("--suite-root", type=Path, default=DEFAULT_SUITE_ROOT)
    answers.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    answers.add_argument("--task", action="append", help="only these task ids")
    answers.add_argument(
        "--backend", action="append", help="only these backends (substring match)"
    )
    answers.add_argument("--repeat", type=int, action="append")
    answers.add_argument(
        "--wrong-only",
        action="store_true",
        help="only sessions the deterministic checks marked wrong.",
    )
    answers.add_argument(
        "--disagreed",
        action="store_true",
        help="only sessions where the advisory judge and the deterministic "
        "checks reached different verdicts. These are where one of the two "
        "instruments is wrong, and they are the ones worth reading.",
    )
    answers.add_argument(
        "--calls",
        action="store_true",
        help="also print the tool call sequence.",
    )

    compare = sub.add_parser(
        "compare", help="render the matrix over one or more run directories"
    )
    compare.add_argument("run_dirs", type=Path, nargs="+")
    compare.add_argument(
        "--allow-mixed-corpus",
        action="store_true",
        help="merge run directories recorded against different task files, "
        "fixtures or system prompts. Refused by default: pooling two "
        "instruments reports one rate over two experiments.",
    )
    compare.add_argument(
        "--tag",
        default=None,
        help="filter to the tasks carrying one tag (sourcing, null-argument, "
        "name-resolution, ...), so a single correctness family is read on "
        "its own.",
    )
    compare.add_argument(
        "--no-score",
        action="store_true",
        help="omit the ranking and print the diagnostics only. The score is "
        "three measurements -- correct, how long, how many tokens -- and "
        "printing it is the default; this is for reading a single run where "
        "there is nothing to rank. The diagnostics stay either way -- a score "
        "says which model, never which measurement failed.",
    )
    compare.add_argument("--out", type=Path, default=None)

    record = sub.add_parser(
        "record", help="capture one class-R tool's live result for review"
    )
    record.add_argument("task", help="suite/task-id, for naming the entry")
    record.add_argument("--tool", required=True)
    record.add_argument(
        "--argument",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="an argument to call the tool with; repeat for several.",
    )
    record.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verb == "run":
        return _run(args)
    if args.verb == "grade":
        return _grade(args)
    if args.verb == "falsify":
        return _falsify(args)
    if args.verb == "answers":
        return _answers(args)
    if args.verb == "compare":
        return _compare(args)
    if args.verb == "record":
        return _record(args)
    raise SystemExit(f"unknown verb {args.verb!r}")


def _falsify(args: Any) -> int:
    """Report candidate false positives in the keys themselves.

    Exit 1 when there are candidates: a key that fires on a defensible answer
    penalises a model for being right, and that is a failing condition for the
    corpus even though every run in it completed.
    """

    from tools.bench.falsify import falsify_run

    findings: list[dict[str, Any]] = []
    for directory in args.run_dir:
        findings += falsify_run(
            directory,
            suite_root=args.suite_root,
            fixture_root=args.fixture_root,
        )["findings"]

    if not findings:
        print(
            f"No candidate false positives across {len(args.run_dir)} run(s). "
            "A key can be shown wrong, never shown right -- this is the "
            "absence of a demonstration, not a clean bill of health."
        )
        return 0

    print(f"{len(findings)} candidate(s) to review:\n")
    for finding in findings:
        print(
            f"- [{finding['probe']}] {finding['task_id']} / "
            f"{finding['backend']} r{finding['repeat']} ({finding['check']})"
        )
        print(f"    {finding['detail']}")
    return 1


def _run(args: Any) -> int:
    from tools.bench.harness import RunConfig, no_sockets, run_suite
    from tools.bench.tasks import load_suite

    if not args.backend:
        print(
            "kepler-bench run: at least one --backend is required", file=sys.stderr
        )
        return 2

    specs = list(dict.fromkeys(args.backend))
    live = [spec for spec in specs if not spec.startswith("replay/")]
    if live and args.max_tokens is None:
        print(
            "kepler-bench run: --max-tokens is required for a live backend "
            f"({', '.join(live)}). Four backends x a suite x repeats against "
            "metered APIs is a self-inflicted billing risk, and there is no "
            "default because a default budget is a number nobody thinks about.",
            file=sys.stderr,
        )
        return 2

    suite = load_suite(
        Path(args.suite_root) / args.suite, fixture_root=args.fixture_root
    )
    out = args.out or (
        DEFAULT_OUT_ROOT
        / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{suite.id}"
    )

    backends = {spec: _build(spec) for spec in specs}
    config = RunConfig(
        suite_id=suite.id,
        backends=tuple(specs),
        out=Path(out),
        repeats=args.repeats,
        temperature=args.temperature,
        seed=args.seed,
        max_tokens=args.max_tokens,
        max_turns_override=args.max_turns,
        enable=tuple(args.enable),
    )

    if args.dry_run:
        from tools.bench.harness import _dry_run_ceiling

        ceiling = _dry_run_ceiling(suite, config, backends)
        print(f"suite {suite.id}: {len(suite)} task(s) x {args.repeats} repeat(s)")
        print(f"backends: {', '.join(specs)}")
        print(f"upper bound on tokens this run can consume: {ceiling:,}")
        return 0

    offline = args.offline or not live
    runner = no_sockets() if offline else _nullcontext()
    with runner:
        record = run_suite(
            suite,
            backends=backends,
            config=config,
            fixture_root=args.fixture_root,
            out=out,
        )

    if not args.no_grade:
        from tools.bench.grade import grade_run

        grade_run(Path(out), suite_root=args.suite_root, fixture_root=args.fixture_root)

    print(json.dumps(record.to_json(), indent=2, sort_keys=True))
    incomplete = [run for run in record.runs if run.incomplete]
    if incomplete:
        print(
            f"\n{len(incomplete)} of {len(record.runs)} run(s) did not answer: "
            + ", ".join(f"{r.task_id}@{r.backend} ({r.outcome})" for r in incomplete),
            file=sys.stderr,
        )
    if record.fixture_miss_rate:
        print(
            f"\nfixture miss rate {record.fixture_miss_rate:.0%}. A suite with "
            "a high miss rate is measuring its own coverage, not the model.",
            file=sys.stderr,
        )
    return 0


def _grade(args: Any) -> int:
    from tools.bench.grade import grade_run

    judge = None
    if args.judge:
        from tools.bench.judge import build_judge

        judge = build_judge(args.judge)

    grades = grade_run(
        Path(args.run_dir),
        suite_root=args.suite_root,
        fixture_root=args.fixture_root,
        judge=judge,
    )
    print(json.dumps(grades, indent=2, sort_keys=True))
    return 0


def _answers(args: Any) -> int:
    from tools.bench.answers import render, sessions

    records = list(
        sessions(
            args.run_dir,
            suite_root=args.suite_root,
            fixture_root=args.fixture_root,
        )
    )
    if args.task:
        records = [r for r in records if r["task_id"] in set(args.task)]
    if args.backend:
        records = [
            r
            for r in records
            if any(spec in r["backend"] for spec in args.backend)
        ]
    if args.repeat:
        records = [r for r in records if r["repeat"] in set(args.repeat)]
    if args.wrong_only:
        records = [r for r in records if r["correct"] is not True]
    if args.disagreed:
        # An ungraded or unjudged session has no disagreement to report; it is
        # filtered out rather than shown, so an empty result means "the two
        # instruments agreed everywhere", not "the judge never ran".
        records = [
            r
            for r in records
            if r["judge"]
            and r["judge"].get("verdict") in ("pass", "fail")
            and (r["judge"]["verdict"] == "pass") is not r["correct"]
        ]
    if not records:
        print("No sessions matched.", file=sys.stderr)
        return 0
    print("\n".join(render(records, verbose=args.calls)))
    return 0


def _compare(args: Any) -> int:
    from tools.bench.grade import GRADES_NAME, grade_run
    from tools.bench.harness import RUN_RECORD_NAME
    from tools.bench.report import (
        build_report,
        has_broken_run,
        has_corpus_conflict,
        render_markdown,
        write_report,
    )

    pairs = []
    for run_dir in args.run_dirs:
        record = json.loads((run_dir / RUN_RECORD_NAME).read_text(encoding="utf-8"))
        grades_path = run_dir / GRADES_NAME
        if not grades_path.exists():
            # Grading is free and repeatable; a compare over an ungraded run
            # should produce the matrix rather than an instruction to go and
            # run another command.
            grade_run(
                run_dir,
                suite_root=DEFAULT_SUITE_ROOT,
                fixture_root=DEFAULT_FIXTURE_ROOT,
            )
        grades = json.loads(grades_path.read_text(encoding="utf-8"))
        pairs.append({"record": record, "grades": grades})

    report = build_report(pairs, composite=not args.no_score, tag=args.tag)

    if has_broken_run(report) and not args.allow_mixed_corpus:
        header = report["header"]
        print(
            f"kepler-bench compare: {len(header['errored'])} of "
            f"{header['sessions']} sessions failed inside the harness "
            f"({header['error_rate']:.0%}). That is an outage, not a result. "
            "Re-run before comparing; --allow-mixed-corpus overrides and the "
            "report then says so in its header.",
            file=sys.stderr,
        )
        return 2

    if has_corpus_conflict(report) and not args.allow_mixed_corpus:
        conflicts = report["header"]["corpus_conflicts"]
        print(
            "kepler-bench compare: these run directories were not measured "
            "with the same instrument, so pooling them would report one rate "
            "over two experiments.",
            file=sys.stderr,
        )
        for kind in ("system_prompts", "tasks", "fixtures"):
            if conflicts.get(kind):
                print(f"  {kind}: {', '.join(conflicts[kind])}", file=sys.stderr)
        print(
            "Re-run the older backends against the current corpus. "
            "--allow-mixed-corpus overrides this, and the report says so in "
            "its header when you do.",
            file=sys.stderr,
        )
        return 2

    out = args.out or args.run_dirs[0]
    md, _ = write_report(report, out)
    print(render_markdown(report))
    print(f"written to {md}", file=sys.stderr)
    return 0


def _record(args: Any) -> int:
    from tools.bench.record import CredentialLeak, capture_entry

    arguments: dict[str, Any] = {}
    for pair in args.argument:
        name, _, value = pair.partition("=")
        if not name or not _:
            print(f"--argument must be NAME=VALUE, got {pair!r}", file=sys.stderr)
            return 2
        arguments[name] = _coerce(value)

    entry_id = args.task.split("/")[-1]
    try:
        captured = capture_entry(
            args.tool,
            arguments,
            entry_id=entry_id,
            content_dir=Path(args.fixture_root) / "content",
        )
    except CredentialLeak as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(captured.to_yaml())
    if captured.reviews:
        print(
            f"\n{len(captured.reviews)} string(s) flagged for review before "
            "committing this fixture.",
            file=sys.stderr,
        )
    return 0


def _coerce(value: str) -> Any:
    """Parse an --argument value as JSON where it parses, so `null`, numbers
    and booleans reach the tool as themselves rather than as strings. That
    distinction is the whole of the null-argument-fidelity check."""

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _build(spec: str) -> Any:
    """Construct a backend, or a per-task factory for a replayed one.

    A transcript is one task's trajectory. ``replay/<name>`` naming a
    directory under benchmarks/transcripts/ therefore yields a factory that
    loads ``<name>/<task-id>.json`` per task; naming a single file yields one
    backend replayed across the whole run.
    """

    if spec.startswith("replay/"):
        from tools.llm.replay_backend import ReplayBackend

        name = spec.split("/", 1)[1]
        root = Path("benchmarks/transcripts")
        directory = root / name
        if directory.is_dir():

            def factory(task: Any, repeat: int) -> Any:
                return ReplayBackend.from_file(directory / f"{task.id}.json")

            return factory
        return ReplayBackend.from_file(root / f"{name}.json")
    from tools.llm.factory import build_backend

    return build_backend(spec)


class _nullcontext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
