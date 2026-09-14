"""The initial Textual shell for Kepler's research console."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.message import Message as TextualMessage
from textual.widgets import Header, Input, Static

from tools.agent.events import Event, TextDelta
from tools.tui.commands import help_text, parse_input, resolve

if TYPE_CHECKING:
    from tools.llm.base import ModelBackend

__all__ = ["KeplerApp"]


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

    def __init__(self, backend: "ModelBackend", *, max_turns: int = 20) -> None:
        super().__init__()
        self.backend = backend
        self.max_turns = max_turns
        self.sub_title = str(getattr(backend, "spec", ""))
        self.engine_starts = 0
        self._transcript_text = ""

    def compose(self) -> ComposeResult:
        """Build the minimal, full-screen console shell."""

        yield Header(name="Kepler")
        yield Static(id="transcript")
        yield Input(placeholder="Ask Kepler…", id="prompt")
        yield Static(self._status_text(), id="status")

    def on_kepler_app_engine_event(self, message: EngineEvent) -> None:
        """Render the event types the initial shell can present directly."""

        if isinstance(message.event, TextDelta):
            self._transcript_text += message.event.text
            self.query_one("#transcript", Static).update(self._transcript_text)

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

    def run_prompt(self, text: str) -> None:
        """Record ordinary user input until Phase D.3 starts the worker."""

        self.engine_starts += 1
        self._append_transcript(f"User: {text}")

    def show_help(self, args: tuple[str, ...]) -> None:
        """Render generated command help in the transcript."""

        self._append_transcript(help_text())

    def quit(self, args: tuple[str, ...]) -> None:
        """Exit the console through its declarative command handler."""

        self.exit()

    def _command_not_available(self, args: tuple[str, ...]) -> None:
        self._append_transcript("This command is not available in the current phase.")

    def _append_transcript(self, text: str) -> None:
        if self._transcript_text:
            self._transcript_text += "\n"
        self._transcript_text += text
        self.query_one("#transcript", Static).update(self._transcript_text)

    def _status_text(self) -> str:
        return f"0/{self.max_turns} turns"
