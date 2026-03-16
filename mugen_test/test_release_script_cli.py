"""Black-box tests for the release script CLI flows."""

from __future__ import annotations

from pathlib import Path
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "release.py"
_VERSION = "0.43.3"
_RELEASE_BRANCH = f"release/{_VERSION}"
_OPEN_PR_URL = "https://github.com/vorsocom/mugen/pull/123"
_MERGED_PR_URL = "https://github.com/vorsocom/mugen/pull/456"
_MERGE_COMMIT = "c2a4d98df475e7b8927f8df55d886cc5014831c1"
_OTHER_COMMIT = "f1f2f3f4f5f6f7f8f9fafbfcfdfeff0011223344"


class TestReleaseScriptCli(unittest.TestCase):
    """Validate the PR-based finish/publish flows through the CLI entrypoint."""

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _install_fake_commands(self, bin_dir: Path) -> None:
        self._write_executable(
            bin_dir / "git",
            """#!/usr/bin/env python3
import json
import os
import sys


def parse_set(name: str) -> set[str]:
    return {
        value for value in os.environ.get(name, "").split(",") if value
    }


def parse_mapping(name: str) -> dict[str, str]:
    mapping = {}
    raw_value = os.environ.get(name, "")
    if raw_value == "":
        return mapping
    for item in raw_value.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key and value:
            mapping[key] = value
    return mapping


def log(command: str, args: list[str]) -> None:
    with open(os.environ["FAKE_RELEASE_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"command": command, "args": args}) + "\\n")


args = sys.argv[1:]
log("git", args)
local_branches = parse_set("FAKE_GIT_LOCAL_BRANCHES")
remote_branches = parse_set("FAKE_GIT_REMOTE_BRANCHES")
local_tags = parse_set("FAKE_GIT_LOCAL_TAGS")
remote_tags = parse_set("FAKE_GIT_REMOTE_TAGS")
known_commits = parse_set("FAKE_GIT_KNOWN_COMMITS")
resolved_commits = parse_mapping("FAKE_GIT_RESOLVED_COMMITS")
ancestor_pairs = parse_set("FAKE_GIT_ANCESTORS")

if args == ["status", "--porcelain"]:
    raise SystemExit(0)
if len(args) == 4 and args[:3] == ["show-ref", "--verify", "--quiet"]:
    branch = args[3].replace("refs/heads/", "", 1)
    raise SystemExit(0 if branch in local_branches else 1)
if len(args) == 4 and args[:3] == ["ls-remote", "--heads", "origin"]:
    branch = args[3]
    if branch in remote_branches:
        print(f"deadbeef\\trefs/heads/{branch}")
    raise SystemExit(0)
if len(args) == 4 and args[:3] == ["ls-remote", "--tags", "origin"]:
    tag_name = args[3]
    if tag_name in remote_tags:
        print(f"deadbeef\\trefs/tags/{tag_name}")
    raise SystemExit(0)
if len(args) == 3 and args[:2] == ["tag", "-l"]:
    tag_name = args[2]
    if tag_name in local_tags:
        print(tag_name)
    raise SystemExit(0)
if len(args) == 6 and args[:2] == ["tag", "-a"] and args[4] == "-m":
    raise SystemExit(0)
if args[:3] == ["push", "-u", "origin"] and len(args) == 4:
    raise SystemExit(0)
if args[:2] == ["push", "origin"] and len(args) == 3:
    raise SystemExit(0)
if args[:3] == ["push", "origin", "--delete"] and len(args) == 4:
    raise SystemExit(0)
if args == ["fetch", "--tags", "origin", "main", "develop"]:
    raise SystemExit(0)
if len(args) == 3 and args[:2] == ["fetch", "origin"] and ":" in args[2]:
    raise SystemExit(0)
if args[:2] == ["checkout", "develop"] and len(args) == 2:
    raise SystemExit(0)
if args == ["pull", "--ff-only", "origin", "develop"]:
    raise SystemExit(0)
if len(args) == 5 and args[:2] == ["merge", "--no-ff"] and args[3] == "-m":
    raise SystemExit(0)
if len(args) == 3 and args[:2] == ["branch", "-d"]:
    raise SystemExit(0)
if len(args) == 4 and args[:3] == ["rev-parse", "--verify", "--quiet"]:
    commitish = args[3].replace("^{commit}", "", 1)
    if (
        commitish in known_commits
        or commitish in local_branches
        or commitish in local_tags
        or commitish in resolved_commits
    ):
        raise SystemExit(0)
    raise SystemExit(1)
if len(args) == 2 and args[0] == "rev-parse":
    commitish = args[1].replace("^{commit}", "", 1)
    if commitish in resolved_commits:
        print(resolved_commits[commitish])
        raise SystemExit(0)
    if commitish in known_commits:
        print(commitish)
        raise SystemExit(0)
    if commitish in local_tags and commitish in resolved_commits:
        print(resolved_commits[commitish])
        raise SystemExit(0)
    print(f"Unknown rev-parse target: {commitish}", file=sys.stderr)
    raise SystemExit(2)
if args[:2] == ["merge-base", "--is-ancestor"] and len(args) == 4:
    pair = f"{args[2]}>{args[3]}"
    raise SystemExit(0 if pair in ancestor_pairs else 1)

print(f"Unexpected git args: {args}", file=sys.stderr)
raise SystemExit(2)
""",
        )
        self._write_executable(
            bin_dir / "gh",
            """#!/usr/bin/env python3
import json
import os
import sys


def log(command: str, args: list[str]) -> None:
    with open(os.environ["FAKE_RELEASE_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"command": command, "args": args}) + "\\n")


args = sys.argv[1:]
log("gh", args)
release_branch = os.environ["FAKE_RELEASE_BRANCH"]

if args == [
    "pr",
    "list",
    "--limit",
    "1",
    "--state",
    "open",
    "--base",
    "main",
    "--head",
    release_branch,
    "--json",
    "url",
]:
    print(os.environ.get("FAKE_GH_OPEN_PRS_JSON", "[]"))
    raise SystemExit(0)

if args == [
    "pr",
    "list",
    "--limit",
    "1",
    "--state",
    "merged",
    "--base",
    "main",
    "--head",
    release_branch,
    "--json",
    "url,mergeCommit",
]:
    print(os.environ.get("FAKE_GH_MERGED_PRS_JSON", "[]"))
    raise SystemExit(0)

if args[:2] == ["pr", "create"]:
    print(os.environ["FAKE_GH_CREATE_URL"])
    raise SystemExit(0)

print(f"Unexpected gh args: {args}", file=sys.stderr)
raise SystemExit(2)
""",
        )

    def _read_commands(self, log_path: Path) -> list[dict[str, object]]:
        if not log_path.exists():
            return []
        return [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def _run_release(
        self,
        command: str,
        *,
        local_branches: list[str] | None = None,
        remote_branches: list[str] | None = None,
        local_tags: list[str] | None = None,
        remote_tags: list[str] | None = None,
        known_commits: list[str] | None = None,
        resolved_commits: dict[str, str] | None = None,
        ancestors: list[str] | None = None,
        open_prs_json: str = "[]",
        merged_prs_json: str = "[]",
        create_url: str = _OPEN_PR_URL,
    ) -> tuple[subprocess.CompletedProcess[str], list[dict[str, object]]]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "commands.jsonl"
            self._install_fake_commands(tmp_path)

            env = os.environ.copy()
            env["PATH"] = f"{tmp_path}:{env['PATH']}"
            env["FAKE_GIT_LOCAL_BRANCHES"] = ",".join(local_branches or [])
            env["FAKE_GIT_REMOTE_BRANCHES"] = ",".join(remote_branches or [])
            env["FAKE_GIT_LOCAL_TAGS"] = ",".join(local_tags or [])
            env["FAKE_GIT_REMOTE_TAGS"] = ",".join(remote_tags or [])
            env["FAKE_GIT_KNOWN_COMMITS"] = ",".join(known_commits or [])
            env["FAKE_GIT_RESOLVED_COMMITS"] = ",".join(
                f"{key}={value}" for key, value in (resolved_commits or {}).items()
            )
            env["FAKE_GIT_ANCESTORS"] = ",".join(ancestors or [])
            env["FAKE_GH_OPEN_PRS_JSON"] = open_prs_json
            env["FAKE_GH_MERGED_PRS_JSON"] = merged_prs_json
            env["FAKE_GH_CREATE_URL"] = create_url
            env["FAKE_RELEASE_BRANCH"] = _RELEASE_BRANCH
            env["FAKE_RELEASE_LOG"] = str(log_path)

            result = subprocess.run(
                [sys.executable, str(_SCRIPT_PATH), command, "--version", _VERSION],
                cwd=_REPO_ROOT,
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )

            return result, self._read_commands(log_path)

    def test_finish_creates_release_pr_instead_of_merging(self) -> None:
        result, commands = self._run_release(
            "finish",
            remote_branches=[_RELEASE_BRANCH],
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"Release PR ready: {_OPEN_PR_URL}", result.stdout)
        self.assertIn(
            f"Next: merge the PR, then run `scripts/release.py publish --version {_VERSION}`.",
            result.stdout,
        )

        git_args = [entry["args"] for entry in commands if entry["command"] == "git"]
        gh_args = [entry["args"] for entry in commands if entry["command"] == "gh"]
        self.assertIn(["status", "--porcelain"], git_args)
        self.assertIn(["ls-remote", "--heads", "origin", _RELEASE_BRANCH], git_args)
        self.assertIn(["ls-remote", "--tags", "origin", _VERSION], git_args)
        self.assertIn(
            [
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                _RELEASE_BRANCH,
                "--title",
                f"chore(release): {_VERSION}",
                "--body",
                "\n".join(
                    [
                        f"Prepare release {_VERSION} for merge into `main`.",
                        "",
                        "Generated by `scripts/release.py finish`.",
                        "Tag the merged `main` commit and sync `develop` after this PR lands.",
                    ]
                ),
            ],
            gh_args,
        )
        self.assertFalse(
            any(
                args[0] in {"checkout", "merge"} or args[:2] == ["push", "origin"]
                for args in git_args
            )
        )

    def test_finish_pushes_release_branch_when_only_local_copy_exists(self) -> None:
        result, commands = self._run_release(
            "finish",
            local_branches=[_RELEASE_BRANCH],
        )

        self.assertEqual(result.returncode, 0)
        git_args = [entry["args"] for entry in commands if entry["command"] == "git"]
        self.assertIn(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{_RELEASE_BRANCH}"],
            git_args,
        )
        self.assertIn(["push", "-u", "origin", _RELEASE_BRANCH], git_args)

    def test_finish_reports_existing_open_release_pr(self) -> None:
        result, commands = self._run_release(
            "finish",
            remote_branches=[_RELEASE_BRANCH],
            open_prs_json=json.dumps([{"url": _OPEN_PR_URL}]),
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"Release PR already open: {_OPEN_PR_URL}", result.stdout)
        self.assertFalse(
            any(
                entry["command"] == "gh" and entry["args"][:2] == ["pr", "create"]
                for entry in commands
            )
        )

    def test_finish_reports_existing_merged_release_pr(self) -> None:
        result, commands = self._run_release(
            "finish",
            remote_branches=[_RELEASE_BRANCH],
            merged_prs_json=json.dumps(
                [{"url": _MERGED_PR_URL, "mergeCommit": {"oid": _MERGE_COMMIT}}]
            ),
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"Release PR already merged: {_MERGED_PR_URL}", result.stdout)
        self.assertIn(
            f"Next: run `scripts/release.py publish --version {_VERSION}`.",
            result.stdout,
        )
        self.assertFalse(
            any(
                entry["command"] == "gh" and entry["args"][:2] == ["pr", "create"]
                for entry in commands
            )
        )

    def test_finish_fails_when_release_branch_does_not_exist(self) -> None:
        result, commands = self._run_release("finish")

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"ERROR: Release branch not found: {_RELEASE_BRANCH}",
            result.stderr,
        )
        self.assertFalse(any(entry["command"] == "gh" for entry in commands))

    def test_finish_fails_when_remote_tag_already_exists(self) -> None:
        result, commands = self._run_release(
            "finish",
            remote_branches=[_RELEASE_BRANCH],
            remote_tags=[_VERSION],
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"ERROR: Tag already exists: {_VERSION}", result.stderr)
        self.assertFalse(any(entry["command"] == "gh" for entry in commands))

    def test_publish_tags_merge_commit_syncs_develop_and_cleans_release_branch(self) -> None:
        result, commands = self._run_release(
            "publish",
            local_branches=[_RELEASE_BRANCH],
            remote_branches=[_RELEASE_BRANCH],
            known_commits=[_MERGE_COMMIT],
            merged_prs_json=json.dumps(
                [{"url": _MERGED_PR_URL, "mergeCommit": {"oid": _MERGE_COMMIT}}]
            ),
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"Release published for {_VERSION}.", result.stdout)
        self.assertIn(f"Release PR: {_MERGED_PR_URL}", result.stdout)
        self.assertIn(f"Tag {_VERSION}: created at {_MERGE_COMMIT}", result.stdout)
        self.assertIn("Develop sync: merged release/0.43.3", result.stdout)
        self.assertIn("Release branch cleanup: local=deleted remote=deleted", result.stdout)

        git_args = [entry["args"] for entry in commands if entry["command"] == "git"]
        self.assertIn(["fetch", "--tags", "origin", "main", "develop"], git_args)
        self.assertIn(
            ["tag", "-a", _VERSION, _MERGE_COMMIT, "-m", f"Release {_VERSION}"],
            git_args,
        )
        self.assertIn(["push", "origin", _VERSION], git_args)
        self.assertIn(["checkout", "develop"], git_args)
        self.assertIn(["pull", "--ff-only", "origin", "develop"], git_args)
        self.assertIn(
            [
                "merge",
                "--no-ff",
                _RELEASE_BRANCH,
                "-m",
                f"Merge {_RELEASE_BRANCH} into develop",
            ],
            git_args,
        )
        self.assertIn(["push", "origin", "develop"], git_args)
        self.assertIn(["branch", "-d", _RELEASE_BRANCH], git_args)
        self.assertIn(["push", "origin", "--delete", _RELEASE_BRANCH], git_args)

    def test_publish_falls_back_to_main_when_release_branch_is_absent(self) -> None:
        result, commands = self._run_release(
            "publish",
            known_commits=[_MERGE_COMMIT],
            merged_prs_json=json.dumps(
                [{"url": _MERGED_PR_URL, "mergeCommit": {"oid": _MERGE_COMMIT}}]
            ),
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Develop sync: merged origin/main", result.stdout)
        self.assertIn("Release branch cleanup: local=kept remote=already absent", result.stdout)

        git_args = [entry["args"] for entry in commands if entry["command"] == "git"]
        self.assertIn(
            [
                "merge",
                "--no-ff",
                "origin/main",
                "-m",
                f"Merge main into develop after release {_VERSION}",
            ],
            git_args,
        )
        self.assertNotIn(["branch", "-d", _RELEASE_BRANCH], git_args)
        self.assertNotIn(["push", "origin", "--delete", _RELEASE_BRANCH], git_args)

    def test_publish_fails_when_release_pr_is_still_open(self) -> None:
        result, commands = self._run_release(
            "publish",
            open_prs_json=json.dumps([{"url": _OPEN_PR_URL}]),
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(f"ERROR: Release PR not merged yet: {_OPEN_PR_URL}", result.stderr)
        self.assertFalse(
            any(
                entry["command"] == "git" and entry["args"][:2] == ["tag", "-a"]
                for entry in commands
            )
        )

    def test_publish_rejects_existing_tag_pointing_elsewhere(self) -> None:
        result, commands = self._run_release(
            "publish",
            local_tags=[_VERSION],
            known_commits=[_MERGE_COMMIT, _OTHER_COMMIT],
            resolved_commits={_VERSION: _OTHER_COMMIT},
            merged_prs_json=json.dumps(
                [{"url": _MERGED_PR_URL, "mergeCommit": {"oid": _MERGE_COMMIT}}]
            ),
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"ERROR: Tag {_VERSION} already points to {_OTHER_COMMIT}, expected {_MERGE_COMMIT}.",
            result.stderr,
        )
        self.assertFalse(
            any(
                entry["command"] == "git" and entry["args"][:2] == ["checkout", "develop"]
                for entry in commands
            )
        )

    def test_publish_skips_matching_tag_and_develop_merge_when_already_synced(self) -> None:
        result, commands = self._run_release(
            "publish",
            local_tags=[_VERSION],
            known_commits=[_MERGE_COMMIT],
            resolved_commits={_VERSION: _MERGE_COMMIT},
            ancestors=[f"{_MERGE_COMMIT}>develop"],
            merged_prs_json=json.dumps(
                [{"url": _MERGED_PR_URL, "mergeCommit": {"oid": _MERGE_COMMIT}}]
            ),
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"Tag {_VERSION}: already existed at {_MERGE_COMMIT}", result.stdout)
        self.assertIn("Develop sync: already up to date", result.stdout)

        git_args = [entry["args"] for entry in commands if entry["command"] == "git"]
        self.assertNotIn(
            ["tag", "-a", _VERSION, _MERGE_COMMIT, "-m", f"Release {_VERSION}"],
            git_args,
        )
        self.assertNotIn(["push", "origin", _VERSION], git_args)
        self.assertNotIn(["push", "origin", "develop"], git_args)
