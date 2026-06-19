"""Focused checks for ACP least privilege global role reseed wiring."""

from pathlib import Path
import unittest


class TestAcpLeastPrivilegeGlobalRolesMigrationGuards(unittest.TestCase):
    """Verifies least privilege global role reseed migration wiring."""

    def test_least_privilege_roles_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "9e4d7c2b1a6f_seed_acp_least_privilege_global_roles.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "7b6e1d2c3a4f"',
            text,
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)
        self.assertIn("least privilege global roles", text)


if __name__ == "__main__":
    unittest.main()
