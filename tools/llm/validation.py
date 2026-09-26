"""Pre-dispatch argument validation (S8).

Hand-rolled -- no ``jsonschema`` dependency, and none is needed: every registry
schema is a flat object with scalar, enum, and array-of-scalar/object
properties. The rules and their evaluation order are
``docs/archive/model-backends.md`` S8. Two are the whole point:

* The string ``"None"`` is never coerced to ``None``. A ``stringified_null``
  fault on a null-accepting property is the highest-value signal in the
  taxonomy.
* A fault is a result returned to the model, not an exception. The caller
  records it, hands the model an error result, and continues the loop.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Iterable, Mapping

from tools.llm.types import ProtocolFault

__all__ = ["index_schemas", "validate_tool_call"]

#: Case-folded strings a model sends when it means JSON ``null`` and gets it
#: wrong -- the confirmed-live failure ``SYSTEM_PROMPT`` documents.
_STRINGY_NULLS = {"none", "null", "nil"}

#: Distinguishes "the caller did not pass a function" from "the function is
#: genuinely missing" for the ``func`` argument of :func:`validate_tool_call`.
_UNSET: Any = object()


def index_schemas(
    schemas: Iterable[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """Build the by-name ``{tool: input_schema}`` index once per run."""

    return {schema["name"]: schema.get("input_schema", {}) for schema in schemas}


def validate_tool_call(
    name: str,
    arguments: Any,
    index: Mapping[str, Mapping[str, Any]],
    *,
    call_id: str | None = None,
    func: Callable[..., Any] | None = _UNSET,
) -> ProtocolFault | None:
    """Return the first :class:`ProtocolFault` a call trips, or ``None``.

    The checks run in the S8 order. A declared but empty ``properties``
    object means the tool takes no arguments, whatever its callable accepts.
    An absent one means the schema does not constrain the shape; when the
    tool's callable is supplied as ``func``, its signature is the fallback
    constraint, so a call with junk arguments still faults cleanly instead of
    raising a ``TypeError`` at dispatch. ``func=None`` (as opposed to omitted) means the
    name has a schema but no registered function -- an ``unknown_tool`` fault.
    """

    def fault(kind: str, detail: str) -> ProtocolFault:
        return ProtocolFault(
            type=kind, detail=detail, tool_name=name, call_id=call_id
        )

    if name not in index:
        return fault("unknown_tool", f"{name!r} is not a registered tool")

    if func is not _UNSET and func is None:
        return fault(
            "unknown_tool", f"{name!r} has a schema but no registered function"
        )

    schema = index[name]
    if not isinstance(arguments, Mapping):
        return fault("schema_violation", "arguments are not a JSON object")

    properties: Mapping[str, Any] = schema.get("properties", {}) or {}
    for required in schema.get("required", []) or []:
        if required not in arguments:
            return fault(
                "schema_violation", f"missing required property {required!r}"
            )

    if "properties" in schema and not properties and arguments:
        # Declared empty: the tool takes no arguments from a model. The
        # function's signature is no licence -- several of these listers take
        # a `directory` keyword their schema leaves out on purpose, and the
        # signature fallback let a model reach it. The MCP server refuses the
        # same call (additionalProperties: false); the two surfaces agree.
        return fault(
            "schema_violation",
            f"{name!r} takes no arguments; got {sorted(arguments)}",
        )

    if not properties:
        if func not in (_UNSET, None) and arguments:
            try:
                inspect.signature(func).bind(**arguments)
            except TypeError as exc:
                return fault(
                    "schema_violation",
                    f"{name!r} does not accept {sorted(arguments)}: {exc}",
                )
        return None

    for key, value in arguments.items():
        if key not in properties:
            return fault("schema_violation", f"unknown property {key!r}")

        prop = properties[key]
        declared = _type_list(prop.get("type"))

        if _is_stringy_null(value) and "null" in declared:
            return fault(
                "stringified_null",
                f"{key!r} was the string {value!r}; pass JSON null for no cap",
            )

        if declared and not _type_matches(value, declared):
            return fault(
                "schema_violation",
                f"{key!r} is {_json_type(value)}, expected {sorted(declared)}",
            )

        if "enum" in prop and value not in prop["enum"]:
            return fault(
                "schema_violation", f"{key!r}={value!r} is not one of {prop['enum']}"
            )

        if "array" in declared and isinstance(value, list):
            item_types = _type_list(prop.get("items", {}).get("type"))
            if item_types and any(
                not _type_matches(item, item_types) for item in value
            ):
                return fault(
                    "schema_violation",
                    f"{key!r} has an element that is not {sorted(item_types)}",
                )

    return None


def _type_list(declared: Any) -> set[str]:
    if declared is None:
        return set()
    if isinstance(declared, str):
        return {declared}
    return {entry for entry in declared if isinstance(entry, str)}


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _type_matches(value: Any, declared: set[str]) -> bool:
    actual = _json_type(value)
    if actual in declared:
        return True
    # JSON has one numeric type: a whole number arrives as int, and an int is
    # acceptable wherever `number` is declared. A bool is NOT -- Python's bool
    # is an int subclass, so `_json_type` already separated it out above.
    if actual == "integer" and "number" in declared:
        return True
    return False


def _is_stringy_null(value: Any) -> bool:
    return isinstance(value, str) and value.lower() in _STRINGY_NULLS
