"""The MCP adapter: hands :mod:`tools.mcp.surface` to the ``mcp`` SDK.

Needs the optional ``mcp`` group (``uv sync --extra mcp``). It is the only
module under ``tools/mcp/`` that imports the SDK, and it adds no behaviour of
its own beyond two things the SDK's low-level server leaves to its caller:

- **Argument validation.** Every call is checked against the tool's registry
  schema before dispatch -- a stringified ``"None"`` on a null-accepting
  property first, with a message that says to send JSON ``null``, then the
  schema itself. A failure is the call's error result, never a raised
  exception, the same as a fault in the agent loop.
- **One call at a time.** Tool calls are dispatched to a worker thread, so the
  event loop keeps answering the host, but under a lock: every Kepler tool was
  written and tested to be called sequentially, and the stdio transport has
  one client (``docs/working/mcp-tool-surface.md`` §3.2).

Each result carries the payload twice, as the protocol recommends: as
``structuredContent`` and as the same JSON in a text block, for a host that
reads only text. No ``outputSchema`` is declared yet. A declared schema is
validated against by clients, and a result whose NaN serialised to ``null``
against a ``number`` field would then fail on a host rather than in a test.
"""

from __future__ import annotations

import functools
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable, Mapping, Sequence

import anyio
import jsonschema
import mcp_types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from tools.models import ToolError
from tools.mcp import surface
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

__all__ = ["build_server", "serve_stdio"]


def _package_version() -> str:
    try:
        return version("kepler")
    except PackageNotFoundError:
        return "0+unknown"


def _result(payload: Mapping[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=surface.to_json_text(payload))],
        structured_content=dict(payload),
        is_error=surface.result_is_error(payload),
    )


def _invalid(message: str) -> types.CallToolResult:
    return _result(surface.error_payload(ToolError(code="invalid_input", message=message)))


def build_server(
    schemas: Sequence[Mapping[str, Any]] = TOOL_SCHEMAS,
    functions: Mapping[str, Callable[..., Any]] = TOOL_FUNCTIONS,
    *,
    instructions: str | None = None,
) -> Server[Any]:
    """One server over every tool in ``schemas``, dispatching to ``functions``."""

    served = surface.served_tools(schemas)
    tools = [
        types.Tool(
            name=tool["name"],
            description=tool["description"],
            input_schema=tool["input_schema"],
        )
        for tool in served
    ]
    validators = {
        tool["name"]: jsonschema.Draft202012Validator(tool["input_schema"])
        for tool in served
    }
    lock = anyio.Lock()

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(
        ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        name = params.name
        arguments = dict(params.arguments or {})
        validator = validators.get(name)
        if validator is not None:
            stringy = surface.stringified_nulls(validator.schema, arguments)
            if stringy:
                return _invalid(
                    f"{', '.join(stringy)}: the text \"None\" is not null. Send the "
                    "JSON value null to lift a cap; omitting the argument keeps the "
                    "default."
                )
            error = jsonschema.exceptions.best_match(validator.iter_errors(arguments))
            if error is not None:
                where = "/".join(str(part) for part in error.absolute_path)
                return _invalid(f"{where + ': ' if where else ''}{error.message}")

        async with lock:
            payload = await anyio.to_thread.run_sync(
                functools.partial(surface.call_tool, name, arguments, functions)
            )
        return _result(payload)

    return Server(
        surface.SERVER_NAME,
        version=_package_version(),
        instructions=instructions,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def serve_stdio(server: Server[Any]) -> None:
    """Serve one host over this process's stdin and stdout until it disconnects."""

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
