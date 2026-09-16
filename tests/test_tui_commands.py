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
