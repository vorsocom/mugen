"""Focused checks for web platform access permission reseed wiring."""

from pathlib import Path
import unittest


class TestWebPlatformAccessPermissionMigrationGuards(unittest.TestCase):
    """Verifies web platform access permission reseed migration wiring."""

    def test_web_access_permission_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "7b6e1d2c3a4f_web_platform_access_permission.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "a7c4e2f9b1d6"',
            text,
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)
        self.assertIn("web platform access permission", text)


if __name__ == "__main__":
    unittest.main()
