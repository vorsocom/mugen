"""Web plugin contribution entrypoint."""

from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    PermissionObjectDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.constants import (
    GLOBAL_ROLE_ADMINISTRATOR,
    GLOBAL_ROLE_WEB_USER,
)
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.web.auth import (
    WEB_PLATFORM_ACCESS_PERMISSION,
    WEB_PLATFORM_ACCESS_PERMISSION_NAME,
    WEB_PLATFORM_PERMISSION_NAMESPACE,
)


def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute web artifacts into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    _plugin_ns = AdminNs(plugin_namespace)

    access_permission = PermissionObjectDef(
        WEB_PLATFORM_PERMISSION_NAMESPACE,
        WEB_PLATFORM_ACCESS_PERMISSION_NAME,
    )
    access_permission_type = PermissionTypeDef(
        WEB_PLATFORM_PERMISSION_NAMESPACE,
        WEB_PLATFORM_ACCESS_PERMISSION_NAME,
    )

    registry.register_permission_object(access_permission)
    registry.register_permission_type(access_permission_type)
    registry.register_default_global_grant(
        DefaultGlobalGrant(
            admin_ns.key(GLOBAL_ROLE_ADMINISTRATOR),
            WEB_PLATFORM_ACCESS_PERMISSION,
            WEB_PLATFORM_ACCESS_PERMISSION,
            True,
        )
    )
    registry.register_default_global_grant(
        DefaultGlobalGrant(
            admin_ns.key(GLOBAL_ROLE_WEB_USER),
            WEB_PLATFORM_ACCESS_PERMISSION,
            WEB_PLATFORM_ACCESS_PERMISSION,
            True,
        )
    )
