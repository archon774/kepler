"""The headless agent package must remain independent of the TUI."""

from __future__ import annotations

import ast
from pathlib import Path

import tools.agent as agent


def _imports(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is_ui_import(name: str) -> bool:
    return name == "rich" or name.startswith(("rich.", "textual", "tools.tui"))


def test_agent_package_imports_no_ui_modules():
    package = Path(agent.__file__).resolve().parent
    imports = {
        imported
        for module_path in package.glob("*.py")
        for imported in _imports(module_path)
    }

    assert not {name for name in imports if _is_ui_import(name)}
