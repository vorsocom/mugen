"""Focused checks for phase6 ops_connector migration contracts and reseed wiring."""

from pathlib import Path
import unittest


class TestPhase6OpsConnectorMigrationGuards(unittest.TestCase):
    """Verifies phase6 migration DDL guards, indexes, and reseed path."""

    def test_schema_migration_contains_required_tables_indexes_and_guards(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "d9f2a4b6c8e0_phase6_ops_connector_schema.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "b7c9d1e3f5a7"', text
        )
        self.assertIn("ops_connector_type", text)
        self.assertIn("ops_connector_instance", text)
        self.assertIn("ops_connector_call_log", text)
        self.assertIn("ops_connector_instance_status", text)
        self.assertIn("ops_connector_call_log_status", text)
        self.assertIn("ix_ops_connector_instance__tenant_status", text)
        self.assertIn("ix_ops_connector_instance__tenant_type", text)
        self.assertIn("ix_ops_connector_call_log__tenant_trace", text)
        self.assertIn("ix_ops_connector_call_log__tenant_instance_created", text)
        self.assertIn("ix_ops_connector_call_log__tenant_status_created", text)
        self.assertIn("tg_guard_ops_connector_call_log_mutation", text)
        self.assertIn("tr_guard_ops_connector_call_log_update", text)
        self.assertIn("tr_guard_ops_connector_call_log_delete", text)
        self.assertIn("ops_connector_call_log is immutable", text)
        self.assertIn("INSERT INTO mugen.admin_key_ref", text)
        self.assertIn("AND purpose = 'ops_connector_secret'", text)
        self.assertIn("AND key_id = 'ops_connector_default'", text)
        self.assertIn("DELETE FROM mugen.admin_key_ref", text)
        self.assertIn(
            "AND attributes ->> 'seed_source' = 'phase6_ops_connector';",
            text,
        )

    def test_phase6_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "e3b5d7f9a1c2_reseed_acp_for_phase6_ops_connector.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "d9f2a4b6c8e0"', text
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)

    def test_merge_revision_collapses_heads(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "f0b2d4e6a8c1_merge_phase5_export_and_phase6_connector_heads.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn("c6e2a4b8d0f1", text)
        self.assertIn("e3b5d7f9a1c2", text)
