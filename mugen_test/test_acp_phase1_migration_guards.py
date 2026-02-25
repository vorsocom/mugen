"""Focused checks for ACP phase1 remediation migration guardrails."""

from pathlib import Path
import unittest


class TestAcpPhase1MigrationGuards(unittest.TestCase):
    """Verifies migration SQL includes expected phase1 remediation contracts."""

    def test_migration_contains_seed_and_split_uniqueness_indexes(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "e7a1c2d3f4b5_phase1_global_tenant_and_schema_binding_uniqueness.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn("INSERT INTO mugen.admin_tenant", text)
        self.assertIn("ON CONFLICT (id) DO UPDATE", text)
        self.assertIn(
            "DROP INDEX IF EXISTS mugen.ux_schema_binding__tenant_target_kind_active",
            text,
        )
        self.assertIn("ux_schema_binding__tenant_target_kind_active_no_action", text)
        self.assertIn("ux_schema_binding__tenant_target_kind_active_with_action", text)
        self.assertIn("target_action IS NULL", text)
        self.assertIn("target_action IS NOT NULL", text)
