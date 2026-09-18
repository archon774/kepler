"""Saved-session history reconstruction for the Kepler console."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from tools.llm.types import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from tools.models import ArtifactMetadata
from tools.workspace import describe_session, list_sessions

__all__ = ["SessionBrowser", "history_from_manifest"]

_MAX_HISTORY_MESSAGES = 128
_MAX_HISTORY_BLOCKS = 256
_MAX_HISTORY_BYTES = 256 * 1024
_MAX_HISTORY_FIELD_BYTES = 64 * 1024
_MAX_ARGUMENT_DEPTH = 8


class SessionBrowser(ModalScreen[Path | None]):
    """Select a saved session without involving the model engine."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    CSS = """
    SessionBrowser {
        align: center middle;
    }

    #session-browser {
        width: 90%;
        height: auto;
        max-height: 90%;
        border: round $accent;
        padding: 1 2;
    }

    #session-list {
        height: auto;
        max-height: 1fr;
    }
    """

    def __init__(self, sessions: tuple[ArtifactMetadata, ...] | None = None) -> None:
        super().__init__()
        self.sessions = tuple(list_sessions() if sessions is None else sessions)
        self.manifests = tuple(_describe_session(session) for session in self.sessions)

    def compose(self) -> ComposeResult:
        """Build a compact list of saved session summaries."""

        with Vertical(id="session-browser"):
            if not self.sessions:
                yield Static("No saved sessions found.")
                return
            yield OptionList(
                *(
                    _session_label(session, manifest)
                    for session, manifest in zip(self.sessions, self.manifests)
                ),
                id="session-list",
                markup=False,
            )

    def on_mount(self) -> None:
        """Title the dialog and place keyboard selection on the session list."""

        self.query_one("#session-browser").border_title = "Sessions"
        if self.sessions:
            self.query_one("#session-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the selected manifest path to the owning application."""

        self.dismiss(Path(self.sessions[event.option_index].file.path))


def _describe_session(session: ArtifactMetadata) -> Mapping[str, Any] | None:
    """Read one manifest while keeping an unreadable row visible to the user."""

    try:
        manifest = describe_session(session.file.path)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, Mapping) else None


def _session_label(
    session: ArtifactMetadata, manifest: Mapping[str, Any] | None
) -> str:
    """Format the manifest fields needed to identify one saved session."""

    if manifest is None:
        return f"{Path(session.file.path).parent.name} · unreadable manifest"
    session_id = manifest.get("session_id", Path(session.file.path).parent.name)
    timestamp = manifest.get("created_at", "unknown time")
    model = manifest.get("model", "unknown model")
    outcome = manifest.get("outcome", "unknown outcome")
    turns = manifest.get("turns")
    turn_count = len(turns) if isinstance(turns, list) else 0
    return f"{session_id} · {timestamp} · {model} · {outcome} · {turn_count} turns"


def history_from_manifest(manifest: Mapping[str, Any]) -> tuple[Message, ...]:
    """Return the faithfully recorded text history from one session manifest."""

    if not isinstance(manifest, Mapping):
        raise ValueError("session manifest is not an object")
    resumable = manifest.get("resumable", True)
    if not isinstance(resumable, bool):
        raise ValueError("session manifest has an invalid resumable flag")
    if not resumable:
        raise ValueError("session manifest is not resumable")
    user_message = manifest.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise ValueError("session manifest has no user message")

    turns = manifest.get("turns")
    if not isinstance(turns, list):
        raise ValueError("session manifest has no recorded turns")

    if "history" in manifest:
        return tuple(_history_from_records(manifest["history"]))

    history = []
    history.append(Message(role="user", blocks=(TextBlock(text=user_message),)))
    for turn in turns:
        if not isinstance(turn, Mapping):
            raise ValueError("session manifest contains an invalid turn")
        assistant_text = turn.get("assistant_text")
        if isinstance(assistant_text, str) and assistant_text:
            history.append(
                Message(role="assistant", blocks=(TextBlock(text=assistant_text),))
            )
    return tuple(history)


def _history_from_records(value: Any) -> list[Message]:
    """Restore a complete neutral conversation from a current manifest."""

    if not isinstance(value, list):
        raise ValueError("session manifest contains an invalid history")
    if len(value) > _MAX_HISTORY_MESSAGES:
        raise ValueError("session manifest history is too large")
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("session manifest contains an invalid history") from exc
    if len(serialized.encode("utf-8")) > _MAX_HISTORY_BYTES:
        raise ValueError("session manifest history is too large")

    history: list[Message] = []
    block_count = 0
    known_tools = _known_tool_names()
    for record in value:
        if not isinstance(record, Mapping):
            raise ValueError("session manifest contains an invalid history entry")
        role = record.get("role")
        blocks = record.get("blocks")
        if role not in {"user", "assistant"} or not isinstance(blocks, list):
            raise ValueError("session manifest contains an invalid history entry")
        restored_blocks = []
        for block in blocks:
            block_count += 1
            if block_count > _MAX_HISTORY_BLOCKS:
                raise ValueError("session manifest history is too large")
            if not isinstance(block, Mapping):
                raise ValueError("session manifest contains an invalid history block")
            block_type = block.get("type")
            if block_type == "text" and isinstance(block.get("text"), str):
                restored_blocks.append(
                    TextBlock(text=_bounded_history_text(block["text"]))
                )
            elif (
                block_type == "thinking"
                and isinstance(block.get("text"), str)
                and isinstance(block.get("signature"), str)
            ):
                restored_blocks.append(
                    ThinkingBlock(
                        text=_bounded_history_text(block["text"]),
                        signature=_bounded_history_text(block["signature"]),
                    )
                )
            elif (
                block_type == "tool_call"
                and isinstance(block.get("call_id"), str)
                and isinstance(block.get("name"), str)
                and isinstance(block.get("arguments"), Mapping)
            ):
                call_id = _bounded_history_text(block["call_id"])
                name = _bounded_history_text(block["name"])
                if not call_id or not name:
                    raise ValueError("session manifest contains an invalid history block")
                if name not in known_tools:
                    raise ValueError("session manifest history contains an unknown tool")
                restored_blocks.append(
                    ToolCallBlock(
                        call_id=call_id,
                        name=name,
                        arguments=_validated_arguments(block["arguments"]),
                    )
                )
            elif (
                block_type == "tool_result"
                and isinstance(block.get("call_id"), str)
                and isinstance(block.get("name"), str)
                and isinstance(block.get("content"), str)
                and isinstance(block.get("is_error"), bool)
            ):
                call_id = _bounded_history_text(block["call_id"])
                name = _bounded_history_text(block["name"])
                if not call_id or not name:
                    raise ValueError("session manifest contains an invalid history block")
                restored_blocks.append(
                    ToolResultBlock(
                        call_id=call_id,
                        name=name,
                        content=_bounded_history_text(block["content"]),
                        is_error=block["is_error"],
                    )
                )
            else:
                raise ValueError("session manifest contains an invalid history block")
        history.append(Message(role=role, blocks=tuple(restored_blocks)))
    _validate_history_protocol(history)
    return history


def _known_tool_names() -> frozenset[str]:
    """Load the current registry only when a manifest contains tool context."""

    from tools.registry import TOOL_FUNCTIONS

    return frozenset(TOOL_FUNCTIONS)


def _bounded_history_text(value: str) -> str:
    if len(value.encode("utf-8")) > _MAX_HISTORY_FIELD_BYTES:
        raise ValueError("session manifest history is too large")
    return value


def _validated_arguments(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded JSON object instead of forwarding manifest objects."""

    restored = _validated_json(value, depth=0)
    if not isinstance(restored, dict):  # Kept explicit for static and runtime safety.
        raise ValueError("session manifest contains invalid tool arguments")
    return restored


def _validated_json(value: Any, *, depth: int) -> Any:
    if depth > _MAX_ARGUMENT_DEPTH:
        raise ValueError("session manifest history is too deeply nested")
    if value is None or isinstance(value, (bool, str, int)):
        if isinstance(value, str):
            _bounded_history_text(value)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("session manifest contains invalid tool arguments")
        return value
    if isinstance(value, list):
        return [_validated_json(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        restored = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("session manifest contains invalid tool arguments")
            _bounded_history_text(key)
            restored[key] = _validated_json(item, depth=depth + 1)
        return restored
    raise ValueError("session manifest contains invalid tool arguments")


def _validate_history_protocol(history: list[Message]) -> None:
    """Reject non-provider history before it can reach a model backend."""

    if not history or history[0].role != "user":
        raise ValueError("session manifest history has an invalid message order")

    seen_call_ids: set[str] = set()
    index = 0
    while index < len(history):
        message = history[index]
        if message.role == "user":
            if not all(isinstance(block, TextBlock) for block in message.blocks):
                raise ValueError("session manifest history has an invalid user message")
            if index + 1 == len(history) or history[index + 1].role != "assistant":
                raise ValueError("session manifest history has an invalid message order")
            index += 1
            continue

        calls = [block for block in message.blocks if isinstance(block, ToolCallBlock)]
        if any(isinstance(block, ToolResultBlock) for block in message.blocks):
            raise ValueError("session manifest history has an invalid assistant message")
        if calls:
            first_call = next(
                position
                for position, block in enumerate(message.blocks)
                if isinstance(block, ToolCallBlock)
            )
            if any(
                not isinstance(block, ToolCallBlock)
                for block in message.blocks[first_call:]
            ):
                raise ValueError("session manifest history has an invalid assistant message")
            for call in calls:
                if call.call_id in seen_call_ids:
                    raise ValueError("session manifest history reuses a tool call id")
                seen_call_ids.add(call.call_id)
            if index + 1 == len(history):
                raise ValueError("session manifest history has an unpaired tool call")
            results = history[index + 1]
            # Tool results first, then any notes the user typed while the turn
            # was running: the engine merges a mid-run message into this one
            # rather than opening a user turn of its own.
            returned = [
                block for block in results.blocks if isinstance(block, ToolResultBlock)
            ]
            trailing = results.blocks[len(returned):]
            if (
                results.role != "user"
                or len(returned) != len(results.blocks) - len(trailing)
                or not all(isinstance(block, TextBlock) for block in trailing)
            ):
                raise ValueError("session manifest history has an unpaired tool call")
            if len(calls) != len(returned):
                raise ValueError("session manifest history has an unpaired tool call")
            for call, result in zip(calls, returned):
                if call.call_id != result.call_id or call.name != result.name:
                    raise ValueError("session manifest tool result does not match its call")
            index += 2
            if index < len(history) and history[index].role != "assistant":
                raise ValueError("session manifest history has an invalid message order")
            continue

        if not all(
            isinstance(block, (TextBlock, ThinkingBlock)) for block in message.blocks
        ):
            raise ValueError("session manifest history has an invalid assistant message")
        index += 1
        if index < len(history) and history[index].role != "user":
            raise ValueError("session manifest history has an invalid message order")
