"""The initial Textual shell for Kepler's research console."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static
from textual.worker import Worker, WorkerState, get_current_worker

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
from tools.agent.events import UserMessage as UserMessageEvent
from tools.agent.policy import SessionPolicy, policy_approver
from tools.llm.base import BackendUnavailableError
from tools.llm.types import Message, TextBlock
from tools.tui.backends import (
    UnknownBackendError,
    choice_for,
    describe_choices,
    offered_models,
    open_backend,
    resolve_spec,
    spec_of,
    unavailable_message,
)
from tools.tui.commands import help_text, parse_input, resolve, suggest
from tools.tui.render.capability import GraphicsTier, detect_tier
from tools.tui.widgets.artifacts import ArtifactBrowser
from tools.tui.widgets.header import KeplerHeader
from tools.tui.widgets.models import ModelBrowser
from tools.tui.widgets.prompt import CommandMenu, PromptInput
from tools.tui.widgets.sessions import SessionBrowser, history_from_manifest
from tools.tui.widgets.transcript import Transcript
from tools.workspace import describe_session, list_artifacts, list_sessions

if TYPE_CHECKING:
    from tools.llm.base import ModelBackend

__all__ = ["ApprovalModal", "KeplerApp", "DEFAULT_THINKING_BUDGET"]

#: What the console asks a provider to spend on reasoning it will show.
#: Enabled by default: a research console whose model works silently for four
#: minutes has nothing to show for the wait, and the working is often the part
#: worth reading. ``--thinking-budget 0`` turns it off.
DEFAULT_THINKING_BUDGET = 4096

LOGGER = logging.getLogger(__name__)

#: How much of a proposed call's arguments the approval modal shows. A model
#: can put a megabyte in one argument; a dialog is not where that is read.
_MAX_ARGUMENT_PREVIEW = 2000

#: How often a worker waiting on an approval re-checks whether it has been
#: cancelled. Short enough that quitting feels immediate, long enough that a
#: modal left open overnight costs nothing.
_APPROVAL_POLL_S = 0.2


def _current_worker() -> Worker | None:
    """The worker this thread belongs to, if it belongs to one."""

    try:
        return get_current_worker()
    except Exception:
        # Called from a plain thread, or from the UI thread in a test.
        return None


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

    #approval-arguments {
        max-height: 12;
        max-width: 80;
        overflow: auto auto;
        padding: 0 0 1 0;
        color: $text-muted;
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
            yield Static(
                f"Allow {self.proposed.name}?", id="approval-question", markup=False
            )
            yield Static(
                self.argument_text(), id="approval-arguments", markup=False
            )
            with Horizontal(id="approval-buttons"):
                yield Button("Allow", id="allow", variant="success")
                yield Button("Allow always", id="allow-always")
                yield Button("Deny", id="deny", variant="error")

    def argument_text(self) -> Text:
        """The arguments this call would run with, as plain text.

        Shown because the name alone is not the decision: approving
        ``search_vizier`` says nothing about what it would query, and the
        transcript node that carries the arguments is behind this modal.
        Rendered as Rich text and bounded, so neither markup nor length in a
        model-supplied argument can reshape the dialog.
        """

        if not self.proposed.arguments:
            return Text("no arguments", style="italic")
        rendered = json.dumps(dict(self.proposed.arguments), indent=2, default=str)
        if len(rendered) > _MAX_ARGUMENT_PREVIEW:
            rendered = rendered[:_MAX_ARGUMENT_PREVIEW] + "\n… truncated"
        return Text(rendered)

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
        Binding("escape", "interrupt", "Stop the turn"),
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
        thinking_budget: int | None = DEFAULT_THINKING_BUDGET,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.max_turns = max_turns
        self.thinking_budget = thinking_budget
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
        # Guards both collections below, which the engine thread touches as
        # well as the UI thread: the worker drains the queue between turns and
        # registers itself as waiting for an approval, while the person types
        # into the queue and answers the modal from here.
        self._queue_lock = threading.Lock()
        self._queued_input: list[str] = []
        self._stop_requested = False
        self._pending_approvals: set[KeplerApp.ApprovalRequest] = set()

    def compose(self) -> ComposeResult:
        """Build the minimal, full-screen console shell."""

        yield KeplerHeader(self.sub_title, id="banner")
        yield Transcript(id="transcript")
        with Vertical(id="composer"):
            yield CommandMenu(id="completions")
            yield PromptInput(placeholder="Ask Kepler…", id="prompt")
        yield Static(self._status_text(), id="status")

    def on_mount(self) -> None:
        """Start keyboard interaction in the prompt, not the transcript."""

        self.query_one("#prompt", Input).focus()

    def on_unmount(self) -> None:
        """Release every worker still waiting on a decision this UI owed it.

        A thread worker blocked on an approval cannot be cancelled -- it is
        blocked on an event only the interface sets, and the interface is
        going away. Nothing would ever set it, and Python joins its executor
        threads at exit, so quitting with a modal open would hang the process
        rather than close it. Every pending request is answered ``DENY``: the
        user is leaving, and a call they did not approve must not run.
        """

        for request in self._release_pending_approvals():
            request.decision = Decision.DENY
            request.ready.set()

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
        elif isinstance(event, SessionFinished):
            self._return_undelivered_input()
        self._refresh_status()

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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Offer the commands the line being typed could still become."""

        if event.input.id == "prompt":
            self.query_one("#completions", CommandMenu).offer(suggest(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Keep UI slash commands out of the headless model engine."""

        parsed = parse_input(event.value)
        event.input.value = ""
        if parsed.kind == "message":
            if not parsed.text.strip():
                return
            if self._session_running():
                self.queue_for_running_session(parsed.text)
                return
            self.query_one("#transcript", Transcript).append_user(parsed.text)
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
        """Start one engine session, leaving the prompt open while it runs.

        The prompt stays live for the whole turn. A person watching a tool
        chain is the person best placed to correct it, and a console that
        locks the input until the model is finished makes them wait to say so
        until saying it no longer helps.
        """

        if self._session_running():
            return self._active_worker
        self._history_ready = False
        self._stop_requested = False
        worker = self._run_prompt(text, history=history)
        self._active_worker = worker
        # The status bar carries how to stop a running turn, so it has to be
        # redrawn when one starts -- not only when the first event arrives,
        # which on a slow first token is many seconds later.
        self._refresh_status()
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
                on_delta=self._post_delta,
                pending_input=self._take_queued_input,
                should_stop=self._stop_is_requested,
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
            self._refresh_status()
            if message.state is WorkerState.SUCCESS:
                self._finish_prompt_if_ready()
            else:
                self._restore_prompt()

    def queue_for_running_session(self, text: str) -> None:
        """Hand a mid-turn note to the running loop, and say it is waiting.

        It is delivered at the next turn boundary, alongside the tool results
        of the turn in flight, rather than starting a second conversation. The
        entry says "queued" until the engine reports it delivered, because a
        note that looks sent but is not is worse than one that looks queued.
        """

        with self._queue_lock:
            self._queued_input.append(text)
        self.query_one("#transcript", Transcript).append_user(text, pending=True)

    def action_interrupt(self) -> None:
        """Ask the running loop to stop at its next safe point."""

        if not self._session_running():
            return
        if self._stop_requested:
            return
        self._stop_requested = True
        self._append_transcript(
            "Stopping — the step in flight has to finish first."
        )
        self._refresh_status()

    def _post_delta(self, event: Event) -> None:
        """Carry one streamed delta from the engine thread to the UI.

        The same message the buffered events travel on, so a delta rendered
        live and a delta replayed afterwards reach the transcript by exactly
        one path.
        """

        self.post_message(self.EngineEvent(event))

    def _take_queued_input(self) -> tuple[str, ...]:
        """Hand the engine everything typed since the last turn, and forget it."""

        with self._queue_lock:
            notes = tuple(self._queued_input)
            self._queued_input.clear()
        return notes

    def _stop_is_requested(self) -> bool:
        return self._stop_requested

    def _return_undelivered_input(self) -> None:
        """Give back a note the session ended before it could take.

        Into the prompt, not into the void: the person wrote it and the loop
        never saw it. It is only put back when the prompt is empty, so it
        cannot overwrite whatever they have started typing since.
        """

        notes = self._take_queued_input()
        if not notes:
            return
        prompt = self.query_one("#prompt", Input)
        self._append_transcript(
            "The session ended before your note was delivered."
        )
        if not prompt.value:
            prompt.value = " ".join(notes)
            prompt.cursor_position = len(prompt.value)

    def show_help(self, args: tuple[str, ...]) -> None:
        """Render generated command help in the transcript."""

        self._append_transcript(help_text())

    def switch_backend(self, args: tuple[str, ...]) -> None:
        """List the model backends, or switch the session to one of them.

        With no arguments this only describes; a switch needs a name. A bare
        provider name whose host publishes an inventory opens the picker
        instead of assuming a default -- a host holding eleven models has ten
        answers a default gets wrong. Naming the model outright
        (``/backend ollama gemma4:12b``) still switches directly, so a keybind
        or a habit does not acquire a dialog.

        The running backend is replaced **only after** the new one is built
        and probed, so a missing key or a stopped Ollama daemon leaves the
        session exactly as it was rather than on a backend that cannot answer.
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

        if len(args) == 1 and self._offer_model_choice(args[0]):
            return

        try:
            backend = open_backend(spec, thinking_budget=self.thinking_budget)
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

    def _offer_model_choice(self, provider: str) -> bool:
        """Open the picker for a bare provider name, if there is one to open.

        Returns whether it opened. A host that cannot be asked reports no
        models, and then this does nothing at all and the caller switches to
        the default as before -- an unanswerable question must not be able to
        stop the switch that was asked for.
        """

        models = offered_models(provider)
        if not models:
            return False

        choice = choice_for(provider)
        self.push_screen(
            ModelBrowser(
                provider,
                models,
                current=_model_of(spec_of(self.backend), provider),
                default=choice.default_model if choice else "",
            ),
            lambda model: self._switch_to_model(provider, model),
        )
        return True

    def _switch_to_model(self, provider: str, model: str | None) -> None:
        """Complete a switch the picker chose, or say nothing if it was closed."""

        if model:
            self.switch_backend((provider, model))

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

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(self._status_text())

    def _append_transcript(self, text: str) -> None:
        self.query_one("#transcript", Transcript).append_notice(text)

    def _request_approval(self, proposed: ToolCallProposed) -> Decision:
        """Block this worker until the UI answers -- or stops being able to.

        The wait is polled rather than indefinite so a cancelled worker can
        give up. ``App.exit`` cancels its workers, so this is what turns a
        quit during an open modal into a denial and a clean shutdown.
        """

        request = self.ApprovalRequest(proposed)
        with self._queue_lock:
            self._pending_approvals.add(request)
        self.post_message(request)

        worker = _current_worker()
        while not request.ready.wait(timeout=_APPROVAL_POLL_S):
            if worker is not None and worker.is_cancelled:
                self._forget_approval(request)
                return Decision.DENY
        self._forget_approval(request)
        return request.decision

    def _release_pending_approvals(self) -> tuple["KeplerApp.ApprovalRequest", ...]:
        with self._queue_lock:
            pending = tuple(self._pending_approvals)
            self._pending_approvals.clear()
        return pending

    def _forget_approval(self, request: "KeplerApp.ApprovalRequest") -> None:
        with self._queue_lock:
            self._pending_approvals.discard(request)

    def _resolve_approval(
        self, request: ApprovalRequest, decision: Decision | None
    ) -> None:
        self._forget_approval(request)
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
        if self._session_running():
            parts.append("stopping" if self._stop_requested else "esc stop")
        return " • ".join(parts)


def _model_of(spec: str | None, provider: str) -> str:
    """The model half of a spec, but only when it is this provider's.

    Comparing providers first is the point: ``claude-sonnet-5`` is not a model
    the Ollama picker should mark as current just because the session is on it.
    """

    if not spec or "/" not in spec:
        return ""
    current_provider, model = spec.split("/", 1)
    return model if current_provider == provider else ""
