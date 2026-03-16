"""Behavior tests for plugin-track core schema qualification."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class TestPluginTrackCoreSchemaContract(unittest.TestCase):
    """Validates separated plugin tracks against non-default core schemas."""

    def test_context_engine_offline_sql_uses_configured_core_schema_for_tenant_fk(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "plugin-schema.toml"
            config_path.write_text(
                textwrap.dedent("""
                    [rdbms.alembic]
                    url = "postgresql+psycopg://user:pass@localhost/db"

                    [rdbms.migration_tracks.core]
                    schema = "core_runtime"
                    version_table = "alembic_version"
                    version_table_schema = "core_runtime"

                    [[rdbms.migration_tracks.plugins]]
                    name = "context_engine"
                    enabled = true
                    alembic_config = "plugins/context_engine/alembic.ini"
                    schema = "ctx_runtime"
                    version_table = "alembic_version_context_engine"
                    version_table_schema = "ctx_runtime"
                    """),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_migration_tracks.py",
                    "--python",
                    sys.executable,
                    "--config-file",
                    str(config_path),
                    "--track",
                    "context_engine",
                    "upgrade",
                    "head",
                    "--sql",
                ],
                cwd=repo_root,
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            "track=context_engine schema=ctx_runtime version=ctx_runtime.alembic_version_context_engine",
            result.stdout,
        )
        self.assertIn(
            "REFERENCES core_runtime.admin_tenant (id)",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
