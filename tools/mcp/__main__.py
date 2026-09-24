"""``kepler-mcp``: serve Kepler's tools to a host over stdio.

The order in :func:`main` is the point of this module. The roots are pinned
into the environment first; only then is anything imported that reads
``tools.config``. Logging goes to stderr, because stdout is the protocol.
"""

from __future__ import annotations

import argparse
import logging
import sys

from tools.mcp.roots import pin_roots

log = logging.getLogger("kepler-mcp")

_MISSING_SDK = (
    "kepler-mcp needs the optional MCP dependencies. From a checkout run "
    "`uv sync --extra mcp`; from an install, `pip install 'kepler[mcp]'`."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kepler-mcp",
        description=(
            "Serve Kepler's astronomy tools over MCP on stdio. A host launches "
            "this; it is not run by hand. Artifacts go to KEPLER_ARTIFACT_DIR, "
            "default a per-user directory, and the resolved roots are logged to "
            "stderr at startup."
        ),
    )
    parser.add_argument(
        "--tools",
        metavar="GROUPS",
        help=(
            "Serve only these comma-separated tool groups (default: all 55 tools; "
            "also KEPLER_MCP_TOOLS). Groups: databases, optical, timeseries, hr, "
            "radio."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="kepler-mcp: %(message)s"
    )

    if "tools.config" in sys.modules:
        raise RuntimeError("tools.config was imported before the roots were pinned")
    roots = pin_roots()

    # The group filter is checked before the SDK is imported, so a typo in a
    # host's configuration is reported as itself wherever it happens.
    from tools.mcp import groups

    try:
        selected = (
            groups.parse_groups(args.tools)
            if args.tools is not None
            else groups.groups_from_environment()
        )
    except ValueError as exc:
        parser.error(str(exc))
    schemas = groups.tools_in_groups(selected)

    try:
        import anyio

        from tools.mcp.server import build_server, serve_stdio
    except ImportError as exc:
        if exc.name in {"mcp", "mcp_types", "jsonschema"}:
            print(_MISSING_SDK, file=sys.stderr)
            return 2
        raise

    from tools import config
    from tools.mcp import surface

    loaded = config.load_dotenv()
    log.info("artifact root: %s (%s)", config.ARTIFACT_DIR, roots.artifact_source)
    log.info("data root: %s (%s)", config.DATA_DIR, roots.data_source)
    log.info("download root: %s", config.FITS_DOWNLOAD_DIR)
    log.info(
        "isochrone grid: %s",
        config.ISOCHRONE_DIR or "not set (KEPLER_ISOCHRONE_DIR); the isochrone fit is unavailable",
    )
    if loaded:
        log.info("read from %s: %s", config.DOTENV_PATH, ", ".join(loaded))
    for group in groups.GROUPS:
        if selected is None or group.name in selected:
            log.info("group %s: %s", group.name, group.description)
    server = build_server(schemas)
    log.info(
        "serving %d tools and %d skill resources over stdio; instructions %d characters",
        len(schemas),
        len(surface.served_resources()),
        len(server.instructions or ""),
    )

    anyio.run(serve_stdio, server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
