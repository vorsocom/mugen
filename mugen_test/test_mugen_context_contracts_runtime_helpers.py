"""Coverage-focused tests for context contracts and helper utilities."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mugen
from mugen.core import di
from mugen.core.bootstrap.extensions import DefaultExtensionRegistry
from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import ContextScope, ContextTurnRequest
from mugen.core.contract.gateway.completion import CompletionMessage
from mugen.core.contract.service.ingress_routing import IngressRouteResolution
from mugen.core.contract.service.messaging import MessagingTurnRequest
from mugen.core.domain.use_case.normalize_composed_message import (
    NormalizeComposedMessageUseCase,
)
from mugen.core.service.context_scope_resolution import (
    ContextScopeResolutionError,
    context_scope_from_ingress_route,
    resolve_context_ingress,
)
from mugen.core.utility.context_runtime import (
    messages_fingerprint,
    prefix_cache_key,
    prefix_cache_prefix,
    retrieval_cache_key,
    retrieval_cache_prefix,
    scope_identity,
    scope_key,
    scope_partition,
    tenant_cache_key,
    working_set_cache_key,
    working_set_cache_prefix,
)


def _scope(*, tenant_id: str = "tenant-1") -> ContextScope:
    return ContextScope(
        tenant_id=tenant_id,
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id="user-1",
        conversation_id="room-1",
    )
class TestMugenContextContractsAndRuntimeHelpers(unittest.TestCase):
    """Exercise remaining branch-heavy helpers introduced by the context runtime."""

    def test_context_scope_normalizes_and_rejects_invalid_values(self) -> None:
        scope = ContextScope(
            tenant_id=" tenant-1 ",
            platform=" matrix ",
            channel_id="",
            room_id=" room-1 ",
            sender_id=None,
            conversation_id=" conv-1 ",
        )

        self.assertEqual(scope.tenant_id, "tenant-1")
        self.assertEqual(scope.platform, "matrix")
        self.assertIsNone(scope.channel_id)
        self.assertEqual(scope.room_id, "room-1")
        self.assertIsNone(scope.sender_id)
        self.assertEqual(scope.conversation_id, "conv-1")

        with self.assertRaisesRegex(TypeError, "strings or None"):
            ContextScope(tenant_id="tenant-1", platform=1)

        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            ContextScope(tenant_id="   ")

    def test_context_turn_request_normalizes_payloads_and_rejects_invalid_shapes(
        self,
    ) -> None:
        request = ContextTurnRequest(
            scope=_scope(),
            user_message=[{"type": "text", "text": "hello"}],
            message_context=[{"type": "seed", "content": "ctx"}],
            attachment_context=[{"type": "attachment", "content": {"id": "a1"}}],
            ingress_metadata={"k": "v"},
            budget_hints={"max": 1},
        )
        self.assertEqual(request.user_message[0]["text"], "hello")
        self.assertEqual(request.message_context, [{"type": "seed", "content": "ctx"}])
        self.assertEqual(
            request.attachment_context,
            [{"type": "attachment", "content": {"id": "a1"}}],
        )
        self.assertEqual(request.ingress_metadata, {"k": "v"})
        self.assertEqual(request.budget_hints, {"max": 1})

        with self.assertRaisesRegex(TypeError, "must be ContextScope"):
            ContextTurnRequest(scope="bad", user_message="hello")
        with self.assertRaisesRegex(TypeError, "must be str, dict, or list\\[dict\\]"):
            ContextTurnRequest(scope=_scope(), user_message=1)
        with self.assertRaisesRegex(TypeError, "list entries must be dict"):
            ContextTurnRequest(scope=_scope(), user_message=["bad"])
        with self.assertRaisesRegex(TypeError, "message_context must be a list\\[dict\\]"):
            ContextTurnRequest(scope=_scope(), user_message="hello", message_context="bad")
        with self.assertRaisesRegex(TypeError, "attachment_context entries must be dict"):
            ContextTurnRequest(
                scope=_scope(),
                user_message="hello",
                attachment_context=["bad"],
            )
        with self.assertRaisesRegex(TypeError, "ingress_metadata must be a dict"):
            ContextTurnRequest(scope=_scope(), user_message="hello", ingress_metadata="bad")
        with self.assertRaisesRegex(TypeError, "budget_hints must be a dict"):
            ContextTurnRequest(scope=_scope(), user_message="hello", budget_hints="bad")

        default_request = ContextTurnRequest(
            scope=_scope(),
            user_message="hello",
            message_context=None,
            attachment_context=None,
            ingress_metadata=None,
            budget_hints=None,
        )
        self.assertEqual(default_request.message_context, [])
        self.assertEqual(default_request.attachment_context, [])
        self.assertEqual(default_request.ingress_metadata, {})
        self.assertEqual(default_request.budget_hints, {})

    def test_messaging_turn_request_normalizes_and_rejects_invalid_shapes(self) -> None:
        request = MessagingTurnRequest(
            scope=_scope(),
            message_type=" Text ",
            message={"body": "hello"},
            message_context=[{"type": "seed", "content": "ctx"}],
            attachment_context=[{"type": "attachment", "content": {"id": "a1"}}],
            ingress_metadata={"trace": "123"},
        )
        self.assertEqual(request.message_type, "text")
        self.assertEqual(request.message["body"], "hello")
        self.assertEqual(request.ingress_metadata, {"trace": "123"})

        with self.assertRaisesRegex(TypeError, "must be ContextScope"):
            MessagingTurnRequest(scope="bad", message_type="text", message="hello")
        with self.assertRaisesRegex(ValueError, "message_type is required"):
            MessagingTurnRequest(scope=_scope(), message_type=" ", message="hello")
        with self.assertRaisesRegex(TypeError, "message must be str or dict"):
            MessagingTurnRequest(scope=_scope(), message_type="text", message=1)
        with self.assertRaisesRegex(TypeError, "message_context entries must be dict"):
            MessagingTurnRequest(
                scope=_scope(),
                message_type="text",
                message="hello",
                message_context=["bad"],
            )
        with self.assertRaisesRegex(TypeError, "attachment_context must be a list\\[dict\\]"):
            MessagingTurnRequest(
                scope=_scope(),
                message_type="text",
                message="hello",
                attachment_context="bad",
            )
        with self.assertRaisesRegex(TypeError, "ingress_metadata must be a dict"):
            MessagingTurnRequest(
                scope=_scope(),
                message_type="text",
                message="hello",
                ingress_metadata="bad",
            )

        default_request = MessagingTurnRequest(
            scope=_scope(),
            message_type="text",
            message="hello",
            message_context=None,
            attachment_context=None,
            ingress_metadata=None,
        )
        self.assertEqual(default_request.message_context, [])
        self.assertEqual(default_request.attachment_context, [])
        self.assertEqual(default_request.ingress_metadata, {})

    def test_context_runtime_helpers_return_tenant_safe_keys(self) -> None:
        scope = ContextScope(
            tenant_id="tenant-1",
            platform="matrix",
            channel_id="matrix",
            room_id="room-1",
            sender_id="user-1",
            conversation_id="",
            case_id=None,
            workflow_id="workflow-1",
        )
        request = ContextTurnRequest(
            scope=scope,
            user_message="hello",
            message_context=[{"type": "seed", "content": "ctx"}],
            attachment_context=[{"type": "attachment", "content": {"id": "a1"}}],
        )
        messages = [
            CompletionMessage(role="system", content={"lane": "persona"}),
            CompletionMessage(role="user", content="hello"),
        ]

        self.assertEqual(
            scope_identity(scope),
            {
                "tenant_id": "tenant-1",
                "platform": "matrix",
                "channel_id": "matrix",
                "room_id": "room-1",
                "sender_id": "user-1",
                "conversation_id": None,
                "case_id": None,
                "workflow_id": "workflow-1",
            },
        )
        self.assertEqual(
            scope_partition(scope),
            {
                "platform": "matrix",
                "channel_id": "matrix",
                "room_id": "room-1",
                "sender_id": "user-1",
                "workflow_id": "workflow-1",
            },
        )
        hashed_scope_key = scope_key(scope)
        self.assertEqual(working_set_cache_key(scope), tenant_cache_key("tenant-1", f"working_set:{hashed_scope_key}"))
        self.assertEqual(working_set_cache_prefix(scope), tenant_cache_key("tenant-1", f"working_set:{hashed_scope_key}"))
        self.assertEqual(retrieval_cache_prefix(scope), tenant_cache_key("tenant-1", f"retrieval:{hashed_scope_key}"))
        self.assertEqual(prefix_cache_prefix(scope), tenant_cache_key("tenant-1", f"prefix_fingerprint:{hashed_scope_key}"))
        self.assertTrue(retrieval_cache_key(request).startswith(f"tenant:tenant-1:retrieval:{hashed_scope_key}:"))
        self.assertTrue(prefix_cache_key(scope, "prefix-1").endswith(f"{hashed_scope_key}:prefix-1"))
        self.assertEqual(len(messages_fingerprint(messages)), 64)

    def test_context_scope_resolution_helpers_cover_missing_routing_and_implicit_route(
        self,
    ) -> None:
        with self.assertRaises(ContextScopeResolutionError) as exc_info:
            resolve_context_ingress(
                platform="matrix",
                channel_key="matrix",
                room_id="room-1",
                sender_id="user-1",
                routing=None,
                source="matrix.messaging",
            )
        self.assertEqual(exc_info.exception.reason_code, "missing_routing_service")

        fallback = resolve_context_ingress(
            platform="matrix",
            channel_key="matrix",
            room_id="room-1",
            sender_id="user-1",
            routing=None,
            source="matrix.messaging",
            allow_global_without_routing=True,
        )
        self.assertEqual(fallback.scope.tenant_id, str(GLOBAL_TENANT_ID))
        self.assertEqual(fallback.tenant_resolution["reason_code"], "no_routing_service")

        resolved = context_scope_from_ingress_route(
            platform="matrix",
            channel_key="matrix",
            room_id="room-1",
            sender_id="user-1",
            ingress_route={"tenant_id": "tenant-1", "platform": "matrix", "channel_key": "matrix"},
        )
        self.assertEqual(resolved.tenant_resolution["mode"], "resolved")

        implicit_global = context_scope_from_ingress_route(
            platform="matrix",
            channel_key="matrix",
            room_id="room-1",
            sender_id="user-1",
            ingress_route={"tenant_id": str(GLOBAL_TENANT_ID)},
        )
        self.assertEqual(implicit_global.tenant_resolution["mode"], "fallback_global")
        self.assertEqual(implicit_global.tenant_resolution["reason_code"], "implicit_global")

    def test_normalize_composed_message_edge_validation(self) -> None:
        use_case = NormalizeComposedMessageUseCase()

        normalized = use_case.handle(
            {
                "composition_mode": "message_with_attachments",
                "parts": [{"type": "text", "text": "hello"}],
                "attachments": [],
                "metadata": {"locale": "en-US"},
                "client_message_id": 123,
            }
        )
        self.assertEqual(normalized["metadata"], {"locale": "en-US"})
        self.assertEqual(normalized["client_message_id"], "123")

        with self.assertRaisesRegex(ValueError, "message.metadata must be an object"):
            use_case.handle(
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [{"type": "text", "text": "hello"}],
                    "attachments": [],
                    "metadata": "bad",
                }
            )
        with self.assertRaisesRegex(ValueError, "message.parts\\[0\\].text must be a non-empty string"):
            use_case._require_non_empty("   ", "message.parts[0].text")  # pylint: disable=protected-access

    def test_legacy_extension_validation_and_core_extension_constructor_helpers(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "Legacy CTX/RAG"):
            di._validate_extension_entry_schema(  # pylint: disable=protected-access
                {"type": "ctx", "token": "core.ctx.system_persona"},
                path="mugen.modules.extensions[0]",
            )

    def test_keyval_storage_gateway_provider_reads_container_member(self) -> None:
        with patch.object(
            mugen.di,
            "container",
            new=SimpleNamespace(keyval_storage_gateway="keyval"),
        ):
            self.assertEqual(mugen._keyval_storage_gateway_provider(), "keyval")


class TestDefaultExtensionRegistryAsync(unittest.IsolatedAsyncioTestCase):
    """Async checks that keep legacy extension rejection covered."""

    async def test_register_rejects_legacy_ctx_type(self) -> None:
        registry = DefaultExtensionRegistry(
            messaging_service=Mock(),
            ipc_service=Mock(),
            platform_service=SimpleNamespace(extension_supported=Mock(return_value=True)),
            logging_gateway=Mock(),
        )

        with self.assertRaisesRegex(RuntimeError, "Legacy extension types 'ctx' and 'rag'"):
            await registry.register(
                app=None,
                extension_type="ctx",
                extension=Mock(),
                token="core.ctx.system_persona",
                critical=False,
            )
