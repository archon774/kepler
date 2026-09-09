"""Agent-session manifest helpers for ``tools.runner``."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from tools.config import artifact_directory

if TYPE_CHECKING:
    from tools.llm.types import ProtocolFault

__all__ = [
    "AgentSession",
    "SESSION_MANIFEST_NAME",
    "make_cache_key",
    "new_session_id",
    "list_session_manifests",
    "read_session_manifest",
]

SESSION_MANIFEST_NAME = "session_manifest.json"
SESSION_SCHEMA_VERSION = 1
SESSION_ROOT_SUBDIR = "sessions"
_TEXT_LIMIT = 4000


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
    turns: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    protocol_faults: list[dict[str, Any]] = field(default_factory=list)

    @property
    def artifact_subdir(self) -> str:
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
    ) -> None:
        self.current_turn = turn
        self.turns.append(
            {
                "turn": turn,
                "stop_reason": stop_reason,
                "assistant_text": _bounded_text(assistant_text),
                "tool_call_sequences": tool_call_sequences,
            }
        )

    def record_fault(self, *, turn: int, fault: "ProtocolFault") -> None:
        """Append a turn-stamped protocol-fault record.

        Faults come from pre-dispatch validation (S8) and from the model
        adapters. ``SESSION_SCHEMA_VERSION`` stays at 1 for now: the key is
        additive, and the bump to 2 lands with the rest of the v2 payload.
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_manifest(), indent=2, sort_keys=True) + "\n")
        return path

    def to_manifest(self) -> dict[str, Any]:
        cache_entries = self._cache_entries()
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "outcome": self.outcome,
            "user_message": self.user_message,
            "model": self.model,
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
                "Tool result previews and full payloads are intentionally omitted; "
                "inspect the referenced artifact paths for complete data."
            ],
        }

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
    return json.loads(manifest_path.read_text(encoding="utf-8"))
