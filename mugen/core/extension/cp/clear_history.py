"""Provides an implementation of ICPExtension to clear chat history."""

__all__ = ["ClearChatHistoryICPExtension"]

from types import SimpleNamespace

from mugen.core import di
from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import ContextScope, ContextTurnRequest
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.utility.context_runtime import (
    prefix_cache_prefix,
    retrieval_cache_prefix,
    working_set_cache_prefix,
)


def _context_component_registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY)


class ClearChatHistoryICPExtension(ICPExtension):
    """An implementation of ICPExtension to clear chat history."""

    def __init__(
        self,
        config: SimpleNamespace,
        context_component_registry_provider=_context_component_registry_provider,
    ) -> None:
        self._config = config
        self._context_component_registry_provider = context_component_registry_provider

    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def commands(self) -> list[str]:
        return [self._config.mugen.commands.clear]

    async def process_message(  # pylint: disable=too-many-arguments
        self,
        message: str,
        room_id: str,
        user_id: str,
        *,
        scope: ContextScope,
    ) -> list[dict] | None:
        _ = message
        _ = room_id
        _ = user_id
        return await self._handle_clear_command(scope)

    async def _handle_clear_command(
        self,
        scope: ContextScope,
    ) -> list[dict]:
        await self._clear_context(scope)
        return [
            {
                "type": "text",
                "content": "Context cleared.",
            },
        ]

    async def _clear_context(self, scope: ContextScope) -> None:
        registry = self._context_component_registry_provider()
        state_store = getattr(registry, "state_store", None)
        if state_store is None:
            raise RuntimeError("Context component registry missing state_store.")
        await state_store.clear(
            ContextTurnRequest(
                scope=scope,
                user_message="",
                ingress_metadata={
                    "tenant_resolution": {
                        "mode": (
                            "resolved"
                            if scope.tenant_id != str(GLOBAL_TENANT_ID)
                            else "fallback_global"
                        ),
                        "reason_code": None,
                        "source": "core.cp.clear_history",
                    }
                },
            )
        )
        cache = getattr(registry, "cache", None)
        if cache is None:
            return
        await cache.invalidate(
            namespace="working_set",
            key_prefix=working_set_cache_prefix(scope),
        )
        await cache.invalidate(
            namespace="retrieval",
            key_prefix=retrieval_cache_prefix(scope),
        )
        await cache.invalidate(
            namespace="prefix_fingerprint",
            key_prefix=prefix_cache_prefix(scope),
        )
