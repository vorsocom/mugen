"""ACP contribution entrypoint for the agent_runtime plugin."""

from __future__ import annotations

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs


def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute the agent_runtime installed flag."""
    _ = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)
    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Agent runtime plugin installed.",
            is_set=True,
        )
    )
