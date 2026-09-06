"""Authorize ACP resource access outside the HTTP transport boundary."""

import uuid
from typing import Any

from quart import abort

from mugen.core import di
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.utility.identity import resolve_acp_admin_namespace
from mugen.core.plugin.acp.utility.ns import AdminNs


async def require_resource_access(
    *,
    registry: IAdminRegistry,
    resource: Any,
    auth_user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    permission_type: str,
    admin_only: bool = False,
) -> None:
    """Require a current principal and grants for the exact resource scope."""
    if tenant_id is not None:
        edm_type = registry.schema.get_type(resource.edm_type_name)
        if edm_type.find_property("TenantId") is None:
            abort(403, "Resource is not tenant-scoped.")

    user_resource = registry.get_resource_by_type("ACP.User")
    user_service = registry.get_edm_service(user_resource.service_key)
    user = await user_service.get_expanded({"id": auth_user_id})
    if user is None or user.deleted_at is not None or user.locked_at is not None:
        abort(403, "Actor is not an active ACP user.")

    if admin_only:
        admin_ns = AdminNs(resolve_acp_admin_namespace(di.container.config))
        roles = {
            f"{role.namespace}:{role.name}" for role in (user.global_roles or [])
        }
        if admin_ns.key("administrator") not in roles:
            abort(403, "Action requires administrator privilege.")

    authorization = di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_SVC_AUTH
    )
    if not await authorization.has_permission(
        user_id=auth_user_id,
        permission_object=resource.perm_obj,
        permission_type=permission_type,
        tenant_id=tenant_id,
        allow_global_admin=False,
    ):
        abort(403, "Resource permission denied.")
