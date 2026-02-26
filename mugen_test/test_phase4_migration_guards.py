"""Focused checks for phase4 migration contracts and ACP reseed wiring."""

from pathlib import Path
import unittest


class TestPhase4MigrationGuards(unittest.TestCase):
    """Verifies phase4 migration DDL guards, indexes, and reseed path."""

    def test_schema_migration_contains_required_indexes_and_guards(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "a4f8c2d9e6b1_phase4_security_compliance_substrate.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn("ux_key_ref__tenant_purpose_key", text)
        self.assertIn("ux_key_ref__tenant_purpose_active", text)
        self.assertIn("ux_plugin_capability_grant__tenant_plugin_active", text)
        self.assertIn("ix_ops_gov_lifecycle_log__tenant_resource_created", text)
        self.assertIn("ix_audit_evidence_blob__tenant_trace", text)
        self.assertIn("ix_audit_evidence_blob__tenant_content_hash", text)
        self.assertIn("evidence_blob_id", text)
        self.assertIn("fkx_ops_gov_data_handling_record__tenant_evidence_blob", text)
        self.assertIn("tg_guard_ops_gov_lifecycle_action_log_mutation", text)
        self.assertIn("tr_guard_ops_gov_lifecycle_action_log_update", text)
        self.assertIn("tr_guard_ops_gov_lifecycle_action_log_delete", text)
        self.assertIn("tg_guard_audit_evidence_blob_update", text)
        self.assertIn(
            "audit_evidence_blob immutable payload fields cannot be updated",
            text,
        )

    def test_phase4_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "aa6d5f4c3b2e_reseed_acp_for_phase4_security_compliance.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "a4f8c2d9e6b1"', text
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)

    def test_active_retention_class_uniqueness_guard_migration(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "f1a9b7c3d5e2_ops_gov_retention_class_active_unique.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "aa6d5f4c3b2e"',
            text,
        )
        self.assertIn("HAVING COUNT(*) > 1", text)
        self.assertIn(
            "ux_ops_gov_retention_class__tenant_resource_active",
            text,
        )
        self.assertIn("Cannot enforce unique active retention classes", text)
