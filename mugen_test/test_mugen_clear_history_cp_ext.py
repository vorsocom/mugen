"""Unit tests for mugen.core.extension.cp.clear_history."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import ContextScope
import mugen.core.extension.cp.clear_history as clear_history_module
from mugen.core.extension.cp.clear_history import ClearChatHistoryICPExtension
from mugen.core.utility.context_runtime import (
    prefix_cache_prefix,
    retrieval_cache_prefix,
    working_set_cache_prefix,
)


def _make_config(command: str = "/clear") -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(commands=SimpleNamespace(clear=command))
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


class TestMugenClearHistoryCpExt(unittest.IsolatedAsyncioTestCase):
    """Covers scoped state/cache invalidation behavior."""

    def _new_ext(self, *, command: str = "/clear", registry=None):
        return ClearChatHistoryICPExtension(
            config=_make_config(command=command),
            context_component_registry_provider=lambda: registry,
        )

    async def test_properties_and_process_message_clear_scoped_state_and_caches(
        self,
    ) -> None:
        state_store = SimpleNamespace(clear=AsyncMock())
        cache = SimpleNamespace(invalidate=AsyncMock(return_value=1))
        registry = SimpleNamespace(state_store=state_store, cache=cache)
        ext = self._new_ext(command="/wipe", registry=registry)
        scope = _scope()

        self.assertEqual(ext.platforms, [])
        self.assertEqual(ext.commands, ["/wipe"])

        result = await ext.process_message(
            message="/wipe",
            room_id="room-1",
            user_id="user-1",
            scope=scope,
        )

        self.assertEqual(result, [{"type": "text", "content": "Context cleared."}])
        clear_request = state_store.clear.await_args.args[0]
        self.assertEqual(clear_request.scope, scope)
        self.assertEqual(clear_request.user_message, "")
        self.assertEqual(
            clear_request.ingress_metadata["tenant_resolution"],
            {
                "mode": "resolved",
                "reason_code": None,
                "source": "core.cp.clear_history",
            },
        )
        self.assertEqual(
            cache.invalidate.await_args_list[0].kwargs,
            {
                "namespace": "working_set",
                "key_prefix": working_set_cache_prefix(scope),
            },
        )
        self.assertEqual(
            cache.invalidate.await_args_list[1].kwargs,
            {
                "namespace": "retrieval",
                "key_prefix": retrieval_cache_prefix(scope),
            },
        )
        self.assertEqual(
            cache.invalidate.await_args_list[2].kwargs,
            {
                "namespace": "prefix_fingerprint",
                "key_prefix": prefix_cache_prefix(scope),
            },
        )

    async def test_clear_global_scope_marks_fallback_global_resolution(self) -> None:
        state_store = SimpleNamespace(clear=AsyncMock())
        registry = SimpleNamespace(state_store=state_store, cache=None)
        ext = self._new_ext(registry=registry)
        scope = _scope(tenant_id=str(GLOBAL_TENANT_ID))

        await ext.process_message(
            message="/clear",
            room_id="room-1",
            user_id="user-1",
            scope=scope,
        )

        clear_request = state_store.clear.await_args.args[0]
        self.assertEqual(
            clear_request.ingress_metadata["tenant_resolution"],
            {
                "mode": "fallback_global",
                "reason_code": None,
                "source": "core.cp.clear_history",
            },
        )

    async def test_clear_requires_state_store(self) -> None:
        ext = self._new_ext(registry=SimpleNamespace(cache=None))

        with self.assertRaisesRegex(RuntimeError, "missing state_store"):
            await ext.process_message(
                message="/clear",
                room_id="room-1",
                user_id="user-1",
                scope=_scope(),
            )

    def test_context_component_registry_provider_uses_container_ext_service(self) -> None:
        registry = object()
        container = SimpleNamespace(get_required_ext_service=Mock(return_value=registry))

        with patch.object(clear_history_module.di, "container", container):
            self.assertIs(
                clear_history_module._context_component_registry_provider(),
                registry,
            )

        container.get_required_ext_service.assert_called_once_with(
            clear_history_module.di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY
        )
