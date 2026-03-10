"""Unit tests for tenant-aware ingress route resolution."""

from __future__ import annotations

from typing import Any
import unittest
from unittest import mock
import uuid

from mugen.core.contract.service.ingress_routing import (
    IngressRouteReason,
    IngressRouteRequest,
    IngressRouteResult,
)
from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.service.ingress_routing import (
    DefaultIngressRoutingService,
    build_ingress_route_context,
    build_ingress_route_message_context_item,
    merge_ingress_route_metadata,
)


class _FakeRsg:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self._rows = rows
        self.find_many_wheres: list[dict[str, Any]] = []

    async def get_one(self, table: str, where: dict[str, Any], *, columns=None):
        for row in self._rows.get(table, []):
            if all(row.get(key) == value for key, value in where.items()):
                if columns is None:
                    return dict(row)
                return {key: row.get(key) for key in columns}
        return None

    async def find_many(
        self,
        table: str,
        *,
        filter_groups=None,
        limit=None,
        **_kwargs,
    ):
        rows = self._rows.get(table, [])
        groups = list(filter_groups or [])
        if not groups:
            filtered = [dict(row) for row in rows]
        else:
            filtered = []
            for row in rows:
                for group in groups:
                    where = dict(getattr(group, "where", {}) or {})
                    self.find_many_wheres.append(where)
                    if all(row.get(key) == value for key, value in where.items()):
                        filtered.append(dict(row))
                        break
        if isinstance(limit, int):
            return filtered[:limit]
        return filtered


class TestMugenServiceIngressRouting(unittest.IsolatedAsyncioTestCase):
    """Covers deterministic resolver outcomes."""

    @staticmethod
    def _resolver(rows: dict[str, list[dict[str, Any]]], *, logger=None):
        return DefaultIngressRoutingService(
            relational_storage_gateway=_FakeRsg(rows),
            logging_gateway=logger or mock.Mock(),
        )

    async def test_ingress_route_context_builders_and_metadata_merging(self) -> None:
        result = IngressRouteResult(
            tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            tenant_slug="tenant-a",
            platform="line",
            channel_key="line",
            identifier_claims={"identifier_type": "path_token", "identifier_value": "tok"},
            channel_profile_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            client_profile_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            service_route_key="valet.customer_inbox",
            route_key="queue.line",
            binding_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
            client_profile_key="default",
        )

        context = build_ingress_route_context(result)
        self.assertEqual(context["tenant_slug"], "tenant-a")
        self.assertEqual(context["route_key"], "queue.line")
        self.assertEqual(context["service_route_key"], "valet.customer_inbox")
        self.assertEqual(
            context["client_profile_id"],
            "44444444-4444-4444-4444-444444444444",
        )
        self.assertEqual(context["client_profile_key"], "default")

        item = build_ingress_route_message_context_item(result)
        self.assertEqual(item["type"], "ingress_route")
        self.assertEqual(item["content"]["channel_key"], "line")

        merged = merge_ingress_route_metadata({"k": "v"}, result)
        self.assertEqual(merged["k"], "v")
        self.assertEqual(merged["ingress_route"]["tenant_id"], str(result.tenant_id))
        merged_empty = merge_ingress_route_metadata(None, result)
        self.assertEqual(merged_empty["ingress_route"]["tenant_slug"], "tenant-a")

    async def test_static_helper_branches_cover_none_and_required_value_error(self) -> None:
        self.assertIsNone(DefaultIngressRoutingService._tenant_slug_from_row(None))
        self.assertFalse(DefaultIngressRoutingService._tenant_active(None))

        resolver = self._resolver({})
        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform=" ",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value=None,
                require_active_binding=False,
            )
        )
        self.assertFalse(resolved.ok)
        self.assertEqual(
            resolved.reason_code,
            IngressRouteReason.RESOLUTION_ERROR.value,
        )

    async def test_has_active_membership_global_short_circuit(self) -> None:
        fake_rsg = _FakeRsg({"admin_tenant_membership": []})
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=fake_rsg,
            logging_gateway=mock.Mock(),
        )
        allowed = await resolver._has_active_membership(  # pylint: disable=protected-access
            tenant_id=GLOBAL_TENANT_ID,
            auth_user_id=uuid.uuid4(),
        )
        self.assertTrue(allowed)

    async def test_resolve_success_returns_tenant_and_route(self) -> None:
        tenant_id = uuid.uuid4()
        channel_profile_id = uuid.uuid4()
        client_profile_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        rows = {
            "admin_tenant": [
                {"id": tenant_id, "slug": "tenant-a", "status": "active"},
            ],
            "channel_orchestration_ingress_binding": [
                {
                    "id": binding_id,
                    "tenant_id": tenant_id,
                    "channel_profile_id": channel_profile_id,
                    "channel_key": "line",
                    "identifier_type": "path_token",
                    "identifier_value": "token-a",
                    "service_route_key": "valet.customer_inbox",
                    "is_active": True,
                    "attributes": {"route_key": "queue.line"},
                }
            ],
            "channel_orchestration_channel_profile": [
                {
                    "id": channel_profile_id,
                    "tenant_id": tenant_id,
                    "is_active": True,
                    "service_route_default_key": "valet.core",
                    "route_default_key": "queue.default",
                    "client_profile_id": client_profile_id,
                }
            ],
            "admin_messaging_client_profile": [
                {
                    "id": client_profile_id,
                    "tenant_id": tenant_id,
                    "is_active": True,
                    "profile_key": "profile-a",
                }
            ],
        }
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=_FakeRsg(rows),
            logging_gateway=mock.Mock(),
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                claims={"path_token": "token-a"},
                require_active_binding=True,
            )
        )

        self.assertTrue(resolved.ok)
        self.assertIsNotNone(resolved.result)
        self.assertEqual(resolved.result.tenant_id, tenant_id)
        self.assertEqual(resolved.result.tenant_slug, "tenant-a")
        self.assertEqual(resolved.result.route_key, "queue.line")
        self.assertEqual(resolved.result.channel_profile_id, channel_profile_id)
        self.assertEqual(resolved.result.client_profile_id, client_profile_id)
        self.assertEqual(resolved.result.binding_id, binding_id)
        self.assertEqual(resolved.result.client_profile_key, "profile-a")
        self.assertEqual(
            resolved.result.service_route_key,
            "valet.customer_inbox",
        )

    async def test_resolve_success_uses_profile_route_key_when_binding_attrs_missing(self) -> None:
        tenant_id = uuid.uuid4()
        channel_profile_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        fake_rsg = _FakeRsg(
            {
                "admin_tenant": [
                    {"id": tenant_id, "slug": "tenant-a", "status": "active"},
                ],
                "channel_orchestration_ingress_binding": [
                    {
                        "id": binding_id,
                        "tenant_id": tenant_id,
                        "channel_profile_id": channel_profile_id,
                        "channel_key": "line",
                        "identifier_type": "path_token",
                        "identifier_value": "token-a",
                        "is_active": True,
                        "attributes": {},
                    }
                ],
                "channel_orchestration_channel_profile": [
                    {
                        "id": channel_profile_id,
                        "tenant_id": tenant_id,
                        "is_active": True,
                        "service_route_default_key": "valet.core",
                        "route_default_key": "queue.default",
                    }
                ],
            }
        )
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=fake_rsg,
            logging_gateway=mock.Mock(),
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                tenant_slug="tenant-a",
                require_active_binding=True,
            )
        )

        self.assertTrue(resolved.ok)
        assert resolved.result is not None
        self.assertEqual(resolved.result.route_key, "queue.default")
        self.assertEqual(resolved.result.service_route_key, "valet.core")
        self.assertIn(
            tenant_id,
            {where.get("tenant_id") for where in fake_rsg.find_many_wheres},
        )

    async def test_resolve_success_handles_missing_client_profile_lookup(self) -> None:
        tenant_id = uuid.uuid4()
        channel_profile_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        resolver = self._resolver(
            {
                "admin_tenant": [
                    {"id": tenant_id, "slug": "tenant-a", "status": "active"},
                ],
                "channel_orchestration_ingress_binding": [
                    {
                        "id": binding_id,
                        "tenant_id": tenant_id,
                        "channel_profile_id": channel_profile_id,
                        "channel_key": "line",
                        "identifier_type": "path_token",
                        "identifier_value": "token-a",
                        "is_active": True,
                        "attributes": {},
                    }
                ],
                "channel_orchestration_channel_profile": [
                    {
                        "id": channel_profile_id,
                        "tenant_id": tenant_id,
                        "is_active": True,
                        "route_default_key": "queue.default",
                        "client_profile_id": uuid.uuid4(),
                    }
                ],
            }
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                tenant_slug="tenant-a",
                require_active_binding=True,
            )
        )

        self.assertTrue(resolved.ok)
        assert resolved.result is not None
        self.assertIsNotNone(resolved.result.client_profile_id)
        self.assertIsNone(resolved.result.client_profile_key)

    async def test_resolve_profile_lookup_missing_returns_none_route_key(self) -> None:
        tenant_id = uuid.uuid4()
        resolver = self._resolver(
            {
                "admin_tenant": [
                    {"id": tenant_id, "slug": "tenant-a", "status": "active"},
                ],
                "channel_orchestration_ingress_binding": [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "channel_profile_id": uuid.uuid4(),
                        "channel_key": "line",
                        "identifier_type": "path_token",
                        "identifier_value": "token-a",
                        "is_active": True,
                    }
                ],
            }
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                require_active_binding=True,
            )
        )
        self.assertTrue(resolved.ok)
        assert resolved.result is not None
        self.assertIsNone(resolved.result.route_key)
        self.assertIsNone(resolved.result.service_route_key)

    async def test_resolve_route_key_returns_none_without_channel_profile_id(self) -> None:
        resolver = self._resolver({})
        route_key = await resolver._resolve_route_key(  # pylint: disable=protected-access
            tenant_id=uuid.uuid4(),
            binding_row={"channel_profile_id": None},
        )
        self.assertIsNone(route_key)

    async def test_resolve_missing_binding(self) -> None:
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=_FakeRsg(
                {
                    "channel_orchestration_ingress_binding": [],
                }
            ),
            logging_gateway=mock.Mock(),
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="telegram",
                channel_key="telegram",
                identifier_type="path_token",
                identifier_value="token-x",
                require_active_binding=True,
            )
        )

        self.assertFalse(resolved.ok)
        self.assertEqual(resolved.reason_code, IngressRouteReason.MISSING_BINDING.value)

    async def test_resolve_missing_identifier_when_binding_required(self) -> None:
        resolver = self._resolver({})
        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value=None,
                require_active_binding=True,
            )
        )
        self.assertFalse(resolved.ok)
        self.assertEqual(
            resolved.reason_code,
            IngressRouteReason.MISSING_IDENTIFIER.value,
        )

    async def test_resolve_inactive_binding(self) -> None:
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=_FakeRsg(
                {
                    "channel_orchestration_ingress_binding": [
                        {
                            "tenant_id": uuid.uuid4(),
                            "channel_key": "wechat",
                            "identifier_type": "path_token",
                            "identifier_value": "token-inactive",
                            "is_active": False,
                        }
                    ],
                }
            ),
            logging_gateway=mock.Mock(),
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="wechat",
                channel_key="wechat",
                identifier_type="path_token",
                identifier_value="token-inactive",
                require_active_binding=True,
            )
        )

        self.assertFalse(resolved.ok)
        self.assertEqual(resolved.reason_code, IngressRouteReason.INACTIVE_BINDING.value)

    async def test_resolve_invalid_and_inactive_tenant_slug(self) -> None:
        missing_slug = self._resolver({"admin_tenant": []})
        missing = await missing_slug.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value="tenant-x",
                tenant_slug="tenant-x",
                require_active_binding=False,
            )
        )
        self.assertFalse(missing.ok)
        self.assertEqual(missing.reason_code, IngressRouteReason.INVALID_TENANT_SLUG.value)

        inactive_slug = self._resolver(
            {
                "admin_tenant": [
                    {"id": uuid.uuid4(), "slug": "tenant-inactive", "status": "inactive"}
                ]
            }
        )
        inactive = await inactive_slug.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value="tenant-inactive",
                tenant_slug="tenant-inactive",
                require_active_binding=False,
            )
        )
        self.assertFalse(inactive.ok)
        self.assertEqual(inactive.reason_code, IngressRouteReason.INACTIVE_TENANT.value)

    async def test_resolve_slug_with_invalid_tenant_id_returns_inactive_tenant(self) -> None:
        resolver = self._resolver(
            {
                "admin_tenant": [
                    {"id": "not-a-uuid", "slug": "tenant-a", "status": "active"},
                ]
            }
        )
        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value="tenant-a",
                tenant_slug="tenant-a",
                require_active_binding=False,
            )
        )
        self.assertFalse(resolved.ok)
        self.assertEqual(resolved.reason_code, IngressRouteReason.INACTIVE_TENANT.value)

    async def test_resolve_ambiguous_binding(self) -> None:
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=_FakeRsg(
                {
                    "channel_orchestration_ingress_binding": [
                        {
                            "tenant_id": tenant_a,
                            "channel_key": "whatsapp",
                            "identifier_type": "phone_number_id",
                            "identifier_value": "123",
                            "is_active": True,
                        },
                        {
                            "tenant_id": tenant_b,
                            "channel_key": "whatsapp",
                            "identifier_type": "phone_number_id",
                            "identifier_value": "123",
                            "is_active": True,
                        },
                    ],
                }
            ),
            logging_gateway=mock.Mock(),
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="whatsapp",
                channel_key="whatsapp",
                identifier_type="phone_number_id",
                identifier_value="123",
                require_active_binding=True,
            )
        )

        self.assertFalse(resolved.ok)
        self.assertEqual(resolved.reason_code, IngressRouteReason.AMBIGUOUS_BINDING.value)

    async def test_resolve_binding_tenant_invalid_and_inactive_paths(self) -> None:
        invalid_binding_tenant = self._resolver(
            {
                "channel_orchestration_ingress_binding": [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": None,
                        "channel_key": "line",
                        "identifier_type": "path_token",
                        "identifier_value": "token-a",
                        "is_active": True,
                    }
                ]
            }
        )
        invalid = await invalid_binding_tenant.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                require_active_binding=True,
            )
        )
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.reason_code, IngressRouteReason.INACTIVE_TENANT.value)

        tenant_id = uuid.uuid4()
        inactive_binding_tenant = self._resolver(
            {
                "channel_orchestration_ingress_binding": [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "channel_key": "line",
                        "identifier_type": "path_token",
                        "identifier_value": "token-a",
                        "is_active": True,
                    }
                ],
                "admin_tenant": [
                    {"id": tenant_id, "slug": "tenant-a", "status": "inactive"}
                ],
            }
        )
        inactive = await inactive_binding_tenant.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                require_active_binding=True,
            )
        )
        self.assertFalse(inactive.ok)
        self.assertEqual(inactive.reason_code, IngressRouteReason.INACTIVE_TENANT.value)

    async def test_resolve_unauthorized_tenant_access(self) -> None:
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        resolver = DefaultIngressRoutingService(
            relational_storage_gateway=_FakeRsg(
                {
                    "admin_tenant": [
                        {"id": tenant_id, "slug": "tenant-a", "status": "active"},
                        {"id": GLOBAL_TENANT_ID, "slug": "global", "status": "active"},
                    ],
                    "admin_tenant_membership": [],
                }
            ),
            logging_gateway=mock.Mock(),
        )

        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value="tenant-a",
                tenant_slug="tenant-a",
                auth_user_id=auth_user_id,
                require_active_binding=False,
            )
        )

        self.assertFalse(resolved.ok)
        self.assertEqual(
            resolved.reason_code,
            IngressRouteReason.UNAUTHORIZED_TENANT.value,
        )

    async def test_resolve_unauthorized_binding_tenant_access(self) -> None:
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        resolver = self._resolver(
            {
                "channel_orchestration_ingress_binding": [
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "channel_key": "line",
                        "identifier_type": "path_token",
                        "identifier_value": "token-a",
                        "is_active": True,
                    }
                ],
                "admin_tenant": [
                    {"id": tenant_id, "slug": "tenant-a", "status": "active"}
                ],
                "admin_tenant_membership": [],
            }
        )
        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                auth_user_id=auth_user_id,
                require_active_binding=True,
            )
        )
        self.assertFalse(resolved.ok)
        self.assertEqual(
            resolved.reason_code,
            IngressRouteReason.UNAUTHORIZED_TENANT.value,
        )

    async def test_resolve_non_binding_global_tenant_paths(self) -> None:
        resolver_missing_global = self._resolver({"admin_tenant": []})
        resolved_missing_global = await resolver_missing_global.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value=None,
                claims={"": "x", "tenant_slug": "  "},
                require_active_binding=False,
            )
        )
        self.assertTrue(resolved_missing_global.ok)
        assert resolved_missing_global.result is not None
        self.assertEqual(resolved_missing_global.result.tenant_id, GLOBAL_TENANT_ID)
        self.assertEqual(resolved_missing_global.result.tenant_slug, "global")
        self.assertEqual(
            resolved_missing_global.result.identifier_claims["identifier_type"],
            "tenant_slug",
        )

        resolver_active_global = self._resolver(
            {
                "admin_tenant": [
                    {"id": GLOBAL_TENANT_ID, "slug": "global", "status": "active"}
                ]
            }
        )
        resolved_active_global = await resolver_active_global.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value=None,
                require_active_binding=False,
            )
        )
        self.assertTrue(resolved_active_global.ok)

        resolver_inactive_global = self._resolver(
            {
                "admin_tenant": [
                    {"id": GLOBAL_TENANT_ID, "slug": "global", "status": "inactive"}
                ]
            }
        )
        resolved_inactive = await resolver_inactive_global.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value=None,
                require_active_binding=False,
            )
        )
        self.assertFalse(resolved_inactive.ok)
        self.assertEqual(
            resolved_inactive.reason_code,
            IngressRouteReason.INACTIVE_TENANT.value,
        )

    async def test_resolve_non_binding_with_explicit_tenant_slug_skips_global_fallback(self) -> None:
        tenant_id = uuid.uuid4()
        resolver = self._resolver(
            {
                "admin_tenant": [
                    {"id": tenant_id, "slug": "tenant-a", "status": "active"}
                ]
            }
        )
        resolved = await resolver.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value="tenant-a",
                tenant_slug="tenant-a",
                require_active_binding=False,
            )
        )
        self.assertTrue(resolved.ok)
        assert resolved.result is not None
        self.assertEqual(resolved.result.tenant_id, tenant_id)
        self.assertEqual(resolved.result.tenant_slug, "tenant-a")

    async def test_resolve_defensive_missing_binding_result_and_resolution_error(self) -> None:
        resolver = self._resolver({})
        resolver._resolve_binding = mock.AsyncMock(return_value=(None, None))  # type: ignore[attr-defined]
        resolved_missing = await resolver.resolve(
            IngressRouteRequest(
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-a",
                require_active_binding=True,
            )
        )
        self.assertFalse(resolved_missing.ok)
        self.assertEqual(
            resolved_missing.reason_code,
            IngressRouteReason.MISSING_BINDING.value,
        )

        exploding_rsg = _FakeRsg({})
        exploding_rsg.get_one = mock.AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )
        logger = mock.Mock()
        exploding_resolver = DefaultIngressRoutingService(
            relational_storage_gateway=exploding_rsg,
            logging_gateway=logger,
        )
        resolved_error = await exploding_resolver.resolve(
            IngressRouteRequest(
                platform="web",
                channel_key="web",
                identifier_type="tenant_slug",
                identifier_value=None,
                require_active_binding=False,
            )
        )
        self.assertFalse(resolved_error.ok)
        self.assertEqual(
            resolved_error.reason_code,
            IngressRouteReason.RESOLUTION_ERROR.value,
        )
        logger.error.assert_called()
