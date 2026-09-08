"""The ModelBackend protocol and its capability record.

Phase 0a of docs/working/model-backends.md, section 4.2.
"""

from __future__ import annotations

import dataclasses

import pytest

from tools.llm import base
from tools.llm.types import ModelResponse


def _capabilities() -> base.Capabilities:
    return base.Capabilities(
        streaming=False,
        parallel_tool_calls=True,
        native_tool_call_ids=True,
        schema_dialect="json_schema",
        supports_union_types=True,
        max_output_tokens=16384,
    )


def test_capabilities_is_frozen_and_complete():
    caps = _capabilities()
    for field in (
        "streaming",
        "parallel_tool_calls",
        "native_tool_call_ids",
        "schema_dialect",
        "supports_union_types",
        "max_output_tokens",
    ):
        assert hasattr(caps, field), field
    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.streaming = True


def test_schema_dialect_is_the_closed_three_value_set():
    assert set(base.SCHEMA_DIALECTS) == {
        "json_schema",
        "openai_function",
        "gemini_openapi",
    }


def test_backend_unavailable_error_names_the_variable_at_fault():
    err = base.BackendUnavailableError("OLLAMA_BASE_URL", "run `ollama serve`")
    assert err.variable == "OLLAMA_BASE_URL"
    assert "OLLAMA_BASE_URL" in str(err)
    assert "ollama serve" in str(err)


def test_a_minimal_conforming_object_is_a_model_backend():
    class Stub:
        spec = "stub/model"
        capabilities = _capabilities()

        def complete(
            self,
            *,
            messages,
            tools,
            system,
            max_tokens,
            temperature=0.0,
            on_text=None,
        ):
            return ModelResponse(stop_reason="end_turn")

    assert isinstance(Stub(), base.ModelBackend)


def test_an_object_without_complete_is_not_a_model_backend():
    class NotABackend:
        spec = "x/y"
        capabilities = _capabilities()

    assert not isinstance(NotABackend(), base.ModelBackend)


def test_base_module_imports_no_vendor_sdk_at_module_scope():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(base.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"anthropic", "httpx", "openai", "google"})
