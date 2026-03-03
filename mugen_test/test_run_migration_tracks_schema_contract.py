"""Behavior tests for migration-track schema contract wiring."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_migration_tracks.py"


class TestRunMigrationTracksSchemaContract(unittest.TestCase):
    """Verify schema contract behavior through script CLI."""

    def _run_script(
        self,
        *,
        config_text: str | None,
        repo_root: Path,
        config_file: str | None = None,
        env_overrides: dict[str, str] | None = None,
        dry_run: bool = True,
    ) -> subprocess.CompletedProcess:
        if config_text is not None:
            config_path = repo_root / "mugen.toml"
            config_path.write_text(config_text, encoding="utf-8")
        (repo_root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

        cmd = [
            sys.executable,
            str(_SCRIPT_PATH),
            "--repo-root",
            str(repo_root),
        ]
        if config_file is not None:
            cmd.extend(["--config-file", config_file])
        if dry_run:
            cmd.append("--dry-run")
        cmd.extend(["upgrade", "head"])

        env = os.environ.copy()
        env.pop("MUGEN_CONFIG_FILE", None)
        if env_overrides:
            env.update(env_overrides)

        return subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=True,
            env=env,
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

    def test_respects_environment_config_file_when_cli_option_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "env.toml").write_text(
                "[rdbms.migration_tracks.core]\nschema = \"env_schema\"\n",
                encoding="utf-8",
            )
            result = self._run_script(
                config_text=None,
                repo_root=repo_root,
                env_overrides={"MUGEN_CONFIG_FILE": "env.toml"},
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("track=core schema=env_schema", result.stdout)

    def test_cli_config_file_overrides_environment_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "env.toml").write_text(
                "[rdbms.migration_tracks.core]\nschema = \"env_schema\"\n",
                encoding="utf-8",
            )
            (repo_root / "cli.toml").write_text(
                "[rdbms.migration_tracks.core]\nschema = \"cli_schema\"\n",
                encoding="utf-8",
            )
            result = self._run_script(
                config_text=None,
                repo_root=repo_root,
                config_file="cli.toml",
                env_overrides={"MUGEN_CONFIG_FILE": "env.toml"},
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("track=core schema=cli_schema", result.stdout)

    def test_sets_config_file_env_for_alembic_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            config_path = repo_root / "custom.toml"
            config_path.write_text("", encoding="utf-8")
            (repo_root / "alembic.py").write_text(
                textwrap.dedent(
                    """
                    import os
                    import sys

                    print(
                        "CHILD_MUGEN_CONFIG_FILE="
                        + str(os.getenv("MUGEN_CONFIG_FILE", ""))
                    )
                    raise SystemExit(0)
                    """
                ),
                encoding="utf-8",
            )
            result = self._run_script(
                config_text=None,
                repo_root=repo_root,
                config_file=str(config_path),
                dry_run=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"CHILD_MUGEN_CONFIG_FILE={config_path.resolve()}", result.stdout)

    def test_fails_fast_when_config_file_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            result = self._run_script(
                config_text=None,
                repo_root=repo_root,
                config_file="missing.toml",
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Config file not found:", result.stderr)
