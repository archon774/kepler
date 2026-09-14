"""The fixture store: recorded results for the class-R tools.

``docs/working/benchmark.md`` section 5.3. A fixture file is one remote tool's
recorded results. The harness never executes a class-R tool during a run, so
these files *are* the archive as far as a benchmarked model is concerned.

Four properties matter more than the format:

* **Matching is loose on purpose.** Different models pass different radii, row
  limits and spellings for the same task, so exact-argument keying would miss
  constantly and measure nothing but argument formatting. The predicate
  vocabulary is deliberately small.
* **Every response is revalidated through the tool's own return model** (B3).
  A fixture that has drifted from the model fails at *load*, before a single
  token is spent -- not at turn 9 of a paid run.
* **A fixture carries content, never a path** (S7). It may not set ``path``,
  ``subdir`` or ``ext`` on an artifact; the shim reserves its own path inside
  the session's ``scoped_artifacts`` context and copies the recorded body
  there. That keeps ``_write_directory()``'s unvalidated ``subdir`` join and
  ``reserve_artifact_path()``'s loosely-stripped ``ext`` unreachable from
  recorded data.
* **``yaml.safe_load``, always** (S5). Fixture files are reviewed as
  adversarial input, not as test data.
"""

from __future__ import annotations

import re
import shutil
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml

from tools.config import within

__all__ = [
    "FixtureError",
    "FixtureMiss",
    "FixtureEntry",
    "FixtureFile",
    "FixtureStore",
    "MISS_POLICIES",
    "PREDICATES",
    "load_fixture_file",
    "build_error_result",
    "return_models",
]

#: What happens when no entry matches a call.
#:
#: ``error`` is the default and the honest one: the model gets a tool error
#: with code ``fixture_miss`` and the grade reflects the trajectory that
#: produced it. ``synthesize`` hands back a schema-valid empty result, for
#: tasks where an off-script call should not derail the run. ``record`` is
#: capture mode only and is never reachable from a benchmark run.
MISS_POLICIES: tuple[str, ...] = ("error", "synthesize", "record")

#: The match vocabulary. Small on purpose -- every addition is another way for
#: a fixture to be subtly wrong about which call it answers.
PREDICATES: tuple[str, ...] = (
    "equals",
    "contains",
    "one_of",
    "matches",
    "present",
    "absent",
    "is_null",
)

#: Keys a fixture may never set on a recorded artifact (S7).
_FORBIDDEN_ARTIFACT_KEYS: tuple[str, ...] = ("path", "subdir", "ext")

_CONTENT_SUBDIR = "content"


class FixtureError(ValueError):
    """A fixture file is malformed or has drifted from its tool's return
    model. Always raised at load, before a run spends anything."""


class FixtureMiss(LookupError):
    """No entry matched a call and the file's policy is ``error``."""


# ---------------------------------------------------------------------------
# Return models
# ---------------------------------------------------------------------------


def return_models(func: Callable[..., Any]) -> tuple[type, ...]:
    """The Pydantic model(s) a tool may return.

    A union return -- ``resolve_pulsar_scan`` gives ``PulsarScan |
    PulsarScanList`` -- yields every member, and a recorded response is valid
    if *any* of them accepts it. Resolved from the function's own annotation
    rather than a table here, so the tool stays the authority on its shape.
    """

    try:
        annotation = typing.get_type_hints(func).get("return")
    except Exception:  # a forward reference that no longer resolves
        return ()
    return tuple(
        member
        for member in typing.get_args(annotation) or (annotation,)
        if isinstance(member, type) and hasattr(member, "model_validate")
    )


def _validate_against_return_model(
    func: Callable[..., Any], body: Mapping[str, Any], where: str
) -> None:
    """B3. Revalidate a recorded body through the tool's own return model."""

    models = return_models(func)
    if not models:
        # A tool whose annotation is a bare list (list[CatalogSummary]) or
        # otherwise unresolvable. Class R has none today; if one appears, the
        # fixture is accepted rather than rejected on a technicality, and the
        # closed-plane test is where that gets noticed.
        return
    errors = []
    for model in models:
        try:
            model.model_validate(dict(body))
            return
        except Exception as exc:
            errors.append(f"{model.__name__}: {exc}")
    raise FixtureError(
        f"{where} does not validate against the tool's return model "
        f"({' | '.join(m.__name__ for m in models)}). This fixture has drifted "
        f"from the code it records:\n  " + "\n  ".join(errors)
    )


def build_error_result(
    func: Callable[..., Any], *, code: str, message: str
) -> Any:
    """A schema-valid error result of ``func``'s own return model.

    Used for a fixture miss and for a blocked tool. Built through the declared
    return type rather than a bare dict so the engine's ``.model_dump()``
    works and the model sees the same shape a real failure produces.
    """

    payload = {"status": "error", "errors": [{"code": code, "message": message}]}
    for model in return_models(func):
        try:
            return model.model_validate(payload)
        except Exception:
            continue
    from tools.models import ToolResult

    return ToolResult.model_validate(payload)


def build_empty_result(func: Callable[..., Any]) -> Any:
    """A schema-valid empty result, for ``miss_policy: synthesize``."""

    for payload in ({"status": "not_found", "count": 0}, {"status": "not_found"}):
        for model in return_models(func):
            try:
                return model.model_validate(payload)
            except Exception:
                continue
    from tools.models import ToolResult

    return ToolResult(status="not_found", count=0)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _match_one(rule: Mapping[str, Any], present: bool, value: Any, where: str) -> bool:
    unknown = set(rule) - set(PREDICATES)
    if unknown:
        raise FixtureError(
            f"{where} uses unknown predicate(s) {sorted(unknown)}; "
            f"the vocabulary is {list(PREDICATES)}"
        )
    for name, operand in rule.items():
        if name == "present":
            if present is not bool(operand):
                return False
            continue
        if name == "absent":
            if present is bool(operand):
                return False
            continue
        if name == "is_null":
            # Distinct from `absent`: JSON null is how an uncapped result is
            # requested, and an omitted argument means the default cap. A
            # fixture that conflated them would answer the wrong call.
            if (value is None and present) is not bool(operand):
                return False
            continue
        if not present:
            return False
        if name == "equals":
            if value != operand:
                return False
        elif name == "contains":
            if not isinstance(value, str) or operand.lower() not in value.lower():
                return False
        elif name == "one_of":
            if value not in operand:
                return False
        elif name == "matches":
            if not isinstance(value, str) or re.match(operand, value) is None:
                return False
    return True


@dataclass(frozen=True)
class FixtureEntry:
    """One recorded (match, response) pair."""

    id: str
    match: Mapping[str, Mapping[str, Any]]
    response: Mapping[str, Any]

    def matches(self, arguments: Mapping[str, Any]) -> bool:
        return all(
            _match_one(
                rule, key in arguments, arguments.get(key), f"entry {self.id!r} [{key}]"
            )
            for key, rule in self.match.items()
        )

    @property
    def is_default(self) -> bool:
        """A trailing ``{match: {}}`` entry is the per-tool default."""

        return not self.match


@dataclass(frozen=True)
class FixtureFile:
    """One class-R tool's recorded results."""

    tool: str
    entries: tuple[FixtureEntry, ...]
    miss_policy: str = "error"
    recorded_on: str | None = None
    source: Path | None = None
    content_root: Path | None = None

    def select(self, arguments: Mapping[str, Any]) -> FixtureEntry | None:
        """First match wins, in file order."""

        for entry in self.entries:
            if entry.matches(arguments):
                return entry
        return None


def load_fixture_file(
    path: str | Path,
    *,
    root: str | Path | None = None,
    functions: Mapping[str, Callable[..., Any]] | None = None,
) -> FixtureFile:
    """Load and fully validate one fixture file.

    Everything checkable is checked here rather than at match time: the tool
    is registered, the miss policy is one of the three, every predicate is in
    the vocabulary, no artifact carries a forbidden key, every ``content_ref``
    resolves inside the fixture root, and every response validates through the
    tool's own return model. A paid run must not discover a typo at turn 9.
    """

    file = Path(path)
    fixture_root = Path(root) if root is not None else file.parent
    try:
        # S5: safe_load only. A `!!python/object` tag raises rather than
        # constructing anything.
        payload = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FixtureError(f"{file} is not valid YAML: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise FixtureError(f"{file} must hold a mapping at the top level")

    unknown = set(payload) - {"tool", "miss_policy", "recorded_on", "entries"}
    if unknown:
        raise FixtureError(f"{file} has unknown top-level key(s) {sorted(unknown)}")

    tool = payload.get("tool")
    if not isinstance(tool, str) or not tool:
        raise FixtureError(f"{file} must name the tool it records")

    if functions is None:
        from tools.registry import TOOL_FUNCTIONS

        functions = TOOL_FUNCTIONS
    if tool not in functions:
        raise FixtureError(
            f"{file} records {tool!r}, which is not a registered tool"
        )

    miss_policy = payload.get("miss_policy", "error")
    if miss_policy not in MISS_POLICIES:
        raise FixtureError(
            f"{file} miss_policy must be one of {list(MISS_POLICIES)}, "
            f"got {miss_policy!r}"
        )

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
        raise FixtureError(f"{file} entries must be a list")

    entries = tuple(
        _load_entry(entry, file, index, functions[tool], fixture_root)
        for index, entry in enumerate(raw_entries)
    )
    for entry in entries[:-1]:
        if entry.is_default:
            raise FixtureError(
                f"{file} entry {entry.id!r} has an empty match but is not last; "
                "a default entry would shadow every entry after it"
            )

    return FixtureFile(
        tool=tool,
        entries=entries,
        miss_policy=miss_policy,
        recorded_on=payload.get("recorded_on"),
        source=file,
        content_root=fixture_root / _CONTENT_SUBDIR,
    )


def _load_entry(
    entry: Any,
    file: Path,
    index: int,
    func: Callable[..., Any],
    fixture_root: Path,
) -> FixtureEntry:
    where = f"{file}[{index}]"
    if not isinstance(entry, Mapping):
        raise FixtureError(f"{where} must be a mapping")
    unknown = set(entry) - {"id", "match", "response"}
    if unknown:
        raise FixtureError(f"{where} has unknown key(s) {sorted(unknown)}")

    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        raise FixtureError(f"{where} needs a non-empty string id")
    where = f"{file}[{entry_id}]"

    match = entry.get("match") or {}
    if not isinstance(match, Mapping):
        raise FixtureError(f"{where} match must be a mapping")
    for key, rule in match.items():
        if not isinstance(rule, Mapping):
            raise FixtureError(
                f"{where} match[{key!r}] must be a mapping of predicates, "
                f"e.g. {{equals: ...}}"
            )
        # Evaluate the vocabulary check now rather than at match time.
        _match_one(rule, False, None, f"{where} match[{key!r}]")

    response = entry.get("response")
    if not isinstance(response, Mapping):
        raise FixtureError(f"{where} response must be a mapping")

    _check_artifacts(response, where, fixture_root)
    _validate_against_return_model(func, _validation_body(response), where)

    return FixtureEntry(id=entry_id, match=dict(match), response=dict(response))


def _artifact_bodies(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bodies: list[Mapping[str, Any]] = []
    single = response.get("artifact")
    if isinstance(single, Mapping):
        bodies.append(single)
    for item in response.get("artifacts") or ():
        if isinstance(item, Mapping):
            bodies.append(item)
    return bodies


def _check_artifacts(
    response: Mapping[str, Any], where: str, fixture_root: Path
) -> None:
    """S7 and S6, at load."""

    for body in _artifact_bodies(response):
        for key in _FORBIDDEN_ARTIFACT_KEYS:
            if key in body:
                raise FixtureError(
                    f"{where} artifact sets {key!r}. A fixture carries content, "
                    "never a path: the replay shim reserves its own path inside "
                    "the session's artifact scope, so a recorded path could only "
                    "be a way to write outside it."
                )
        ref = body.get("content_ref")
        if ref is None:
            continue
        if not isinstance(ref, str) or not ref:
            raise FixtureError(f"{where} content_ref must be a non-empty string")
        # S6: a bare name, resolved under the fixture root's content directory.
        # Rejected before resolution, then re-checked for containment after.
        if "/" in ref or "\\" in ref or ref in (".", "..") or Path(ref).is_absolute():
            raise FixtureError(
                f"{where} content_ref {ref!r} must be a bare filename under "
                f"{_CONTENT_SUBDIR}/"
            )
        content_root = fixture_root / _CONTENT_SUBDIR
        resolved = content_root / ref
        if not within(resolved, content_root):
            raise FixtureError(
                f"{where} content_ref {ref!r} resolves outside {content_root}"
            )
        if not resolved.exists():
            raise FixtureError(
                f"{where} content_ref {ref!r} does not exist at {resolved}"
            )


def _validation_body(response: Mapping[str, Any]) -> dict[str, Any]:
    """The response as the return model will see it once artifacts are given
    their synthesized paths.

    ``path`` is required on ``ArtifactRef`` and a fixture may not set it, so a
    placeholder stands in for validation only. This is why B3 catches drift in
    every *other* field without S7 having to be relaxed.
    """

    body = {
        key: value for key, value in response.items() if key not in ("artifact", "artifacts")
    }
    single = response.get("artifact")
    if isinstance(single, Mapping):
        body["artifact"] = _placeholder_artifact(single)
    if response.get("artifacts"):
        body["artifacts"] = [
            _placeholder_artifact(item) if isinstance(item, Mapping) else item
            for item in response["artifacts"]
        ]
    return body


def _placeholder_artifact(body: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        key: value for key, value in body.items() if key != "content_ref"
    }
    record.setdefault("format", "ecsv")
    record["path"] = "<synthesized at replay>"
    return record


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


@dataclass
class FixtureStore:
    """The fixture files one task is allowed to draw on, plus its miss policy.

    Also the run's fixture-miss counter: a suite with a high miss rate is
    measuring its own coverage rather than the model, and the report says so
    in those words.
    """

    files: Mapping[str, FixtureFile] = field(default_factory=dict)
    miss_policy_override: str | None = None
    task_id: str = "task"
    misses: list[dict[str, Any]] = field(default_factory=list)
    hits: int = 0

    @classmethod
    def load(
        cls,
        names: Iterable[str],
        *,
        root: str | Path,
        task_id: str = "task",
        miss_policy: str | None = None,
        functions: Mapping[str, Callable[..., Any]] | None = None,
    ) -> "FixtureStore":
        """Load the named fixture files from ``root``.

        S6: ``names`` are bare names resolved as ``<root>/<name>.yaml``.
        Anything carrying a path separator, a ``..`` segment or an absolute
        prefix is rejected *before* resolution, and the resolved path is then
        re-checked for containment.
        """

        fixture_root = Path(root)
        files: dict[str, FixtureFile] = {}
        for name in names:
            path = resolve_fixture_path(name, fixture_root)
            loaded = load_fixture_file(path, root=fixture_root, functions=functions)
            files[loaded.tool] = loaded
        if miss_policy is not None and miss_policy not in MISS_POLICIES:
            raise FixtureError(
                f"miss_policy must be one of {list(MISS_POLICIES)}, got "
                f"{miss_policy!r}"
            )
        return cls(
            files=files, miss_policy_override=miss_policy, task_id=task_id
        )

    @property
    def miss_rate(self) -> float:
        total = self.hits + len(self.misses)
        return len(self.misses) / total if total else 0.0

    def replay(self, tool: str, arguments: Mapping[str, Any]) -> Any:
        """Answer one class-R call from the recorded entries."""

        from tools.registry import TOOL_FUNCTIONS

        func = TOOL_FUNCTIONS[tool]
        file = self.files.get(tool)
        entry = file.select(arguments) if file is not None else None
        if entry is None:
            return self._miss(tool, func, arguments, file)

        self.hits += 1
        return _materialize(func, entry, file, task_id=self.task_id)

    def _miss(
        self,
        tool: str,
        func: Callable[..., Any],
        arguments: Mapping[str, Any],
        file: FixtureFile | None,
    ) -> Any:
        policy = self.miss_policy_override or (
            file.miss_policy if file is not None else "error"
        )
        self.misses.append({"tool": tool, "arguments": dict(arguments)})
        if policy == "synthesize":
            return build_empty_result(func)
        detail = (
            "no fixture file is declared for this tool in the task"
            if file is None
            else "no recorded entry matches these arguments"
        )
        return build_error_result(
            func,
            code="fixture_miss",
            message=(
                f"{tool} is replayed from recorded fixtures in this benchmark "
                f"run and {detail}. Nothing was queried."
            ),
        )


def resolve_fixture_path(name: str, root: Path) -> Path:
    """S6. A bare fixture name resolved under ``root``."""

    if (
        not name
        or "/" in name
        or "\\" in name
        or ".." in name
        or Path(name).is_absolute()
    ):
        raise FixtureError(
            f"fixture reference {name!r} must be a bare name; it is resolved "
            f"as <fixture-root>/{name}.yaml"
        )
    path = root / f"{name}.yaml"
    if not within(path, root):
        raise FixtureError(f"fixture {name!r} resolves outside {root}")
    if not path.exists():
        raise FixtureError(f"fixture {name!r} does not exist at {path}")
    return path


def _materialize(
    func: Callable[..., Any],
    entry: FixtureEntry,
    file: FixtureFile | None,
    *,
    task_id: str,
) -> Any:
    """Turn a recorded response into the tool's own return model.

    S7 happens here: each recorded artifact gets a path the harness reserves
    inside the session's ``scoped_artifacts`` context, and the recorded body
    (if any) is copied there. The fixture never chooses where a byte lands.
    """

    from tools import artifacts as artifacts_module

    body = {
        key: value
        for key, value in entry.response.items()
        if key not in ("artifact", "artifacts")
    }

    def synthesize(recorded: Mapping[str, Any]) -> dict[str, Any]:
        fmt = str(recorded.get("format") or "ecsv")
        reserved = artifacts_module.reserve_artifact_path(
            f"{task_id}_{file.tool if file else 'fixture'}", ext=fmt
        )
        ref = recorded.get("content_ref")
        if ref and file is not None and file.content_root is not None:
            shutil.copyfile(file.content_root / ref, reserved)
        else:
            # No recorded body: the row counts and columns are still real, so
            # the artifact exists and is empty rather than being a dangling
            # path in the answer. must_report_artifact_path checks the path
            # against the manifest, and a path to nothing would still pass it.
            reserved.write_text("", encoding="utf-8")
        record = {
            key: value for key, value in recorded.items() if key != "content_ref"
        }
        record["format"] = fmt
        record["path"] = str(reserved)
        return record

    single = entry.response.get("artifact")
    if isinstance(single, Mapping):
        body["artifact"] = synthesize(single)
    if entry.response.get("artifacts"):
        body["artifacts"] = [
            synthesize(item) if isinstance(item, Mapping) else item
            for item in entry.response["artifacts"]
        ]

    for model in return_models(func):
        try:
            return model.model_validate(body)
        except Exception:
            continue
    raise FixtureError(
        f"entry {entry.id!r} no longer validates against {func.__name__}'s "
        "return model at replay time; this should have been caught at load"
    )
