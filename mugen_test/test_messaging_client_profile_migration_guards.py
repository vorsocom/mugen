"""Focused checks for ACP-owned messaging client profile migration contracts."""

from pathlib import Path
import unittest


class TestMessagingClientProfileMigrationGuards(unittest.TestCase):
    """Verifies the cutover migration keeps the intended schema and data semantics."""

    def test_migration_contains_client_profile_cutover_and_state_reset(self) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "6d5f8a2c1b3e_acp_owned_messaging_client_profiles.py"
        )
        text = migration.read_text(encoding="utf8")

        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "5a8c1e2d9f3b"',
            text,
        )
        self.assertIn("admin_messaging_client_profile", text)
        self.assertIn("fk_msg_client_profile_tenant", text)
        self.assertIn("ux_msg_client_profile__tenant_platform_profile", text)
        self.assertIn("ux_msg_client_profile__platform_path_token_active", text)
        self.assertIn("client_profile_id", text)
        self.assertIn("fk_chorch_profile__client_profile_id", text)
        self.assertIn("_clear_runtime_state()", text)
        self.assertIn("_RUNTIME_STATE_TABLES = (", text)
        self.assertIn('"messaging_ingress_dead_letter"', text)
        self.assertIn('"messaging_ingress_event"', text)
        self.assertIn('"messaging_ingress_dedup"', text)
        self.assertIn('"messaging_ingress_checkpoint"', text)
        self.assertIn('f"DELETE FROM {_SCHEMA}.{table_name};"', text)
        self.assertIn("runtime_profile_key = client_profile_id::text", text)


if __name__ == "__main__":
    unittest.main()
