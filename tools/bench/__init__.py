"""``tools.bench`` -- the model benchmark harness.

``docs/benchmarking/harness.md``. The harness answers two questions about swapping
one model for another on Kepler's tool surface: **which model is actually
better, and at what** (answer correctness), and **at what cost in work**
(efficiency). Everything else it reports exists to explain one of those.

It owns no tool and adds nothing to the tool surface. It reads
``tools/registry.py``'s schemas, substitutes ``run_session``'s
``tool_functions=`` mapping, and grades the session manifest the engine already
writes. The dependency runs one way: ``tools.bench`` -> ``tools.agent`` ->
``tools.llm`` -> ``tools.registry``. Nothing under ``algorithms/`` or
``tools/llm/`` imports this package.

Import-light on purpose: the names below are re-exported lazily, so
``import tools.bench`` costs no YAML parse and no registry import.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "TOOL_CLASSES",
    "ToolClass",
    "build_tool_plane",
    "classify_call",
    "FixtureStore",
    "load_fixture_file",
]


def __getattr__(name: str) -> Any:
    if name in ("TOOL_CLASSES", "ToolClass", "build_tool_plane", "classify_call"):
        from tools.bench import plane

        return getattr(plane, name)
    if name in ("FixtureStore", "load_fixture_file"):
        from tools.bench import fixtures

        return getattr(fixtures, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
