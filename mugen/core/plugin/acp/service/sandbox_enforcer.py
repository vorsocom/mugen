"""Runtime capability sandbox enforcer for ACP action dispatch."""

__all__ = ["SandboxEnforcer"]

from types import SimpleNamespace
import uuid
from typing import Any, Mapping

from mugen.core import di
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import IPluginCapabilityGrantService
from mugen.core.plugin.acp.contract.service.sandbox_enforcer import (
    CapabilityDeniedError,
    ISandboxEnforcer,
)


def _config_provider():
    return di.container.config


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class SandboxEnforcer(ISandboxEnforcer):
    """Evaluates declared capability requirements using grant resolution rules."""

    def __init__(
        self,
        config_provider=_config_provider,
        registry_provider=_registry_provider,
    ) -> None:
        self._config_provider = config_provider
        self._registry_provider = registry_provider

    @staticmethod
    def _normalize_required_text(value: str | None, *, field_name: str) -> str:
        text = str(value or "").strip()
        if text == "":
            raise ValueError(f"{field_name} must be non-empty.")
        return text

    def _sandbox_mode(self) -> str:
        config = self._config_provider()
        acp_cfg = getattr(config, "acp", SimpleNamespace())
        sandbox_cfg = getattr(acp_cfg, "sandbox", SimpleNamespace())
        mode = str(getattr(sandbox_cfg, "mode", "enforce") or "enforce")
        mode = mode.strip().lower()
        if mode in {"off", "disabled", "none"}:
            return "disabled"
        if mode in {"audit", "log"}:
            return "audit"
        return "enforce"

    def _grant_service(self) -> IPluginCapabilityGrantService | None:
        try:
            registry: IAdminRegistry = self._registry_provider()
            resource = registry.get_resource("PluginCapabilityGrants")
            service = registry.get_edm_service(resource.service_key)
        except Exception:  # pylint: disable=broad-except
            return None

        return service

    async def require(
        self,
        tenant_id: uuid.UUID | None,
        plugin_key: str,
        capability: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_plugin_key = self._normalize_required_text(
            plugin_key,
            field_name="PluginKey",
        )
        normalized_capability = self._normalize_required_text(
            capability,
            field_name="Capability",
        ).lower()

        mode = self._sandbox_mode()
        if mode == "disabled":
            return

        service = self._grant_service()
        if service is None:
            if mode == "audit":
                return
            raise CapabilityDeniedError(
                tenant_id=tenant_id,
                plugin_key=normalized_plugin_key,
                capability=normalized_capability,
                context=dict(context or {}),
            )

        granted, source_tenant_id, grant = await service.resolve_capability(
            tenant_id=tenant_id,
            plugin_key=normalized_plugin_key,
            capability=normalized_capability,
        )
        if granted:
            return

        if mode == "audit":
            return

        deny_context = dict(context or {})
        deny_context["mode"] = mode
        deny_context["resolved_source_tenant_id"] = (
            str(source_tenant_id) if source_tenant_id is not None else None
        )
        deny_context["grant_id"] = str(grant.id) if grant is not None else None

        raise CapabilityDeniedError(
            tenant_id=tenant_id,
            plugin_key=normalized_plugin_key,
            capability=normalized_capability,
            context=deny_context,
        )
