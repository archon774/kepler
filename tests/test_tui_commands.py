"""Headless behavior of the TUI slash-command registry."""

from __future__ import annotations

import ast
from pathlib import Path

from tools.tui import commands


def test_parse_input_distinguishes_messages_commands_and_unknown_commands():
    assert commands.parse_input("M31").kind == "message"

    parsed = commands.parse_input("/status verbose")
    assert parsed.kind == "command"
    assert parsed.name == "status"
    assert parsed.args == ("verbose",)

    unknown = commands.parse_input("/nope")
    assert unknown.kind == "unknown"
    assert unknown.name == "nope"


def test_double_slash_escapes_a_literal_message_prefix():
    parsed = commands.parse_input("//catalog path")

    assert parsed.kind == "message"
    assert parsed.text == "/catalog path"


def test_resolve_accepts_names_and_declared_aliases():
    assert commands.resolve("help") is commands.resolve("?")
    assert commands.resolve("quit") is commands.resolve("q")
    assert commands.resolve("missing") is None


def test_help_text_is_generated_from_every_command():
    help_text = commands.help_text()

    for name in (
        "help",
        "artifacts",
        "sessions",
        "resume",
        "status",
        "backend",
        "tools",
        "approve",
        "prompt",
        "new",
        "quit",
    ):
        assert f"/{name}" in help_text


def test_command_registry_has_no_textual_import():
    source = Path(commands.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        for alias in (
            node.names
            if isinstance(node, ast.Import)
            else ()
        )
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not {name for name in imports if name.startswith("textual")}


def test_a_bare_slash_offers_every_command():
    """Typing the character that starts a command is the discovery path."""

    offered = [suggestion.value for suggestion in commands.suggest("/")]

    assert offered == [f"/{command.name}" for command in commands.COMMANDS]
    assert all(suggestion.help for suggestion in commands.suggest("/"))


def test_a_prefix_narrows_the_offers_to_what_it_could_still_become():
    assert [s.value for s in commands.suggest("/bac")] == ["/backend"]
    assert [s.value for s in commands.suggest("/s")] == ["/sessions", "/status"]
    assert commands.suggest("/zzz") == ()


def test_an_alias_matches_but_the_name_is_what_gets_completed():
    """`/q` is a shortcut for typing, not a second name to learn."""

    assert [s.value for s in commands.suggest("/q")] == ["/quit"]
    assert commands.complete("/q") == "/quit "


def test_nothing_is_offered_for_a_message_or_an_escaped_slash():
    assert commands.suggest("M31") == ()
    assert commands.suggest("//catalog") == ()
    assert commands.complete("M31") == "M31"


def test_one_match_completes_whole_and_runs_on_into_its_arguments():
    assert commands.complete("/bac") == "/backend "
    assert [s.value for s in commands.suggest("/backend ")] == ["anthropic", "ollama"]
    assert commands.complete("/backend o") == "/backend ollama "


def test_several_matches_extend_only_as_far_as_they_agree():
    """The shell rule. Guessing between equal candidates is how a completion
    puts a command nobody asked for into the prompt."""

    assert commands.complete("/s") == "/s"
    assert commands.complete("/") == "/"


def test_a_command_without_a_completer_offers_nothing_for_its_arguments():
    assert commands.suggest("/resume 2026") == ()
