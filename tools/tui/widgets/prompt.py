"""The composer: the prompt line and the completion menu above it.

Both halves exist so that typing ``/`` is enough to discover the command
registry. The menu answers "what can I type here", and Tab on the prompt
answers "finish typing it for me"; neither knows anything about a command
beyond what :mod:`tools.tui.commands` declares.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Input, Static

from tools.tui.commands import Suggestion, complete

__all__ = ["CommandMenu", "PromptInput"]


class CommandMenu(Static):
    """List the commands the typed line could still become.

    Hidden until there is something to offer, and only ever as tall as it has
    to be: a console whose menu covers the transcript has traded the
    conversation for a lookup table.
    """

    #: Offers beyond this are counted rather than listed. The full registry is
    #: eleven commands, which on a short terminal is most of the screen.
    MAX_ROWS = 8

    DEFAULT_CSS = """
    CommandMenu {
        height: auto;
        padding: 0 2;
        margin-bottom: 1;
        background: $panel;
        border-left: tall $accent;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.suggestions: tuple[Suggestion, ...] = ()
        self.display = False

    def offer(self, suggestions: tuple[Suggestion, ...]) -> None:
        """Show these completions, or nothing at all when there are none."""

        self.suggestions = suggestions
        self.display = bool(suggestions)
        if suggestions:
            self.update(self.menu_text())

    def menu_text(self) -> Text:
        """The menu's rendered lines, built without driving a terminal."""

        shown = self.suggestions[: self.MAX_ROWS]
        width = max(len(suggestion.value) for suggestion in shown)
        text = Text()
        for index, suggestion in enumerate(shown):
            if index:
                text.append("\n")
            text.append(suggestion.value.ljust(width), style="bold")
            if suggestion.help:
                text.append(f"  {suggestion.help}", style="dim")
        remaining = len(self.suggestions) - len(shown)
        if remaining:
            text.append(f"\n… {remaining} more", style="dim")
        return text


class PromptInput(Input):
    """The prompt line, with Tab bound to slash-command completion.

    The binding lives on the widget rather than the application because a
    widget's bindings are consulted before the screen's, and the screen binds
    Tab to moving focus. Completion takes the key only when it has something
    to complete; on an ordinary message Tab still moves focus, because a
    console that swallows Tab has made its own footer unreachable.
    """

    BINDINGS = [Binding("tab", "complete", "Complete", show=False)]

    def action_complete(self) -> None:
        """Extend the typed line as far as the registry agrees it goes."""

        completed = complete(self.value)
        if completed == self.value:
            self.screen.focus_next()
            return
        self.value = completed
        self.cursor_position = len(completed)
