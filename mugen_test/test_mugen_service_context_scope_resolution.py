"""Unit tests for mugen.core.service.context_scope_resolution."""

from __future__ import annotations

import unittest
import uuid

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.service.ingress_routing import (
    IngressRouteReason,
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.service.context_scope_resolution import (
    ContextScopeResolutionError,
    context_scope_from_ingress_route,
    resolve_context_ingress,
    resolve_ingress_route_context,
)


def _resolved_route() -> IngressRouteResolution:
    return IngressRouteResolution(
        ok=True,
        result=IngressRouteResult(
            tenant_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            tenant_slug="tenant-a",
            platform="whatsapp",
            channel_key="whatsapp",
            identifier_claims={"phone": "+15550000"},
            channel_profile_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            route_key="default",
            binding_id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        ),
    )


class TestContextScopeResolution(unittest.TestCase):
    """Covers resolved and fallback-global tenant scope behavior."""

    def test_resolve_context_ingress_uses_resolved_tenant(self) -> None:
        resolved = resolve_context_ingress(
            platform="whatsapp",
            channel_key="whatsapp",
            room_id="room-1",
            sender_id="user-1",
            routing=_resolved_route(),
            source="whatsapp.ipc",
            conversation_id="conv-1",
            case_id="case-1",
            workflow_id="wf-1",
        )

        self.assertEqual(
            resolved.scope.tenant_id,
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        self.assertEqual(resolved.scope.platform, "whatsapp")
        self.assertEqual(resolved.scope.channel_id, "whatsapp")
        self.assertEqual(resolved.scope.conversation_id, "conv-1")
        self.assertEqual(resolved.tenant_resolution["mode"], "resolved")
        self.assertEqual(
            resolved.ingress_route["tenant_resolution"]["source"],
            "whatsapp.ipc",
        )

    def test_missing_binding_and_missing_identifier_fallback_to_global(self) -> None:
        for reason in (
            IngressRouteReason.MISSING_BINDING.value,
            IngressRouteReason.MISSING_IDENTIFIER.value,
        ):
            resolved = resolve_context_ingress(
                platform="telegram",
                channel_key="telegram",
                room_id="room-1",
                sender_id="user-1",
                routing=IngressRouteResolution(ok=False, reason_code=reason),
                source="telegram.ipc",
            )
            self.assertEqual(resolved.scope.tenant_id, str(GLOBAL_TENANT_ID))
            self.assertEqual(resolved.tenant_resolution["mode"], "fallback_global")
            self.assertEqual(resolved.tenant_resolution["reason_code"], reason)

    def test_fail_closed_reasons_raise(self) -> None:
        for reason in (
            IngressRouteReason.INACTIVE_BINDING.value,
            IngressRouteReason.AMBIGUOUS_BINDING.value,
            IngressRouteReason.INVALID_TENANT_SLUG.value,
            IngressRouteReason.INACTIVE_TENANT.value,
            IngressRouteReason.UNAUTHORIZED_TENANT.value,
            IngressRouteReason.RESOLUTION_ERROR.value,
        ):
            with self.assertRaises(ContextScopeResolutionError):
                resolve_context_ingress(
                    platform="line",
                    channel_key="line",
                    room_id="room-1",
                    sender_id="user-1",
                    routing=IngressRouteResolution(
                        ok=False,
                        reason_code=reason,
                        reason_detail="blocked",
                    ),
                    source="line.ipc",
                )

    def test_allow_global_without_routing_uses_global_tenant(self) -> None:
        resolved = resolve_context_ingress(
            platform="matrix",
            channel_key="matrix",
            room_id="room-1",
            sender_id="user-1",
            routing=None,
            source="matrix.client",
            allow_global_without_routing=True,
        )

        self.assertEqual(resolved.scope.tenant_id, str(GLOBAL_TENANT_ID))
        self.assertEqual(resolved.tenant_resolution["reason_code"], "no_routing_service")

    def test_resolve_ingress_route_context_returns_route_envelope(self) -> None:
        route = resolve_ingress_route_context(
            platform="wechat",
            channel_key="wechat",
            routing=IngressRouteResolution(
                ok=False,
                reason_code=IngressRouteReason.MISSING_BINDING.value,
            ),
            source="wechat.ipc",
        )

        self.assertEqual(route["tenant_id"], str(GLOBAL_TENANT_ID))
        self.assertEqual(route["tenant_resolution"]["mode"], "fallback_global")

    def test_context_scope_from_ingress_route_defaults_missing_route_to_global(self) -> None:
        resolved = context_scope_from_ingress_route(
            platform="web",
            channel_key="web",
            room_id="room-1",
            sender_id="user-1",
            ingress_route=None,
            source="web.messaging",
        )

        self.assertEqual(resolved.scope.tenant_id, str(GLOBAL_TENANT_ID))
        self.assertEqual(resolved.tenant_resolution["reason_code"], "no_ingress_route")
        self.assertEqual(
            resolved.ingress_route["tenant_resolution"]["mode"],
            "fallback_global",
        )
