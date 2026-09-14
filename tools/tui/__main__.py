"""Console-script entry point for the Kepler Textual application."""

from __future__ import annotations

import argparse
import sys

from tools.llm.base import BackendUnavailableError
from tools.llm.factory import build_backend
from tools.tui.app import KeplerApp

__all__ = ["main"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kepler")
    parser.add_argument(
        "--backend",
        help="Provider/model backend spec; defaults to KEPLER_MODEL_BACKEND.",
    )
    parser.add_argument("--max-turns", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    """Build the selected backend and launch the full-screen console."""

    args = _parse_args()
    try:
        backend = build_backend(args.backend)
    except BackendUnavailableError as exc:
        print(f"Configure {exc.variable} before starting Kepler.", file=sys.stderr)
        return
    KeplerApp(backend=backend, max_turns=args.max_turns).run()


if __name__ == "__main__":
    main()
