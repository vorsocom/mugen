"""Service Profile contribution entrypoint for ACP."""

from __future__ import annotations

import re
from typing import Any

from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.acp.contract.sdk.binding import (
    EdmTypeSpec,
    RelationalServiceSpec,
    TableSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    PermissionObjectDef,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminBehavior,
    AdminCapabilities,
    AdminPermissions,
    AdminResource,
    CrudPolicy,
    SoftDeleteMode,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.service_profile.api.validation import (
    ServiceProfileCreateValidation,
    ServiceProfileIngressBindingCreateValidation,
    ServiceProfileIngressBindingUpdateValidation,
    ServiceProfileSubscriptionCreateValidation,
    ServiceProfileSubscriptionUpdateValidation,
    ServiceProfileUpdateValidation,
)
from mugen.core.utility.string.case_conversion_helper import title_to_snake

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|\d+")


def _humanize(value: str) -> str:
    return " ".join(_WORD_RE.findall(value)).strip()


# pylint: disable=too-many-locals
def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute tenant-scoped Service Profile resources into ACP."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)
    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Service Profile plugin installed.",
            is_set=True,
        )
    )

    lifecycle_actions = {
        "activate": {
            "perm": admin_ns.verb("manage"),
            "schema": RowVersionValidation,
            "confirm": "Activate this Service Profile?",
        },
        "disable": {
            "perm": admin_ns.verb("manage"),
            "schema": RowVersionValidation,
            "confirm": "Disable this Service Profile?",
        },
    }
    subscription_actions = {
        "activate": {
            "perm": admin_ns.verb("manage"),
            "schema": RowVersionValidation,
            "confirm": "Activate this Service Profile Subscription assignment?",
        },
        "disable": {
            "perm": admin_ns.verb("manage"),
            "schema": RowVersionValidation,
            "confirm": "Disable this Service Profile Subscription assignment?",
        },
    }
    soft_delete = SoftDeletePolicy(
        mode=SoftDeleteMode.TIMESTAMP,
        column="DeletedAt",
        allow_restore=False,
        allow_hard_delete=False,
    )
    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "ServiceProfiles",
            "entity": "ServiceProfile",
            "table": "service_profile_service_profile",
            "description": "Tenant-scoped channel-neutral routable service identities.",
            "crud": CrudPolicy(
                create_schema=ServiceProfileCreateValidation,
                update_schema=ServiceProfileUpdateValidation,
            ),
            "actions": lifecycle_actions,
            "soft_delete": soft_delete,
        },
        {
            "set": "ServiceProfileIngressBindings",
            "entity": "ServiceProfileIngressBinding",
            "table": "service_profile_ingress_binding",
            "description": "Exact assignments from Ingress Bindings to profiles.",
            "crud": CrudPolicy(
                create_schema=ServiceProfileIngressBindingCreateValidation,
                update_schema=ServiceProfileIngressBindingUpdateValidation,
            ),
        },
        {
            "set": "ServiceProfileSubscriptions",
            "entity": "ServiceProfileSubscription",
            "table": "service_profile_subscription",
            "description": "Exact Billing Subscription allocations to profiles.",
            "crud": CrudPolicy(
                create_schema=ServiceProfileSubscriptionCreateValidation,
                update_schema=ServiceProfileSubscriptionUpdateValidation,
            ),
            "actions": subscription_actions,
            "soft_delete": soft_delete,
        },
    )

    permission_objects: list[PermissionObjectDef] = []
    for resource in resources:
        permission_object = PermissionObjectDef(
            plugin_ns.ns,
            title_to_snake(resource["entity"]),
        )
        permission_objects.append(permission_object)
        registry.register_permission_object(permission_object)
    registry.register_default_global_grants(
        DefaultGlobalGrant(
            admin_ns.key("administrator"),
            permission_object.key,
            admin_ns.verb(verb),
            True,
        )
        for permission_object in permission_objects
        for verb in ("read", "create", "update", "manage")
    )

    for resource in resources:
        entity_set = str(resource["set"])
        entity = str(resource["entity"])
        object_name = title_to_snake(entity)
        permission_object = PermissionObjectDef(plugin_ns.ns, object_name)
        edm_type_name = f"SERVICEPROFILE.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(resource["table"])
        registry.register_resource(
            AdminResource(
                namespace=plugin_ns.ns,
                entity_set=entity_set,
                edm_type_name=edm_type_name,
                perm_obj=permission_object.key,
                service_key=service_key,
                permissions=AdminPermissions(
                    permission_object=permission_object.key,
                    read=admin_ns.verb("read"),
                    create=admin_ns.verb("create"),
                    update=admin_ns.verb("update"),
                    delete=admin_ns.verb("delete"),
                    manage=admin_ns.verb("manage"),
                ),
                capabilities=AdminCapabilities(
                    allow_read=True,
                    allow_create=True,
                    allow_update=True,
                    allow_delete=False,
                    allow_manage=bool(resource.get("actions")),
                    actions=dict(resource.get("actions", {})),
                ),
                behavior=AdminBehavior(
                    soft_delete=resource.get("soft_delete", SoftDeletePolicy()),
                    rgql_enabled=True,
                ),
                crud=resource["crud"],
                title=_humanize(entity_set),
                description=str(resource["description"]),
            )
        )
        registry.register_table_spec(
            TableSpec(
                table_name=table_name,
                table_provider=(
                    f"mugen.core.plugin.service_profile.model.{object_name}:{entity}"
                ),
            )
        )
        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=(
                    "mugen.core.plugin.service_profile.edm:" f"{object_name}_type"
                ),
            )
        )
        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    "mugen.core.plugin.service_profile.service."
                    f"{object_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
