"""The declared code vocabulary matches what the tools actually construct.

``tools/codes.py`` names every ``ToolError.code`` and ``ToolWarning.code`` this
surface raises. This module is what stops it becoming a stale list: it walks
the AST of ``tools/`` and ``algorithms/`` and compares what is constructed
against what is declared, in both directions.

Three construction forms have to be collected, and missing any one of them is
how ``docs/analysis/applicable-designs.md`` §3 came to report three error codes
where there are 41:

1. ``ToolError(code="x", ...)`` / ``ToolWarning(code="x", ...)``;
2. a ``{"code": "x", "message": ...}`` dict literal passed to ``errors=`` or
   ``warnings=`` -- how every class-R database tool builds an error;
3. a code passed through a module-local helper, which the two indirect
   constructors below name explicitly. A dynamic ``code=`` that is neither is a
   failure here rather than a silent gap.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.codes import TOOL_ERROR_CODES, TOOL_WARNING_CODES

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCANNED = ("tools", "algorithms")

#: Helpers that take a code as a positional argument and construct the model
#: themselves. ``(module, callee, argument index, model)``. These exist because
#: a tool re-raises a code carried on an exception rather than writing a
#: literal at the ``ToolError(...)`` call -- see ``tools/pulsar.py``'s
#: ``_LoadError`` and ``tools/variable_star.py``'s ``_error``.
_INDIRECT = (
    ("tools/pulsar.py", "_LoadError", 0, "ToolError"),
    ("tools/variable_star.py", "_error", 1, "ToolError"),
)

#: Call sites whose ``code=`` is a variable rather than a literal, resolved by
#: an entry in ``_INDIRECT`` instead. Keyed by path so a *new* dynamic site
#: fails this test rather than quietly widening the vocabulary.
_DYNAMIC_SITES = {"tools/pulsar.py", "tools/variable_star.py"}


def _relative(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _python_files() -> list[Path]:
    files: list[Path] = []
    for package in _SCANNED:
        files.extend(sorted((_REPO_ROOT / package).rglob("*.py")))
    return files


def _collect() -> tuple[dict[str, set[str]], set[str]]:
    """Return ``{"ToolError": {code, ...}, "ToolWarning": {...}}`` and the set
    of files holding a ``code=`` this scan could not read as a literal."""

    found: dict[str, set[str]] = {"ToolError": set(), "ToolWarning": set()}
    dynamic: set[str] = set()

    for path in _python_files():
        rel = _relative(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))

        indirect = {
            (callee, index): model
            for source, callee, index, model in _INDIRECT
            if source == rel
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func.id if isinstance(node.func, ast.Name) else None

            # Form 1 -- a direct model construction.
            if callee in found:
                keywords = {kw.arg: kw.value for kw in node.keywords}
                code = keywords.get("code") or (node.args[0] if node.args else None)
                if isinstance(code, ast.Constant):
                    found[callee].add(code.value)
                else:
                    dynamic.add(rel)
                continue

            # Form 3 -- a module-local helper that constructs the model.
            for (name, index), model in indirect.items():
                if callee == name and len(node.args) > index:
                    argument = node.args[index]
                    if isinstance(argument, ast.Constant):
                        found[model].add(argument.value)

        # Form 2 -- a dict literal passed to errors= or warnings=.
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg not in ("errors", "warnings"):
                continue
            model = "ToolError" if node.arg == "errors" else "ToolWarning"
            for element in ast.walk(node.value):
                if not isinstance(element, ast.Dict):
                    continue
                for key, value in zip(element.keys, element.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "code"
                        and isinstance(value, ast.Constant)
                    ):
                        found[model].add(value.value)

    return found, dynamic


def test_every_constructed_code_is_declared():
    found, _ = _collect()
    undeclared = {
        "ToolError": found["ToolError"] - set(TOOL_ERROR_CODES),
        "ToolWarning": found["ToolWarning"] - set(TOOL_WARNING_CODES),
    }
    assert undeclared == {"ToolError": set(), "ToolWarning": set()}, (
        "a code is constructed that tools/codes.py does not declare. Declare it "
        "with a one-line meaning, or reuse an existing code if a caller would "
        f"act on it the same way: {undeclared}"
    )


def test_every_declared_code_is_constructed():
    found, _ = _collect()
    unused = {
        "ToolError": set(TOOL_ERROR_CODES) - found["ToolError"],
        "ToolWarning": set(TOOL_WARNING_CODES) - found["ToolWarning"],
    }
    assert unused == {"ToolError": set(), "ToolWarning": set()}, (
        "tools/codes.py declares a code no tool raises. A vocabulary that lists "
        "codes a caller will never see is worse than no vocabulary, because a "
        f"model reads it as a promise: {unused}"
    )


def test_no_new_dynamic_code_site_appears():
    """A ``code=`` built from a variable is readable only through ``_INDIRECT``.

    A new one somewhere else would silently escape both assertions above, so it
    fails here instead and gets an ``_INDIRECT`` entry in the same commit.
    """

    _, dynamic = _collect()
    assert dynamic == _DYNAMIC_SITES


def test_declarations_are_one_line_sentences():
    for name, codes in (("TOOL_ERROR_CODES", TOOL_ERROR_CODES), ("TOOL_WARNING_CODES", TOOL_WARNING_CODES)):
        for code, meaning in codes.items():
            assert code == code.lower() and code.replace("_", "").isalnum(), (
                f"{name}[{code!r}] is not a lower_snake_case identifier"
            )
            assert "\n" not in meaning and meaning.endswith("."), (
                f"{name}[{code!r}] should be one sentence ending in a period"
            )
