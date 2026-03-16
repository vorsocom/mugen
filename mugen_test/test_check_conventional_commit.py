"""Regression tests for the conventional-commit validator CLI."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_conventional_commit.py"


class TestCheckConventionalCommitCli(unittest.TestCase):
    """Covers release-branch validation ranges used by CI."""

    def _git(self, repo_dir: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=True,
            text=True,
            capture_output=True,
        )

    def _write_and_commit(self, repo_dir: Path, *, content: str, message: str) -> None:
        target = repo_dir / "tracked.txt"
        target.write_text(content, encoding="utf-8")
        self._git(repo_dir, "add", str(target))
        self._git(repo_dir, "commit", "-m", message)

    def test_release_branch_is_validated_relative_to_develop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir)
            self._git(repo_dir, "init")
            self._git(repo_dir, "branch", "-m", "main")
            self._git(repo_dir, "config", "user.name", "Test User")
            self._git(repo_dir, "config", "user.email", "test@example.com")

            self._write_and_commit(
                repo_dir,
                content="init\n",
                message="chore: init repo",
            )

            self._git(repo_dir, "checkout", "-b", "develop")
            self._write_and_commit(
                repo_dir,
                content="develop work\n",
                message="Added relational database storage support.",
            )

            self._git(repo_dir, "checkout", "-b", "release/0.44.0")
            self._write_and_commit(
                repo_dir,
                content="release prep\n",
                message="chore(release): prepare 0.44.0",
            )

            main_range = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT_PATH),
                    "--from-ref",
                    "main",
                    "--to-ref",
                    "release/0.44.0",
                ],
                cwd=repo_dir,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(main_range.returncode, 1)
            self.assertIn(
                "Added relational database storage support.",
                main_range.stderr,
            )

            develop_range = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPT_PATH),
                    "--from-ref",
                    "develop",
                    "--to-ref",
                    "release/0.44.0",
                ],
                cwd=repo_dir,
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(develop_range.returncode, 0)
            self.assertIn("Conventional commit check passed.", develop_range.stdout)


if __name__ == "__main__":
    unittest.main()
