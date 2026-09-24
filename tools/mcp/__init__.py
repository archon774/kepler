"""Kepler's MCP server: the registry, served over stdio to a host's own console.

A fourth consumer of ``tools/registry.py``, beside the agent loop, the
benchmark harness and the console (``docs/working/mcp-tool-surface.md``). It
is generated from ``TOOL_SCHEMAS``/``TOOL_FUNCTIONS`` and keeps no parallel
list; a test asserts the served names equal the registry's.

- :mod:`tools.mcp.roots` pins the artifact and data roots before anything
  imports ``tools.config``;
- :mod:`tools.mcp.surface` derives what is served, with no SDK import, so a
  plain ``uv run pytest`` tests it;
- :mod:`tools.mcp.server` adapts it to the ``mcp`` SDK, the optional
  ``[mcp]`` group;
- ``kepler-mcp`` (:mod:`tools.mcp.__main__`) is the entry point a host
  launches.

It imports nothing from ``tools/agent/`` or ``tools/llm/``: the dependency runs
``tools/mcp -> tools/registry``, parallel to the loop, not through it.

This package module imports nothing either. Importing ``tools.mcp`` must not
import ``tools.config``, or the roots would be resolved before they are pinned.
"""

__all__: list[str] = []
