#!/usr/bin/env python3
"""Validate Conventional Commit messages for local hooks and CI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)

TYPE_PATTERN = "|".join(ALLOWED_TYPES)
CONVENTIONAL_RE = re.compile(rf"^({TYPE_PATTERN})(\([a-z0-9][a-z0-9._/-]*\))?(!)?: .+$")
MERGE_RE = re.compile(r"^Merge (?:pull request|branch) .+")
MERGE_INTO_RE = re.compile(r"^Merge .+ into .+")
GIT_REVERT_RE = re.compile(r'^Revert ".*"$')


def _run(args: list[str]) -> str:
    result = subprocess.run(  # noqa: S603
        args,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def _is_valid_message(subject: str) -> bool:
    if subject == "":
        return False
    return (
        CONVENTIONAL_RE.match(subject) is not None
        or MERGE_RE.match(subject) is not None
        or MERGE_INTO_RE.match(subject) is not None
        or GIT_REVERT_RE.match(subject) is not None
    )


def _read_commit_subject(message_file: Path) -> str:
    for line in message_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        return stripped
    return ""


def _validate_one(label: str, subject: str) -> str | None:
    if _is_valid_message(subject):
        return None
    return f"{label}: {subject!r}"


def _validate_message_file(message_file: str) -> list[str]:
    subject = _read_commit_subject(Path(message_file))
    err = _validate_one("commit-msg", subject)
    return [] if err is None else [err]


def _validate_pr_title(pr_title: str) -> list[str]:
    err = _validate_one("pr-title", pr_title.strip())
    return [] if err is None else [err]


def _validate_commit_range(from_ref: str, to_ref: str) -> list[str]:
    output = _run(["git", "log", "--format=%H%x00%s", f"{from_ref}..{to_ref}"])
    errors: list[str] = []
    for line in output.splitlines():
        sha, subject = line.split("\x00", maxsplit=1)
        err = _validate_one(sha[:12], subject.strip())
        if err is not None:
            errors.append(err)
    return errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Conventional Commit messages."
    )
    parser.add_argument(
        "--message-file",
        help="Path to a commit message file (for commit-msg hooks).",
    )
    parser.add_argument(
        "--pr-title",
        help="Pull request title to validate.",
    )
    parser.add_argument(
        "--from-ref",
        help="Starting git ref (exclusive) for commit-range validation.",
    )
    parser.add_argument(
        "--to-ref",
        help="Ending git ref (inclusive) for commit-range validation.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if (
        args.message_file is None
        and args.pr_title is None
        and args.from_ref is None
        and args.to_ref is None
    ):
        parser.error(
            "Specify at least one mode: --message-file, --pr-title, or --from-ref/--to-ref."
        )

    if (args.from_ref is None) ^ (args.to_ref is None):
        parser.error("--from-ref and --to-ref must be provided together.")

    errors: list[str] = []
    if args.message_file is not None:
        errors.extend(_validate_message_file(args.message_file))
    if args.pr_title is not None:
        errors.extend(_validate_pr_title(args.pr_title))
    if args.from_ref is not None and args.to_ref is not None:
        errors.extend(_validate_commit_range(args.from_ref, args.to_ref))

    if errors:
        print("Conventional commit check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(
            "Expected format: <type>(<scope>): <description> "
            "(scope and ! are optional).",
            file=sys.stderr,
        )
        print(
            f"Allowed types: {', '.join(ALLOWED_TYPES)}.",
            file=sys.stderr,
        )
        return 1

    print("Conventional commit check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
