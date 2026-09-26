"""Kepler's Textual research-console interface."""

from __future__ import annotations


def launch() -> int:
    """The ``kepler`` console script: load ``.env``, then start the console.

    ``tools.config`` fixes its settings at import (``KEPLER_ARTIFACT_DIR``,
    ``KEPLER_DATA_DIR``, ``KEPLER_ISOCHRONE_DIR``, ...), and the console's own
    module imports it. Pointing the script at ``tools.tui.__main__:main`` meant
    that import ran first and a setting kept in ``.env`` was read, then
    ignored. ``tools.dotenv`` resolves nothing at import, so it goes first.
    """

    from tools.dotenv import load_dotenv
    from tools.paths import pin_numba_cache

    load_dotenv()
    pin_numba_cache()
    from tools.tui.__main__ import main

    return main()
