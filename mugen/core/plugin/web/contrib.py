"""Web plugin contribution entrypoint."""

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs


def contribute(
    _registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute web artifacts into the ACP registry."""
    _admin_ns = AdminNs(admin_namespace)
    _plugin_ns = AdminNs(plugin_namespace)
