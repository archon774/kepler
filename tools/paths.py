"""The per-user Kepler home, and the bundled data that ships with the package.

Two locations that exist whether Kepler is a checkout or an installed wheel,
and that code on both sides of the import-time boundary needs:

- :func:`kepler_home` -- the user-writable directory Kepler owns:
  ``$XDG_DATA_HOME/kepler`` (default ``~/.local/share/kepler``),
  ``~/Library/Application Support/kepler`` on macOS, ``%LOCALAPPDATA%\\kepler``
  on Windows, or ``KEPLER_HOME`` when set. The MCP server's artifacts, an
  installed Kepler's archive downloads, and fetched data bundles live under it
  (``docs/working/mcp-tool-surface.md`` §3.2, §3.5).
- :data:`BUNDLED_DATA_LINK` -- ``tools/_data``. In a checkout it is a symlink to
  the repository's ``data/``; in a wheel it is a real directory holding the
  core data (``pulsar/``, ``fieldcal/``, ``afterglow/``) that
  ``pyproject.toml``'s package-data ships. Every tool reads bundled data
  through it, so the same code finds the same files in both layouts.

Nothing here is resolved at import. ``tools.mcp.roots`` imports this module
before the roots are pinned, which is safe only because of that; keep it so.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

__all__ = [
    "BUNDLED_DATA_LINK",
    "KEPLER_HOME_ENV",
    "is_checkout",
    "kepler_home",
]

KEPLER_HOME_ENV = "KEPLER_HOME"

#: ``tools/_data``: the repository's ``data/`` in a checkout, the shipped core
#: data in an installed wheel.
BUNDLED_DATA_LINK = Path(__file__).parent / "_data"


def is_checkout() -> bool:
    """Whether this is a development checkout rather than an installed wheel.

    A checkout carries ``tools/_data`` as a symlink into its ``data/``; a wheel
    carries a real directory. An editable install is a checkout.
    """

    return BUNDLED_DATA_LINK.is_symlink()


def kepler_home(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """The per-user directory Kepler owns, for this platform. Not created here.

    ``KEPLER_HOME`` wins when set. Otherwise the platform's per-user data
    directory plus ``kepler``; a relative ``XDG_DATA_HOME`` is ignored, as the
    XDG specification requires.
    """

    environ = os.environ if environ is None else environ
    explicit = environ.get(KEPLER_HOME_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()

    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "darwin":
        base = home / "Library" / "Application Support"
    elif platform == "win32":
        local = environ.get("LOCALAPPDATA", "")
        base = Path(local) if local else home / "AppData" / "Local"
    else:
        xdg = environ.get("XDG_DATA_HOME", "")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".local" / "share"
    return base / "kepler"
