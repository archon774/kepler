"""Tool-schema translation into each provider dialect.

Phase 1a of docs/archive/model-backends.md, section 4.4.

The golden renderings under tests/fixtures/llm/schemas/ are the record of what
every provider sees for the live registry. Any change to tools/registry.py
shows up here as a reviewable diff in all four dialects at once -- including
whether it broke Gemini's OpenAPI subset.

Regenerate after an intended registry change with:

    KEPLER_REGEN_SCHEMA_GOLDEN=1 uv run pytest tests/test_llm_schema.py

then read every changed file before committing it.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from tools.llm import schema
from tools.registry import TOOL_SCHEMAS

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "llm" / "schemas"

_UNION = {
    "name": "probe",
    "description": "A synthetic probe tool.",
    "input_schema": {
        "type": "object",
        "properties": {
            "capped": {"type": "integer", "description": "a plain int"},
            "max_catalogs": {
                "type": ["integer", "null"],
                "description": "null means uncapped",
            },
            "radius": {"type": ["number", "null"], "description": "or null"},
            "table": {"type": "string", "enum": ["a", "b"], "description": "pick"},
            "fields": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["capped"],
    },
}

_EMPTY = {
    "name": "fake_lookup",
    "description": "Fake lookup.",
    "input_schema": {"type": "object", "properties": {}},
}


# --- Anthropic ------------------------------------------------------------


def test_anthropic_translation_is_not_the_identity_function():
    source = [copy.deepcopy(_UNION)]
    out = schema.to_anthropic(source)
    out[0]["input_schema"]["properties"]["capped"]["type"] = "MUTATED"
    assert source[0]["input_schema"]["properties"]["capped"]["type"] == "integer"


def test_anthropic_preserves_the_envelope_and_the_schema():
    out = schema.to_anthropic([copy.deepcopy(_UNION)])
    assert set(out[0]) == {"name", "description", "input_schema"}
    assert out[0]["input_schema"] == _UNION["input_schema"]


def test_anthropic_handles_the_empty_properties_gate_schema():
    out = schema.to_anthropic([copy.deepcopy(_EMPTY)])
    assert out[0]["input_schema"] == {"type": "object", "properties": {}}


def test_anthropic_does_not_mutate_the_registry_list():
    before = json.dumps(TOOL_SCHEMAS, sort_keys=True)
    schema.to_anthropic(TOOL_SCHEMAS)
    assert json.dumps(TOOL_SCHEMAS, sort_keys=True) == before


# --- OpenAI / Ollama ---------------------------------------------------


def test_openai_wraps_each_tool_in_a_function_envelope():
    out = schema.to_openai([copy.deepcopy(_UNION)])
    assert out[0]["type"] == "function"
    fn = out[0]["function"]
    assert fn["name"] == "probe"
    assert fn["description"] == "A synthetic probe tool."
    assert fn["parameters"] == _UNION["input_schema"]


def test_openai_non_strict_passes_the_union_through_untouched():
    out = schema.to_openai([copy.deepcopy(_UNION)])
    props = out[0]["function"]["parameters"]["properties"]
    assert props["max_catalogs"]["type"] == ["integer", "null"]
    assert props["radius"]["type"] == ["number", "null"]


def test_openai_non_strict_does_not_force_required_or_additional_properties():
    out = schema.to_openai([copy.deepcopy(_UNION)])
    params = out[0]["function"]["parameters"]
    assert params["required"] == ["capped"]
    assert "additionalProperties" not in params
    assert "strict" not in out[0]["function"]


def test_openai_strict_seals_the_object_and_lists_every_property():
    out = schema.to_openai([copy.deepcopy(_UNION)], strict=True)
    fn = out[0]["function"]
    assert fn["strict"] is True
    params = fn["parameters"]
    assert params["additionalProperties"] is False
    assert set(params["required"]) == set(params["properties"])


def test_openai_strict_is_not_the_default():
    out = schema.to_openai([copy.deepcopy(_UNION)])
    assert "strict" not in out[0]["function"]
    assert "additionalProperties" not in out[0]["function"]["parameters"]


# --- Gemini ----------------------------------------------------------


def test_gemini_envelope_is_a_single_function_declarations_block():
    out = schema.to_gemini([copy.deepcopy(_UNION)])
    assert list(out[0]) == ["functionDeclarations"]
    decl = out[0]["functionDeclarations"][0]
    assert set(decl) == {"name", "description", "parameters"}


def test_gemini_uppercases_openapi_types():
    out = schema.to_gemini([copy.deepcopy(_UNION)])
    props = out[0]["functionDeclarations"][0]["parameters"]["properties"]
    assert out[0]["functionDeclarations"][0]["parameters"]["type"] == "OBJECT"
    assert props["capped"]["type"] == "INTEGER"
    assert props["table"]["type"] == "STRING"
    assert props["fields"]["type"] == "ARRAY"
    assert props["fields"]["items"]["type"] == "STRING"
    assert props["rows"]["items"]["type"] == "OBJECT"


def test_gemini_rewrites_the_integer_or_null_union_to_a_nullable_integer():
    out = schema.to_gemini([copy.deepcopy(_UNION)])
    prop = out[0]["functionDeclarations"][0]["parameters"]["properties"]["max_catalogs"]
    assert prop["type"] == "INTEGER"
    assert prop["nullable"] is True


def test_gemini_never_downgrades_the_union_to_a_plain_scalar():
    out = schema.to_gemini([copy.deepcopy(_UNION)])
    props = out[0]["functionDeclarations"][0]["parameters"]["properties"]
    # A plain integer would have no "nullable" key at all -- that is the
    # downgrade the benchmark exists to catch, and it must never happen here.
    assert props["max_catalogs"].get("nullable") is True
    assert props["radius"]["type"] == "NUMBER"
    assert props["radius"]["nullable"] is True
    assert props["capped"].get("nullable") is None


def test_gemini_preserves_enum_on_a_string():
    out = schema.to_gemini([copy.deepcopy(_UNION)])
    prop = out[0]["functionDeclarations"][0]["parameters"]["properties"]["table"]
    assert prop["enum"] == ["a", "b"]


def test_gemini_drops_keywords_its_subset_cannot_express():
    noisy = copy.deepcopy(_UNION)
    noisy["input_schema"]["additionalProperties"] = False
    noisy["input_schema"]["properties"]["capped"]["format"] = "int64"
    noisy["input_schema"]["properties"]["table"]["pattern"] = "^[ab]$"
    out = schema.to_gemini([noisy])
    params = out[0]["functionDeclarations"][0]["parameters"]
    assert "additionalProperties" not in params
    assert "format" not in params["properties"]["capped"]
    assert "pattern" not in params["properties"]["table"]


# --- dispatch and purity --------------------------------------------


def test_for_dialect_dispatches_on_the_backend_dialect():
    src = [copy.deepcopy(_UNION)]
    assert schema.for_dialect("json_schema", src) == schema.to_anthropic(src)
    assert schema.for_dialect("openai_function", src) == schema.to_openai(src)
    assert schema.for_dialect("gemini_openapi", src) == schema.to_gemini(src)


def test_for_dialect_rejects_an_unknown_dialect():
    with pytest.raises(ValueError):
        schema.for_dialect("mystery", [copy.deepcopy(_UNION)])


@pytest.mark.parametrize("fn", ["to_anthropic", "to_openai", "to_gemini"])
def test_translations_are_pure(fn):
    src = [copy.deepcopy(_UNION), copy.deepcopy(_EMPTY)]
    snapshot = json.dumps(src, sort_keys=True)
    first = json.dumps(getattr(schema, fn)(src), sort_keys=True)
    second = json.dumps(getattr(schema, fn)(src), sort_keys=True)
    assert first == second
    assert json.dumps(src, sort_keys=True) == snapshot


# --- golden byte-stability ----------------------------------------


def _render() -> dict[str, object]:
    return {
        "anthropic.json": schema.to_anthropic(TOOL_SCHEMAS),
        "openai.json": schema.to_openai(TOOL_SCHEMAS),
        "openai_strict.json": schema.to_openai(TOOL_SCHEMAS, strict=True),
        "gemini.json": schema.to_gemini(TOOL_SCHEMAS),
    }


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", ["anthropic.json", "openai.json", "openai_strict.json", "gemini.json"])
def test_golden_dialect_rendering_is_byte_stable(name):
    rendered = _dump(_render()[name])
    path = GOLDEN / name
    if os.environ.get("KEPLER_REGEN_SCHEMA_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        pytest.skip(f"regenerated {name}")
    assert path.read_text(encoding="utf-8") == rendered, (
        f"{name} is stale. Regenerate with "
        "KEPLER_REGEN_SCHEMA_GOLDEN=1 uv run pytest tests/test_llm_schema.py "
        "and review the diff in every dialect."
    )
