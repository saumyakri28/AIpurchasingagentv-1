"""Eval runner.

Usage:
    python -m evals.run --suite all --repeat 3 --llm fake
    python -m evals.run --suite E1 --repeat 1 --llm fake
"""

from __future__ import annotations

import argparse
import sys

from evals.report import write_report
from evals.runner import run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the purchasing-agent eval suite.")
    parser.add_argument("--suite", default="all", help="all, E1..E13, or a case id prefix")
    parser.add_argument("--repeat", type=int, default=1, help="repeats per case (stability)")
    parser.add_argument("--llm", choices=["real", "fake"], default="fake")
    args = parser.parse_args(argv)
    report = run_suite(suite=args.suite, repeat=args.repeat, llm=args.llm)
    path = write_report(report)
    print(path.read_text())
    print(f"wrote {path}")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
