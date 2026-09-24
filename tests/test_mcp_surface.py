"""The MCP surface serves exactly the registry, and pins its roots first.

Two layers, tested separately. :mod:`tools.mcp.surface` and
:mod:`tools.mcp.roots` import no SDK, so the tests of *what* is served run in
every ``uv run pytest``. The tests of the adapter drive a real
:class:`mcp.server.Server` through the SDK's in-process client -- no
subprocess and no socket -- and skip when the optional ``[mcp]`` group is not
installed (``uv sync --extra mcp``).
"""

from __future__ import annotations

import base64
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tools import config
from tools.mcp import roots, surface
from tools.models import ToolError, ToolResult
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

_REPO_ROOT = Path(__file__).resolve().parents[1]


# --- what is served -----------------------------------------------------------


def test_the_served_tool_list_is_the_registry():
    served = surface.served_tools()
    assert [tool["name"] for tool in served] == [s["name"] for s in TOOL_SCHEMAS]
    assert {tool["name"] for tool in served} == set(TOOL_FUNCTIONS)
    for tool, schema in zip(served, TOOL_SCHEMAS):
        if schema["name"] not in surface._SERVED_CORRECTIONS:
            assert tool["description"] == schema["description"]
        assert tool["input_schema"] is schema["input_schema"]


def test_a_served_correction_replaces_a_sentence_the_registry_still_has():
    served = {t["name"]: t["description"] for t in surface.served_tools()}
    registry = {s["name"]: s["description"] for s in TOOL_SCHEMAS}
    for name, (old, new) in surface._SERVED_CORRECTIONS.items():
        assert old in registry[name], f"{name}: the registry moved {old!r}"
        assert old not in served[name] and new in served[name]


@pytest.mark.parametrize(
    ("declared", "value", "flagged"),
    [
        (["integer", "null"], "None", True),
        (["string", "null"], "null", True),
        (["integer", "null"], "NIL", True),
        (["integer", "null"], None, False),
        (["integer", "null"], 5, False),
        ("string", "None", False),
        (["string", "null"], "Nonesuch", False),
    ],
)
def test_stringified_nulls(declared, value, flagged):
    schema = {"properties": {"cap": {"type": declared}}}
    assert surface.stringified_nulls(schema, {"cap": value}) == (["cap"] if flagged else [])


def test_a_model_result_is_json_with_nan_as_null():
    result = ToolResult(status="ok", count=1, preview=[{"flux": math.nan}])
    payload = surface.normalize_result("x", result)
    assert payload["status"] == "ok"
    assert payload["preview"] == [{"flux": None}]
    json.dumps(payload, allow_nan=False)


def test_a_list_result_is_wrapped_like_the_agent_loop_wraps_it():
    items = [ToolError(code="a", message="b")]
    payload = surface.normalize_result("x", items)
    assert payload == {"status": "ok", "count": 1, "results": [{"code": "a", "message": "b"}]}


def test_a_non_model_result_is_a_registry_defect():
    with pytest.raises(TypeError, match="must return a Kepler model"):
        surface.normalize_result("x", {"not": "a model"})


def test_an_unknown_tool_is_an_error_payload():
    payload = surface.call_tool("no_such_tool", {})
    assert surface.result_is_error(payload)
    assert payload["errors"][0]["code"] == "unknown_tool"


def test_a_raising_tool_is_an_error_payload_not_an_exception():
    def boom(**_):
        raise ValueError("bad frame")

    payload = surface.call_tool("boom", {}, {"boom": boom})
    assert surface.result_is_error(payload)
    assert payload["errors"][0] == {"code": "tool_exception", "message": "ValueError: bad frame"}


def test_a_local_tool_round_trips_through_the_surface():
    payload = surface.call_tool("list_pulsar_scans", {})
    assert not surface.result_is_error(payload)
    assert len(payload["scans"]) == 5
    json.dumps(payload, allow_nan=False)


def test_the_workspace_tools_name_the_pinned_root_and_nothing_else_changes(tmp_path):
    served = {t["name"]: t for t in surface.served_tools(artifact_root=tmp_path)}
    registry = {s["name"]: s for s in TOOL_SCHEMAS}
    for name in ("list_artifacts", "describe_artifact"):
        assert served[name]["description"].startswith(registry[name]["description"])
        assert str(tmp_path) in served[name]["description"]
    assert "subdirectories" in served["list_artifacts"]["description"]
    for name in set(registry) - {"list_artifacts", "describe_artifact"} - set(surface._SERVED_CORRECTIONS):
        assert served[name]["description"] == registry[name]["description"]


# --- media (C4) ---------------------------------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
_WAV = b"RIFF" + b"\0" * 40


def _media_payload(*refs):
    return {"status": "ok", "artifact": refs[0], "artifacts": list(refs[1:])}


def test_png_and_wav_artifacts_come_back_inline(tmp_path):
    (tmp_path / "pulsar").mkdir()
    png, wav = tmp_path / "pulsar" / "p.png", tmp_path / "pulsar" / "s.wav"
    png.write_bytes(_PNG)
    wav.write_bytes(_WAV)
    payload = _media_payload(
        {"path": str(png), "format": "png"},
        {"path": str(wav), "format": "wav"},
        {"path": str(png), "format": "png"},
        {"path": str(tmp_path / "rows.ecsv"), "format": "ecsv"},
    )

    blocks = surface.inline_media(payload, tmp_path)

    assert [(b["type"], b["mime_type"]) for b in blocks] == [
        ("image", "image/png"),
        ("audio", "audio/wav"),
    ]
    assert base64.b64decode(blocks[0]["data"]) == _PNG
    assert base64.b64decode(blocks[1]["data"]) == _WAV


def test_media_outside_the_artifact_root_is_named_not_read(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(_PNG)
    (root / "link.png").symlink_to(outside)

    for path in (outside, root / "link.png", root / "missing.png"):
        blocks = surface.inline_media(_media_payload({"path": str(path), "format": "png"}), root)
        assert blocks == [
            {"type": "text", "text": f"Not inlined: {path} is not a file under the artifact directory."}
        ]


def test_media_over_its_limit_is_named_with_its_size(tmp_path, monkeypatch):
    monkeypatch.setitem(surface.MEDIA_FORMATS, "wav", ("audio", "audio/wav", 10))
    wav = tmp_path / "s.wav"
    wav.write_bytes(_WAV)

    (block,) = surface.inline_media(_media_payload({"path": str(wav), "format": "wav"}), tmp_path)

    assert block["type"] == "text"
    assert "44 bytes, over the 10-byte audio limit" in block["text"]


def test_the_default_sonification_fits_the_audio_limit():
    """60 s of 44.1 kHz 16-bit stereo, sonify_pulsar's default, is inlined."""
    assert 60 * 44_100 * 2 * 2 + 44 <= surface.MEDIA_FORMATS["wav"][2]


# --- the served skill and install facts (C5) -----------------------------------


def test_the_instructions_are_the_brief_then_the_install(tmp_path):
    from tools.skill import served_brief

    text = surface.served_instructions(tmp_path)
    assert text.startswith(served_brief())
    assert f"Artifacts are local files under {tmp_path}" in text


def test_the_instructions_fit_the_budget_in_the_worst_case(tmp_path, monkeypatch):
    """Every bundle missing and a long artifact path: still inside BRIEF_LIMIT."""
    from tools.mcp import install
    from tools.skill import BRIEF_LIMIT

    monkeypatch.setattr(install, "_has_files", lambda directory, pattern: False)
    for name in ("ANET_INDEX_PATH", "ATLAS_CATALOG_ROOT", "ADS_DEV_KEY"):
        monkeypatch.delenv(name, raising=False)
    long_root = tmp_path / ("a" * 60) / ("b" * 60)
    assert len(surface.served_instructions(long_root)) <= BRIEF_LIMIT


def test_install_facts_say_whether_a_key_is_set_never_what_it_is(tmp_path):
    from tools.mcp.install import install_facts

    with_key = install_facts(tmp_path, {"ADS_DEV_KEY": "sekrit-value"})
    without = install_facts(tmp_path, {})
    assert "ADS_DEV_KEY is set." in with_key and "sekrit" not in with_key
    assert "ADS_DEV_KEY is not set" in without
    assert "plate solving not configured" in without
    assert "plate solving configured" in install_facts(tmp_path, {"ANET_INDEX_PATH": "/x"})


def test_served_resources_are_the_skill_documents():
    from tools.skill import SERVED_URI_PREFIX, served_documents

    resources = surface.served_resources()
    assert [r["uri"] for r in resources] == [SERVED_URI_PREFIX + n for n in served_documents()]
    assert {r["title"] for r in resources} >= {"Kepler astronomy tools"}


# --- the roots ----------------------------------------------------------------


def test_roots_names_the_same_variables_as_tools_config():
    assert roots.ARTIFACT_DIR_ENV == config.ARTIFACT_DIR_ENV
    assert roots.DATA_DIR_ENV == config.DATA_DIR_ENV
    assert roots.default_data_dir() == config._REPO_ROOT / "data"


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    [
        ("linux", {}, "home/.local/share/kepler/artifacts"),
        ("linux", {"XDG_DATA_HOME": "/xdg"}, "/xdg/kepler/artifacts"),
        ("linux", {"XDG_DATA_HOME": "relative"}, "home/.local/share/kepler/artifacts"),
        ("darwin", {}, "home/Library/Application Support/kepler/artifacts"),
        ("win32", {"LOCALAPPDATA": "/local"}, "/local/kepler/artifacts"),
        ("win32", {}, "home/AppData/Local/kepler/artifacts"),
    ],
)
def test_user_artifact_dir_per_platform(platform, environ, expected):
    path = roots.user_artifact_dir(environ, platform=platform, home=Path("home"))
    assert path.as_posix() == expected


def test_pin_roots_defaults_to_the_per_user_directory(tmp_path, monkeypatch):
    target = tmp_path / "user" / "kepler" / "artifacts"
    monkeypatch.setattr(roots, "user_artifact_dir", lambda environ: target)
    environ = {"KEPLER_ARTIFACT_DIR": "  "}

    pinned = roots.pin_roots(environ)

    assert pinned.artifact_dir == target and pinned.artifact_source == "per-user default"
    assert target.is_dir()
    assert pinned.data_dir == roots.default_data_dir()
    assert pinned.data_source == "package default"
    assert environ == {
        "KEPLER_ARTIFACT_DIR": str(target),
        "KEPLER_DATA_DIR": str(roots.default_data_dir()),
    }


def test_pin_roots_keeps_an_explicit_value_and_makes_it_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    environ = {"KEPLER_ARTIFACT_DIR": "out", "KEPLER_DATA_DIR": "data"}

    pinned = roots.pin_roots(environ)

    assert pinned.artifact_dir == tmp_path / "out"
    assert pinned.artifact_source == "KEPLER_ARTIFACT_DIR"
    assert pinned.data_dir == tmp_path / "data"
    assert environ["KEPLER_ARTIFACT_DIR"] == str(tmp_path / "out")


def test_the_entry_point_does_not_import_tools_config_before_pinning():
    """Importing the server's entry module must leave the roots unresolved."""
    probe = (
        "import sys, tools.mcp.__main__, tools.mcp.roots; "
        "print('tools.config' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_kepler_mcp_is_a_declared_script():
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'kepler-mcp = "tools.mcp.__main__:main"' in text


# --- the adapter, through the SDK's in-process client ---------------------------


def _client_session(coroutine):
    pytest.importorskip("mcp")
    import anyio
    from mcp.client.client import Client

    from tools.mcp.server import build_server

    async def run():
        async with Client(build_server()) as client:
            return await coroutine(client)

    return anyio.run(run)


def test_every_registry_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    for schema in TOOL_SCHEMAS:
        jsonschema.Draft202012Validator.check_schema(schema["input_schema"])


def test_the_server_lists_exactly_the_registry():
    async def names(client):
        return [tool.name for tool in (await client.list_tools()).tools]

    assert _client_session(names) == [s["name"] for s in TOOL_SCHEMAS]


def test_a_call_returns_structured_content_and_the_same_json_as_text():
    async def call(client):
        return await client.call_tool("list_pulsar_scans", {})

    result = _client_session(call)
    assert result.is_error is False
    assert len(result.structured_content["scans"]) == 5
    assert json.loads(result.content[0].text) == result.structured_content


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("search_vizier", {"target": "M31", "max_catalogs": "None"}, "is not null"),
        ("load_pulsar_lightcurve", {"path": "x", "back_scale": "wide"}, "back_scale"),
        ("load_pulsar_lightcurve", {}, "'path' is a required property"),
        ("no_such_tool", {}, "No tool named"),
    ],
)
def test_a_bad_call_is_an_error_result_before_any_dispatch(name, arguments, expected):
    """Validation refuses these before the tool runs -- search_vizier opens no socket."""

    async def call(client):
        return await client.call_tool(name, arguments)

    result = _client_session(call)
    assert result.is_error is True
    error = result.structured_content["errors"][0]
    assert error["code"] in {"invalid_input", "unknown_tool"}
    assert expected in error["message"]


def test_a_media_result_carries_the_image_and_audio_after_the_json(tmp_path):
    pytest.importorskip("mcp")
    import anyio
    from mcp.client.client import Client

    from tools.mcp.server import build_server
    from tools.models import ArtifactRef

    png, wav = tmp_path / "p.png", tmp_path / "s.wav"
    png.write_bytes(_PNG)
    wav.write_bytes(_WAV)

    def render():
        return ToolResult(
            status="ok",
            artifacts=[ArtifactRef(path=str(png), format="png"), ArtifactRef(path=str(wav), format="wav")],
        )

    schemas = [{"name": "render", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    server = build_server(schemas, {"render": render}, artifact_root=tmp_path)

    async def run():
        async with Client(server) as client:
            return await client.call_tool("render", {})

    result = anyio.run(run)
    assert [block.type for block in result.content] == ["text", "image", "audio"]
    assert base64.b64decode(result.content[1].data) == _PNG
    assert result.content[2].mime_type == "audio/wav"
    assert result.structured_content["artifacts"][0]["path"] == str(png)


def test_the_server_delivers_the_instructions_and_the_skill_resources():
    from tools.skill import SERVED_URI_PREFIX, served_documents

    async def session(client):
        listed = [str(r.uri) for r in (await client.list_resources()).resources]
        pulsar = await client.read_resource(SERVED_URI_PREFIX + "references/pulsar.md")
        return client.instructions, listed, pulsar.contents[0].text

    instructions, listed, pulsar = _client_session(session)
    assert instructions.startswith("Kepler: astronomy tools.")
    assert "This install:" in instructions
    assert listed == [SERVED_URI_PREFIX + name for name in served_documents()]
    assert pulsar == served_documents()["references/pulsar.md"]


def test_an_unknown_resource_is_a_protocol_error():
    pytest.importorskip("mcp")
    from mcp.shared.exceptions import MCPError

    async def session(client):
        return await client.read_resource("kepler://skill/references/checkout.md")

    # In process, the SDK re-raises the handler's error, possibly inside an
    # exception group; over a transport the client receives it as a JSON-RPC
    # error. Either way it is an MCPError naming the URI, not a result.
    with pytest.raises(BaseException) as raised:
        _client_session(session)

    def leaves(exc):
        if isinstance(exc, BaseExceptionGroup):
            for inner in exc.exceptions:
                yield from leaves(inner)
        else:
            yield exc

    assert any(
        isinstance(exc, MCPError) and "No resource" in str(exc) for exc in leaves(raised.value)
    )
