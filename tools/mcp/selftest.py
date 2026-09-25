"""``kepler-mcp self-test``: prove an install works, the way a host would use it.

Launches this interpreter's own ``kepler-mcp`` over stdio -- the transport a
host uses -- and checks, through the protocol alone:

1. every registered tool is served, with the skill brief as instructions and
   the skill documents as resources;
2. the bundled pulsar scans are present;
3. the pulsar chain detects B0329+54 **from a measured period**: the blind
   periodogram's peak folds above the detection threshold and agrees with the
   curated period, and the sonification comes back as audio.

It opens no socket -- the chain is local -- and writes its artifacts to a
temporary directory it removes. It reports which optional data bundles are
installed, without requiring them. The release workflow runs it on a clean
runner against the built wheel (``docs/releasing.md``); a tester runs it after
installing.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Any

__all__ = ["main"]

#: The detection threshold the pulsar tools use (``pulse_snr`` above ~8).
_DETECTION_SNR = 8.0
#: B0329+54's blind period agrees with the curated one to 0.04%; allow 0.5%.
_PERIOD_TOLERANCE = 0.005


class _Failed(Exception):
    pass


def _check(ok: bool, message: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + message)
    if not ok:
        raise _Failed(message)


async def _run(env: dict[str, str]) -> None:
    from mcp.client.client import Client
    from mcp.client.stdio import StdioServerParameters

    from tools.registry import TOOL_SCHEMAS
    from tools.skill import served_documents

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "tools.mcp"], env=env, cwd=env["KEPLER_ARTIFACT_DIR"]
    )
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        _check(len(tools) == len(TOOL_SCHEMAS), f"{len(tools)} tools served")
        resources = (await client.list_resources()).resources
        _check(len(resources) == len(served_documents()), f"{len(resources)} skill resources")
        _check(bool(client.instructions), f"instructions ({len(client.instructions or '')} characters)")

        async def call(name: str, **arguments: Any) -> Any:
            result = await client.call_tool(name, arguments)
            _check(not result.is_error, f"{name} returned without error")
            return result

        scans = (await call("list_pulsar_scans")).structured_content["scans"]
        _check(len(scans) == 5, f"{len(scans)} bundled pulsar scans")
        scan = next(s for s in scans if "b0329" in s["path"])
        lightcurve = (await call("load_pulsar_lightcurve", path=scan["path"])).structured_content
        path = lightcurve["artifact"]["path"]
        periodogram = (await call("compute_pulsar_periodogram", path=path)).structured_content
        measured, curated = periodogram["peak_period_s"], scan["curated_period_s"]
        _check(
            periodogram["peak_fold_snr"] > _DETECTION_SNR,
            f"blind search folds at {periodogram['peak_fold_snr']:.1f} sigma",
        )
        _check(
            abs(measured - curated) / curated < _PERIOD_TOLERANCE,
            f"measured period {measured:.5f} s agrees with the curated {curated:.5f} s",
        )
        fold = (await call("fold_pulsar_lightcurve", path=path, period_s=measured)).structured_content
        _check(fold["pulse_snr"] > _DETECTION_SNR, f"fold at the measured period: {fold['pulse_snr']:.1f} sigma")
        sonified = await call("sonify_pulsar", path=path, period_s=measured)
        _check(
            any(block.type == "audio" for block in sonified.content),
            "sonification returned as an audio block",
        )


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("usage: kepler-mcp self-test", file=sys.stderr)
        return 2
    try:
        import anyio
        import mcp  # noqa: F401
    except ImportError:
        print("self-test needs Kepler's [mcp] extra; see docs/installing.md", file=sys.stderr)
        return 2

    from tools import config
    from tools.mcp.bundles import load_manifest

    print("kepler-mcp self-test", flush=True)
    status = 0
    with tempfile.TemporaryDirectory(prefix="kepler-self-test-") as artifacts:
        env = {**os.environ, "KEPLER_ARTIFACT_DIR": artifacts}
        try:
            anyio.run(_run, env)
        except _Failed:
            status = 1
    for name in load_manifest():
        where = config.fetched_bundle(name)
        print(f"  info  {name} bundle: " + (f"installed at {where}" if where else "not installed"))
    print("passed" if status == 0 else "FAILED")
    return status
