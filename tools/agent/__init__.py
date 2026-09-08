"""Kepler's headless agent loop.

``tools.agent.engine.run_session`` drives a model backend from ``tools.llm``
over the tool registry and yields a stream of events; a ``Decision`` flows back
through an approver callable. The shim in ``tools/runner.py``, the Kepler
console in ``tools/tui/``, and the benchmark harness all consume that one
stream.

This package imports no UI toolkit -- no ``textual``, no ``rich`` -- which is
what keeps every tool callable from plain Python per
``docs/tool-architecture.md`` section 7. A test asserts it.
"""

from __future__ import annotations
