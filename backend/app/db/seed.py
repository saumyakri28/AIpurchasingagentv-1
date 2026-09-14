"""Deterministic world seeder.

Usage (implemented in Prompt 1):
    python -m app.db.seed --world base
"""

from __future__ import annotations

import argparse
import sys


def seed_world(world: str, *, reset: bool = True) -> None:
    """Reset the database and load a named YAML fixture world.

    Fixed random seed and a frozen "today" date will be applied here
    so evals are reproducible.
    """
    raise NotImplementedError(
        f"Seeding world {world!r} is implemented in Prompt 1 (reset={reset})."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset and seed a fixture world.")
    parser.add_argument("--world", default="base", help="Fixture world name (default: base)")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Load fixtures without dropping existing tables.",
    )
    args = parser.parse_args(argv)
    seed_world(args.world, reset=not args.no_reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
