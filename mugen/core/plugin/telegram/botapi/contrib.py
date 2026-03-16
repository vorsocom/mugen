"""Telegram Bot API plugin contribution entrypoint."""

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs


def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute Telegram Bot API artifacts into `registry`."""
    _ = registry
    _ = AdminNs(admin_namespace)
    _ = AdminNs(plugin_namespace)
