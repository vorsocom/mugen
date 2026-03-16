"""Focused checks for audit integrity/lifecycle migration guardrails."""

from pathlib import Path
import unittest


class TestAuditMigrationGuards(unittest.TestCase):
    """Verifies migration SQL includes expected guard and index contracts."""

    def test_migration_contains_guard_triggers_and_scope_indexes(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "f4c9b2d1e6a7_audit_chain_integrity_and_lifecycle.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn("tg_guard_audit_event_update", text)
        self.assertIn("tg_guard_audit_event_delete", text)
        self.assertIn("tr_guard_audit_event_update", text)
        self.assertIn("tr_guard_audit_event_delete", text)
        self.assertIn("ux_audit_event__scope_seq", text)
        self.assertIn("ix_audit_event__redact_due_work", text)
        self.assertIn("ix_audit_event__tombstone_due_work", text)
        self.assertIn("ix_audit_event__purge_due_work", text)
        self.assertIn("audit_event delete denied: active legal hold", text)
