"""The run loop and the run-directory writer.

``docs/working/benchmark.md`` sections 5.5-5.7. ``run`` produces evidence;
``grade`` produces verdicts. Keeping them apart is what makes a grader fix free
-- the first version of any grader is wrong, and re-grading must not cost a
re-spend against four paid backends.

Per ``(backend, task, repeat)`` the harness writes four files:

* ``session_manifest.json`` -- ``AgentSession``'s own file, unmodified.
* ``events.jsonl`` -- every event in order. The only record of
  ``ToolCallDenied``, of per-call ``duration_ms``, and of the full tool result
  payloads the manifest deliberately omits. ``must_source_value`` has nowhere
  else to look for the numbers a model actually saw.
* ``answer.txt`` -- the final turn's text, **unbounded**. The manifest bounds
  ``assistant_text`` at 4,000 characters, so a ``must_not_match`` on a long
  answer would otherwise be evaluated against a truncated one.
* ``error.txt`` -- only when the session raised.

And once per run, ``run.json``: every knob, so the run can state its inputs
(B4). A run that cannot is not a benchmark.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from tools import artifacts
from tools.agent import events as event_types
from tools.agent.engine import run_session
from tools.agent.prompt import SYSTEM_PROMPT
from tools.bench.fixtures import FixtureStore
from tools.bench.plane import DEFAULT_BLOCKED, build_tool_plane
from tools.bench.tasks import Suite, Task
from tools.sessions import AgentSession, backend_record

__all__ = [
    "BudgetExceeded",
    "RunConfig",
    "RunRecord",
    "TaskRun",
    "run_suite",
    "corpus_digest",
    "sha256_file",
]

RUN_RECORD_NAME = "run.json"
ANSWER_NAME = "answer.txt"
EVENTS_NAME = "events.jsonl"
ERROR_NAME = "error.txt"

#: Outcomes that mean the model did not answer, as opposed to answering badly.
#: Reported in their own column and never scored as a low pass rate.
INCOMPLETE_OUTCOMES: frozenset[str] = frozenset(
    {"max_turns", "budget_exceeded", "error"}
)


class BudgetExceeded(RuntimeError):
    """The run crossed its token ceiling. B5.

    Raised before dispatching a turn, never after: checking afterwards means
    the spend has already happened.
    """


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_digest(suite: Suite, fixture_root: Path) -> dict[str, Any]:
    """The SHA-256 of every task file and every fixture file the suite uses.

    B4. The harness refuses to start if it cannot read these, and stamps
    ``corpus_dirty`` rather than silently grading against uncommitted tasks.
    """

    from tools.bench.fixtures import resolve_fixture_path

    tasks = {task.id: sha256_file(task.source) for task in suite}
    fixtures: dict[str, str] = {}
    for task in suite:
        for name in task.fixtures:
            if name not in fixtures:
                fixtures[name] = sha256_file(resolve_fixture_path(name, fixture_root))
    return {
        "suite": sha256_file(suite.source),
        "tasks": tasks,
        "fixtures": fixtures,
    }


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _corpus_dirty(paths: Sequence[Path]) -> bool | None:
    """Whether any corpus path has uncommitted changes.

    ``None`` means git could not answer -- reported as unknown rather than as
    clean, because "we could not tell" and "it was clean" are different
    statements about a recorded run.
    """

    status = _git("status", "--porcelain", "--", *[str(p) for p in paths])
    if status is None:
        return None
    return bool(status.strip())


@dataclass(frozen=True)
class RunConfig:
    """Every knob a run is started with. Written verbatim into ``run.json``."""

    suite_id: str
    backends: tuple[str, ...]
    out: Path
    repeats: int = 1
    temperature: float = 0.0
    seed: int | None = None
    max_tokens: int | None = None
    max_turns_override: int | None = None
    enable: tuple[str, ...] = ()
    judge: str | None = None
    system_prompt: str = SYSTEM_PROMPT


@dataclass
class TaskRun:
    """One ``(backend, task, repeat)`` result, as the grader will read it."""

    backend: str
    task_id: str
    repeat: int
    directory: Path
    outcome: str
    manifest_path: Path | None = None
    answer_path: Path | None = None
    events_path: Path | None = None
    error: str | None = None
    wall_ms: float = 0.0
    fixture_misses: list[dict[str, Any]] = field(default_factory=list)
    fixture_hits: int = 0

    @property
    def incomplete(self) -> bool:
        return self.outcome in INCOMPLETE_OUTCOMES


@dataclass
class RunRecord:
    """The whole run: its config, its inputs, and its per-task results."""

    run_id: str
    config: RunConfig
    started_at: str
    finished_at: str | None = None
    host: str | None = None
    git_head: str | None = None
    corpus_dirty: bool | None = None
    corpus: Mapping[str, Any] = field(default_factory=dict)
    env_overrides: Mapping[str, str] = field(default_factory=dict)
    backend_details: dict[str, Any] = field(default_factory=dict)
    dry_run_ceiling: int | None = None
    usage_total: int = 0
    runs: list[TaskRun] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        config = asdict(self.config)
        config["out"] = str(config["out"])
        # The prompt itself is ~270 lines and is already hashed per session;
        # the run record carries the hash so two runs can be compared without
        # carrying the text twice.
        import hashlib

        config["system_prompt_sha256"] = hashlib.sha256(
            self.config.system_prompt.encode("utf-8")
        ).hexdigest()
        del config["system_prompt"]
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "host": self.host,
            "git_head": self.git_head,
            "corpus_dirty": self.corpus_dirty,
            "corpus": self.corpus,
            "env_overrides": self.env_overrides,
            "config": config,
            "backends": self.backend_details,
            "dry_run_ceiling_tokens": self.dry_run_ceiling,
            "tokens_used": self.usage_total,
            "runs": [
                {
                    "backend": run.backend,
                    "task_id": run.task_id,
                    "repeat": run.repeat,
                    "directory": str(run.directory),
                    "outcome": run.outcome,
                    "incomplete": run.incomplete,
                    "wall_ms": run.wall_ms,
                    "error": run.error,
                    "fixture_hits": run.fixture_hits,
                    "fixture_misses": run.fixture_misses,
                }
                for run in self.runs
            ],
        }

    @property
    def fixture_miss_rate(self) -> float:
        hits = sum(run.fixture_hits for run in self.runs)
        misses = sum(len(run.fixture_misses) for run in self.runs)
        total = hits + misses
        return misses / total if total else 0.0


@contextmanager
def _task_env(env: Mapping[str, str]) -> Iterator[None]:
    """Apply a task's ``KEPLER_*`` overrides for the duration of one run.

    ``tools.config`` resolves most settings at import, so the modules that
    read them are reloaded rather than trusted to re-read the environment.
    """

    if not env:
        yield
        return

    import importlib

    from tools import config as config_module

    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        importlib.reload(config_module)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(config_module)


def _event_json(event: Any) -> dict[str, Any]:
    payload = {"event": type(event).__name__}
    for key, value in (asdict(event) if is_dataclass(event) else vars(event)).items():
        payload[key] = value
    return json.loads(json.dumps(payload, default=str))


def _answer_text(stream: Sequence[Any]) -> str:
    """The text of the **final** turn, unbounded.

    Reset at every ``TurnStarted`` rather than accumulated across the whole
    session: a model that narrates its tool use for six turns and then answers
    should be graded on the answer, not on the narration.
    """

    text: list[str] = []
    for event in stream:
        if isinstance(event, event_types.TurnStarted):
            text.clear()
        elif isinstance(event, event_types.TextDelta):
            text.append(event.text)
    return "".join(text)


def run_suite(
    suite: Suite,
    *,
    backends: Mapping[str, Any],
    config: RunConfig,
    fixture_root: str | Path,
    out: str | Path | None = None,
) -> RunRecord:
    """Run every ``(backend, task, repeat)`` and write the run directory.

    ``backends`` maps a spec to a constructed ``ModelBackend``; the harness
    never builds one itself, so a test can hand it a ``ReplayBackend`` and the
    CLI can hand it a real adapter without this function knowing the
    difference.
    """

    fixture_root = Path(fixture_root)
    out_dir = Path(out) if out is not None else Path(config.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    record = RunRecord(
        run_id=out_dir.name,
        config=config,
        started_at=_utc_now(),
        host=platform.node(),
        git_head=_git("rev-parse", "HEAD"),
        corpus=corpus_digest(suite, fixture_root),
        env_overrides={
            key: value
            for key, value in sorted(os.environ.items())
            if key.startswith("KEPLER_")
        },
        backend_details={
            spec: backend_record(backend) for spec, backend in backends.items()
        },
    )
    record.corpus_dirty = _corpus_dirty(
        [suite.source.parent, fixture_root]
    )
    record.dry_run_ceiling = _dry_run_ceiling(suite, config, backends)

    budget_hit = False
    for spec, backend in backends.items():
        for task in suite:
            for repeat in range(1, config.repeats + 1):
                if budget_hit:
                    break
                task_run = _run_one(
                    suite=suite,
                    task=task,
                    backend=backend,
                    spec=spec,
                    repeat=repeat,
                    config=config,
                    fixture_root=fixture_root,
                    out_dir=out_dir,
                    record=record,
                )
                record.runs.append(task_run)
                if task_run.outcome == "budget_exceeded":
                    budget_hit = True

    record.finished_at = _utc_now()
    (out_dir / RUN_RECORD_NAME).write_text(
        json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def _dry_run_ceiling(
    suite: Suite, config: RunConfig, backends: Mapping[str, Any]
) -> int:
    """An upper bound on what the run can consume, printed before the first
    live call. Tasks x repeats x max_turns x the per-turn output ceiling."""

    per_turn = max(
        (
            int(getattr(backend.capabilities, "max_output_tokens", 0) or 0)
            for backend in backends.values()
        ),
        default=0,
    )
    turns = sum(config.max_turns_override or task.max_turns for task in suite)
    return turns * config.repeats * len(backends) * per_turn


def _run_one(
    *,
    suite: Suite,
    task: Task,
    backend: Any,
    spec: str,
    repeat: int,
    config: RunConfig,
    fixture_root: Path,
    out_dir: Path,
    record: RunRecord,
) -> TaskRun:
    directory = out_dir / _slug(spec) / task.id / f"r{repeat}"
    directory.mkdir(parents=True, exist_ok=True)

    store = FixtureStore.load(
        task.fixtures,
        root=fixture_root,
        task_id=task.id,
        miss_policy=task.miss_policy,
    )
    functions = build_tool_plane(
        replay=store.replay,
        blocked=DEFAULT_BLOCKED,
        enabled=frozenset(task.enable) | frozenset(config.enable),
    )

    subdir = Path(directory).relative_to(artifacts.ARTIFACT_DIR) if _under_artifacts(
        directory
    ) else None
    session = AgentSession(
        user_message=task.prompt,
        model=spec.split("/", 1)[-1],
        max_turns=config.max_turns_override or task.max_turns,
        system=config.system_prompt,
        artifact_subdir_override=str(subdir) if subdir else None,
    )

    stream: list[Any] = []
    outcome = "error"
    error: str | None = None
    started = time.monotonic()

    try:
        with _task_env(task.env):
            for event in _budgeted(
                run_session(
                    task.prompt,
                    backend=backend,
                    system=config.system_prompt,
                    max_turns=config.max_turns_override or task.max_turns,
                    session=session,
                    tool_functions=functions,
                ),
                record=record,
                config=config,
                backend=backend,
            ):
                stream.append(event)
                if isinstance(event, event_types.SessionFinished):
                    outcome = event.outcome
    except BudgetExceeded as exc:
        outcome = "budget_exceeded"
        error = str(exc)
    except Exception as exc:  # a backend or tool failure ends this task only
        outcome = "error"
        error = f"{type(exc).__name__}: {exc}"

    wall_ms = (time.monotonic() - started) * 1000.0

    events_path = directory / EVENTS_NAME
    with events_path.open("w", encoding="utf-8") as handle:
        for event in stream:
            handle.write(json.dumps(_event_json(event), sort_keys=True) + "\n")

    answer_path = directory / ANSWER_NAME
    answer_path.write_text(_answer_text(stream), encoding="utf-8")

    manifest_path = session.manifest_path
    if manifest_path.exists() and manifest_path.parent != directory:
        # The session wrote outside the run directory (its artifact root is
        # elsewhere); copy the manifest in so grading reads one directory.
        (directory / manifest_path.name).write_bytes(manifest_path.read_bytes())
        manifest_path = directory / manifest_path.name

    if error is not None:
        (directory / ERROR_NAME).write_text(error, encoding="utf-8")

    return TaskRun(
        backend=spec,
        task_id=task.id,
        repeat=repeat,
        directory=directory,
        outcome=outcome,
        manifest_path=manifest_path if manifest_path.exists() else None,
        answer_path=answer_path,
        events_path=events_path,
        error=error,
        wall_ms=wall_ms,
        fixture_misses=list(store.misses),
        fixture_hits=store.hits,
    )


def _under_artifacts(directory: Path) -> bool:
    from tools.config import within

    return within(directory, artifacts.ARTIFACT_DIR)


def _budgeted(
    stream: Iterator[Any], *, record: RunRecord, config: RunConfig, backend: Any
) -> Iterator[Any]:
    """B5. Check the ceiling **before** dispatching each turn.

    Crossing it ends the run with outcome ``budget_exceeded``, the partial
    results kept and clearly marked partial. Replay backends are exempt: a
    transcript cannot run away. Ollama is not -- a local daemon costs no money
    but a runaway loop still costs hours.
    """

    exempt = str(getattr(backend, "spec", "")).startswith("replay/")
    for event in stream:
        if isinstance(event, event_types.TurnStarted) and not exempt:
            if config.max_tokens is not None and record.usage_total >= config.max_tokens:
                raise BudgetExceeded(
                    f"token budget of {config.max_tokens} reached "
                    f"({record.usage_total} used) before turn {event.turn}; "
                    "partial results are kept and marked partial"
                )
        if isinstance(event, event_types.TurnFinished) and event.usage is not None:
            record.usage_total += (event.usage.input_tokens or 0) + (
                event.usage.output_tokens or 0
            )
        yield event


def _slug(spec: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in spec)


@contextmanager
def no_sockets() -> Iterator[None]:
    """B2's mechanism, exported so a test and the CLI's ``--offline`` flag use
    the same one: any attempt to construct a socket raises."""

    original = socket.socket

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "a benchmark run opened a socket; every class-R tool is replayed "
            "and no class-L tool queries anything"
        )

    socket.socket = refuse  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = original  # type: ignore[assignment]
