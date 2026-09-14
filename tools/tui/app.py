"""The initial Textual shell for Kepler's research console."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from textual import work
from textual.app import App, ComposeResult
from textual.message import Message as TextualMessage
from textual.screen import ModalScreen
from textual.widgets import Button, Header, Input, Static

from tools.agent.approval import Decision
from tools.agent.engine import run_session
from tools.agent.events import (
    Event,
    TextDelta,
    ToolCallFinished,
    ToolCallProposed,
    TurnFinished,
    TurnStarted,
)
from tools.agent.policy import SessionPolicy, policy_approver
from tools.tui.commands import help_text, parse_input, resolve
from tools.tui.widgets.transcript import Transcript

if TYPE_CHECKING:
    from tools.llm.base import ModelBackend

__all__ = ["ApprovalModal", "KeplerApp"]


class ApprovalModal(ModalScreen[Decision]):
    """Ask the UI user for one risky tool-call decision."""

    def __init__(self, proposed: ToolCallProposed) -> None:
        super().__init__()
        self.proposed = proposed

    def compose(self) -> ComposeResult:
        yield Static(f"Allow {self.proposed.name}?")
        yield Button("Allow", id="allow", variant="success")
        yield Button("Allow always", id="allow-always")
        yield Button("Deny", id="deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        decisions = {
            "allow": Decision.ALLOW,
            "allow-always": Decision.ALLOW_ALWAYS,
            "deny": Decision.DENY,
        }
        self.dismiss(decisions[event.button.id or "deny"])


class KeplerApp(App[None]):
    """The single-column shell shared by the console's later UI phases."""

    TITLE = "Kepler"

    CSS = """
    #transcript {
        height: 1fr;
        padding: 1 2;
    }

    #prompt {
        dock: bottom;
    }

    #status {
        dock: bottom;
        height: 1;
        padding: 0 1;
    }
    """

    class EngineEvent(TextualMessage):
        """Carry one headless-engine event onto Textual's UI thread."""

        def __init__(self, event: Event) -> None:
            self.event = event
            super().__init__()

    class ApprovalRequest(TextualMessage):
        """Carry a blocking worker approval request to the UI thread."""

        def __init__(self, proposed: ToolCallProposed) -> None:
            self.proposed = proposed
            self.ready = threading.Event()
            self.decision = Decision.DENY
            super().__init__()

    def __init__(self, backend: "ModelBackend", *, max_turns: int = 20) -> None:
        super().__init__()
        self.backend = backend
        self.max_turns = max_turns
        self.sub_title = str(getattr(backend, "spec", ""))
        self.engine_starts = 0
        self.current_turn = 0
        self.artifact_count = 0
        self.token_usage = None
        self.policy = SessionPolicy(self._request_approval)

    def compose(self) -> ComposeResult:
        """Build the minimal, full-screen console shell."""

        yield Header(name="Kepler")
        yield Transcript(id="transcript")
        yield Input(placeholder="Ask Kepler…", id="prompt")
        yield Static(self._status_text(), id="status")

    def on_mount(self) -> None:
        """Start keyboard interaction in the prompt, not the transcript."""

        self.query_one("#prompt", Input).focus()

    def on_kepler_app_engine_event(self, message: EngineEvent) -> None:
        """Render each worker event on Textual's UI thread."""

        event = message.event
        self.query_one("#transcript", Transcript).handle_event(event)
        if isinstance(event, TurnStarted):
            self.current_turn = event.turn
        elif isinstance(event, TurnFinished):
            self.token_usage = event.usage
        elif isinstance(event, ToolCallFinished):
            self.artifact_count += len(event.artifacts)
        self.query_one("#status", Static).update(self._status_text())

    def on_kepler_app_approval_request(self, request: ApprovalRequest) -> None:
        """Display a modal and unblock the worker when the user answers."""

        self.push_screen(
            ApprovalModal(request.proposed),
            lambda decision: self._resolve_approval(request, decision),
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Keep UI slash commands out of the headless model engine."""

        parsed = parse_input(event.value)
        event.input.value = ""
        if parsed.kind == "message":
            self.run_prompt(parsed.text)
            return
        if parsed.kind == "unknown":
            self._append_transcript(f"Unknown command: /{parsed.name}")
            return

        command = resolve(parsed.name)
        if command is not None:
            handler = getattr(self, command.handler, self._command_not_available)
            handler(parsed.args)

    @work(thread=True, exclusive=True)
    def run_prompt(self, text: str) -> None:
        """Run the synchronous engine in a Textual thread worker."""

        self.engine_starts += 1
        for event in run_session(
            text,
            backend=self.backend,
            max_turns=self.max_turns,
            approver=policy_approver(self.policy),
        ):
            self.post_message(self.EngineEvent(event))

    def show_help(self, args: tuple[str, ...]) -> None:
        """Render generated command help in the transcript."""

        self._append_transcript(help_text())

    def quit(self, args: tuple[str, ...]) -> None:
        """Exit the console through its declarative command handler."""

        self.exit()

    def _command_not_available(self, args: tuple[str, ...]) -> None:
        self._append_transcript("This command is not available in the current phase.")

    def _append_transcript(self, text: str) -> None:
        self.query_one("#transcript", Transcript).append_notice(text)

    def _request_approval(self, proposed: ToolCallProposed) -> Decision:
        request = self.ApprovalRequest(proposed)
        self.post_message(request)
        request.ready.wait()
        return request.decision

    def _resolve_approval(
        self, request: ApprovalRequest, decision: Decision | None
    ) -> None:
        request.decision = decision or Decision.DENY
        request.ready.set()

    def _status_text(self) -> str:
        parts = [f"{self.current_turn}/{self.max_turns} turns"]
        if self.token_usage is not None:
            if self.token_usage.input_tokens is not None:
                parts.append(f"{self.token_usage.input_tokens} input tokens")
            if self.token_usage.output_tokens is not None:
                parts.append(f"{self.token_usage.output_tokens} output tokens")
        parts.extend(
            [
                f"{self.artifact_count} artifacts",
                "F3 artifacts",
                "F4 sessions",
            ]
        )
        return " • ".join(parts)
