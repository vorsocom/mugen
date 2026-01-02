"""
Provides an implementation of IAuthorizationService.
"""

import uuid

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import (
    IAuthorizationService,
    IGlobalPermissionEntryService,
    IGlobalRoleMembershipService,
    IPermissionEntryService,
    IPermissionObjectService,
    IPermissionTypeService,
    IRoleMembershipService,
    IUserService,
)


# pylint: disable=too-many-instance-attributes
# pylint: disable=too-few-public-methods
class AuthorizationService(IAuthorizationService):
    """An implemntation of IAuthorizationService."""

    _perm_obj_id_cache: dict[tuple[str, str], uuid.UUID]
    _perm_type_id_cache: dict[tuple[str, str], uuid.UUID]

    def __init__(
        self,
        config_provider=lambda: di.container.config,
        registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    ) -> None:
        self._config = config_provider()
        self._registry: IAdminRegistry = registry_provider()

        self._perm_obj_id_cache = {}
        self._perm_type_id_cache = {}

        self._admin_fqn = f"{self._config.acp.namespace}:administrator"

        self._gperm_entry_svc: IGlobalPermissionEntryService = (
            self._registry.get_edm_service(
                f"{self._config.acp.namespace}:ACP.GlobalPermissionEntry",
            )
        )
        self._grole_mship_svc: IGlobalRoleMembershipService = (
            self._registry.get_edm_service(
                f"{self._config.acp.namespace}:ACP.GlobalRoleMembership",
            )
        )
        self._perm_entry_svc: IPermissionEntryService = self._registry.get_edm_service(
            f"{self._config.acp.namespace}:ACP.PermissionEntry",
        )
        self._perm_obj_svc: IPermissionObjectService = self._registry.get_edm_service(
            f"{self._config.acp.namespace}:ACP.PermissionObject",
        )
        self._perm_type_svc: IPermissionTypeService = self._registry.get_edm_service(
            f"{self._config.acp.namespace}:ACP.PermissionType",
        )
        self._role_mship_svc: IRoleMembershipService = self._registry.get_edm_service(
            f"{self._config.acp.namespace}:ACP.RoleMembership",
        )
        self._user_svc: IUserService = self._registry.get_edm_service(
            f"{self._config.acp.namespace}:ACP.User",
        )

    async def _get_perm_obj_id(self, ns: str, name: str) -> uuid.UUID | None:
        key = (ns, name)
        if key in self._perm_obj_id_cache:
            return self._perm_obj_id_cache[key]

        row = await self._perm_obj_svc.get({"namespace": ns, "name": name})
        if row:
            self._perm_obj_id_cache[key] = row.id
            return row.id
        return None

    async def _get_perm_type_id(self, ns: str, name: str) -> uuid.UUID | None:
        key = (ns, name)
        if key in self._perm_type_id_cache:
            return self._perm_type_id_cache[key]

        row = await self._perm_type_svc.get({"namespace": ns, "name": name})
        if row:
            self._perm_type_id_cache[key] = row.id
            return row.id
        return None

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-locals
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    async def has_permission(
        self,
        *,
        user_id: uuid.UUID,
        permission_object: str,  # namespace:name
        permission_type: str,  # namespace:name
        tenant_id: uuid.UUID | None,
        allow_global_admin: bool = False,
    ) -> bool:
        if permission_object.startswith(":"):
            obj_ns = self._config.acp.namespace
            obj_name = permission_object[1:]
        else:
            obj_ns, obj_name = permission_object.split(":", 1)

        if permission_type.startswith(":"):
            typ_ns = self._config.acp.namespace
            typ_name = permission_type[1:]
        else:
            typ_ns, typ_name = permission_type.split(":", 1)

        obj_id = await self._get_perm_obj_id(obj_ns, obj_name)
        typ_id = await self._get_perm_type_id(typ_ns, typ_name)
        if obj_id is None or typ_id is None:
            return False

        # Global admin override.
        if allow_global_admin:
            user = await self._user_svc.get_expanded({"id": user_id})
            if user:
                global_roles = {
                    f"{r.namespace}:{r.name}" for r in (user.global_roles or [])
                }
                if self._admin_fqn in global_roles:
                    return True

        # 1) Global permissions (global roles)
        global_role_ids = [
            m.global_role_id
            for m in await self._grole_mship_svc.get_role_memberships_by_user(
                {"user_id": user_id},
            )
        ]

        if global_role_ids:
            entries = await self._gperm_entry_svc.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "permission_object_id": obj_id,
                            "permission_type_id": typ_id,
                        },
                        scalar_filters=[
                            ScalarFilter(
                                field="global_role_id",
                                op=ScalarFilterOp.IN,
                                value=global_role_ids,
                            )
                        ],
                    )
                ]
            )
            if any(e.permitted is False for e in entries):
                return False
            if any(e.permitted is True for e in entries):
                return True

        # 2) Tenant permissions (tenant roles)
        if tenant_id is None:
            return False

        role_ids = [
            m.role_id
            for m in await self._role_mship_svc.get_role_memberships_by_user(
                {"tenant_id": tenant_id, "user_id": user_id},
            )
        ]

        if not role_ids:
            return False

        entries = await self._perm_entry_svc.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "permission_object_id": obj_id,
                        "permission_type_id": typ_id,
                    },
                    scalar_filters=[
                        ScalarFilter(
                            field="role_id",
                            op=ScalarFilterOp.IN,
                            value=role_ids,
                        )
                    ],
                )
            ]
        )
        if any(e.permitted is False for e in entries):
            return False
        return any(e.permitted is True for e in entries)
