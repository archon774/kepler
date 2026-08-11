"""Kepler: one thin tool module per astronomy database.

Each module validates input, calls one thing (an astroquery/psrqpy service, or
a shared helper), and returns a ``kepler.models.ToolResult``: a bounded inline
preview plus, for anything larger, a path to the complete result written by
``kepler.artifacts``. See ``docs/tool-architecture.md``.

``kepler.tools.registry`` lists every tool schema together for wiring into an
agent loop; import the module you need directly otherwise.
"""

__all__: list[str] = []
