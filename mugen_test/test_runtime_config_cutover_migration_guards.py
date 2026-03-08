"""Focused checks for runtime-config cutover migration contracts."""

from pathlib import Path
import unittest


class TestRuntimeConfigCutoverMigrationGuards(unittest.TestCase):
    """Verifies the schema and reseed migrations contain required cutover wiring."""

    def test_schema_migration_contains_runtime_profile_and_key_material_changes(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "fa1c2d3e4b5c_tenant_runtime_config_and_managed_secrets.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "6d5f8a2c1b3e"',
            text,
        )
        self.assertIn("admin_runtime_config_profile", text)
        self.assertIn("encrypted_secret", text)
        self.assertIn("has_material", text)
        self.assertIn("material_last_set_at", text)
        self.assertIn("material_last_set_by_user_id", text)
        self.assertIn("fk_runtime_cfg_profile_tenant", text)
        self.assertIn("ux_runtime_cfg_profile__tenant_category_profile", text)
        self.assertIn("ix_runtime_cfg_profile__tenant_category_active", text)

    def test_reseed_migration_reapplies_manifest(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "fb1c2d3e4f5a_reseed_acp_for_runtime_config_cutover.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "fa1c2d3e4b5c"',
            text,
        )
        self.assertIn("seed_acp", text)
        self.assertIn("contribute_all", text)
        self.assertIn("build_seed_manifest", text)
        self.assertIn("apply_manifest", text)
        self.assertIn("admin_plugin_capability_grant", text)
        self.assertIn("kms.key.rotate", text)
        self.assertIn("runtime_config_cutover_default_acp_kms_grant", text)


if __name__ == "__main__":
    unittest.main()
