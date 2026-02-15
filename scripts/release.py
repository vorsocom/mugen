#!/usr/bin/env python3
"""Automate mugen release preparation and finish flow."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
PYPROJECT_PATH = ROOT / "pyproject.toml"
QUARTMAN_PATH = ROOT / "quartman.py"
QUALITY_GATES_SCRIPT = (
    ROOT
    / ".codex"
    / "skills"
    / "prepush-quality-gates"
    / "scripts"
    / "run_prepush_quality_gates.sh"
)

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _run(
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    cwd: Path = ROOT,
) -> str:
    result = subprocess.run(  # noqa: S603
        args,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def _ensure_clean_worktree() -> None:
    status = _run(["git", "status", "--porcelain"], capture=True)
    if status != "":
        raise RuntimeError("Working tree is not clean.")


def _current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)


def _ensure_branch(branch: str) -> None:
    current = _current_branch()
    if current != branch:
        raise RuntimeError(f"Expected current branch '{branch}', found '{current}'.")


def _branch_exists_local(branch: str) -> bool:
    return (
        subprocess.run(  # noqa: S603
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )


def _branch_exists_remote(branch: str) -> bool:
    output = _run(
        ["git", "ls-remote", "--heads", "origin", branch],
        capture=True,
    )
    return output != ""


def _read_current_version() -> str:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find [tool.poetry] version in pyproject.toml.")
    return match.group(1)


def _validate_version(version: str) -> None:
    if SEMVER_RE.match(version) is None:
        raise RuntimeError(f"Version '{version}' is not valid semver (x.y.z).")


def _bump_version(version: str, part: str) -> str:
    _validate_version(version)
    major, minor, patch = [int(v) for v in version.split(".")]
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _replace_once(path: Path, pattern: re.Pattern[str], replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Failed to update expected pattern in {path}.")
    path.write_text(updated, encoding="utf-8")


def _update_version_files(version: str) -> None:
    _validate_version(version)

    _replace_once(
        PYPROJECT_PATH,
        re.compile(r'^version = "[^"]+"$', flags=re.MULTILINE),
        f'version = "{version}"',
    )

    _replace_once(
        QUARTMAN_PATH,
        re.compile(r'^__version__ = "[^"]+"$', flags=re.MULTILINE),
        f'__version__ = "{version}"',
    )


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
            "Could not parse coverage total. Run gates first or pass --coverage."
        )
    return int(coverage_total)


def _update_coverage_badge(coverage_total: int) -> None:
    color = _coverage_color(coverage_total)
    _replace_once(
        README_PATH,
        re.compile(r"Test_Coverage-\d+%25-(?:green|yellow|red)"),
        f"Test_Coverage-{coverage_total}%25-{color}",
    )


def _run_quality_gates(python_bin: str) -> None:
    if not QUALITY_GATES_SCRIPT.exists():
        raise RuntimeError(f"Quality gates script not found: {QUALITY_GATES_SCRIPT}")
    _run(
        [
            "bash",
            str(QUALITY_GATES_SCRIPT),
            "--python",
            python_bin,
        ]
    )


def _prepare_release(args: argparse.Namespace) -> None:
    _ensure_clean_worktree()
    _ensure_branch("develop")

    current = _read_current_version()
    target = args.version if args.version else _bump_version(current, args.bump)
    _validate_version(target)
    if target == current:
        raise RuntimeError("Target version equals current version.")

    release_branch = f"release/{target}"
    if _branch_exists_local(release_branch):
        raise RuntimeError(f"Local branch already exists: {release_branch}")
    if _branch_exists_remote(release_branch):
        raise RuntimeError(f"Remote branch already exists: {release_branch}")

    _run(["git", "checkout", "-b", release_branch, "develop"])

    _update_version_files(target)

    if args.skip_gates:
        if args.coverage is not None:
            coverage_total = args.coverage
        else:
            coverage_total = _resolve_coverage_total(args.python)
    else:
        _run_quality_gates(args.python)
        coverage_total = _resolve_coverage_total(args.python)

    _update_coverage_badge(coverage_total)

    _run(["git", "add", str(PYPROJECT_PATH), str(QUARTMAN_PATH), str(README_PATH)])
    _run(["git", "commit", "-m", f"Prepare release {target}"])

    if args.push:
        _run(["git", "push", "-u", "origin", release_branch])

    print(f"Release branch ready: {release_branch}")
    print("Next: open PR to main or run `scripts/release.py finish --version ...`")


def _ensure_release_branch_available(release_branch: str) -> None:
    if _branch_exists_local(release_branch):
        return

    _run(["git", "fetch", "origin", f"{release_branch}:{release_branch}"])
    if not _branch_exists_local(release_branch):
        raise RuntimeError(f"Release branch not found: {release_branch}")


def _finish_release(args: argparse.Namespace) -> None:
    _validate_version(args.version)
    _ensure_clean_worktree()
    release_branch = f"release/{args.version}"
    _ensure_release_branch_available(release_branch)

    tag_exists = _run(["git", "tag", "-l", args.version], capture=True)
    if tag_exists != "":
        raise RuntimeError(f"Tag already exists: {args.version}")

    _run(["git", "checkout", "main"])
    _run(
        [
            "git",
            "merge",
            "--no-ff",
            release_branch,
            "-m",
            f"Merge {release_branch} into main",
        ]
    )
    _run(["git", "tag", "-a", args.version, "-m", f"Release {args.version}"])
    _run(["git", "push", "origin", "main"])
    _run(["git", "push", "origin", args.version])

    _run(["git", "checkout", "develop"])
    _run(
        [
            "git",
            "merge",
            "--no-ff",
            release_branch,
            "-m",
            f"Merge {release_branch} into develop",
        ]
    )
    _run(["git", "push", "origin", "develop"])

    if not args.keep_release_branch:
        _run(["git", "branch", "-d", release_branch])
        if not args.keep_remote_release_branch:
            _run(["git", "push", "origin", "--delete", release_branch], check=False)

    print(f"Release flow complete for {args.version}.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automate mugen release operations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create release branch and bump files.")
    prepare_group = prepare.add_mutually_exclusive_group(required=False)
    prepare_group.add_argument(
        "--bump",
        choices=("major", "minor", "patch"),
        default="patch",
        help="Semver component to bump from current version.",
    )
    prepare_group.add_argument(
        "--version",
        help="Explicit target version (x.y.z).",
    )
    prepare.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used for quality gates and coverage lookup.",
    )
    prepare.add_argument(
        "--skip-gates",
        action="store_true",
        help="Skip full pre-push quality gates.",
    )
    prepare.add_argument(
        "--coverage",
        type=int,
        help="Coverage percentage for README badge when --skip-gates is set.",
    )
    prepare.add_argument(
        "--push",
        action="store_true",
        help="Push release branch to origin after commit.",
    )
    prepare.set_defaults(handler=_prepare_release)

    finish = subparsers.add_parser("finish", help="Merge/tag/push and clean release branch.")
    finish.add_argument("--version", required=True, help="Release version (x.y.z).")
    finish.add_argument(
        "--keep-release-branch",
        action="store_true",
        help="Keep local release branch after finish flow.",
    )
    finish.add_argument(
        "--keep-remote-release-branch",
        action="store_true",
        help="Keep remote release branch after finish flow.",
    )
    finish.set_defaults(handler=_finish_release)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
