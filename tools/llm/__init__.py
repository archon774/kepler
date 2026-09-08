"""Kepler's provider-neutral model port.

Two rules govern the design:

    The core owns the loop; adapters own the dialect.
    Replay the tools, never the model.

This package is import-light on purpose: importing it pulls in no provider SDK
and no HTTP stack. Adapters (``anthropic_backend``, ``openai_backend``,
``ollama_backend``, ``gemini_backend``) are imported explicitly by the factory,
never at package scope. See ``docs/working/model-backends.md``.
"""

from __future__ import annotations

from tools.llm.base import (
    SCHEMA_DIALECTS,
    BackendUnavailableError,
    Capabilities,
    ModelBackend,
    OnText,
    SchemaDialect,
)
from tools.llm.types import (
    FAULT_TYPES,
    STOP_REASONS,
    Block,
    FaultType,
    Message,
    ModelResponse,
    ProtocolFault,
    Role,
    StopReason,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    Usage,
)

__all__ = [
    "TextBlock",
    "ToolCallBlock",
    "ToolResultBlock",
    "Block",
    "Role",
    "Message",
    "Usage",
    "StopReason",
    "STOP_REASONS",
    "FaultType",
    "FAULT_TYPES",
    "ProtocolFault",
    "ModelResponse",
    "SchemaDialect",
    "SCHEMA_DIALECTS",
    "Capabilities",
    "OnText",
    "BackendUnavailableError",
    "ModelBackend",
]
