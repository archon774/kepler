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
    "parse_input",
    "resolve",
    "help_text",
]

Completer = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class Command:
    """One UI-level command and the application handler that performs it."""

    name: str
    help: str
    handler: str
    aliases: tuple[str, ...] = ()
    completer: Completer | None = None


@dataclass(frozen=True)
class Parsed:
    """A message, known command, or unknown slash-command input."""

    kind: Literal["message", "command", "unknown"]
    text: str = ""
    name: str = ""
    args: tuple[str, ...] = ()


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
