"""The scrolling event consumer for the Kepler console transcript."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from tools.agent.events import (
    Event,
    ProtocolFault,
    SessionFinished,
    SessionStarted,
    TextDelta,
    ToolCallDenied,
    ToolCallFinished,
    ToolCallProposed,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
)
from tools.tui.widgets.tool_node import ToolNode

__all__ = ["Transcript"]


class Transcript(VerticalScroll):
    """Render engine events without making the engine aware of Textual."""

    def __init__(self, *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.assistant_text = ""
        self.tool_nodes: dict[str, ToolNode] = {}
        self._assistant = Static("")
        self._notices: list[Static] = []

    def compose(self) -> ComposeResult:
        yield self._assistant

    def handle_event(self, event: Event) -> None:
        """Apply one immutable engine event to the visible transcript."""

        if isinstance(event, TextDelta):
            self.assistant_text += event.text
            self._assistant.update(self.assistant_text)
        elif isinstance(event, ToolCallProposed):
            node = ToolNode(event.call_id, event.name, event.arguments)
            self.tool_nodes[event.call_id] = node
            self.mount(node)
        elif isinstance(event, ToolCallStarted):
            self._node(event.call_id).start(event.cache_hit)
        elif isinstance(event, ToolCallFinished):
            self._node(event.call_id).finish(
                event.result, event.artifacts, event.duration_ms
            )
        elif isinstance(event, ToolCallDenied):
            self._node(event.call_id).deny(event.reason)
        elif isinstance(event, TurnStarted):
            self._append_note(f"Turn {event.turn} started.")
        elif isinstance(event, TurnFinished):
            self._append_note(f"Turn {event.turn} finished: {event.stop_reason}.")
        elif isinstance(event, ProtocolFault):
            self._append_note(f"Protocol fault ({event.type}): {event.detail}")
        elif isinstance(event, SessionStarted):
            self._append_note(f"Session {event.session_id} started.")
        elif isinstance(event, SessionFinished):
            self._append_note(f"Session finished: {event.outcome}.")
        self.scroll_end(animate=False)

    def append_notice(self, text: str) -> None:
        """Append a UI-only error, command response, or user-message notice."""

        self._append_note(text)
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """Remove live nodes before replacing the transcript with saved text."""

        self.assistant_text = ""
        self.tool_nodes = {}
        self._notices = []
        self._assistant = Static("")
        self.remove_children()
        self.mount(self._assistant)

    def restore_assistant_text(self, text: str) -> None:
        """Display saved assistant text without replaying tool calls or artifacts."""

        self.assistant_text = text
        self._assistant.update(text)
        self.scroll_end(animate=False)

    def _append_note(self, text: str) -> None:
        notice = Static(text)
        self._notices.append(notice)
        self.mount(notice)

    def _node(self, call_id: str) -> ToolNode:
        return self.tool_nodes[call_id]
