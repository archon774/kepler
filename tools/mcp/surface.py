"""The served surface, derived from ``tools/registry.py`` and nothing else.

Everything here is independent of the ``mcp`` SDK, so the parts that decide
*what* is served -- the tool list, the argument pre-check, the result shape --
are tested by a plain ``uv run pytest`` that never installs the optional
group. ``tools.mcp.server`` is the thin adapter that hands them to the SDK.

The registry is the single source of truth: this module reads
``TOOL_SCHEMAS``/``TOOL_FUNCTIONS`` and keeps no list of its own.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import pydantic_core

from tools import skill
from tools.bench.plane import TOOL_CLASSES
from tools.config import within
from tools.mcp.groups import annotations_for
from tools.mcp.install import install_facts
from tools.models import ToolError, ToolResult
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

__all__ = [
    "MEDIA_FORMATS",
    "SERVER_NAME",
    "call_tool",
    "error_payload",
    "inline_media",
    "normalize_result",
    "result_is_error",
    "served_instructions",
    "served_resources",
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


#: Appended to the registry description of the two workspace tools when an
#: artifact root is known. The registry is read, never edited, by this track;
#: what only the server knows -- where it pinned the root, and that a served
#: root is shared -- is added here instead.
_ARTIFACT_NOTES = {
    "list_artifacts": (
        " Served by kepler-mcp: the artifact directory is {root}, pinned when "
        "the server started (KEPLER_ARTIFACT_DIR, or a per-user default) and "
        "shared by every session on this machine. This lists only the files "
        "directly inside the directory given, and tools write into per-tool "
        "subdirectories of it (pulsar/, vizier/, simbad/, ...): pass one as "
        "`directory` to see its files. Nothing there is overwritten or cleaned "
        "up -- a repeated call writes a new file with a numeric suffix -- so "
        "read the path a result named rather than the newest-looking file."
    ),
    "describe_artifact": (
        " Served by kepler-mcp: tools write their artifacts under {root}, "
        "pinned when the server started. The paths are local to this machine "
        "and readable directly; pass the path a tool result named."
    ),
}


#: Registry sentences that are false once served, and what the server says
#: instead. Replaced, not appended, so a model is not handed both. A test
#: asserts each original is still in the registry, so a registry edit that
#: moves one fails loudly rather than leaving the stale sentence served.
_SERVED_CORRECTIONS = {
    "sonify_pulsar": (
        "the audio is never inlined.",
        "served by kepler-mcp, the WAV also comes back inline as an audio block "
        "when it is under the server's audio limit -- a host that cannot play "
        "it may save it to a file instead.",
    ),
}


def served_tools(
    schemas: Sequence[Mapping[str, Any]] = TOOL_SCHEMAS,
    *,
    artifact_root: Path | None = None,
) -> list[dict[str, Any]]:
    """One ``{name, description, input_schema, annotations}`` per tool, in order.

    With ``artifact_root``, ``list_artifacts`` and ``describe_artifact`` say
    which directory they enumerate (C4); every other description is the
    registry's, unchanged -- except where :data:`_SERVED_CORRECTIONS` replaces
    a sentence the server makes false. ``annotations`` come from
    :func:`tools.mcp.groups.annotations_for` (C6) and are ``None`` for a name
    the tool plane does not classify, which only a test's own schema can be.
    """

    served = []
    for schema in schemas:
        description = schema["description"]
        correction = _SERVED_CORRECTIONS.get(schema["name"])
        if correction is not None:
            description = description.replace(*correction)
        note = _ARTIFACT_NOTES.get(schema["name"])
        if note is not None and artifact_root is not None:
            description += note.format(root=artifact_root)
        served.append(
            {
                "name": schema["name"],
                "description": description,
                "input_schema": schema["input_schema"],
                "annotations": (
                    annotations_for(schema) if schema["name"] in TOOL_CLASSES else None
                ),
            }
        )
    return served


def served_instructions(artifact_root: Path | None = None) -> str:
    """The skill brief, then what this install has (C5).

    Short on purpose: a host may deliver only the first ~2,000 characters
    (``tools.skill.BRIEF_LIMIT``). The brief points at the resources for
    everything else.
    """

    return skill.served_brief() + "\n\n" + install_facts(artifact_root)


def served_resources() -> list[dict[str, str]]:
    """One ``{uri, name, title, text}`` per published skill document."""

    resources = []
    for name, text in skill.served_documents().items():
        heading = next(
            (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")),
            name,
        )
        resources.append(
            {
                "uri": skill.SERVED_URI_PREFIX + name,
                "name": name,
                "title": heading,
                "text": text,
            }
        )
    return resources


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


#: ``ArtifactRef.format`` -> (content type, MIME type, largest file inlined).
#: A default 60-second stereo sonification is ~10.6 MB, so the audio limit
#: admits it; 5 MB is the image size model APIs commonly refuse above. Over a
#: limit the file is named in a note instead -- the path still works.
MEDIA_FORMATS: dict[str, tuple[str, str, int]] = {
    "png": ("image", "image/png", 5_000_000),
    "wav": ("audio", "audio/wav", 12_000_000),
}


def _artifact_refs(value: Any) -> Iterator[Mapping[str, Any]]:
    """Every ``ArtifactRef``-shaped object in a payload, depth first."""

    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(value.get("format"), str):
            yield value
        for item in value.values():
            yield from _artifact_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _artifact_refs(item)


def inline_media(payload: Mapping[str, Any], artifact_root: Path) -> list[dict[str, Any]]:
    """Content blocks for the PNG and WAV artifacts a result names.

    A model handed a path to audio has not heard anything, and a path to a plot
    has not seen it (``docs/archive/mcp-tool-surface.md`` §3.1). Each media
    artifact becomes ``{type: image|audio, mime_type, data}`` with base64 data,
    once per path. Only a regular file inside ``artifact_root`` is read -- a
    result naming a path elsewhere is not a way to pull arbitrary files into a
    model's context -- and anything refused becomes a ``{type: text}`` note
    saying why. The ``ArtifactRef`` in the payload is left as it was.
    """

    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in _artifact_refs(payload):
        media = MEDIA_FORMATS.get(ref["format"].lower())
        if media is None or ref["path"] in seen:
            continue
        seen.add(ref["path"])
        kind, mime_type, limit = media
        path = Path(ref["path"])
        if not within(path, artifact_root) or not path.is_file():
            blocks.append(
                {"type": "text", "text": f"Not inlined: {path} is not a file under the artifact directory."}
            )
            continue
        size = path.stat().st_size
        if size > limit:
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        f"Not inlined: {path} is {size:,} bytes, over the "
                        f"{limit:,}-byte {kind} limit. Read it from the path."
                    ),
                }
            )
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        blocks.append({"type": kind, "mime_type": mime_type, "data": data})
    return blocks


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
