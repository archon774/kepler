"""The MCP adapter: hands :mod:`tools.mcp.surface` to the ``mcp`` SDK.

Needs the optional ``mcp`` group (``uv sync --extra mcp``). It is the only
module under ``tools/mcp/`` that imports the SDK, and it adds no behaviour of
its own beyond two things the SDK's low-level server leaves to its caller:

- **Argument validation.** Every call is checked against the tool's registry
  schema before dispatch -- a stringified ``"None"`` on a null-accepting
  property first, with a message that says to send JSON ``null``, then the
  schema itself. A failure is the call's error result, never a raised
  exception, the same as a fault in the agent loop.
- **The skill** (C5): the instructions are ``surface.served_instructions()``
  -- the skill brief and this install's facts -- and the skill's documents are
  resources, ``kepler://skill/...``, read on demand.
- **One call at a time.** Tool calls are dispatched to a worker thread, so the
  event loop keeps answering the host, but under a lock: every Kepler tool was
  written and tested to be called sequentially, and the stdio transport has
  one client (``docs/archive/mcp-tool-surface.md`` §3.2).

Each result carries the payload twice, as the protocol recommends: as
``structuredContent`` and as the same JSON in a text block, for a host that
reads only text. After the text come the PNG and WAV artifacts the result
names, as image and audio content (C4) -- :func:`surface.inline_media` decides
which, and the ``ArtifactRef`` paths stay in the payload either way. No ``outputSchema`` is declared yet. A declared schema is
validated against by clients, and a result whose NaN serialised to ``null``
against a ``number`` field would then fail on a host rather than in a test.
"""

from __future__ import annotations

import functools
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import anyio
import jsonschema
import mcp_types as types
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.server.stdio import stdio_server

from tools import config
from tools.models import ToolError
from tools.mcp import surface
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

__all__ = ["build_server", "serve_stdio"]


def _package_version() -> str:
    try:
        return version("kepler")
    except PackageNotFoundError:
        return "0+unknown"


def _content_block(block: Mapping[str, Any]) -> types.ContentBlock:
    if block["type"] == "image":
        return types.ImageContent(type="image", data=block["data"], mime_type=block["mime_type"])
    if block["type"] == "audio":
        return types.AudioContent(type="audio", data=block["data"], mime_type=block["mime_type"])
    return types.TextContent(type="text", text=block["text"])


def _result(
    payload: Mapping[str, Any], media: Sequence[Mapping[str, Any]] = ()
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(type="text", text=surface.to_json_text(payload)),
            *(_content_block(block) for block in media),
        ],
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
    artifact_root: Path | None = None,
) -> Server[Any]:
    """One server over every tool in ``schemas``, dispatching to ``functions``.

    ``schemas`` is the registry, or the part of it a ``--tools`` filter chose
    (:func:`tools.mcp.groups.tools_in_groups`); a tool not in it is neither
    listed nor callable.

    ``artifact_root`` defaults to ``tools.config.ARTIFACT_DIR`` as it stands
    when the server is built -- after ``kepler-mcp`` has pinned it. It is what
    the workspace tools' descriptions name and the only directory media is
    inlined from. ``instructions`` defaults to the served skill brief plus the
    install facts.
    """

    root = config.ARTIFACT_DIR if artifact_root is None else artifact_root
    if instructions is None:
        instructions = surface.served_instructions(root)
    documents = {doc["uri"]: doc for doc in surface.served_resources()}
    resources = [
        types.Resource(
            uri=doc["uri"],
            name=doc["name"],
            title=doc["title"],
            mime_type="text/markdown",
            size=len(doc["text"].encode("utf-8")),
        )
        for doc in documents.values()
    ]
    served = surface.served_tools(schemas, artifact_root=root)
    tools = [
        types.Tool(
            name=tool["name"],
            description=tool["description"],
            input_schema=tool["input_schema"],
            annotations=(
                types.ToolAnnotations(**tool["annotations"]) if tool["annotations"] else None
            ),
        )
        for tool in served
    ]
    # Only what is listed can be called: a group filter (C6) narrows both.
    functions = {tool["name"]: functions[tool["name"]] for tool in served if tool["name"] in functions}
    validators = {
        tool["name"]: jsonschema.Draft202012Validator(tool["input_schema"])
        for tool in served
    }
    lock = anyio.Lock()

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=resources)

    async def on_read_resource(
        ctx: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        doc = documents.get(str(params.uri))
        if doc is None:
            raise MCPError(types.INVALID_PARAMS, f"No resource {params.uri!s} is served.")
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=doc["uri"], mime_type="text/markdown", text=doc["text"]
                )
            ]
        )

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
            media = await anyio.to_thread.run_sync(surface.inline_media, payload, root)
        return _result(payload, media)

    return Server(
        surface.SERVER_NAME,
        version=_package_version(),
        instructions=instructions,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )


async def serve_stdio(server: Server[Any]) -> None:
    """Serve one host over this process's stdin and stdout until it disconnects."""

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
