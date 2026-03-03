"""Behavior tests for migration-track schema contract wiring."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_migration_tracks.py"


class TestRunMigrationTracksSchemaContract(unittest.TestCase):
    """Verify schema contract behavior through script CLI."""

    def _run_script(self, *, config_text: str, repo_root: Path) -> subprocess.CompletedProcess:
        config_path = repo_root / "mugen.toml"
        config_path.write_text(config_text, encoding="utf-8")
        (repo_root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

        return subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--repo-root",
                str(repo_root),
                "--config-file",
                str(config_path),
                "--dry-run",
                "upgrade",
                "head",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_defaults_core_schema_to_mugen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            result = self._run_script(
                config_text="",
                repo_root=repo_root,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("track=core schema=mugen", result.stdout)

    def test_uses_configured_core_schema(self) -> None:
        config_text = textwrap.dedent(
            """
            [rdbms.migration_tracks.core]
            schema = "core_runtime"
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            result = self._run_script(
                config_text=config_text,
                repo_root=repo_root,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("track=core schema=core_runtime", result.stdout)

    def test_rejects_invalid_core_schema(self) -> None:
        config_text = textwrap.dedent(
            """
            [rdbms.migration_tracks.core]
            schema = "bad-schema"
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            result = self._run_script(
                config_text=config_text,
                repo_root=repo_root,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid rdbms.migration_tracks.core.schema", result.stderr)
