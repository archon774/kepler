"""Console-script entry point for the Kepler Textual application."""

from __future__ import annotations

import argparse
import os
import sys

if __name__ == "__main__":
    # `python -m tools.tui`: load .env before the imports below read
    # tools.config, as the `kepler` script does (tools.tui.launch).
    from tools.dotenv import load_dotenv as _load_dotenv_first

    _load_dotenv_first()

from tools.config import load_dotenv
from tools.llm.base import BackendUnavailableError
from tools.tui.app import DEFAULT_THINKING_BUDGET, KeplerApp
from tools.tui.backends import (
    CHOICES,
    UnknownBackendError,
    names,
    open_backend,
    resolve_spec,
    unavailable_message,
)

__all__ = ["main", "launch_spec"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kepler")
    parser.add_argument(
        "--backend",
        help=(
            "Backend to start on: a name (" + ", ".join(names()) + ") or a "
            "provider/model spec. Defaults to KEPLER_MODEL_BACKEND, then to "
            f"{CHOICES[0].provider}. Switch at any time with /backend."
        ),
    )
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=DEFAULT_THINKING_BUDGET,
        help=(
            "Tokens the model may spend on reasoning the console will show. "
            "0 turns it off; providers that reveal reasoning without being "
            "asked still do."
        ),
    )
    return parser.parse_args(argv)


def launch_spec(requested: str | None = None) -> str:
    """The ``provider/model`` spec the console starts on.

    Resolution order, and no other: the ``--backend`` flag, then
    ``KEPLER_MODEL_BACKEND``, then the first offered choice. The flag accepts a
    bare name so ``kepler --backend ollama`` works; the environment variable
    does not, because it is the model port's own contract and is read
    identically by the model port's own factory and the benchmark harness.

    Falling back to a default rather than refusing is deliberate. The backend
    is no longer a launch-time decision a person is stuck with -- ``/backend``
    changes it inside the session -- so an unset variable should open the
    console, not print a usage error at someone who has not seen it yet.
    """

    if requested:
        return resolve_spec(requested)
    configured = os.environ.get("KEPLER_MODEL_BACKEND")
    if configured:
        return configured
    first = CHOICES[0]
    return f"{first.provider}/{first.default_model}"


def main() -> int:
    """Build the selected backend and launch the full-screen console.

    Returns a process exit status. A console that could not be configured
    exits non-zero: it is launched from shells and scripts, and reporting
    success after printing "cannot use" to stderr is how a wrapper ends up
    believing a session ran.
    """

    args = _parse_args()
    # Before any spec is resolved: a key in .env is what makes the default
    # Anthropic choice work on a fresh checkout, and it must be in the
    # environment before the factory reads it.
    load_dotenv()

    try:
        spec = launch_spec(args.backend)
    except UnknownBackendError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    thinking_budget = args.thinking_budget if args.thinking_budget > 0 else None

    try:
        backend = open_backend(spec, thinking_budget=thinking_budget)
    except BackendUnavailableError as exc:
        print(unavailable_message(spec, exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Cannot start on {spec}: {exc}", file=sys.stderr)
        return 2

    KeplerApp(
        backend=backend,
        max_turns=args.max_turns,
        thinking_budget=thinking_budget,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
