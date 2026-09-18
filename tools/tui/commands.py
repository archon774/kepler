"""Declarative slash commands for the Kepler console.

This module deliberately contains no Textual imports. Parsing and resolution
are reusable by the UI and directly testable without a terminal event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Literal

__all__ = [
    "Command",
    "COMMANDS",
    "Parsed",
    "Suggestion",
    "parse_input",
    "resolve",
    "help_text",
    "suggest",
    "complete",
]

#: Offers completions for a command's arguments. It is handed every argument
#: word typed so far, the last of which is the one being completed and may be
#: empty -- so a completer can answer differently for the first argument than
#: for the second. Filtering by that partial word is :func:`suggest`'s job.
Completer = Callable[[tuple[str, ...]], Iterable[str]]


@dataclass(frozen=True)
class Command:
    """One UI-level command and the application handler that performs it."""

    name: str
    help: str
    handler: str
    aliases: tuple[str, ...] = ()
    completer: Completer | None = None


@dataclass(frozen=True)
class Suggestion:
    """One completion the console offers for a partially typed line.

    Carries its own help text so the menu is generated from the registry the
    same way :func:`help_text` is, rather than describing the commands twice.
    """

    value: str
    help: str = ""


@dataclass(frozen=True)
class Parsed:
    """A message, known command, or unknown slash-command input."""

    kind: Literal["message", "command", "unknown"]
    text: str = ""
    name: str = ""
    args: tuple[str, ...] = ()


def _backend_completions(args: tuple[str, ...]) -> tuple[str, ...]:
    """The provider names first, then the models that provider holds.

    The second question is answered by the provider's host, so completing a
    model name asks the daemon what it has. That is a five-second question at
    worst (``OLLAMA_PROBE_TIMEOUT_S``) and only asked on Tab, and a host that
    will not answer offers nothing rather than blocking the key.

    Imported on call rather than at module scope. This registry is the
    import-light half of the console -- no Textual, and nothing that reaches
    the network until asked -- while :mod:`tools.tui.backends` pulls in the
    whole model port.
    """

    from tools.tui.backends import names, offered_models

    if len(args) <= 1:
        return names()
    if len(args) == 2:
        return offered_models(args[0])
    return ()


COMMANDS: tuple[Command, ...] = (
    Command("help", "List available commands.", "show_help", aliases=("?",)),
    Command("artifacts", "Browse session artifacts.", "show_artifacts", aliases=("a",)),
    Command("sessions", "Browse saved sessions.", "show_sessions", aliases=("s",)),
    Command("resume", "Resume a saved session.", "resume", aliases=("r",)),
    Command("status", "Show backend and session status.", "show_status"),
    Command(
        "backend",
        "Show the model backends, or switch to one (anthropic, ollama).",
        "switch_backend",
        aliases=("b",),
        completer=_backend_completions,
    ),
    Command("tools", "Browse registered tool schemas.", "show_tools", aliases=("t",)),
    Command("approve", "View or change approval policy.", "configure_approval"),
    Command("prompt", "Show the active system prompt.", "show_prompt", aliases=("p",)),
    Command("new", "Start a fresh session.", "new_session", aliases=("n",)),
    Command("quit", "Exit the console.", "quit", aliases=("q", "exit")),
)


def resolve(name: str) -> Command | None:
    """Return the command matching a name or alias, if any."""

    normalized = name.lstrip("/")
    for command in COMMANDS:
        if normalized == command.name or normalized in command.aliases:
            return command
    return None


def parse_input(text: str) -> Parsed:
    """Classify one submitted prompt without ever forwarding slash commands."""

    if text.startswith("//"):
        return Parsed(kind="message", text=text[1:])
    if not text.startswith("/"):
        return Parsed(kind="message", text=text)

    words = text[1:].split()
    if not words:
        return Parsed(kind="unknown")
    name, *args = words
    kind: Literal["command", "unknown"] = (
        "command" if resolve(name) is not None else "unknown"
    )
    return Parsed(kind=kind, name=name, args=tuple(args))


def help_text() -> str:
    """Return a generated, human-readable list of every command."""

    lines = []
    for command in COMMANDS:
        aliases = "".join(f", /{alias}" for alias in command.aliases)
        lines.append(f"/{command.name}{aliases} — {command.help}")
    return "\n".join(lines)


def suggest(text: str) -> tuple[Suggestion, ...]:
    """Offer what a partially typed line could still become.

    A bare ``/`` offers every command, which is the point: the registry is
    discoverable by typing the character that starts one, rather than by
    remembering to ask ``/help`` first. Once the command word is finished the
    offers come from that command's own completer, if it declares one.

    Aliases match but are never offered as the completion. ``/q`` finds
    ``quit`` and completes to ``/quit`` -- the short form stays a shortcut for
    typing, and what lands in the prompt is the name the help text lists.
    """

    if not text.startswith("/") or text.startswith("//"):
        return ()

    body = text[1:]
    if " " not in body:
        prefix = body.lower()
        return tuple(
            Suggestion(f"/{command.name}", command.help)
            for command in COMMANDS
            if command.name.startswith(prefix)
            or any(alias.startswith(prefix) for alias in command.aliases)
        )

    words = body.split()
    command = resolve(words[0]) if words else None
    if command is None or command.completer is None:
        return ()
    arguments = tuple(words[1:]) + (("",) if body.endswith(" ") else ())
    partial = arguments[-1] if arguments else ""
    return tuple(
        Suggestion(value)
        for value in command.completer(arguments)
        if value.startswith(partial)
    )


def complete(text: str) -> str:
    """Return the line Tab should leave behind, completed as far as it can go.

    One match is filled in whole and given a trailing space, so completing a
    command runs straight on into completing its first argument. Several
    matches extend only as far as they agree, leaving the rest to the menu --
    the shell behaviour, chosen because guessing between equal candidates is
    how a completion puts a command nobody asked for into the prompt.
    """

    matches = suggest(text)
    if not matches:
        return text

    values = [match.value for match in matches]
    if len(values) == 1:
        return _replace_last_token(text, values[0]) + " "

    shared = _shared_prefix(values)
    extended = _replace_last_token(text, shared)
    return extended if len(extended) > len(text) else text


def _replace_last_token(text: str, value: str) -> str:
    """Swap the word Tab was pressed inside for a completion of it."""

    if " " not in text:
        # The command word, whose completions carry their own leading slash.
        return value
    head, _, _ = text.rpartition(" ")
    return f"{head} {value}"


def _shared_prefix(values: list[str]) -> str:
    """The longest prefix every candidate agrees on."""

    shortest = min(values, key=len)
    for index, character in enumerate(shortest):
        if any(value[index] != character for value in values):
            return shortest[:index]
    return shortest
