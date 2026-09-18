"""The initial Textual shell for Kepler's research console."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static
from textual.worker import Worker, WorkerState

from tools.agent.approval import Decision
from tools.agent.engine import run_session
from tools.agent.events import (
    Event,
    SessionFinished,
    SessionStarted,
    TextDelta,
    ToolCallFinished,
    ToolCallProposed,
    TurnFinished,
    TurnStarted,
)
from tools.agent.policy import SessionPolicy, policy_approver
from tools.llm.base import BackendUnavailableError
from tools.llm.types import Message, TextBlock
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
from tools.tui.widgets.sessions import SessionBrowser, history_from_manifest
from tools.tui.widgets.transcript import Transcript
from tools.workspace import describe_session, list_artifacts, list_sessions

if TYPE_CHECKING:
    from tools.llm.base import ModelBackend

__all__ = ["ApprovalModal", "KeplerApp"]

LOGGER = logging.getLogger(__name__)


class ApprovalModal(ModalScreen[Decision]):
    """Ask the UI user for one risky tool-call decision."""

    CSS = """
    ApprovalModal {
        align: center middle;
    }

    #approval-dialog {
        width: auto;
        height: auto;
        padding: 1 3;
        border: round $accent;
        background: $surface;
    }

    #approval-question {
        padding: 0 0 1 0;
    }

    #approval-buttons {
        width: auto;
        height: auto;
    }

    #approval-buttons Button {
        margin-right: 2;
    }
    """

    def __init__(self, proposed: ToolCallProposed) -> None:
        super().__init__()
        self.proposed = proposed

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Static(f"Allow {self.proposed.name}?", id="approval-question")
            with Horizontal(id="approval-buttons"):
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

    BINDINGS = [
        Binding("f3", "show_artifacts", "Artifacts"),
        Binding("f4", "show_sessions", "Sessions"),
    ]

    CSS = """
    #transcript {
        height: 1fr;
        padding: 1 2;
        scrollbar-gutter: stable;
    }

    /* Assistant text, notices and tool nodes are separate widgets stacked
       edge to edge, which reads as one dense paragraph however different
       they are. The blank row between them is what makes a transcript entry
       look like an entry. */
    #transcript > * {
        margin-bottom: 1;
    }

    #composer {
        dock: bottom;
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }

    #status {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: $text-muted;
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

    class HistoryUpdated(TextualMessage):
        """Carry the completed prompt and its text answer back to the UI."""

        def __init__(self, history: tuple[Message, ...]) -> None:
            self.history = history
            super().__init__()

    class EngineFailed(TextualMessage):
        """Report a worker failure that did not reach the engine event stream."""

        pass

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
        self._history: tuple["Message", ...] = ()
        self._history_ready = False
        self._artifact_directory: Path | None = None
        self._active_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        """Build the minimal, full-screen console shell."""

        yield KeplerHeader(self.sub_title, id="banner")
        yield Transcript(id="transcript")
        with Vertical(id="composer"):
            yield Input(placeholder="Ask Kepler…", id="prompt")
        yield Static(self._status_text(), id="status")

    def on_mount(self) -> None:
        """Start keyboard interaction in the prompt, not the transcript."""

        self.query_one("#prompt", Input).focus()

    def on_kepler_app_engine_event(self, message: EngineEvent) -> None:
        """Render each worker event on Textual's UI thread."""

        event = message.event
        self.query_one("#transcript", Transcript).handle_event(event)
        if isinstance(event, SessionStarted):
            self._artifact_directory = Path(event.manifest_path).parent
        elif isinstance(event, TurnStarted):
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

    def on_kepler_app_history_updated(self, message: HistoryUpdated) -> None:
        """Keep completed text exchanges available to the next prompt."""

        self._history = message.history
        self._history_ready = True
        self._finish_prompt_if_ready()

    def on_kepler_app_engine_failed(self, message: EngineFailed) -> None:
        """Make unexpected worker failures visible in the transcript."""

        self._append_transcript("The engine stopped unexpectedly.")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Keep UI slash commands out of the headless model engine."""

        parsed = parse_input(event.value)
        event.input.value = ""
        if parsed.kind == "message":
            if self._session_running():
                self._append_transcript("A session is already running.")
                return
            self.run_prompt(parsed.text, history=self._history)
            return
        if parsed.kind == "unknown":
            self._append_transcript(f"Unknown command: /{parsed.name}")
            return

        command = resolve(parsed.name)
        if command is not None:
            handler = getattr(self, command.handler, self._command_not_available)
            handler(parsed.args)

    def run_prompt(
        self, text: str, *, history: tuple["Message", ...] = ()
    ) -> Worker[None]:
        """Start one engine session and keep the prompt unavailable until it ends."""

        if self._session_running():
            return self._active_worker
        self.query_one("#prompt", Input).disabled = True
        self._history_ready = False
        worker = self._run_prompt(text, history=history)
        self._active_worker = worker
        return worker

    @work(thread=True)
    def _run_prompt(self, text: str, *, history: tuple["Message", ...] = ()) -> None:
        """Run the synchronous engine in a Textual thread worker."""

        self.engine_starts += 1
        policy = SessionPolicy(self._request_approval)
        assistant_text: list[str] = []
        manifest_path: Path | None = None
        try:
            for event in run_session(
                text,
                backend=self.backend,
                max_turns=self.max_turns,
                approver=policy_approver(policy),
                history=history,
            ):
                if isinstance(event, TextDelta):
                    assistant_text.append(event.text)
                elif isinstance(event, SessionFinished):
                    manifest_path = Path(event.manifest_path)
                self.post_message(self.EngineEvent(event))
        except Exception as exc:
            # The engine emits its error SessionFinished event before reraising.
            # Its saved manifest is enough to make the next prompt recoverable.
            LOGGER.warning("Agent engine worker stopped: %s", type(exc).__name__)
            self.post_message(self.EngineFailed())

        if manifest_path is not None:
            try:
                completed_history = history_from_manifest(describe_session(manifest_path))
            except (OSError, ValueError):
                pass
            else:
                self.post_message(self.HistoryUpdated(completed_history))
                return
        if assistant_text:
            updated_history = (
                *history,
                Message(role="user", blocks=(TextBlock(text=text),)),
                Message(
                    role="assistant",
                    blocks=(TextBlock(text="".join(assistant_text)),),
                ),
            )
        else:
            updated_history = history
        self.post_message(self.HistoryUpdated(updated_history))

    def on_worker_state_changed(self, message: Worker.StateChanged) -> None:
        """Restore prompt input only after the active synchronous worker stops."""

        if (
            message.worker is self._active_worker
            and message.state
            in {WorkerState.CANCELLED, WorkerState.ERROR, WorkerState.SUCCESS}
        ):
            self._active_worker = None
            if message.state is WorkerState.SUCCESS:
                self._finish_prompt_if_ready()
            else:
                self._restore_prompt()

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

        if self._session_running():
            # run_session() was handed self.backend by value when the turn
            # started; swapping it now would change the header while the old
            # backend finished the turn behind it. _session_running() is set
            # on the UI thread before the worker starts, so unlike a flag set
            # inside the worker it is already true the moment it matters.
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

        artifacts = (
            None
            if self._artifact_directory is None
            else list_artifacts(self._artifact_directory)
        )
        self.push_screen(ArtifactBrowser(artifacts, tier=self.graphics_tier))

    def action_show_artifacts(self) -> None:
        """Open the artifact browser from its F3 keybinding."""

        self.show_artifacts(())

    def show_sessions(self, args: tuple[str, ...]) -> None:
        """Open the saved-session browser without involving the model."""

        if self._session_running():
            self._append_transcript("A session is already running.")
            return
        self.push_screen(SessionBrowser(), self.resume_session)

    def action_show_sessions(self) -> None:
        """Open the session browser from its F4 keybinding."""

        self.show_sessions(())

    def resume(self, args: tuple[str, ...]) -> None:
        """Load the saved session named by a `/resume <id>` command."""

        if len(args) != 1:
            self._append_transcript("Usage: /resume <session-id>")
            return
        session_id = args[0]
        for session in list_sessions():
            try:
                manifest = describe_session(session.file.path)
            except (OSError, ValueError):
                continue
            if (
                isinstance(manifest, Mapping)
                and manifest.get("session_id") == session_id
            ):
                self.resume_session(Path(session.file.path))
                return
        self._append_transcript(f"Unknown session: {session_id}")

    def resume_session(self, path: Path | None) -> None:
        """Load a saved trace for the next submitted follow-up prompt."""

        if path is None:
            return
        if self._session_running():
            self._append_transcript("A session is already running.")
            return
        try:
            manifest = describe_session(path)
            history = history_from_manifest(manifest)
        except (OSError, ValueError):
            self._append_transcript(f"Unable to load session: {path}")
            return

        self._artifact_directory = path.expanduser().resolve().parent
        transcript = self.query_one("#transcript", Transcript)
        transcript.clear()
        transcript.restore_assistant_text(
            "\n\n".join(
                block.text
                for message in history
                if message.role == "assistant"
                for block in message.blocks
                if isinstance(block, TextBlock)
            )
        )
        session_id = manifest.get("session_id", path.parent.name)
        transcript.append_notice(
            f"Loaded session {session_id}. Artifacts remain available by path."
        )
        self._history = history
        self.query_one("#prompt", Input).focus()

    def quit(self, args: tuple[str, ...]) -> None:
        """Exit the console through its declarative command handler."""

        self.exit()

    def _command_not_available(self, args: tuple[str, ...]) -> None:
        self._append_transcript("This command is not available in the current phase.")

    def _session_running(self) -> bool:
        """Return whether the application still owns a synchronous engine worker."""

        return (
            self._active_worker is not None and not self._active_worker.is_finished
        )

    def _finish_prompt_if_ready(self) -> None:
        """Re-enable input only after both worker completion and history sync."""

        if self._active_worker is None and self._history_ready:
            self._history_ready = False
            self._restore_prompt()

    def _restore_prompt(self) -> None:
        """Return focus to the prompt after a finished or cancelled worker."""

        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()

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
