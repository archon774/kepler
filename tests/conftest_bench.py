"""Shared builders for synthetic run directories in the bench grader tests.

Not a conftest: imported explicitly, so a reader of one test file can see
where its evidence comes from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.bench.tasks import load_task


def write_task(tmp_path: Path, body: str, name: str = "t.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return load_task(path)


MINIMAL_TASK = "id: a-task\ntitle: A task\nprompt: Do the thing.\n"


def manifest(
    *,
    outcome: str = "end_turn",
    tool_calls: Sequence[Mapping[str, Any]] = (),
    turns: Sequence[Mapping[str, Any]] = (),
    protocol_faults: Sequence[Mapping[str, Any]] = (),
    usage_totals: Mapping[str, Any] | None = None,
    backend: Mapping[str, Any] | None = None,
    schema_version: int = 2,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "session_id": "s",
        "outcome": outcome,
        "model": "m",
        "max_turns": 8,
        "tool_calls": [dict(call) for call in tool_calls],
        "tool_call_count": len(tool_calls),
        "cache_entry_count": len({call.get("tool_name") for call in tool_calls}),
        "call_cache": [],
        "turns": [dict(turn) for turn in turns],
        "protocol_faults": [dict(fault) for fault in protocol_faults],
    }
    if schema_version >= 2:
        payload["usage_totals"] = usage_totals
        payload["backend"] = backend
    return payload


def call(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    sequence: int = 1,
    status: str = "ok",
    cache_hit: bool = False,
    artifacts: Sequence[Mapping[str, Any]] = (),
    warnings: Sequence[Mapping[str, Any]] = (),
    errors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "turn": 1,
        "tool_use_id": f"c{sequence}",
        "tool_name": name,
        "arguments": dict(arguments or {}),
        "cache_key_sha256": "0" * 64,
        "cache_hit": cache_hit,
        "status": status,
        "count": None,
        "artifacts": [dict(a) for a in artifacts],
        "warnings": [dict(w) for w in warnings],
        "errors": [dict(e) for e in errors],
    }


def finished(name: str, result: Mapping[str, Any], *, duration_ms: float = 1.0):
    return {
        "event": "ToolCallFinished",
        "call_id": "c1",
        "name": name,
        "result": dict(result),
        "artifacts": [],
        "duration_ms": duration_ms,
    }


def run_directory(
    tmp_path: Path,
    *,
    answer: str = "",
    manifest_body: Mapping[str, Any] | None = None,
    events: Sequence[Mapping[str, Any]] = (),
    error: str | None = None,
) -> Path:
    directory = tmp_path / "r1"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "answer.txt").write_text(answer, encoding="utf-8")
    if manifest_body is not None:
        (directory / "session_manifest.json").write_text(
            json.dumps(manifest_body), encoding="utf-8"
        )
    with (directory / "events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    if error is not None:
        (directory / "error.txt").write_text(error, encoding="utf-8")
    return directory
