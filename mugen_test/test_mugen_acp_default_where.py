"""Unit tests for mugen.core.plugin.acp.utility.rgql.default_where."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid

from mugen.core.plugin.acp.contract.sdk.resource import SoftDeleteMode
from mugen.core.plugin.acp.utility.rgql.default_where import make_default_where_provider


def _registry_for(type_entries: list, resources: list):
    return SimpleNamespace(
        schema=SimpleNamespace(types={str(i): t for i, t in enumerate(type_entries)}),
        resources={str(i): r for i, r in enumerate(resources)},
    )


class TestMugenAcpDefaultWhere(unittest.TestCase):
    """Covers tenant and soft-delete default where composition."""

    def test_unknown_type_returns_empty_constraints(self) -> None:
        registry = _registry_for([], [])
        provider = make_default_where_provider(registry=registry)
        self.assertEqual(provider("ACP.Unknown"), {})

    def test_tenant_and_soft_delete_timestamp_and_flag_paths(self) -> None:
        tenant_id = uuid.uuid4()
        user_type = SimpleNamespace(
            name="ACP.User",
            properties={"TenantId": object(), "DeletedAt": object()},
        )
        doc_type = SimpleNamespace(
            name="ACP.Document",
            properties={"TenantId": object(), "IsDeleted": object()},
        )
        no_tenant_type = SimpleNamespace(name="ACP.GlobalThing", properties={})
        resources = [
            SimpleNamespace(
                edm_type_name="ACP.User",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="DeletedAt",
                    )
                ),
            ),
            SimpleNamespace(
                edm_type_name="ACP.Document",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode=SoftDeleteMode.FLAG,
                        column="IsDeleted",
                    )
                ),
            ),
            SimpleNamespace(
                edm_type_name="ACP.GlobalThing",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode=SoftDeleteMode.NONE,
                        column=None,
                    )
                ),
            ),
        ]
        registry = _registry_for([user_type, doc_type, no_tenant_type], resources)
        provider = make_default_where_provider(
            registry=registry,
            tenant_id=tenant_id,
            include_deleted=False,
        )

        self.assertEqual(
            provider("ACP.User"),
            {
                "tenant_id": tenant_id,
                "deleted_at": None,
            },
        )
        self.assertEqual(
            provider("ACP.Document"),
            {
                "tenant_id": tenant_id,
                "is_deleted": False,
            },
        )
        self.assertEqual(provider("ACP.GlobalThing"), {})

    def test_include_deleted_and_missing_policy_fields(self) -> None:
        tenant_id = uuid.uuid4()
        item_type = SimpleNamespace(name="ACP.Item", properties={"TenantId": object()})
        resources = [
            SimpleNamespace(
                edm_type_name="ACP.Item",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="DeletedAt",
                    )
                ),
            ),
            SimpleNamespace(
                edm_type_name="ACP.ItemNoColumn",
                behavior=SimpleNamespace(
                    soft_delete=SimpleNamespace(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column=None,
                    )
                ),
            ),
        ]
        no_column_type = SimpleNamespace(
            name="ACP.ItemNoColumn",
            properties={"TenantId": object()},
        )
        registry = _registry_for([item_type, no_column_type], resources)

        include_deleted_provider = make_default_where_provider(
            registry=registry,
            tenant_id=tenant_id,
            include_deleted=True,
        )
        self.assertEqual(include_deleted_provider("ACP.Item"), {"tenant_id": tenant_id})

        no_tenant_provider = make_default_where_provider(
            registry=registry,
            tenant_id=None,
            include_deleted=False,
        )
        self.assertEqual(no_tenant_provider("ACP.ItemNoColumn"), {})

        no_resource_registry = _registry_for(
            [SimpleNamespace(name="ACP.NoResource", properties={"TenantId": object()})],
            [],
        )
        no_resource_provider = make_default_where_provider(
            registry=no_resource_registry,
            tenant_id=tenant_id,
            include_deleted=False,
        )
        self.assertEqual(
            no_resource_provider("ACP.NoResource"),
            {"tenant_id": tenant_id},
        )

        none_mode_registry = _registry_for(
            [SimpleNamespace(name="ACP.NoneMode", properties={})],
            [
                SimpleNamespace(
                    edm_type_name="ACP.NoneMode",
                    behavior=SimpleNamespace(
                        soft_delete=SimpleNamespace(
                            mode=SoftDeleteMode.NONE,
                            column="DeletedAt",
                        )
                    ),
                )
            ],
        )
        none_mode_provider = make_default_where_provider(
            registry=none_mode_registry,
            include_deleted=False,
        )
        self.assertEqual(none_mode_provider("ACP.NoneMode"), {})

        unknown_mode_registry = _registry_for(
            [SimpleNamespace(name="ACP.UnknownMode", properties={"TenantId": object()})],
            [
                SimpleNamespace(
                    edm_type_name="ACP.UnknownMode",
                    behavior=SimpleNamespace(
                        soft_delete=SimpleNamespace(
                            mode="legacy-mode",
                            column="DeletedAt",
                        )
                    ),
                )
            ],
        )
        unknown_mode_provider = make_default_where_provider(
            registry=unknown_mode_registry,
            tenant_id=tenant_id,
            include_deleted=False,
        )
        self.assertEqual(
            unknown_mode_provider("ACP.UnknownMode"),
            {"tenant_id": tenant_id},
        )
