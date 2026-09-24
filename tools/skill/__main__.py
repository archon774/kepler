"""``python -m tools.skill`` renders ``skills/kepler-tools/``; ``--check`` reports drift."""

from __future__ import annotations

import argparse
import sys

from tools.skill import REPOSITORY_COPY, check_repository_copy, write_repository_copy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.skill",
        description=f"Render the Kepler skill source into {REPOSITORY_COPY}.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit 1 if the rendered copy is out of date.",
    )
    args = parser.parse_args(argv)

    if args.check:
        drift = check_repository_copy()
        for name in drift:
            print(f"stale: {name}", file=sys.stderr)
        return 1 if drift else 0

    for name in write_repository_copy():
        print(f"rendered: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
