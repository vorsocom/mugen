#!/usr/bin/env python3
"""Automate mugen release preparation, release PR, and publish flow."""

from __future__ import annotations

import argparse
import json
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


def _tag_exists_remote(tag: str) -> bool:
    output = _run(
        ["git", "ls-remote", "--tags", "origin", tag],
        capture=True,
    )
    return output != ""


def _tag_exists(tag: str) -> bool:
    return _run(["git", "tag", "-l", tag], capture=True) != "" or _tag_exists_remote(tag)


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
    _run(["git", "commit", "-m", f"chore(release): prepare {target}"])

    if args.push:
        _run(["git", "push", "-u", "origin", release_branch])

    print(f"Release branch ready: {release_branch}")
    print("Next: open a PR to main or run `scripts/release.py finish --version ...`")


def _ensure_release_branch_ready_for_pr(release_branch: str) -> None:
    if _branch_exists_remote(release_branch):
        return
    if not _branch_exists_local(release_branch):
        raise RuntimeError(f"Release branch not found: {release_branch}")

    _run(["git", "push", "-u", "origin", release_branch])


def _ensure_release_branch_available_locally(release_branch: str) -> bool:
    if _branch_exists_local(release_branch):
        return True
    if not _branch_exists_remote(release_branch):
        return False

    _run(["git", "fetch", "origin", f"{release_branch}:{release_branch}"])
    return True


def _release_pr_title(version: str) -> str:
    return f"chore(release): {version}"


def _release_pr_body(version: str) -> str:
    return "\n".join(
        [
            f"Prepare release {version} for merge into `main`.",
            "",
            "Generated by `scripts/release.py finish`.",
            "Tag the merged `main` commit and sync `develop` after this PR lands.",
        ]
    )


def _release_pr(
    release_branch: str,
    *,
    state: str,
) -> dict[str, object] | None:
    fields = "url"
    if state == "merged":
        fields = "url,mergeCommit"
    output = _run(
        [
            "gh",
            "pr",
            "list",
            "--limit",
            "1",
            "--state",
            state,
            "--base",
            "main",
            "--head",
            release_branch,
            "--json",
            fields,
        ],
        capture=True,
    )
    pull_requests = json.loads(output)
    if not pull_requests:
        return None
    return dict(pull_requests[0])


def _commit_exists_locally(commitish: str) -> bool:
    return (
        subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--verify", "--quiet", f"{commitish}^{{commit}}"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )


def _resolve_commitish(commitish: str) -> str:
    return _run(["git", "rev-parse", f"{commitish}^{{commit}}"], capture=True)


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(  # noqa: S603
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )


def _finish_release(args: argparse.Namespace) -> None:
    _validate_version(args.version)
    _ensure_clean_worktree()
    release_branch = f"release/{args.version}"
    _ensure_release_branch_ready_for_pr(release_branch)

    if _tag_exists(args.version):
        raise RuntimeError(f"Tag already exists: {args.version}")

    merged_pr = _release_pr(release_branch, state="merged")
    if merged_pr is not None:
        print(f"Release PR already merged: {merged_pr['url']}")
        print(f"Next: run `scripts/release.py publish --version {args.version}`.")
        return

    existing_pr = _release_pr(release_branch, state="open")
    if existing_pr is not None:
        print(f"Release PR already open: {existing_pr['url']}")
        print(
            f"Next: merge the PR, then run `scripts/release.py publish --version {args.version}`."
        )
        return

    pr_url = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            release_branch,
            "--title",
            _release_pr_title(args.version),
            "--body",
            _release_pr_body(args.version),
        ],
        capture=True,
    )
    print(f"Release PR ready: {pr_url}")
    print(
        f"Next: merge the PR, then run `scripts/release.py publish --version {args.version}`."
    )


def _publish_release(args: argparse.Namespace) -> None:
    _validate_version(args.version)
    _ensure_clean_worktree()
    release_branch = f"release/{args.version}"

    merged_pr = _release_pr(release_branch, state="merged")
    if merged_pr is None:
        open_pr = _release_pr(release_branch, state="open")
        if open_pr is not None:
            raise RuntimeError(f"Release PR not merged yet: {open_pr['url']}")
        raise RuntimeError(f"Merged release PR not found for {release_branch}.")

    merge_commit = merged_pr.get("mergeCommit")
    merge_commit_oid = ""
    if isinstance(merge_commit, dict):
        merge_commit_oid = str(merge_commit.get("oid", ""))
    if merge_commit_oid == "":
        raise RuntimeError(
            f"Could not determine merge commit for release PR: {merged_pr['url']}"
        )

    _run(["git", "fetch", "--tags", "origin", "main", "develop"])
    release_branch_available = _ensure_release_branch_available_locally(release_branch)
    if not _commit_exists_locally(merge_commit_oid):
        raise RuntimeError(f"Merge commit is not available locally: {merge_commit_oid}")

    if _run(["git", "tag", "-l", args.version], capture=True) == "":
        _run(["git", "tag", "-a", args.version, merge_commit_oid, "-m", f"Release {args.version}"])
        _run(["git", "push", "origin", args.version])
        tag_status = "created"
    else:
        existing_tag_target = _resolve_commitish(args.version)
        if existing_tag_target != merge_commit_oid:
            raise RuntimeError(
                f"Tag {args.version} already points to {existing_tag_target}, expected {merge_commit_oid}."
            )
        tag_status = "already existed"

    _run(["git", "checkout", "develop"])
    _run(["git", "pull", "--ff-only", "origin", "develop"])

    develop_sync_source = "origin/main"
    develop_sync_marker = merge_commit_oid
    develop_merge_message = f"Merge main into develop after release {args.version}"
    if release_branch_available:
        develop_sync_source = release_branch
        develop_sync_marker = release_branch
        develop_merge_message = f"Merge {release_branch} into develop"

    if _is_ancestor(develop_sync_marker, "develop"):
        develop_status = "already up to date"
    else:
        _run(["git", "merge", "--no-ff", develop_sync_source, "-m", develop_merge_message])
        _run(["git", "push", "origin", "develop"])
        develop_status = f"merged {develop_sync_source}"

    local_cleanup = "kept"
    if not args.keep_release_branch and _branch_exists_local(release_branch):
        _run(["git", "branch", "-d", release_branch])
        local_cleanup = "deleted"

    remote_cleanup = "kept"
    if not args.keep_remote_release_branch:
        if _branch_exists_remote(release_branch):
            _run(["git", "push", "origin", "--delete", release_branch], check=False)
            remote_cleanup = "deleted"
        else:
            remote_cleanup = "already absent"

    print(f"Release published for {args.version}.")
    print(f"Release PR: {merged_pr['url']}")
    print(f"Tag {args.version}: {tag_status} at {merge_commit_oid}")
    print(f"Develop sync: {develop_status}")
    print(f"Release branch cleanup: local={local_cleanup} remote={remote_cleanup}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automate mugen release operations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="Create release branch and bump files."
    )
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

    finish = subparsers.add_parser("finish", help="Open a release PR to main.")
    finish.add_argument("--version", required=True, help="Release version (x.y.z).")
    finish.add_argument(
        "--keep-release-branch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    finish.add_argument(
        "--keep-remote-release-branch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    finish.set_defaults(handler=_finish_release)

    publish = subparsers.add_parser(
        "publish",
        help="Tag the merged release, sync develop, and clean the release branch.",
    )
    publish.add_argument("--version", required=True, help="Release version (x.y.z).")
    publish.add_argument(
        "--keep-release-branch",
        action="store_true",
        help="Keep the local release branch after publish.",
    )
    publish.add_argument(
        "--keep-remote-release-branch",
        action="store_true",
        help="Keep the remote release branch after publish.",
    )
    publish.set_defaults(handler=_publish_release)

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
