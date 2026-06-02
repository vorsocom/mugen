"""Focused checks for human handoff operator permission reseed wiring."""

from pathlib import Path
import unittest


class TestHumanHandoffOperatorPermissionMigrationGuards(unittest.TestCase):
    """Verifies human handoff operator permission reseed migration wiring."""

    def test_operator_permission_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "fe9a8b7c6d5e_human_handoff_operator_permission.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "fd4e1b2c3a9d"',
            text,
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)
        self.assertIn("human handoff operator permission", text)


if __name__ == "__main__":
    unittest.main()
