"""Static guards for the additive Service Profile migration."""

from pathlib import Path
import unittest


class TestServiceProfileMigrationGuards(unittest.TestCase):
    """Keep the Service Profile schema and safe downgrade contract explicit."""

    @classmethod
    def setUpClass(cls) -> None:
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "a6c1d8e4f2b7_service_profile_core_integration.py"
        )
        cls.text = migration.read_text(encoding="utf8")

    def test_revision_extends_the_released_core_head(self) -> None:
        self.assertIn(
            'down_revision: Union[str, Sequence[str], None] = "c4e8a2f6b1d9"',
            self.text,
        )

    def test_schema_contains_required_resources_and_constraints(self) -> None:
        for required in (
            '"service_profile_service_profile"',
            '"service_profile_ingress_binding"',
            '"service_profile_subscription"',
            'name="service_profile_lifecycle_status"',
            '"ux_service_profile__tenant_key"',
            '"ux_service_profile_ingress__active_binding"',
            '"ux_service_profile_subscription__active_subscription"',
            '"ux_service_profile_subscription__active_profile_product"',
            '"fkx_service_profile_ingress__tenant_binding"',
            '"fkx_service_profile_subscription__tenant_subscription"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.text)

    def test_knowledge_scope_integration_is_additive_and_restrictive(self) -> None:
        self.assertIn(
            'sa.Column("service_profile_id", sa.Uuid(), nullable=True)',
            self.text,
        )
        self.assertIn('"fkx_knowledge_scope__tenant_service_profile"', self.text)
        self.assertIn('ondelete="RESTRICT"', self.text)
        self.assertIn(
            '"ix_knowledge_scope__tenant_service_profile_active"',
            self.text,
        )

    def test_downgrade_removes_scope_integration_before_profile_tables(self) -> None:
        drop_scope_column = self.text.index(
            'op.drop_column(\n        "knowledge_pack_knowledge_scope"'
        )
        drop_subscription = self.text.index(
            'op.drop_table("service_profile_subscription"'
        )
        drop_ingress = self.text.index(
            'op.drop_table("service_profile_ingress_binding"'
        )
        drop_profile = self.text.index(
            'op.drop_table("service_profile_service_profile"'
        )
        self.assertLess(drop_scope_column, drop_subscription)
        self.assertLess(drop_subscription, drop_ingress)
        self.assertLess(drop_ingress, drop_profile)
        self.assertNotIn('drop_table("billing_', self.text)
        self.assertNotIn('drop_table("channel_orchestration_', self.text)


if __name__ == "__main__":
    unittest.main()
