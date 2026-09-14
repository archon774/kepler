"""The registry is the agent's whole world; anything absent does not exist.

BL-2: before this test, every module in tools/ that reads local data -- except
tools.pulsar -- was unregistered, so an agent loop could query eight remote
archives but could not open any of the 39 bundled FITS frames.
"""

from __future__ import annotations

from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

#: Modules that are infrastructure, not a public tool surface.
NOT_TOOL_MODULES = {
    "tools.artifacts",
    "tools.config",
    "tools.models",
    "tools.registry",
    "tools.runner",
    "tools.sessions",
    # A CLI entry point; its library halves are re-exported through
    # tools.optical and tools.photometry instead.
    "tools.claude_photometry_haiku_tool",
    # The provider-neutral model port -- a backend interface for the agent
    # loop, not a callable tool. pkgutil.iter_modules yields it as a package.
    "tools.llm",
    # The headless agent loop (run_session, events, the moved SYSTEM_PROMPT).
    # Infrastructure the runner shim and the console consume, not a tool.
    "tools.agent",
    # The model benchmark harness. It *reads* the registry and substitutes
    # run_session's tool_functions mapping; it owns no tool and adds nothing
    # to the tool surface. pkgutil.iter_modules yields it as a package.
    "tools.bench",
}


def _tool_modules() -> set[str]:
    import pkgutil

    import tools

    return {
        f"tools.{module.name}"
        for module in pkgutil.iter_modules(tools.__path__)
    } - NOT_TOOL_MODULES


def test_every_public_tool_module_is_represented_in_the_registry():
    registered = {fn.__module__ for fn in TOOL_FUNCTIONS.values()}
    assert _tool_modules() - registered == set()


def test_schemas_and_functions_agree():
    assert {s["name"] for s in TOOL_SCHEMAS} == set(TOOL_FUNCTIONS)


def test_the_local_no_network_tools_are_reachable():
    """docs/tool-architecture.md 2 calls these the first local tools."""
    for name in (
        "describe_image_wcs",
        "list_photometric_catalogs",
        "resolve_reference_band",
        "solve_zeropoint_from_measurements",
        "list_artifacts",
        "describe_artifact",
    ):
        assert name in TOOL_FUNCTIONS, name
