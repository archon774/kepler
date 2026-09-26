"""The per-user Kepler home, and the bundled data that ships with the package.

Two locations that exist whether Kepler is a checkout or an installed wheel,
and that code on both sides of the import-time boundary needs:

- :func:`kepler_home` -- the user-writable directory Kepler owns:
  ``$XDG_DATA_HOME/kepler`` (default ``~/.local/share/kepler``),
  ``~/Library/Application Support/kepler`` on macOS, ``%LOCALAPPDATA%\\kepler``
  on Windows, or ``KEPLER_HOME`` when set. The MCP server's artifacts, an
  installed Kepler's archive downloads, and fetched data bundles live under it
  (``docs/archive/mcp-tool-surface.md`` §3.2, §3.5).
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
    "bundled_data_dir",
    "is_checkout",
    "kepler_home",
]

KEPLER_HOME_ENV = "KEPLER_HOME"

#: ``tools/_data``: the repository's ``data/`` in a checkout, the shipped core
#: data in an installed wheel.
BUNDLED_DATA_LINK = Path(__file__).parent / "_data"


def is_checkout(link: Path = BUNDLED_DATA_LINK) -> bool:
    """Whether this is a development checkout rather than an installed wheel.

    A wheel carries ``tools/_data`` as a **real directory**; anything else is a
    checkout. Usually that is a symlink into ``data/``, but a clone made
    without symlink support (Git for Windows' default ``core.symlinks=false``,
    or an archive that drops links) writes the link as a small text file, and
    that is a checkout too. An editable install is a checkout.
    """

    return not (link.is_dir() and not link.is_symlink())


def bundled_data_dir(link: Path = BUNDLED_DATA_LINK) -> Path:
    """The bundled data root, resolved: ``tools/_data`` or the checkout's ``data/``.

    ``tools/_data`` when it is a directory -- the shipped core data in a
    wheel, or the symlink into ``data/`` in a checkout. When it is not (the
    link written as a text file by a clone without symlinks), the
    repository's own ``data/`` beside ``tools/``. Without this fallback such a
    clone found no bundled data, and the fixture-write guard, rooted here,
    stopped protecting ``data/`` at all.
    """

    if link.is_dir():
        return link.resolve()
    repository_data = link.parent.parent / "data"
    if repository_data.is_dir():
        return repository_data.resolve()
    return link.resolve()


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
    if home is None:
        try:
            home = Path.home()
        except (RuntimeError, KeyError, OSError):
            # No resolvable home (a service account, a stripped container).
            # tools.config calls this at import, so failing here would make
            # every tool unimportable; a per-user temporary directory keeps
            # them working, and KEPLER_HOME is the way to choose a real one.
            import tempfile

            return Path(tempfile.gettempdir()) / f"kepler-{os.getuid() if hasattr(os, 'getuid') else 'user'}"
    if platform == "darwin":
        base = home / "Library" / "Application Support"
    elif platform == "win32":
        local = environ.get("LOCALAPPDATA", "")
        base = Path(local) if local else home / "AppData" / "Local"
    else:
        xdg = environ.get("XDG_DATA_HOME", "")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else home / ".local" / "share"
    return base / "kepler"
