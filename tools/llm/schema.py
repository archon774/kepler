"""Tool-schema translation: the registry's schemas rendered into each provider
dialect. Pure -- no I/O, every case a unit test. See
``docs/working/model-backends.md`` section 4.4.

Two rules the translations must never break:

* **The Anthropic translation is not the identity function.** It deep-copies,
  so a caller cannot mutate ``TOOL_SCHEMAS`` through the returned value.
* **The scalar-or-null union is never downgraded.** ``["integer", "null"]`` and
  ``["number", "null"]`` mean "pass JSON null for no cap"; ``SYSTEM_PROMPT``
  depends on that semantic. The Gemini translation rewrites the union to a
  *nullable* scalar; it never emits the bare form. A model's failure to use the
  union is a benchmark result, not a bug to paper over -- weak local models
  included.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = ["to_anthropic", "to_openai", "to_gemini", "for_dialect"]


# --- Anthropic -----------------------------------------------------------


def to_anthropic(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``name`` / ``description`` / ``input_schema``, JSON Schema, unchanged --
    but deep-copied, so the result cannot be used to mutate the input."""

    return [copy.deepcopy(schema) for schema in schemas]


# --- OpenAI / Ollama --------------------------------------------------


def to_openai(
    schemas: list[dict[str, Any]], *, strict: bool = False
) -> list[dict[str, Any]]:
    """Each tool wrapped as ``{"type": "function", "function": {...}}`` with
    ``input_schema`` moved to ``parameters``.

    ``strict=True`` builds the strict-mode variant -- ``additionalProperties:
    false`` and *every* property in ``required`` -- which turns optional
    parameters into mandatory ones, a semantic change. It is implemented and
    golden-tested but is **not** the default.
    """

    tools: list[dict[str, Any]] = []
    for schema in schemas:
        parameters = copy.deepcopy(schema["input_schema"])
        function: dict[str, Any] = {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": parameters,
        }
        if strict:
            _seal_strict(parameters)
            function["strict"] = True
        tools.append({"type": "function", "function": function})
    return tools


def _seal_strict(node: Any) -> None:
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "object" or (isinstance(node_type, list) and "object" in node_type):
        properties = node.get("properties", {})
        node["additionalProperties"] = False
        node["required"] = list(properties)
        for child in properties.values():
            _seal_strict(child)
    if node_type == "array":
        _seal_strict(node.get("items"))


# --- Gemini ---------------------------------------------------------


_OPENAPI_TYPES = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}

#: Keywords the Gemini OpenAPI 3.0 subset does not accept.
_GEMINI_UNSUPPORTED = {
    "additionalProperties",
    "$ref",
    "$defs",
    "$schema",
    "$id",
    "format",
    "pattern",
    "patternProperties",
}


def to_gemini(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A single ``functionDeclarations`` block. Types are the uppercase OpenAPI
    subset; a scalar-or-null union becomes a nullable scalar; keywords the
    subset cannot express are dropped."""

    declarations = [
        {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": _gemini_node(schema["input_schema"]),
        }
        for schema in schemas
    ]
    return [{"functionDeclarations": declarations}]


def _gemini_node(node: Any) -> Any:
    if not isinstance(node, dict):
        return copy.deepcopy(node)

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _GEMINI_UNSUPPORTED:
            continue
        if key == "type":
            out["type"] = _gemini_type(value)
            if isinstance(value, list) and "null" in value:
                out["nullable"] = True
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {
                name: _gemini_node(child) for name, child in value.items()
            }
        elif key == "items":
            out["items"] = _gemini_node(value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _gemini_type(value: Any) -> str:
    if isinstance(value, list):
        non_null = [entry for entry in value if entry != "null"]
        head = non_null[0] if non_null else "string"
        return _OPENAPI_TYPES.get(head, head.upper())
    return _OPENAPI_TYPES.get(value, str(value).upper())


# --- dispatch ------------------------------------------------------


def for_dialect(
    dialect: str, schemas: list[dict[str, Any]], *, strict: bool = False
) -> list[dict[str, Any]]:
    """Translate ``schemas`` for a backend's declared ``schema_dialect``."""

    if dialect == "json_schema":
        return to_anthropic(schemas)
    if dialect == "openai_function":
        return to_openai(schemas, strict=strict)
    if dialect == "gemini_openapi":
        return to_gemini(schemas)
    raise ValueError(f"unknown schema dialect: {dialect!r}")
