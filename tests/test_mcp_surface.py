"""The MCP surface serves exactly the registry, and pins its roots first.

Two layers, tested separately. :mod:`tools.mcp.surface` and
:mod:`tools.mcp.roots` import no SDK, so the tests of *what* is served run in
every ``uv run pytest``. The tests of the adapter drive a real
:class:`mcp.server.Server` through the SDK's in-process client -- no
subprocess and no socket -- and skip when the optional ``[mcp]`` group is not
installed (``uv sync --extra mcp``).
"""

from __future__ import annotations

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
        assert tool["description"] == schema["description"]
        assert tool["input_schema"] is schema["input_schema"]


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
