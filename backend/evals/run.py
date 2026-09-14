"""Eval runner.

Usage (Prompt 7):
    python -m evals.run --suite all --repeat 3 --llm fake
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the purchasing-agent eval suite.")
    parser.add_argument("--suite", default="all")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--llm", choices=["real", "fake"], default="fake")
    args = parser.parse_args(argv)
    raise NotImplementedError(
        f"Eval harness lands in Prompt 7 (suite={args.suite}, repeat={args.repeat}, llm={args.llm})."
    )


if __name__ == "__main__":
    sys.exit(main())
