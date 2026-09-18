"""The model picker: which of a provider's models to switch to.

A bare ``/backend ollama`` used to pick a default and switch, which is fine
until the host holds eleven models and the default is not the one you want.
This asks instead, and only for a provider whose host publishes what it holds.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

__all__ = ["ModelBrowser"]


class ModelBrowser(ModalScreen[str | None]):
    """Choose one model from what a provider's host reports."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    CSS = """
    ModelBrowser {
        align: center middle;
    }

    #model-browser {
        width: 70%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }

    #model-list {
        height: auto;
        max-height: 1fr;
    }
    """

    def __init__(
        self,
        provider: str,
        models: tuple[str, ...],
        *,
        current: str = "",
        default: str = "",
    ) -> None:
        super().__init__()
        self.provider = provider
        self.models = tuple(models)
        self.current = current
        self.default = default

    def compose(self) -> ComposeResult:
        """List what the host holds, in the order it reported them."""

        with Vertical(id="model-browser"):
            if not self.models:
                yield Static("This host reported no models.")
                return
            yield OptionList(
                *(self.label_for(model) for model in self.models),
                id="model-list",
                markup=False,
            )

    def label_for(self, model: str) -> str:
        """One row: the model, and what it already is to this session.

        Both marks matter and they are not the same thing. *current* is what
        the session is on now, so choosing it changes nothing; *default* is
        what a bare ``--backend`` would have given, which is the one a person
        is comparing against when they came here to pick something else.
        """

        marks = []
        if model == self.current:
            marks.append("current")
        if model == self.default:
            marks.append("default")
        return f"{model}  · {', '.join(marks)}" if marks else model

    def on_mount(self) -> None:
        """Title the dialog and open the list on the model in use."""

        self.query_one("#model-browser").border_title = f"{self.provider} models"
        if not self.models:
            return
        option_list = self.query_one("#model-list", OptionList)
        if self.current in self.models:
            option_list.highlighted = self.models.index(self.current)
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the chosen model name to the owning application."""

        self.dismiss(self.models[event.option_index])
