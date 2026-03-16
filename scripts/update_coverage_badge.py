#!/usr/bin/env python3
"""Update or validate the README coverage badge from coverage.py totals."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
BADGE_RE = re.compile(r"Test_Coverage-\d+%25-(?:green|yellow|red)")


def _run(args: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(  # noqa: S603
        args,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def _coverage_color(coverage_total: int) -> str:
    if coverage_total >= 90:
        return "green"
    if coverage_total >= 70:
        return "yellow"
    return "red"


def _resolve_coverage_total(python_bin: str) -> int:
    coverage_total = _run(
        [python_bin, "-m", "coverage", "report", "--format=total"],
        capture=True,
    )
    if not coverage_total.isdigit():
        raise RuntimeError(
            "Could not parse coverage total from coverage.py. "
            "Run coverage first or pass --coverage."
        )
    return int(coverage_total)


def _render_badge(coverage_total: int) -> str:
    color = _coverage_color(coverage_total)
    return f"Test_Coverage-{coverage_total}%25-{color}"


def _update_or_check_badge(coverage_total: int, check_only: bool) -> int:
    readme_text = README_PATH.read_text(encoding="utf-8")
    badge_text = _render_badge(coverage_total)
    updated_text, count = BADGE_RE.subn(badge_text, readme_text, count=1)
    if count != 1:
        raise RuntimeError("Could not find coverage badge in README.md.")

    if check_only:
        if updated_text != readme_text:
            print(
                "README coverage badge is stale. "
                "Run scripts/update_coverage_badge.py without --check."
            )
            return 1
        print(f"README coverage badge is current at {coverage_total}%.")
        return 0

    if updated_text != readme_text:
        README_PATH.write_text(updated_text, encoding="utf-8")
        print(f"Updated README coverage badge to {coverage_total}%.")
        return 0

    print(f"README coverage badge already current at {coverage_total}%.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update or validate README coverage badge."
    )
    parser.add_argument(
        "--python",
        default="python",
        help="Python interpreter used to query coverage totals.",
    )
    parser.add_argument(
        "--coverage",
        type=int,
        help="Explicit coverage percentage to use instead of coverage.py report.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; exit non-zero when badge is out of date.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    coverage_total = (
        args.coverage
        if args.coverage is not None
        else _resolve_coverage_total(args.python)
    )

    if coverage_total < 0 or coverage_total > 100:
        raise RuntimeError(f"Coverage percentage out of range: {coverage_total}")

    return _update_or_check_badge(coverage_total, args.check)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
