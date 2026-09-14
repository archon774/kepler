"""Task and suite loading.

``docs/working/benchmark.md`` section 6. One task per file, so a corpus diff is
reviewable per task and a suite's membership and order are explicit.

The loader is strict in one specific way that matters: **unknown keys are an
error, not ignored.** A typo in ``must_not_call`` that silently grades nothing
is worse than a load failure, because the suite keeps reporting a pass that
was never checked. The same reasoning makes ``because`` mandatory on every
hard-failure check -- it is printed verbatim in the report beside the failure,
so a scoreboard entry explains itself without anyone opening the suite file.

Security requirements realized here: S5 (``yaml.safe_load``, always), S6
(suite and fixture paths are contained), B7 (a task's ``env`` is ``KEPLER_*``
only -- it can shrink ``KEPLER_MAX_FRAMES`` to exercise the truncation
warning; it cannot set ``ANTHROPIC_API_KEY``, ``OPENAI_BASE_URL`` or ``PATH``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from tools.config import within

__all__ = [
    "TaskError",
    "Task",
    "Suite",
    "load_task",
    "load_suite",
    "TASK_ID_RE",
    "ENV_KEY_RE",
    "HARD_ANSWER_CHECKS",
]

#: A task id becomes an artifact subdirectory name, and ``scoped_artifacts``
#: would reject anything else anyway. Rejected here instead, with a better
#: message and before a run starts.
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: B7. A task may shape Kepler's own configuration and nothing else.
ENV_KEY_RE = re.compile(r"^KEPLER_[A-Z0-9_]+$")

_TASK_KEYS = frozenset(
    {
        "id",
        "title",
        "tags",
        "prompt",
        "max_turns",
        "fixtures",
        "miss_policy",
        "env",
        "enable",
        "expect",
    }
)

_TRAJECTORY_KEYS = frozenset({"must_call", "must_not_call", "order", "arguments"})
_ANSWER_KEYS = frozenset(
    {
        "must_match",
        "must_not_match",
        "must_report_artifact_path",
        "must_report_value",
        "conditional",
        "must_reach_verdict",
        "must_disclose",
        "must_label",
        "must_state_uncertainty",
        "must_source_value",
    }
)
_PROTOCOL_KEYS = frozenset({"null_argument_fidelity"})

#: Answer checks whose failure is a *hard* failure, and which therefore must
#: carry a ``because``. ``must_match``/``must_not_match`` are bare regexes over
#: prose (7.1.6's weakest row) and take a plain list, so they are excluded.
HARD_ANSWER_CHECKS: tuple[str, ...] = (
    "must_reach_verdict",
    "must_disclose",
    "must_label",
    "must_state_uncertainty",
    "must_source_value",
    "conditional",
)


class TaskError(ValueError):
    """A task or suite file is malformed. Always raised at load."""


@dataclass(frozen=True)
class Task:
    """One benchmark question, its fixtures, and its answer key."""

    id: str
    title: str
    prompt: str
    source: Path
    tags: tuple[str, ...] = ()
    max_turns: int = 12
    fixtures: tuple[str, ...] = ()
    miss_policy: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    enable: tuple[str, ...] = ()
    trajectory: Mapping[str, Any] = field(default_factory=dict)
    answer: Mapping[str, Any] = field(default_factory=dict)
    protocol: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Suite:
    """An ordered set of tasks, loaded from ``suite.yaml``."""

    id: str
    description: str
    tasks: tuple[Task, ...]
    source: Path

    def __iter__(self):
        return iter(self.tasks)

    def __len__(self) -> int:
        return len(self.tasks)

    def tagged(self, tag: str) -> tuple[Task, ...]:
        """The member tasks carrying ``tag`` -- how a single correctness
        family (``sourcing``, ``null-argument``, ...) gets read on its own."""

        return tuple(task for task in self.tasks if tag in task.tags)


def _safe_load(path: Path) -> Any:
    """S5. ``yaml.safe_load`` and nothing else; a Python-object tag raises."""

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskError(f"{path} is not valid YAML: {exc}") from exc


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TaskError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _string_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TaskError(f"{where} must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise TaskError(f"{where} must be a list of strings, found {item!r}")
    return tuple(value)


def load_task(
    path: str | Path, *, fixture_root: str | Path | None = None
) -> Task:
    """Load and fully validate one task file."""

    file = Path(path)
    payload = _require_mapping(_safe_load(file), str(file))

    unknown = set(payload) - _TASK_KEYS
    if unknown:
        raise TaskError(
            f"{file} has unknown top-level key(s) {sorted(unknown)}. A typo in "
            "a check name silently grades nothing, which is worse than a load "
            f"failure; known keys are {sorted(_TASK_KEYS)}"
        )

    task_id = payload.get("id")
    if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
        raise TaskError(
            f"{file} id must match {TASK_ID_RE.pattern} (it becomes an artifact "
            f"subdirectory name), got {task_id!r}"
        )

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise TaskError(f"{file} needs a non-empty prompt")

    fixtures = _resolve_fixture_list(payload.get("fixtures"), file, fixture_root)
    if fixture_root is not None:
        from tools.bench.fixtures import FixtureError, resolve_fixture_path

        for name in fixtures:
            try:
                resolve_fixture_path(name, Path(fixture_root))
            except FixtureError as exc:
                raise TaskError(f"{file}: {exc}") from exc

    miss_policy = payload.get("miss_policy")
    if miss_policy is not None:
        from tools.bench.fixtures import MISS_POLICIES

        if miss_policy not in MISS_POLICIES:
            raise TaskError(
                f"{file} miss_policy must be one of {list(MISS_POLICIES)}, "
                f"got {miss_policy!r}"
            )
        if miss_policy == "record":
            raise TaskError(
                f"{file} sets miss_policy: record, which is capture mode only "
                "and would make a benchmark run perform live remote calls"
            )

    env = _load_env(payload.get("env"), file)
    enable = _string_list(payload.get("enable"), f"{file} enable")
    _check_enable(enable, file)

    expect = _require_mapping(payload.get("expect") or {}, f"{file} expect")
    unknown = set(expect) - {"trajectory", "answer", "protocol"}
    if unknown:
        raise TaskError(f"{file} expect has unknown key(s) {sorted(unknown)}")

    trajectory = _load_trajectory(expect.get("trajectory"), file)
    # Derived from the task, never typed into it. See derive_turn_cap.
    if "max_turns" in payload:
        raise TaskError(
            f"{file} sets max_turns. The cap is derived from the task's own "
            "declared requirement (derive_turn_cap) so that it cannot be "
            "fitted to whichever model was measured first."
        )
    max_turns = derive_turn_cap(trajectory)
    answer = _load_answer(expect.get("answer"), file, fixture_root=fixture_root)
    protocol = _load_protocol(expect.get("protocol"), file)
    _require_an_answer_check(answer, file)

    return Task(
        id=task_id,
        title=str(payload.get("title") or task_id),
        prompt=prompt.strip(),
        source=file,
        tags=_string_list(payload.get("tags"), f"{file} tags"),
        max_turns=max_turns,
        fixtures=fixtures,
        miss_policy=miss_policy,
        env=env,
        enable=enable,
        trajectory=trajectory,
        answer=answer,
        protocol=protocol,
    )


def _require_an_answer_check(answer: Mapping[str, Any], file: Path) -> None:
    """A task must assert something about the answer.

    The answer axis is the headline one, and ``passed`` is "every hard check is
    green" -- so a task with *no* answer checks passes it vacuously, forever,
    whatever the model says. Two tasks shipped that way and a live run scored
    both as passes on a 0/0 check count, which is worse than a failure: it
    inflates a scoreboard with tasks that measure nothing.

    Trajectory and protocol are diagnostic (7.3, 7.4). They explain a headline
    number; they cannot be the whole key.
    """

    if any(answer.get(name) for name in _ANSWER_KEYS):
        return
    raise TaskError(
        f"{file} asserts nothing about the answer. The answer axis is the "
        "headline one and `passed` means every hard check is green, so a task "
        "with no answer checks passes it vacuously whatever the model says. "
        "Trajectory and protocol are diagnostic and cannot be the whole key; "
        f"add at least one of {sorted(_ANSWER_KEYS)}."
    )


#: A task may write ``fixtures: all`` for "every recorded fixture". It is the
#: right default for a task whose prompt is open-ended: a model that reaches
#: for an adjacent archive then gets a recorded answer rather than silence.
#: A live run made the alternative concrete -- one model made 38 calls across
#: 12 tools and never answered, because each undeclared tool returned nothing
#: and it kept looking for one that would.
FIXTURES_ALL = "all"


def _resolve_fixture_list(
    value: Any, file: Path, fixture_root: str | Path | None
) -> tuple[str, ...]:
    """Resolve a task's ``fixtures:`` key, expanding the ``all`` sentinel."""

    if value == FIXTURES_ALL:
        if fixture_root is None:
            return ()
        return tuple(
            sorted(path.stem for path in Path(fixture_root).glob("*.yaml"))
        )
    return _string_list(value, f"{file} fixtures")


def _load_env(value: Any, file: Path) -> dict[str, str]:
    """B7. ``KEPLER_*`` only, and string values only."""

    if value is None:
        return {}
    env = _require_mapping(value, f"{file} env")
    resolved: dict[str, str] = {}
    for key, item in env.items():
        if not isinstance(key, str) or not ENV_KEY_RE.match(key):
            raise TaskError(
                f"{file} env key {key!r} is not allowed. A task may shape "
                "Kepler's own configuration (KEPLER_*) and nothing else: it "
                "cannot set a credential, a provider base URL, or PATH."
            )
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise TaskError(
                f"{file} env[{key!r}] must be a string, got {type(item).__name__}"
            )
        resolved[key] = str(item)
    return resolved


def _check_enable(enable: Sequence[str], file: Path) -> None:
    from tools.bench.plane import DEFAULT_BLOCKED

    unknown = set(enable) - set(DEFAULT_BLOCKED)
    if unknown:
        raise TaskError(
            f"{file} enable names {sorted(unknown)}, which are not blocked by "
            f"default; the blocked set is {sorted(DEFAULT_BLOCKED)}"
        )


#: One required call may need a resolution step before it, one retry after a
#: recoverable error, the call itself, and a turn to say what it found.
REFERENCE_CALL_FACTOR = 4

#: The loop-breaker, and *only* the loop-breaker.
#:
#: A turn cap is not a measurement parameter. Its whole job is to stop a
#: pathological loop, and a run that reaches it is recorded incomplete --
#: excluded from the pass rate rather than failed (INCOMPLETE_OUTCOMES). The
#: number is uniform and sits above every task's derived floor so that it
#: cannot decide an outcome for anyone.
#:
#: It replaced per-task caps of 20/16/12/6. Those were defensible individually
#: and indefensible together: an earlier cap of 8 was chosen with no evidence,
#: and a live sweep showed one model never exceeding 5 turns while another
#: routinely needed 8-10 and was recorded incomplete for it. Any number read
#: off a transcript is a number fitted to whoever produced the transcript.
TURN_SAFETY_STOP = 20


def derive_turn_cap(trajectory: Mapping[str, Any]) -> int:
    """The turn cap a task's own declared requirement implies.

    Mechanical, and deliberately generous: it scales with how many calls the
    task *requires* (``must_call``, which the trajectory axis already grades)
    and never with how many calls a model was observed to make. A task needing
    eight tool calls gets a cap of 32 without anyone deciding that; a task
    needing one gets the safety stop.
    """

    required = len(trajectory.get("must_call", ()))
    return max(TURN_SAFETY_STOP, required * REFERENCE_CALL_FACTOR)


def _load_trajectory(value: Any, file: Path) -> dict[str, Any]:
    if value is None:
        return {}
    trajectory = _require_mapping(value, f"{file} expect.trajectory")
    unknown = set(trajectory) - _TRAJECTORY_KEYS
    if unknown:
        raise TaskError(
            f"{file} expect.trajectory has unknown key(s) {sorted(unknown)}"
        )

    from tools.registry import TOOL_FUNCTIONS

    loaded: dict[str, Any] = {}
    for key in ("must_call", "order"):
        names = _string_list(trajectory.get(key), f"{file} expect.trajectory.{key}")
        unknown_tools = set(names) - set(TOOL_FUNCTIONS)
        if unknown_tools:
            raise TaskError(
                f"{file} expect.trajectory.{key} names unregistered tool(s) "
                f"{sorted(unknown_tools)}"
            )
        loaded[key] = names

    # must_not_call is the one hard-failure check the documented format spells
    # as a bare list of names, which leaves a scoreboard entry with nothing to
    # explain itself. Both forms are accepted: a bare name, or a
    # {tool, because} mapping. The mapping is the one to reach for.
    loaded["must_not_call"] = [
        _load_must_not_call(item, file, index)
        for index, item in enumerate(trajectory.get("must_not_call") or [])
    ]

    rules = trajectory.get("arguments") or []
    if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
        raise TaskError(f"{file} expect.trajectory.arguments must be a list")
    loaded["arguments"] = [
        _load_argument_rule(rule, file, index) for index, rule in enumerate(rules)
    ]
    return loaded


def _load_must_not_call(item: Any, file: Path, index: int) -> dict[str, Any]:
    from tools.registry import TOOL_FUNCTIONS

    where = f"{file} expect.trajectory.must_not_call[{index}]"
    if isinstance(item, str):
        record = {"tool": item, "because": None}
    elif isinstance(item, Mapping):
        unknown = set(item) - {"tool", "because"}
        if unknown:
            raise TaskError(f"{where} has unknown key(s) {sorted(unknown)}")
        record = {"tool": item.get("tool"), "because": _require_because(item, where)}
    else:
        raise TaskError(
            f"{where} must be a tool name or a {{tool, because}} mapping"
        )
    if record["tool"] not in TOOL_FUNCTIONS:
        raise TaskError(f"{where} names unregistered tool {record['tool']!r}")
    return record


def _load_argument_rule(rule: Any, file: Path, index: int) -> dict[str, Any]:
    where = f"{file} expect.trajectory.arguments[{index}]"
    rule = _require_mapping(rule, where)
    unknown = set(rule) - {"tool", "quantifier", "where", "because"}
    if unknown:
        raise TaskError(f"{where} has unknown key(s) {sorted(unknown)}")

    from tools.registry import TOOL_FUNCTIONS

    tool = rule.get("tool")
    if tool not in TOOL_FUNCTIONS:
        raise TaskError(f"{where} names unregistered tool {tool!r}")

    quantifier = rule.get("quantifier", "all")
    if quantifier not in ("all", "any"):
        raise TaskError(f"{where} quantifier must be 'all' or 'any', got {quantifier!r}")

    predicates = _require_mapping(rule.get("where") or {}, f"{where}.where")
    if not predicates:
        raise TaskError(f"{where} needs at least one predicate under `where`")

    from tools.bench.fixtures import PREDICATES

    for key, spec in predicates.items():
        spec = _require_mapping(spec, f"{where}.where[{key!r}]")
        unknown_predicates = set(spec) - set(PREDICATES)
        if unknown_predicates:
            raise TaskError(
                f"{where}.where[{key!r}] uses unknown predicate(s) "
                f"{sorted(unknown_predicates)}; the vocabulary is {list(PREDICATES)}"
            )

    because = _require_because(rule, where)
    return {
        "tool": tool,
        "quantifier": quantifier,
        "where": {key: dict(spec) for key, spec in predicates.items()},
        "because": because,
    }


def _require_because(rule: Mapping[str, Any], where: str) -> str:
    """Every hard-failure check explains itself.

    The text is printed verbatim in the report next to the failure, so a
    scoreboard entry is readable without opening the suite file. This is an
    untested convention elsewhere; here the loader enforces it.
    """

    because = rule.get("because")
    if not isinstance(because, str) or not because.strip():
        raise TaskError(
            f"{where} needs a non-empty `because`: it is printed verbatim in "
            "the report beside the failure, so a hard failure explains itself"
        )
    return " ".join(because.split())


def _load_answer(
    value: Any, file: Path, *, fixture_root: str | Path | None = None
) -> dict[str, Any]:
    if value is None:
        return {}
    answer = _require_mapping(value, f"{file} expect.answer")
    unknown = set(answer) - _ANSWER_KEYS
    if unknown:
        raise TaskError(
            f"{file} expect.answer has unknown key(s) {sorted(unknown)}; known "
            f"checks are {sorted(_ANSWER_KEYS)}"
        )

    loaded: dict[str, Any] = {}
    for key in ("must_match", "must_not_match"):
        loaded[key] = _string_list(answer.get(key), f"{file} expect.answer.{key}")
        for pattern in loaded[key]:
            _compile(pattern, f"{file} expect.answer.{key}")

    artifact = answer.get("must_report_artifact_path", False)
    if not isinstance(artifact, bool):
        raise TaskError(f"{file} expect.answer.must_report_artifact_path must be a bool")
    loaded["must_report_artifact_path"] = artifact

    loaded["must_report_value"] = [
        _load_value_check(item, file, index, fixture_root=fixture_root)
        for index, item in enumerate(answer.get("must_report_value") or [])
    ]

    for key in HARD_ANSWER_CHECKS:
        loaded[key] = [
            _load_hard_check(key, item, file, index)
            for index, item in enumerate(answer.get(key) or [])
        ]
    return loaded


def _load_value_check(
    item: Any, file: Path, index: int, *, fixture_root: str | Path | None = None
) -> dict[str, Any]:
    """One ``must_report_value`` check.

    The expected number is **named, never typed**. ``source:`` cites the
    fixture field, repository data file, or tool return value the number comes
    from, and the loader resolves it -- so a key cannot drift from the archive
    it claims to transcribe, and a reader can see what the number is a
    measurement *of*. :mod:`tools.bench.sources` carries the argument.
    """

    from tools.bench.sources import SourceError, load_source, resolve_static

    where = f"{file} expect.answer.must_report_value[{index}]"
    item = _require_mapping(item, where)
    # Checked before the unknown-key sweep so the corpus gets the reason
    # rather than "unknown key ['expected']".
    if "expected" in item:
        raise TaskError(
            f"{where} carries a hand-typed `expected:`. A value check names "
            "its mechanical source instead -- `source: {fixture|dataset|"
            "tool_result: ...}` -- so the key cannot drift from the archive "
            "and no model's answer decides what is correct."
        )
    unknown = set(item) - {"name", "source", "rel_tol", "unit", "because"}
    if unknown:
        raise TaskError(f"{where} has unknown key(s) {sorted(unknown)}")
    if "source" not in item:
        raise TaskError(
            f"{where} needs a `source:` naming where the expected number comes "
            "from; see tools/bench/sources.py"
        )
    try:
        source = load_source(item["source"], where=where)
    except SourceError as exc:
        raise TaskError(str(exc)) from exc

    rel_tol = item.get("rel_tol", 0.01)
    if isinstance(rel_tol, bool) or not isinstance(rel_tol, (int, float)) or rel_tol < 0:
        raise TaskError(f"{where} rel_tol must be a non-negative number")

    check = {
        "name": str(item.get("name") or f"value_{index}"),
        "source": source,
        "rel_tol": float(rel_tol),
        "unit": item.get("unit"),
        "because": item.get("because"),
    }
    # A static source resolves now, so a corpus that cites a field the archive
    # does not have fails to load rather than failing every model at grade
    # time. `tool_result` has no value until a session exists.
    # A `dataset` source is repository data and resolves anywhere; a `fixture`
    # source needs the corpus root it is relative to, which a bare load_task()
    # may not have been given.
    if source["kind"] == "dataset" or (
        source["kind"] == "fixture" and fixture_root is not None
    ):
        try:
            check["expected"] = resolve_static(
                source, fixture_root=fixture_root, where=where
            )
        except SourceError as exc:
            raise TaskError(str(exc)) from exc
    return check


_HARD_CHECK_KEYS: Mapping[str, frozenset[str]] = {
    "must_reach_verdict": frozenset({"tool", "field", "equals", "because"}),
    "must_disclose": frozenset({"when_warning", "must_match", "because"}),
    "must_label": frozenset({"value_pattern", "near", "within_chars", "because"}),
    "must_state_uncertainty": frozenset(
        {"field", "must_match", "must_not_match", "because"}
    ),
    "must_source_value": frozenset({"pattern", "because"}),
    "conditional": frozenset(
        {"when_not_called", "when_called", "answer_must_not_match", "answer_must_match", "because"}
    ),
}

_HARD_CHECK_REQUIRED: Mapping[str, tuple[str, ...]] = {
    "must_reach_verdict": ("tool", "field", "equals"),
    "must_disclose": ("when_warning", "must_match"),
    "must_label": ("value_pattern", "near"),
    "must_state_uncertainty": ("field",),
    "must_source_value": ("pattern",),
    "conditional": (),
}

_HARD_CHECK_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "must_disclose": ("must_match",),
    "must_label": ("value_pattern",),
    "must_state_uncertainty": ("must_match", "must_not_match"),
    "must_source_value": ("pattern",),
    "conditional": ("answer_must_not_match", "answer_must_match"),
}


def _load_hard_check(
    kind: str, item: Any, file: Path, index: int
) -> dict[str, Any]:
    where = f"{file} expect.answer.{kind}[{index}]"
    item = _require_mapping(item, where)
    unknown = set(item) - _HARD_CHECK_KEYS[kind]
    if unknown:
        raise TaskError(
            f"{where} has unknown key(s) {sorted(unknown)}; known keys are "
            f"{sorted(_HARD_CHECK_KEYS[kind])}"
        )
    missing = [key for key in _HARD_CHECK_REQUIRED[kind] if key not in item]
    if missing:
        raise TaskError(f"{where} is missing {missing}")

    for key in _HARD_CHECK_PATTERNS.get(kind, ()):
        if item.get(key) is not None:
            _compile(str(item[key]), f"{where}.{key}")

    if kind == "must_reach_verdict":
        from tools.registry import TOOL_FUNCTIONS

        if item["tool"] not in TOOL_FUNCTIONS:
            raise TaskError(f"{where} names unregistered tool {item['tool']!r}")

    if kind == "conditional":
        guards = [key for key in ("when_not_called", "when_called") if key in item]
        if len(guards) != 1:
            raise TaskError(
                f"{where} needs exactly one of when_not_called / when_called"
            )
        asserts = [
            key for key in ("answer_must_not_match", "answer_must_match") if key in item
        ]
        if len(asserts) != 1:
            raise TaskError(
                f"{where} needs exactly one of answer_must_not_match / "
                "answer_must_match"
            )

    if kind == "must_label":
        within_chars = item.get("within_chars", 80)
        if isinstance(within_chars, bool) or not isinstance(within_chars, int):
            raise TaskError(f"{where} within_chars must be an integer")

    if kind == "must_state_uncertainty" and not (
        item.get("must_match") or item.get("must_not_match")
    ):
        raise TaskError(f"{where} needs must_match or must_not_match")

    record = {key: item[key] for key in item}
    record["because"] = _require_because(item, where)
    return record


def _load_protocol(value: Any, file: Path) -> dict[str, Any]:
    if value is None:
        return {}
    protocol = _require_mapping(value, f"{file} expect.protocol")
    unknown = set(protocol) - _PROTOCOL_KEYS
    if unknown:
        raise TaskError(f"{file} expect.protocol has unknown key(s) {sorted(unknown)}")

    from tools.registry import TOOL_SCHEMAS

    schemas = {schema["name"]: schema["input_schema"] for schema in TOOL_SCHEMAS}
    rules = []
    for index, rule in enumerate(protocol.get("null_argument_fidelity") or []):
        where = f"{file} expect.protocol.null_argument_fidelity[{index}]"
        rule = _require_mapping(rule, where)
        unknown = set(rule) - {"tool", "property", "because"}
        if unknown:
            raise TaskError(f"{where} has unknown key(s) {sorted(unknown)}")
        tool, prop = rule.get("tool"), rule.get("property")
        if tool not in schemas:
            raise TaskError(f"{where} names unregistered tool {tool!r}")
        declared = schemas[tool].get("properties", {}).get(prop, {}).get("type")
        types = {declared} if isinstance(declared, str) else set(declared or ())
        if "null" not in types:
            # The check asks whether the model used JSON null where the schema
            # offers it. On a property that never accepts null it would grade
            # nothing, so the suite says so at load rather than reporting a
            # free pass.
            raise TaskError(
                f"{where} {tool}.{prop} is declared {sorted(types) or 'nothing'}, "
                "which does not accept null; null_argument_fidelity only means "
                "something on a null-accepting property"
            )
        rules.append({"tool": tool, "property": prop, "because": rule.get("because")})
    return {"null_argument_fidelity": rules}


def _compile(pattern: str, where: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise TaskError(f"{where} is not a valid regular expression: {exc}") from exc


def load_suite(
    path: str | Path, *, fixture_root: str | Path | None = None
) -> Suite:
    """Load ``suite.yaml`` and every task it names, in order.

    S6: member names are bare filenames resolved under the suite directory.
    A suite that could name ``../../etc/passwd`` is a suite that can be made
    to read anything the process can.
    """

    file = Path(path)
    if file.is_dir():
        file = file / "suite.yaml"
    payload = _require_mapping(_safe_load(file), str(file))

    unknown = set(payload) - {"id", "description", "tasks"}
    if unknown:
        raise TaskError(f"{file} has unknown top-level key(s) {sorted(unknown)}")

    suite_id = payload.get("id")
    if not isinstance(suite_id, str) or not TASK_ID_RE.match(suite_id):
        raise TaskError(f"{file} id must match {TASK_ID_RE.pattern}, got {suite_id!r}")

    members = _string_list(payload.get("tasks"), f"{file} tasks")
    if not members:
        raise TaskError(f"{file} lists no tasks")

    directory = file.parent
    tasks = []
    seen: set[str] = set()
    for member in members:
        task_path = _resolve_member(member, directory, file)
        task = load_task(task_path, fixture_root=fixture_root)
        if task.id in seen:
            raise TaskError(f"{file} lists task id {task.id!r} more than once")
        seen.add(task.id)
        tasks.append(task)

    return Suite(
        id=suite_id,
        description=str(payload.get("description") or ""),
        tasks=tuple(tasks),
        source=file,
    )


def _resolve_member(member: str, directory: Path, file: Path) -> Path:
    if (
        not member
        or "/" in member
        or "\\" in member
        or ".." in member
        or Path(member).is_absolute()
    ):
        raise TaskError(
            f"{file} member {member!r} must be a bare filename in the suite "
            "directory"
        )
    path = directory / (member if member.endswith(".yaml") else f"{member}.yaml")
    if not within(path, directory):
        raise TaskError(f"{file} member {member!r} resolves outside {directory}")
    if not path.exists():
        raise TaskError(f"{file} member {member!r} does not exist at {path}")
    return path
