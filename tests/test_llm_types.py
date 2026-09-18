"""Neutral model-port types: the currency every adapter speaks.

Phase 0a of docs/archive/model-backends.md, section 4.1 and 4.6. These types
carry no provider dialect, do no I/O, and import no vendor SDK.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from tools import llm
from tools.llm import types as llm_types


def test_text_block_is_frozen():
    block = llm_types.TextBlock(text="hello")
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.text = "world"


def test_tool_call_block_keeps_arguments_as_a_mapping():
    call = llm_types.ToolCallBlock(
        call_id="call_0", name="search_simbad", arguments={"target": "M31"}
    )
    assert call.arguments == {"target": "M31"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        call.name = "other"


def test_tool_result_block_defaults_to_not_an_error():
    result = llm_types.ToolResultBlock(
        call_id="call_0", name="search_simbad", content="{}"
    )
    assert result.is_error is False


def test_message_stores_blocks_as_a_tuple_even_when_given_a_list():
    message = llm_types.Message(
        role="user", blocks=[llm_types.TextBlock(text="hi")]
    )
    assert isinstance(message.blocks, tuple)
    assert message.blocks[0].text == "hi"


def test_message_is_frozen():
    message = llm_types.Message(role="assistant", blocks=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        message.role = "user"


def test_message_rejects_a_system_role():
    with pytest.raises(ValueError):
        llm_types.Message(role="system", blocks=())


def test_usage_fields_absent_means_none_never_zero():
    usage = llm_types.Usage()
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.cache_read_tokens is None
    assert usage.cache_write_tokens is None
    assert usage.reasoning_tokens is None


def test_usage_is_frozen():
    usage = llm_types.Usage(input_tokens=10)
    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.input_tokens = 20


def test_stop_reason_is_a_closed_set():
    assert llm_types.STOP_REASONS == (
        "end_turn",
        "tool_use",
        "max_tokens",
        "refusal",
        "other",
    )


def test_fault_taxonomy_has_exactly_seven_values():
    assert llm_types.FAULT_TYPES == (
        "malformed_arguments_json",
        "schema_violation",
        "unknown_tool",
        "stringified_null",
        "call_id_mismatch",
        "empty_tool_call",
        "truncated_output",
    )


def test_protocol_fault_carries_its_context():
    fault = llm_types.ProtocolFault(
        type="stringified_null",
        detail="max_catalogs was the string 'None'",
        tool_name="search_vizier",
        call_id="call_1",
    )
    assert fault.type == "stringified_null"
    with pytest.raises(dataclasses.FrozenInstanceError):
        fault.detail = "changed"


def test_model_response_collection_defaults_are_empty_not_none():
    response = llm_types.ModelResponse(stop_reason="end_turn")
    assert response.tool_calls == ()
    assert response.faults == ()
    assert response.raw_stop_reason is None
    assert response.usage is None
    assert response.text == ""


def test_model_response_stores_tool_calls_as_a_tuple_from_a_list():
    call = llm_types.ToolCallBlock(call_id="c0", name="t", arguments={})
    response = llm_types.ModelResponse(stop_reason="tool_use", tool_calls=[call])
    assert isinstance(response.tool_calls, tuple)


def test_model_response_is_frozen():
    response = llm_types.ModelResponse(stop_reason="end_turn")
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.text = "mutated"


def test_types_module_imports_no_provider_sdk():
    source = Path(llm_types.__file__).read_text(encoding="utf-8")
    for name in ("anthropic", "httpx", "openai", "google"):
        assert name not in source, f"{name} leaked into tools/llm/types.py"


def test_package_reexports_the_neutral_types():
    for name in (
        "TextBlock",
        "ToolCallBlock",
        "ToolResultBlock",
        "Message",
        "Usage",
        "ProtocolFault",
        "ModelResponse",
        "ModelBackend",
        "Capabilities",
        "BackendUnavailableError",
    ):
        assert hasattr(llm, name), name
    assert len(llm.__all__) == len(set(llm.__all__)), "duplicate name in __all__"
    assert "ModelResponse" in llm.__all__


def test_importing_the_package_pulls_in_no_vendor_sdk():
    # A fresh interpreter: importing tools.llm must not import anthropic, httpx,
    # openai, or google. Run in a subprocess so another test's imports cannot
    # mask a regression here.
    code = (
        "import sys; import tools.llm; "
        "bad = [m for m in sys.modules "
        "if m.split('.')[0] in {'anthropic', 'httpx', 'openai', 'google'}]; "
        "print(bad); assert not bad, bad"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr
