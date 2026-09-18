"""Agent-session manifest helpers for ``tools.agent``.

The manifest is schema version 2 (``docs/benchmarking/harness.md`` section 8).
Version 2 is *additive over version 1*: every key version 1 wrote is still
written with the same meaning, so a recorded v1 manifest still reads. The
new keys are the ones a benchmark needs and a console run does not --
token accounting, per-turn latency, and the backend identity.

Readers must treat an absent key as ``None``, never as ``0``: a provider
that did not report cache tokens did not report zero of them, and folding
the two together turns "unknown" into a measurement.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from tools.config import artifact_directory

if TYPE_CHECKING:
    from tools.llm.types import ProtocolFault, Usage

__all__ = [
    "AgentSession",
    "backend_record",
    "SESSION_MANIFEST_NAME",
    "make_cache_key",
    "new_session_id",
    "list_session_manifests",
    "read_session_manifest",
    "USAGE_FIELDS",
]

SESSION_MANIFEST_NAME = "session_manifest.json"
SESSION_SCHEMA_VERSION = 2
SESSION_ROOT_SUBDIR = "sessions"
_TEXT_LIMIT = 4000
_MAX_SESSION_MANIFEST_BYTES = 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat()


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so manifests never depend on custom objects."""

    return json.loads(json.dumps(value, default=str))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_text(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if len(value) <= _TEXT_LIMIT:
        return value
    return value[: _TEXT_LIMIT - 15] + "... [truncated]"


def _validated_subdir(value: str | Path) -> str:
    """Validate an artifact-subdirectory override the way ``scoped_artifacts``
    validates its argument, and for the same reason: the value becomes a path
    join under the artifact root, so it must stay relative and may not climb
    out. Rejecting it here gives a caller the error at construction rather
    than at the first artifact write, several turns in.
    """

    relative = Path(value)
    if not str(value) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(
            f"artifact_subdir must be a relative subdirectory: {value!r}"
        )
    return str(relative)


def new_session_id() -> str:
    """Return a sortable, filesystem-safe session id."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid.uuid4().hex[:12]}"


def make_cache_key(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return the stable cache key used for repeated tool calls in one session."""

    payload = {"tool": tool_name, "arguments": arguments}
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _artifact_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    artifact = result.get("artifact")
    if artifact:
        records.append(_artifact_record(artifact))
    for item in result.get("artifacts") or []:
        records.append(_artifact_record(item))
    return records


def _artifact_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"path": str(value)}
    return {
        key: _json_safe(value[key])
        for key in ("path", "format", "row_count", "columns")
        if key in value and value[key] is not None
    }


#: The token classes recorded per turn and rolled up into ``usage_totals``.
#: They stay separate rather than being summed into one "input" number:
#: SYSTEM_PROMPT plus 55 tool schemas is a large fixed prefix resent every
#: turn, so a backend that caches it and one that does not are doing visibly
#: different amounts of work at identical behaviour.
USAGE_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)


def _usage_record(usage: "Usage | None") -> dict[str, int | None] | None:
    """Serialize one turn's :class:`~tools.llm.types.Usage`, or ``None``.

    A backend that reported no usage at all records ``None`` for the whole
    turn -- not a dict of zeros, which would read as "it cost nothing".
    """

    if usage is None:
        return None
    return {name: getattr(usage, name, None) for name in USAGE_FIELDS}


def _usage_totals(turns: list[dict[str, Any]]) -> dict[str, int | None]:
    """Sum each token class across turns, keeping "not reported" distinct
    from zero.

    A class stays ``None`` until some turn reports it; from then on the total
    is the sum of the turns that did. A provider reporting cache reads on two
    turns out of five has a real total over those two, and reporting it as
    ``None`` would be as wrong as reporting the other three as zero.
    """

    totals: dict[str, int | None] = {name: None for name in USAGE_FIELDS}
    for turn in turns:
        usage = turn.get("usage")
        if not usage:
            continue
        for name in USAGE_FIELDS:
            value = usage.get(name)
            if value is None:
                continue
            totals[name] = (totals[name] or 0) + value
    return totals


def _base_url_host(backend: Any) -> str | None:
    """The host a backend talks to, with any userinfo stripped (S4).

    ``BaseHTTPBackend`` stores the base URL privately; the Anthropic SDK
    adapter has none of its own and records ``None``. Only the host is kept:
    the path carries nothing worth recording and a URL can carry a credential
    in its userinfo, which must never reach a manifest even though the port
    never puts one there.
    """

    raw = getattr(backend, "_base_url", None)
    if not raw:
        return None
    return urllib.parse.urlparse(str(raw)).hostname


def backend_record(backend: Any) -> dict[str, Any]:
    """Describe a :class:`~tools.llm.base.ModelBackend` for the manifest.

    Capabilities are recorded alongside the spec because they are what makes
    two runs comparable or not: a model reached through the Gemini OpenAPI
    subset is not being asked the same question as one reached through JSON
    Schema, and ``schema_dialect`` is where that shows.
    """

    spec = str(getattr(backend, "spec", "") or "")
    provider, _, model = spec.partition("/")
    capabilities = getattr(backend, "capabilities", None)
    record = {
        "spec": spec or None,
        "provider": provider or None,
        "model": model or None,
        "base_url_host": _base_url_host(backend),
        "capabilities": (
            dataclasses.asdict(capabilities)
            if dataclasses.is_dataclass(capabilities)
            else None
        ),
    }
    # A benchmark claims determinism from temperature 0. Where a provider
    # refuses the parameter that claim does not hold, and a record that stayed
    # silent would overstate its own reproducibility. Absent on backends that
    # do not report it -- never assumed true.
    supported = getattr(backend, "temperature_supported", None)
    if supported is not None:
        record["temperature_supported"] = bool(supported)
    return record


def _message_records(values: Any) -> list[dict[str, str]]:
    if not values:
        return []
    records: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, dict):
            record = {}
            if value.get("code") is not None:
                record["code"] = str(value["code"])
            if value.get("message") is not None:
                record["message"] = str(value["message"])
            if not record:
                record["message"] = json.dumps(value, default=str, sort_keys=True)
            records.append(record)
        else:
            records.append({"message": str(value)})
    return records


@dataclass
class AgentSession:
    """Small persisted trace for one bounded agent loop."""

    user_message: str
    model: str
    max_turns: int
    system: str
    session_id: str = field(default_factory=new_session_id)
    created_at: str = field(default_factory=_utc_iso)
    updated_at: str = field(default_factory=_utc_iso)
    completed_at: str | None = None
    outcome: Literal["running", "end_turn", "max_turns", "error"] = "running"
    current_turn: int | None = None
    resumable: bool = True
    history: list[dict[str, Any]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    protocol_faults: list[dict[str, Any]] = field(default_factory=list)
    #: Where this session's artifacts and manifest land, relative to the
    #: artifact root. ``None`` keeps the default ``sessions/<session_id>``.
    #: The benchmark harness sets it so a run's artifacts sit beside its run
    #: record, which is what makes a reported artifact path still resolvable
    #: when grading runs later.
    artifact_subdir_override: str | None = None
    #: ``{spec, provider, model, base_url_host, capabilities}`` for the backend
    #: that drove this session, or ``None`` when nothing set it. Recorded
    #: because two models answering identically through different schema
    #: dialects are not the same observation.
    backend: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.artifact_subdir_override is not None:
            self.artifact_subdir_override = _validated_subdir(
                self.artifact_subdir_override
            )

    @property
    def artifact_subdir(self) -> str:
        if self.artifact_subdir_override is not None:
            return self.artifact_subdir_override
        return f"{SESSION_ROOT_SUBDIR}/{self.session_id}"

    @property
    def directory(self) -> Path:
        return artifact_directory() / self.artifact_subdir

    @property
    def manifest_path(self) -> Path:
        return self.directory / SESSION_MANIFEST_NAME

    def record_turn(
        self,
        *,
        turn: int,
        stop_reason: str | None,
        assistant_text: str,
        tool_call_sequences: list[int],
        usage: "Usage | None" = None,
        latency_ms: float | None = None,
        raw_stop_reason: str | None = None,
    ) -> None:
        """Append one turn record.

        ``stop_reason`` is the *normalized* value -- one of
        ``tools.llm.types.STOP_REASONS`` -- and ``raw_stop_reason`` is the
        provider's own string. Version 1 stored ``raw or normalized`` in the
        single ``stop_reason`` key, which lost exactly the distinction
        ``StopReason`` exists to make: ``length``, ``MAX_TOKENS`` and
        ``max_tokens`` all mean the ceiling was hit, and only the normalized
        value says so without a per-provider lookup.

        The three new arguments are keyword-only and defaulted, so every
        existing caller is unaffected.
        """

        self.current_turn = turn
        self.turns.append(
            {
                "turn": turn,
                "stop_reason": stop_reason,
                "raw_stop_reason": raw_stop_reason,
                "assistant_text": _bounded_text(assistant_text),
                "tool_call_sequences": tool_call_sequences,
                "latency_ms": latency_ms,
                "usage": _usage_record(usage),
            }
        )

    def record_fault(self, *, turn: int, fault: "ProtocolFault") -> None:
        """Append a turn-stamped protocol-fault record.

        Faults come from pre-dispatch validation (S8) and from the model
        adapters. The protocol grader counts these by ``type``.
        """

        self.protocol_faults.append(
            {
                "turn": turn,
                "type": fault.type,
                "detail": fault.detail,
                "tool_name": fault.tool_name,
                "call_id": fault.call_id,
            }
        )

    def record_tool_call(
        self,
        *,
        turn: int,
        tool_use_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        cache_key: str,
        cache_hit: bool,
        result: dict[str, Any],
    ) -> int:
        self.current_turn = turn
        sequence = len(self.tool_calls) + 1
        record = {
            "sequence": sequence,
            "turn": turn,
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "arguments": _json_safe(arguments),
            "cache_key_sha256": _sha256(cache_key),
            "cache_hit": cache_hit,
            "status": result.get("status"),
            "count": result.get("count"),
            "artifacts": _artifact_records(result),
            "warnings": _message_records(result.get("warnings")),
            "errors": _message_records(result.get("errors")),
        }
        self.tool_calls.append(record)
        return sequence

    def save(
        self,
        *,
        outcome: Literal["running", "end_turn", "max_turns", "error"] | None = None,
        current_turn: int | None = None,
    ) -> Path:
        if outcome is not None:
            self.outcome = outcome
            if outcome != "running" and self.completed_at is None:
                self.completed_at = _utc_iso()
        if current_turn is not None:
            self.current_turn = current_turn
        self.updated_at = _utc_iso()

        path = self.manifest_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        _write_private_json(path, self.to_manifest())
        return path

    def to_manifest(self) -> dict[str, Any]:
        cache_entries = self._cache_entries()
        manifest = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "outcome": self.outcome,
            "resumable": self.resumable,
            "user_message": self.user_message,
            "model": self.model,
            "backend": self.backend,
            "usage_totals": _usage_totals(self.turns),
            "max_turns": self.max_turns,
            "current_turn": self.current_turn,
            "system_prompt_sha256": _sha256(self.system),
            "artifact_directory": str(self.directory),
            "manifest_path": str(self.manifest_path),
            "turns": self.turns,
            "tool_call_count": len(self.tool_calls),
            "cache_entry_count": len(cache_entries),
            "tool_calls": self.tool_calls,
            "call_cache": cache_entries,
            "protocol_faults": self.protocol_faults,
            "notes": [
                "Tool-call diagnostic previews omit full payloads; the neutral "
                "conversation history retains them so a session can resume. "
                "Session manifests may therefore contain sensitive prompts and "
                "tool payloads."
            ],
        }
        if self.history:
            manifest["history"] = self.history
        return manifest

    def _cache_entries(self) -> list[dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for call in self.tool_calls:
            key = call["cache_key_sha256"]
            entry = entries.setdefault(
                key,
                {
                    "cache_key_sha256": key,
                    "tool_name": call["tool_name"],
                    "arguments": call["arguments"],
                    "first_sequence": call["sequence"],
                    "last_sequence": call["sequence"],
                    "use_count": 0,
                    "cache_hit_count": 0,
                    "status": call["status"],
                    "count": call["count"],
                    "artifacts": call["artifacts"],
                    "warnings": call["warnings"],
                    "errors": call["errors"],
                },
            )
            entry["last_sequence"] = call["sequence"]
            entry["use_count"] += 1
            if call["cache_hit"]:
                entry["cache_hit_count"] += 1
        return list(entries.values())


def list_session_manifests(directory: str | Path | None = None) -> list[Path]:
    """Return known session manifest paths below the artifact directory."""

    root = artifact_directory(directory) / SESSION_ROOT_SUBDIR
    if not root.exists():
        return []
    return sorted(root.glob(f"*/{SESSION_MANIFEST_NAME}"))


def read_session_manifest(path: str | Path) -> dict[str, Any]:
    """Read a session manifest file or session directory."""

    manifest_path = Path(path).expanduser()
    if manifest_path.is_dir():
        manifest_path = manifest_path / SESSION_MANIFEST_NAME
    if manifest_path.stat().st_size > _MAX_SESSION_MANIFEST_BYTES:
        raise ValueError("session manifest is too large")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    """Atomically replace a session manifest with owner-only permissions."""

    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
