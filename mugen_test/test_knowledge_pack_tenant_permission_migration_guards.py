"""Focused checks for knowledge_pack tenant permission reseed wiring."""

from pathlib import Path
import unittest


class TestKnowledgePackTenantPermissionMigrationGuards(unittest.TestCase):
    """Verifies knowledge_pack tenant permission reseed migration wiring."""

    def test_tenant_permission_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "a7c4e2f9b1d6_knowledge_pack_tenant_permissions.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"',
            text,
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)
        self.assertIn("knowledge_pack tenant permissions", text)


if __name__ == "__main__":
    unittest.main()
