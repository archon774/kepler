"""Saved-session history reconstruction for the Kepler console."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from tools.llm.types import Message, TextBlock
from tools.models import ArtifactMetadata
from tools.workspace import describe_session, list_sessions

__all__ = ["SessionBrowser", "history_from_manifest"]


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
            yield Static("Sessions")
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
        """Place keyboard selection on the session list."""

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
    user_message = manifest.get("user_message")
    if not isinstance(user_message, str) or not user_message.strip():
        raise ValueError("session manifest has no user message")

    turns = manifest.get("turns")
    if not isinstance(turns, list):
        raise ValueError("session manifest has no recorded turns")

    history = [Message(role="user", blocks=(TextBlock(text=user_message),))]
    for turn in turns:
        if not isinstance(turn, Mapping):
            raise ValueError("session manifest contains an invalid turn")
        assistant_text = turn.get("assistant_text")
        if isinstance(assistant_text, str) and assistant_text:
            history.append(
                Message(role="assistant", blocks=(TextBlock(text=assistant_text),))
            )
    return tuple(history)
