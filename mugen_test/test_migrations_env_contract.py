"""Contract tests for migration env configuration and schema bootstrapping."""

from __future__ import annotations

from pathlib import Path
import unittest

from mugen.core.contract.migration_config import (
    configured_core_extension_entries,
    migration_schema_bootstrap_order,
)


class TestMigrationsEnvContract(unittest.TestCase):
    """Protect migration env contract guarantees for first deployment."""

    def test_rejects_legacy_core_plugins_key(self) -> None:
        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "plugins": [{"models": "legacy.module"}],
                    }
                }
            }
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.modules.core.plugins is no longer supported",
        ):
            configured_core_extension_entries(config)

    def test_bootstrap_order_includes_distinct_version_schema(self) -> None:
        self.assertEqual(
            migration_schema_bootstrap_order(
                runtime_schema="mugen",
                version_table_schema="mugen_version",
            ),
            ("mugen", "mugen_version"),
        )

    def test_bootstrap_order_deduplicates_identical_schemas(self) -> None:
        self.assertEqual(
            migration_schema_bootstrap_order(
                runtime_schema="mugen",
                version_table_schema="mugen",
            ),
            ("mugen",),
        )

    def test_env_bootstrap_imports_shared_migration_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env_source = (repo_root / "migrations" / "env.py").read_text(encoding="utf-8")

        self.assertIn(
            "from mugen.core.contract.migration_config import",
            env_source,
        )
        self.assertNotIn('core_cfg.get("plugins"', env_source)


if __name__ == "__main__":
    unittest.main()
