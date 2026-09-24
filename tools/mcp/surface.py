"""The served surface, derived from ``tools/registry.py`` and nothing else.

Everything here is independent of the ``mcp`` SDK, so the parts that decide
*what* is served -- the tool list, the argument pre-check, the result shape --
are tested by a plain ``uv run pytest`` that never installs the optional
group. ``tools.mcp.server`` is the thin adapter that hands them to the SDK.

The registry is the single source of truth: this module reads
``TOOL_SCHEMAS``/``TOOL_FUNCTIONS`` and keeps no list of its own.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

import pydantic_core

from tools.models import ToolError, ToolResult
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

__all__ = [
    "SERVER_NAME",
    "call_tool",
    "error_payload",
    "normalize_result",
    "result_is_error",
    "served_tools",
    "stringified_nulls",
    "to_json_text",
]

SERVER_NAME = "kepler"

#: Case-folded strings a model sends when it means JSON ``null`` -- the
#: confirmed-live failure ``SYSTEM_PROMPT`` and the skill both warn about.
#: ``tools/llm/validation.py`` holds the same set for the agent loop; this
#: surface does not import ``tools/llm/``, so it states it again.
_STRINGY_NULLS = frozenset({"none", "null", "nil"})


def served_tools(
    schemas: Sequence[Mapping[str, Any]] = TOOL_SCHEMAS,
) -> list[dict[str, Any]]:
    """One ``{name, description, input_schema}`` per registered tool, in order."""

    return [
        {
            "name": schema["name"],
            "description": schema["description"],
            "input_schema": schema["input_schema"],
        }
        for schema in schemas
    ]


def stringified_nulls(
    input_schema: Mapping[str, Any], arguments: Mapping[str, Any]
) -> list[str]:
    """Arguments that send the *text* ``"None"`` where the schema accepts ``null``.

    A JSON Schema check alone does not catch this on a property typed
    ``["string", "null"]``, and on an ``["integer", "null"]`` one it reports a
    type mismatch that does not say what went wrong. Named here so the error
    can say it: send JSON ``null``, not the string.
    """

    properties = input_schema.get("properties") or {}
    found = []
    for name, value in arguments.items():
        declared = (properties.get(name) or {}).get("type")
        accepts_null = declared == "null" or (
            isinstance(declared, list) and "null" in declared
        )
        if accepts_null and isinstance(value, str) and value.casefold() in _STRINGY_NULLS:
            found.append(name)
    return found


def normalize_result(name: str, value: Any) -> dict[str, Any]:
    """Serialize one tool's return value into a JSON object.

    Mirrors ``tools/agent/engine.py::_normalize_result``, which this surface
    may not import: a Kepler model becomes its fields, and the three tools that
    return a bare ``list`` of models are wrapped as ``{status, count,
    results}``. Serialization goes through ``pydantic_core.to_json`` rather
    than ``model_dump()``, so a NaN or infinity becomes ``null`` and a path or
    timestamp becomes a string -- structured content has to be valid JSON,
    and ``json.dumps`` of a raw dump is not.
    """

    if isinstance(value, (list, tuple)):
        items = json.loads(pydantic_core.to_json(list(value)))
        return {"status": "ok", "count": len(items), "results": items}
    if callable(getattr(value, "model_dump", None)):
        return json.loads(pydantic_core.to_json(value))
    raise TypeError(
        f"tool {name!r} returned {type(value).__name__}; a registered tool must "
        "return a Kepler model or a list of them"
    )


def result_is_error(payload: Mapping[str, Any]) -> bool:
    """The agent loop's rule: a result is an error when its status says so."""

    return payload.get("status") == "error"


def error_payload(error: ToolError) -> dict[str, Any]:
    """A ``ToolResult`` error for a call that never reached, or never finished, a tool.

    Takes a constructed :class:`ToolError` rather than a code, so every code
    stays a literal at its construction site where ``tests/test_tool_codes.py``
    can see it.
    """

    return normalize_result("", ToolResult(status="error", errors=[error]))


def to_json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def call_tool(
    name: str,
    arguments: Mapping[str, Any],
    functions: Mapping[str, Callable[..., Any]] = TOOL_FUNCTIONS,
) -> dict[str, Any]:
    """Dispatch one call and return its JSON payload; never raises.

    Schema validation is the adapter's job and has already run. An unknown
    name and a tool that raises both come back as error payloads, so a single
    bad call ends that call, not the session.
    """

    function = functions.get(name)
    if function is None:
        return error_payload(
            ToolError(code="unknown_tool", message=f"No tool named {name!r} is served.")
        )
    try:
        return normalize_result(name, function(**arguments))
    except Exception as exc:  # noqa: BLE001 -- reported to the caller, not swallowed
        return error_payload(
            ToolError(code="tool_exception", message=f"{type(exc).__name__}: {exc}")
        )
