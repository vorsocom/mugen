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
from mugen.core.plugin.acp.utility.identity import resolve_acp_admin_namespace
from mugen.core.plugin.acp.utility.ns import AdminNs

_ROLE_ADMINISTRATOR = "administrator"

_EDM_GLOBAL_PERMISSION_ENTRY = "ACP.GlobalPermissionEntry"
_EDM_GLOBAL_ROLE_MEMBERSHIP = "ACP.GlobalRoleMembership"
_EDM_PERMISSION_ENTRY = "ACP.PermissionEntry"
_EDM_PERMISSION_OBJECT = "ACP.PermissionObject"
_EDM_PERMISSION_TYPE = "ACP.PermissionType"
_EDM_ROLE_MEMBERSHIP = "ACP.RoleMembership"
_EDM_USER = "ACP.User"


def _config_provider():
    return di.container.config


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


# pylint: disable=too-many-instance-attributes
# pylint: disable=too-few-public-methods
class AuthorizationService(IAuthorizationService):
    """An implemntation of IAuthorizationService."""

    _perm_obj_id_cache: dict[tuple[str, str], uuid.UUID]
    _perm_type_id_cache: dict[tuple[str, str], uuid.UUID]
    _admin_namespace: str

    def __init__(
        self,
        config_provider=_config_provider,
        registry_provider=_registry_provider,
    ) -> None:
        self._config = config_provider()
        self._registry: IAdminRegistry = registry_provider()

        self._perm_obj_id_cache = {}
        self._perm_type_id_cache = {}

        admin_ns = AdminNs(resolve_acp_admin_namespace(self._config))
        self._admin_namespace = admin_ns.ns
        self._admin_fqn = admin_ns.key(_ROLE_ADMINISTRATOR)

        self._gperm_entry_svc: IGlobalPermissionEntryService = (
            self._registry.get_edm_service(
                admin_ns.key(_EDM_GLOBAL_PERMISSION_ENTRY),
            )
        )
        self._grole_mship_svc: IGlobalRoleMembershipService = (
            self._registry.get_edm_service(
                admin_ns.key(_EDM_GLOBAL_ROLE_MEMBERSHIP),
            )
        )
        self._perm_entry_svc: IPermissionEntryService = self._registry.get_edm_service(
            admin_ns.key(_EDM_PERMISSION_ENTRY),
        )
        self._perm_obj_svc: IPermissionObjectService = self._registry.get_edm_service(
            admin_ns.key(_EDM_PERMISSION_OBJECT),
        )
        self._perm_type_svc: IPermissionTypeService = self._registry.get_edm_service(
            admin_ns.key(_EDM_PERMISSION_TYPE),
        )
        self._role_mship_svc: IRoleMembershipService = self._registry.get_edm_service(
            admin_ns.key(_EDM_ROLE_MEMBERSHIP),
        )
        self._user_svc: IUserService = self._registry.get_edm_service(
            admin_ns.key(_EDM_USER),
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
        try:
            if permission_object.startswith(":"):
                obj_ns = self._admin_namespace
                obj_name = permission_object[1:]
            else:
                obj_ns, obj_name = permission_object.split(":", 1)

            if permission_type.startswith(":"):
                typ_ns = self._admin_namespace
                typ_name = permission_type[1:]
            else:
                typ_ns, typ_name = permission_type.split(":", 1)
        except ValueError:
            return False

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
