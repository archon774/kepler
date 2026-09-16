"""The initial Textual shell for Kepler's research console."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message as TextualMessage
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

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
from tools.llm.base import BackendUnavailableError
from tools.tui.backends import (
    UnknownBackendError,
    describe_choices,
    open_backend,
    resolve_spec,
    spec_of,
    unavailable_message,
)
from tools.tui.commands import help_text, parse_input, resolve
from tools.tui.render.capability import GraphicsTier, detect_tier
from tools.tui.widgets.artifacts import ArtifactBrowser
from tools.tui.widgets.header import KeplerHeader
from tools.tui.widgets.transcript import Transcript

if TYPE_CHECKING:
    from tools.llm.base import ModelBackend

__all__ = ["ApprovalModal", "KeplerApp", "ENGINE_WORKER_GROUP"]

#: The Textual worker group the engine turn runs in. Named so a command can
#: ask whether a turn is in flight without keeping a second copy of that fact.
ENGINE_WORKER_GROUP = "engine"


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

    BINDINGS = [Binding("f3", "show_artifacts", "Artifacts")]

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

    def __init__(
        self,
        backend: "ModelBackend",
        *,
        max_turns: int = 20,
        graphics_tier: GraphicsTier | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.max_turns = max_turns
        self.sub_title = spec_of(backend)
        self.engine_starts = 0
        self.current_turn = 0
        self.artifact_count = 0
        self.token_usage = None
        self.graphics_tier = detect_tier() if graphics_tier is None else graphics_tier
        self.policy = SessionPolicy(self._request_approval)

    def compose(self) -> ComposeResult:
        """Build the minimal, full-screen console shell."""

        yield KeplerHeader(self.sub_title, id="banner")
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

    @work(thread=True, exclusive=True, group=ENGINE_WORKER_GROUP)
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

    def engine_running(self) -> bool:
        """Whether a turn is in flight.

        Asked of Textual's own worker registry rather than tracked in a flag.
        A flag would have to be set from inside the worker -- after the input
        is already accepting the next line -- so the one moment it exists to
        cover is the moment it would still be ``False``.
        """

        return any(
            worker.group == ENGINE_WORKER_GROUP and worker.is_running
            for worker in self.workers
        )

    def show_help(self, args: tuple[str, ...]) -> None:
        """Render generated command help in the transcript."""

        self._append_transcript(help_text())

    def switch_backend(self, args: tuple[str, ...]) -> None:
        """List the model backends, or switch the session to one of them.

        With no arguments this only describes; a switch needs a name. The
        running backend is replaced **only after** the new one is built and
        probed, so a missing key or a stopped Ollama daemon leaves the session
        exactly as it was rather than on a backend that cannot answer.
        """

        if not args:
            self._append_transcript(describe_choices(spec_of(self.backend)))
            return

        if self.engine_running():
            # run_session() was handed self.backend by value when the turn
            # started; swapping it now would change the header while the old
            # backend finished the turn behind it.
            self._append_transcript(
                "A turn is still running. Wait for it to finish, then switch."
            )
            return

        try:
            spec = resolve_spec(*args)
        except UnknownBackendError as exc:
            self._append_transcript(str(exc))
            return

        try:
            backend = open_backend(spec)
        except BackendUnavailableError as exc:
            self._append_transcript(
                unavailable_message(
                    spec, exc, spec_of(self.backend) or "the current backend"
                )
            )
            return
        except ValueError as exc:
            # An unrecognized provider in an explicit provider/model spec.
            self._append_transcript(f"Cannot use {spec}: {exc}")
            return

        self.backend = backend
        self.sub_title = spec_of(backend)
        self.query_one("#banner", KeplerHeader).set_backend(self.sub_title)
        self._append_transcript(f"Backend switched to {self.sub_title}.")

    def show_artifacts(self, args: tuple[str, ...]) -> None:
        """Open the current artifact browser without involving the model."""

        self.push_screen(ArtifactBrowser(tier=self.graphics_tier))

    def action_show_artifacts(self) -> None:
        """Open the artifact browser from its F3 keybinding."""

        self.show_artifacts(())

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
                f"{self.graphics_tier.value} graphics",
                "F3 artifacts",
                "F4 sessions",
            ]
        )
        return " • ".join(parts)
