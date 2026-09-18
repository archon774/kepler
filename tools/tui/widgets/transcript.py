"""The scrolling event consumer for the Kepler console transcript."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from tools.agent.events import (
    Event,
    ProtocolFault,
    SessionFinished,
    SessionStarted,
    TextDelta,
    ThinkingDelta,
    ToolCallDenied,
    ToolCallFinished,
    ToolCallProposed,
    ToolCallStarted,
    TurnFinished,
    TurnStarted,
    UserMessage,
)
from tools.tui.widgets.tool_node import ToolNode

__all__ = ["Transcript", "ThoughtBlock", "UserEntry"]


class UserEntry(Static):
    """One thing the person said, kept visible for the rest of the session.

    A question scrolls out of the input the moment it is sent, and an answer
    read without the question that produced it is a different claim. Typed
    while a turn is running, it is marked queued until the engine says it has
    been delivered -- the loop is mid-turn and cannot take it yet, and a note
    that looks sent but is not is worse than one that looks queued.
    """

    DEFAULT_CSS = """
    UserEntry {
        color: $text;
        text-style: bold;
    }
    """

    def __init__(self, text: str, *, pending: bool = False) -> None:
        super().__init__()
        self.text = text
        self.pending = pending
        self._render_entry()

    def deliver(self, turn: int) -> None:
        """Mark a queued note as having reached the conversation."""

        self.pending = False
        self.turn = turn
        self._render_entry()

    def _render_entry(self) -> None:
        entry = Text("› ", style="bold")
        entry.append(self.text)
        if self.pending:
            entry.append("  queued for the next turn", style="dim not bold")
        self.update(entry)


class ThoughtBlock(Static):
    """The model's reasoning for one turn, as the provider revealed it.

    Muted and marked, never styled like the answer: a model's working is a
    different kind of claim from its conclusion, and a discarded hypothesis
    rendered like a finding is how a transcript misleads.
    """

    DEFAULT_CSS = """
    ThoughtBlock {
        color: $text-muted;
        text-style: italic;
        padding-left: 2;
        border-left: tall $panel-lighten-2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.thinking = ""
        self._render_thought()

    def add(self, text: str) -> None:
        """Append one revealed run of reasoning."""

        self.thinking += text
        self._render_thought()

    def _render_thought(self) -> None:
        body = Text("✻ thinking\n", style="not italic dim")
        body.append(self.thinking or "…")
        self.update(body)


class Transcript(VerticalScroll):
    """Render engine events without making the engine aware of Textual."""

    DEFAULT_CSS = """
    /* Session, turn and command notices are the console talking about the
       session; the model's answer is the session. Muting one distinguishes
       them without spending a row on a label. */
    Transcript .notice {
        color: $text-muted;
    }
    """

    def __init__(self, *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.assistant_text = ""
        self.tool_nodes: dict[str, ToolNode] = {}
        self._notices: list[Static] = []
        # Both are per-turn and mounted in the order they happen, so the
        # transcript reads chronologically: question, reasoning, answer, the
        # calls it made. A single answer widget pinned at the top would put
        # every answer above the notices that preceded it.
        self._answer: Static | None = None
        self._thought: ThoughtBlock | None = None
        self._queued: list[UserEntry] = []
        self._turn_text_start = 0

    def compose(self) -> ComposeResult:
        return iter(())

    def handle_event(self, event: Event) -> None:
        """Apply one immutable engine event to the visible transcript."""

        if isinstance(event, TextDelta):
            self.assistant_text += event.text
            self._answer_block().update(self.assistant_text_this_turn)
        elif isinstance(event, ThinkingDelta):
            self._thought_block().add(event.text)
        elif isinstance(event, UserMessage):
            self._deliver_queued(event)
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
            # A new turn reasons and answers afresh; the previous turn's
            # blocks stay where they are rather than growing forever.
            self._answer = None
            self._thought = None
            self._turn_text_start = len(self.assistant_text)
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

    @property
    def assistant_text_this_turn(self) -> str:
        """The answer text belonging to the turn currently being rendered."""

        return self.assistant_text[self._turn_text_start:]

    def append_user(self, text: str, *, pending: bool = False) -> UserEntry:
        """Show what the person just said, queued or not."""

        entry = UserEntry(text, pending=pending)
        if pending:
            self._queued.append(entry)
        self.mount(entry)
        self.scroll_end(animate=False)
        return entry

    def append_notice(self, text: str) -> None:
        """Append a UI-only error, command response, or user-message notice."""

        self._append_note(text)
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """Remove live nodes before replacing the transcript with saved text."""

        self.assistant_text = ""
        self.tool_nodes = {}
        self._notices = []
        self._answer = None
        self._thought = None
        self._queued = []
        self._turn_text_start = 0
        self.remove_children()

    def restore_assistant_text(self, text: str) -> None:
        """Display saved assistant text without replaying tool calls or artifacts."""

        self.assistant_text = text
        self._turn_text_start = 0
        if text:
            self._answer_block().update(text)
        self.scroll_end(animate=False)

    def _deliver_queued(self, event: UserMessage) -> None:
        """Mark the queued note the engine just took into the conversation."""

        for entry in list(self._queued):
            if entry.text == event.text:
                entry.deliver(event.turn)
                self._queued.remove(entry)
                return
        # Delivered without ever being shown as queued -- a caller queued it
        # some other way. Show it rather than lose it.
        self.append_user(event.text)

    def _answer_block(self) -> Static:
        if self._answer is None:
            # markup=False: this holds whatever the model said. Textual parses
            # content markup in a `Static` by default, which would let a model
            # mint clickable action links in the transcript -- and would quietly
            # eat ordinary astronomy text, since `The [OIII] line` renders as
            # `The  line`. Every other transcript widget passes Rich `Text`,
            # which is never parsed; these two take a plain string.
            self._answer = Static("", markup=False)
            self.mount(self._answer)
        return self._answer

    def _thought_block(self) -> ThoughtBlock:
        if self._thought is None:
            self._thought = ThoughtBlock()
            self.mount(self._thought)
        return self._thought

    def _append_note(self, text: str) -> None:
        notice = Static(text, classes="notice", markup=False)
        self._notices.append(notice)
        self.mount(notice)

    def _node(self, call_id: str) -> ToolNode:
        return self.tool_nodes[call_id]
