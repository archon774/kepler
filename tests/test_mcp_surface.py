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
import os
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
    assert "44 bytes (60 encoded), over the 10-byte audio limit" in block["text"]


def test_the_default_sonification_fits_the_audio_limit():
    """60 s of 44.1 kHz 16-bit stereo, sonify_pulsar's default, is inlined."""
    assert 60 * 44_100 * 2 * 2 + 44 <= surface.MEDIA_FORMATS["wav"][2]


# --- the served skill and install facts (C5) -----------------------------------


def test_the_instructions_are_the_brief_then_the_install(tmp_path):
    from tools.skill import served_brief

    text = surface.served_instructions(tmp_path)
    assert text.startswith(served_brief())
    assert f"Artifacts are local files under {tmp_path}" in text


@pytest.mark.parametrize("outcome", ["missing", "failed"])
def test_the_instructions_fit_the_budget_in_the_worst_case(tmp_path, monkeypatch, outcome):
    """Every bundle missing -- or every check failing -- and a long artifact
    path: still inside BRIEF_LIMIT."""
    from tools.mcp import install
    from tools.skill import BRIEF_LIMIT

    def probe(*_args):
        if outcome == "failed":
            raise OSError("unreadable")
        return False

    for check in ("_pulsar_scans_present", "_references_present", "_frames_present",
                  "_isochrones_present", "_plate_solving_available", "_ads_token_available"):
        monkeypatch.setattr(install, check, probe)
    long_root = tmp_path / ("a" * 60) / ("b" * 60)
    assert len(surface.served_instructions(long_root)) <= BRIEF_LIMIT


def test_install_facts_say_whether_a_key_is_set_never_what_it_is(tmp_path, monkeypatch):
    from tools.mcp.install import install_facts

    monkeypatch.setenv("HOME", str(tmp_path))
    with_key = install_facts(tmp_path, {"ADS_DEV_KEY": "sekrit-value"})
    without = install_facts(tmp_path, {})
    assert "ADS token is set." in with_key and "sekrit" not in with_key
    assert "ADS token is not set" in without
    assert "plate solving not configured" in without


def test_install_facts_find_the_ads_token_file_astroquery_reads(tmp_path, monkeypatch):
    """Second review, finding 13: astroquery also reads ~/.ads/dev_key."""
    from tools.mcp.install import install_facts

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".ads").mkdir()
    (tmp_path / ".ads" / "dev_key").write_text("sekrit-file-value\n", encoding="utf-8")
    facts = install_facts(tmp_path, {})
    assert "ADS token is set." in facts and "sekrit" not in facts


def test_a_failing_fact_does_not_stop_the_server(tmp_path, monkeypatch):
    """Second review, finding 6: a probe that raised made startup raise."""
    from tools.mcp import install

    def broken():
        raise PermissionError("data directory unreadable")

    monkeypatch.setattr(install, "_pulsar_scans_present", broken)
    facts = install.install_facts(tmp_path, {})
    assert "Pulsar scans unknown (check failed)" in facts


def test_install_facts_are_the_tools_own_answers(tmp_path, monkeypatch):
    """Finding 8: the facts looked in their own places and disagreed with the tools.

    With KEPLER_DATA_DIR moved (it moves only downloads), the tools still see
    the scans and references; so must the facts. An index path holding no
    index files is not "plate solving configured".
    """
    from tools.mcp.install import install_facts

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "elsewhere")
    facts = install_facts(tmp_path, {"ANET_INDEX_PATH": str(tmp_path)})
    assert "Pulsar scans present" in facts
    assert "zero-point references present" in facts
    assert "plate solving not configured" in facts


def test_served_resources_are_the_skill_documents():
    from tools.skill import SERVED_URI_PREFIX, served_documents

    resources = surface.served_resources()
    assert [r["uri"] for r in resources] == [SERVED_URI_PREFIX + n for n in served_documents()]
    assert {r["title"] for r in resources} >= {"Kepler astronomy tools"}


# --- groups and annotations (C6) ------------------------------------------------

from tools.bench.plane import TOOL_CLASSES  # noqa: E402
from tools.mcp import groups  # noqa: E402


def test_the_groups_partition_the_registry_exactly():
    """Every tool in exactly one group; every group module is a real tool module."""
    membership = {name: groups.group_of(name) for name in TOOL_FUNCTIONS}
    assert [name for name, group in membership.items() if group is None] == []
    modules = [module for group in groups.GROUPS for module in group.modules]
    assert len(modules) == len(set(modules))
    assert set(modules) == {fn.__module__ for fn in TOOL_FUNCTIONS.values()}


def test_group_sizes_are_those_measured_at_c0():
    sizes = {g.name: len(groups.tools_in_groups((g.name,))) for g in groups.GROUPS}
    assert sizes == {"databases": 16, "optical": 16, "timeseries": 12, "hr": 8, "radio": 3}


def test_no_group_schema_payload_exceeds_about_four_thousand_tokens():
    """The reason the groups exist (C6 gate): each is at most ~16 KB of schema."""
    for group in groups.GROUPS:
        payload = len(json.dumps(groups.tools_in_groups((group.name,))))
        assert payload <= 16_000, (group.name, payload)


def test_every_group_says_whether_it_runs_without_a_data_bundle():
    for group in groups.GROUPS:
        assert "without a bundle" in group.description or "with no data bundle" in group.description


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("  ", None), ("hr", ("hr",)), (" databases , hr,hr ", ("databases", "hr"))],
)
def test_parse_groups(value, expected):
    assert groups.parse_groups(value) == expected


def test_an_unknown_group_names_the_valid_ones():
    with pytest.raises(ValueError, match="databses.*choose from databases, optical"):
        groups.parse_groups("databses")


def test_the_environment_selects_groups():
    assert groups.groups_from_environment({"KEPLER_MCP_TOOLS": "radio"}) == ("radio",)
    assert groups.groups_from_environment({}) is None


def test_annotations_are_derived_from_the_plane_and_the_schemas():
    hints = {s["name"]: groups.annotations_for(s) for s in TOOL_SCHEMAS}
    writers = {name for name, h in hints.items() if not h["read_only_hint"]}
    assert writers == {"search_mast", "search_casda", "solve_astrometry"}
    assert {name for name, h in hints.items() if h.get("destructive_hint")} == {"solve_astrometry"}
    assert all("destructive_hint" not in h for name, h in hints.items() if name not in writers)
    for name, h in hints.items():
        assert h["open_world_hint"] is (TOOL_CLASSES[name] != "local"), name
    assert sum(h["open_world_hint"] for h in hints.values()) == 29


def test_every_served_registry_tool_carries_annotations():
    assert all(tool["annotations"] for tool in surface.served_tools())


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


def test_a_group_filter_narrows_what_is_listed_and_what_is_callable():
    pytest.importorskip("mcp")
    import anyio
    from mcp.client.client import Client

    from tools.mcp.server import build_server

    async def run():
        async with Client(build_server(groups.tools_in_groups(("databases",)))) as client:
            listed = (await client.list_tools()).tools
            refused = await client.call_tool("list_pulsar_scans", {})
            return listed, refused

    listed, refused = anyio.run(run)
    assert len(listed) == 16
    mast = next(tool for tool in listed if tool.name == "search_mast")
    assert mast.annotations.read_only_hint is False
    assert mast.annotations.destructive_hint is False
    assert mast.annotations.open_world_hint is True
    assert refused.is_error and refused.structured_content["errors"][0]["code"] == "unknown_tool"


def test_self_test_passes_against_this_checkout(capfd):
    """``kepler-mcp self-test`` launches the server over stdio and runs the chain.

    ``capfd``, not ``capsys``: the SDK hands ``sys.stderr`` to the server
    subprocess, which needs a real file descriptor.
    """
    pytest.importorskip("mcp")
    from tools.mcp.selftest import main

    assert main([]) == 0
    out = capfd.readouterr().out
    assert "blind search folds at" in out and out.rstrip().endswith("passed")


def _imported_modules(path: Path) -> set[str]:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_the_server_sits_beside_the_agent_loop_not_on_it():
    """``tools/mcp -> tools/registry``; never through ``tools/agent`` or ``tools/llm``.

    ``docs/tool-architecture.md`` 10.3 and ``CLAUDE.md``: the server is a
    sibling consumer of the registry. And nothing under ``algorithms/``
    reaches up into it.
    """
    forbidden = ("tools.agent", "tools.llm", "tools.tui")
    for path in sorted((_REPO_ROOT / "tools" / "mcp").glob("*.py")):
        bad = {m for m in _imported_modules(path) if m.startswith(forbidden)}
        assert bad == set(), f"{path.name} imports {sorted(bad)}"
    for path in sorted((_REPO_ROOT / "algorithms").rglob("*.py")):
        bad = {m for m in _imported_modules(path) if m.startswith("tools.mcp")}
        assert bad == set(), f"{path} imports {sorted(bad)}"


# --- review fixes: argument strictness ---------------------------------------


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        # An undeclared keyword the tool function does accept: it wrote outside
        # the artifact root. Refused before dispatch.
        ("load_pulsar_lightcurve", {"path": "x", "subdir": "/tmp/elsewhere"}, "subdir"),
        ("analyze_source_spectrum", {"name": "Cas A", "output_dir": "/tmp/x"}, "output_dir"),
        # A misspelled keyword is an argument error, not a tool exception.
        ("search_vizier", {"target": "M31", "radius": 1.0}, "radius"),
        # JSON Schema's integer accepts 100.0; the loop's validator does not.
        ("fold_pulsar_lightcurve", {"path": "x", "period_s": 0.7, "bins": 100.0}, "integer"),
    ],
)
def test_undeclared_or_mistyped_arguments_are_refused_before_dispatch(name, arguments, expected, tmp_path):
    pytest.importorskip("mcp")
    import anyio
    from mcp.client.client import Client

    from tools.mcp.server import build_server

    def must_not_run(**_):
        raise AssertionError("dispatched")

    functions = {s["name"]: must_not_run for s in TOOL_SCHEMAS}
    server = build_server(TOOL_SCHEMAS, functions, artifact_root=tmp_path)

    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    result = anyio.run(run)
    assert result.is_error
    error = result.structured_content["errors"][0]
    assert error["code"] == "invalid_input" and expected in error["message"]
    assert list(tmp_path.iterdir()) == []


def test_reserved_artifact_names_are_claimed_atomically(tmp_path):
    """Two writers asking for the same name get different files (finding 5)."""
    from tools import artifacts

    first = artifacts.reserve_path_in(tmp_path, "psr_b0329_54_lightcurve", "ecsv")
    second = artifacts.reserve_path_in(tmp_path, "psr_b0329_54_lightcurve", "ecsv")
    assert first != second
    assert first.exists() and second.name == "psr_b0329_54_lightcurve_1.ecsv"


def test_reservation_holds_across_processes(tmp_path):
    """The check-then-write gave both processes one path in 4 of 4 trials."""
    import concurrent.futures

    code = (
        "import sys; from pathlib import Path; from tools import artifacts; "
        "print(artifacts.reserve_path_in(Path(sys.argv[1]), 'same', 'ecsv'))"
    )

    def claim(_):
        return subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        claimed = list(pool.map(claim, range(8)))
    assert len(set(claimed)) == 8


def test_a_preview_with_quantities_and_arrays_still_serialises():
    """Every non-empty search_mpc failed over MCP on astropy Quantity cells (finding 2)."""
    import astropy.units as u
    import numpy as np

    result = ToolResult(
        status="ok",
        count=1,
        preview=[{"RA": 10.5 * u.deg, "mag": np.float32(17.25), "spectrum": np.array([1.0, np.nan])}],
    )
    payload = surface.normalize_result("search_mpc", result)
    row = payload["preview"][0]
    assert row["RA"] == "10.5 deg"
    assert row["mag"] == 17.25
    assert row["spectrum"][0] == 1.0
    json.dumps(payload, allow_nan=True)
    assert not surface.result_is_error(payload)


# --- review fixes: startup ordering, backend, messages ---------------------------


def test_the_entry_point_loads_dotenv_before_anything_reads_configuration(tmp_path):
    """Finding 12: .env values were logged as read and never took effect."""
    probe = (
        "import sys, tools.mcp.__main__ as m\n"
        "from tools import dotenv\n"
        "dotenv.DOTENV_PATH = __import__('pathlib').Path(sys.argv[1])\n"
        "import tools.dotenv as d; d.DOTENV_PATH = dotenv.DOTENV_PATH\n"
        "print('tools.config' in sys.modules)\n"
    )
    env_file = tmp_path / ".env"
    env_file.write_text("KEPLER_MCP_TOOLS=hr\n")
    result = subprocess.run(
        [sys.executable, "-c", probe, str(env_file)], cwd=_REPO_ROOT,
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False"
    source = (_REPO_ROOT / "tools" / "mcp" / "__main__.py").read_text()
    assert source.index("load_dotenv()") < source.index("pin_roots()")
    assert source.index("pin_roots()") < source.index("from tools import config")


def test_tools_dotenv_resolves_nothing_at_import():
    result = subprocess.run(
        [sys.executable, "-c", "import sys, tools.dotenv; print('tools.config' in sys.modules)"],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False"


def test_config_still_re_exports_the_dotenv_loader():
    from tools import dotenv

    assert config.load_dotenv is dotenv.load_dotenv
    assert config.DOTENV_PATH == dotenv.DOTENV_PATH


def test_the_server_never_uses_a_gui_matplotlib_backend():
    """Finding 13: photometry failed on macOS off the main thread."""
    source = (_REPO_ROOT / "tools" / "mcp" / "__main__.py").read_text()
    assert 'os.environ.setdefault("MPLBACKEND", "Agg")' in source
    assert source.index('setdefault("MPLBACKEND"') < source.index("from tools.mcp import groups")


def test_the_missing_sdk_advice_never_names_the_pypi_project():
    """Finding 15: `pip install 'kepler[mcp]'` installed an unrelated PyPI project."""
    from tools.mcp.__main__ import _missing_sdk_message

    message = _missing_sdk_message()
    assert sys.executable in message and "kepler[mcp] @" in message
    assert "not on PyPI" in message


def test_a_group_list_naming_nothing_is_an_error():
    with pytest.raises(ValueError, match="no tool group named"):
        groups.parse_groups(" , ")


def test_self_test_reports_failure_rather_than_a_traceback(capfd, monkeypatch):
    """Finding 11: a failed check ended in an ExceptionGroup traceback."""
    pytest.importorskip("mcp")
    from tools.mcp import selftest

    monkeypatch.setattr(selftest, "_DETECTION_SNR", 1e9)  # force a failure
    assert selftest.main([]) == 1
    out = capfd.readouterr().out
    assert "FAIL" in out and out.rstrip().endswith("FAILED")


def test_self_test_ignores_the_callers_tool_filter(monkeypatch):
    from tools.mcp import selftest

    monkeypatch.setenv("KEPLER_MCP_TOOLS", "databases")
    monkeypatch.setenv("KEPLER_PULSAR_DATA_DIR", "/nowhere")
    env = selftest._server_environment("/tmp/artifacts")
    assert "KEPLER_MCP_TOOLS" not in env
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(_REPO_ROOT)


def test_self_test_pins_what_a_dotenv_could_set_again():
    """Second review, finding 11: the child loads .env, which re-set the
    variables the parent stripped. Both are pinned where .env cannot reach."""
    from tools.mcp import selftest

    env = selftest._server_environment("/tmp/artifacts")
    assert env["KEPLER_PULSAR_DATA_DIR"] == str(config.BUNDLED_DATA_DIR / "pulsar")
    arguments = selftest._server_arguments()
    assert arguments[:3] == ["-m", "tools.mcp", "--tools"]
    assert set(arguments[3].split(",")) == {group.name for group in groups.GROUPS}


def test_a_served_artifact_listing_is_bounded_and_newest_first(tmp_path):
    """Finding 14: an unbounded listing passed hosts' output limits, oldest first."""
    import os as _os
    import time

    from tools.workspace import list_artifacts

    for i in range(surface.ARTIFACT_LISTING_CAP + 20):
        path = tmp_path / f"vizier_{i}.ecsv"
        path.write_text("x")
        _os.utime(path, (time.time() - 10_000 + i, time.time() - 10_000 + i))

    payload = surface.call_tool(
        "list_artifacts", {"directory": str(tmp_path)}, {"list_artifacts": list_artifacts}
    )

    assert payload["count"] == surface.ARTIFACT_LISTING_CAP + 20
    assert len(payload["results"]) == surface.ARTIFACT_LISTING_CAP
    newest = payload["results"][0]["file"]["path"]
    assert newest.endswith(f"vizier_{surface.ARTIFACT_LISTING_CAP + 19}.ecsv")
    assert [w["code"] for w in payload["warnings"]] == ["listing_truncated"]


# --- the second review ---------------------------------------------------------------


def test_a_relative_artifact_directory_is_inside_the_artifact_root(tmp_path, monkeypatch):
    """Finding 3: `directory="pulsar"` -- what the served description tells a
    model to pass -- named a directory beside the server's working directory."""
    from tools.workspace import describe_artifact, list_artifacts

    (tmp_path / "pulsar").mkdir()
    (tmp_path / "pulsar" / "scan_lightcurve.ecsv").write_text("x")
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    functions = {"list_artifacts": list_artifacts, "describe_artifact": describe_artifact}

    listing = surface.call_tool("list_artifacts", {"directory": "pulsar"}, functions)
    described = surface.call_tool(
        "describe_artifact", {"path": "pulsar/scan_lightcurve.ecsv"}, functions
    )

    assert listing["count"] == 1
    assert listing["results"][0]["file"]["path"] == str(tmp_path / "pulsar" / "scan_lightcurve.ecsv")
    assert described["file"]["exists"] is True


def test_a_served_listing_describes_only_what_it_returns(tmp_path, monkeypatch):
    """Efficiency: bounding afterwards described every file on the root."""
    import tools.artifacts

    for i in range(surface.ARTIFACT_LISTING_CAP + 5):
        (tmp_path / f"f_{i}.txt").write_text("x")
    described = []
    original = tools.artifacts.describe_artifact_file
    monkeypatch.setattr(
        tools.artifacts, "describe_artifact_file",
        lambda path: described.append(path) or original(path),
    )

    payload = surface.call_tool("list_artifacts", {"directory": str(tmp_path)})

    assert payload["count"] == surface.ARTIFACT_LISTING_CAP + 5
    assert len(described) == surface.ARTIFACT_LISTING_CAP


def test_bytes_that_are_not_utf8_do_not_turn_a_result_into_an_error():
    payload = surface.normalize_result(
        "search_x", ToolResult(status="ok", preview=[{"flag": b"\xff\x00"}])
    )
    assert payload["status"] == "ok" and isinstance(payload["preview"][0]["flag"], str)
    text = surface.normalize_result("search_x", ToolResult(status="ok", preview=[{"f": b"ok"}]))
    assert text["preview"][0]["f"] == "ok"


def test_the_media_limit_is_measured_after_base64(tmp_path, monkeypatch):
    """A 3.75-5 MB PNG went out as a 5-6.7 MB block, over the image limit."""
    monkeypatch.setitem(surface.MEDIA_FORMATS, "png", ("image", "image/png", 64))
    png = tmp_path / "p.png"
    png.write_bytes(b"\0" * 60)  # 60 raw bytes, 80 encoded

    (block,) = surface.inline_media(_media_payload({"path": str(png), "format": "png"}), tmp_path)

    assert block["type"] == "text" and "80 encoded" in block["text"]


_PRINTING_SERVER = """
import anyio
from tools.models import ToolResult
from tools.mcp.server import build_server, serve_stdio

def noisy():
    print("[source_extraction] total_flux=1.0 num_sources=3")
    return ToolResult(status="ok", count=0)

schema = {"name": "noisy", "description": "prints",
          "input_schema": {"type": "object", "properties": {}}}
anyio.run(serve_stdio, build_server([schema], {"noisy": noisy}, instructions="x"))
"""


def test_a_tool_that_prints_never_writes_to_the_protocol_stream(tmp_path):
    """source_extraction prints a flux line on every extraction; buffered in
    sys.stdout, it reached the wire once the SDK restored fd 1."""
    pytest.importorskip("mcp")
    import anyio
    from mcp.client.client import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    script = tmp_path / "server.py"
    script.write_text(_PRINTING_SERVER)
    errlog_path = tmp_path / "stderr.txt"
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}

    async def run():
        params = StdioServerParameters(command=sys.executable, args=[str(script)], env=env)
        with errlog_path.open("w") as errlog:
            async with Client(stdio_client(params, errlog=errlog)) as client:
                result = await client.call_tool("noisy", {})
                assert not result.is_error

    anyio.run(run)
    assert "[source_extraction] total_flux=1.0" in errlog_path.read_text()


def test_self_test_without_the_sdk_gives_the_servers_advice(monkeypatch, capsys):
    """It pointed at docs/, which a wheel does not ship, and not at the pip
    command that avoids the unrelated PyPI project."""
    from tools.mcp import selftest

    monkeypatch.setitem(sys.modules, "mcp", None)  # import mcp -> ImportError
    assert selftest.main([]) == 2
    err = capsys.readouterr().err
    assert "uv sync --extra mcp" in err and "-m pip install" in err


# --- the third review -----------------------------------------------------------------


def test_an_empty_or_climbing_artifact_path_never_leaves_the_artifact_root(tmp_path, monkeypatch):
    """`directory=""` listed the server's launch directory -- the user's project."""
    from tools.workspace import describe_artifact, list_artifacts

    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "table.ecsv").write_text("x")
    launch = tmp_path / "project"
    launch.mkdir()
    (launch / "secret_notes.txt").write_text("private")
    monkeypatch.setattr(config, "ARTIFACT_DIR", root)
    monkeypatch.chdir(launch)
    functions = {"list_artifacts": list_artifacts, "describe_artifact": describe_artifact}

    listing = surface.call_tool("list_artifacts", {"directory": ""}, functions)
    assert [r["file"]["path"] for r in listing["results"]] == [str(root / "table.ecsv")]

    for name, key in (("list_artifacts", "directory"), ("describe_artifact", "path")):
        refused = surface.call_tool(name, {key: "../project"}, functions)
        assert refused["status"] == "error"
        assert refused["errors"][0]["code"] == "invalid_input"
        assert "secret_notes" not in json.dumps(refused)


def test_a_substituted_list_artifacts_is_called_not_bypassed():
    called = []

    def substitute(directory=None):
        called.append(directory)
        return []

    payload = surface.call_tool("list_artifacts", {}, {"list_artifacts": substitute})
    assert called == [None] and payload["count"] == 0


def test_a_very_long_artifact_root_still_fits_the_instructions(tmp_path, monkeypatch):
    """Third review: past ~410 characters of path the facts overflowed."""
    from tools.mcp import install
    from tools.skill import BRIEF_LIMIT

    def failed(*_args):
        raise OSError("unreadable")

    for check in ("_pulsar_scans_present", "_references_present", "_frames_present",
                  "_isochrones_present", "_plate_solving_available", "_ads_token_available"):
        monkeypatch.setattr(install, check, failed)
    root = tmp_path.joinpath(*(["d" * 60] * 12))

    text = surface.served_instructions(root)
    assert len(text) <= BRIEF_LIMIT
    assert "the artifact directory list_artifacts names" in text
