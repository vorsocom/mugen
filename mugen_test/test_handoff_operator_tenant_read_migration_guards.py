"""Focused checks for handoff operator tenant read reseed wiring."""

from pathlib import Path
import unittest


class TestHandoffOperatorTenantReadMigrationGuards(unittest.TestCase):
    """Verifies handoff operator tenant read reseed migration wiring."""

    def test_tenant_read_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "2d6a4f8c9b1e_seed_handoff_operator_tenant_read.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "9e4d7c2b1a6f"',
            text,
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)
        self.assertIn("handoff operator tenant read grant", text)


if __name__ == "__main__":
    unittest.main()
