"""OPS connector plugin contribution entrypoint.

Contributes external connector type/instance/call-log resources into ACP.
"""

import re
from typing import Any

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
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_connector.api.validation import (
    ConnectorInstanceCreateValidation,
    ConnectorInstanceInvokeValidation,
    ConnectorInstanceTestConnectionValidation,
    ConnectorTypeCreateValidation,
)
from mugen.core.utility.string.case_conversion_helper import title_to_snake

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|\d+")


def _humanize(s: str) -> str:
    """Convert PascalCase/camelCase identifiers into a display title."""
    return " ".join(_WORD_RE.findall(s)).strip()


# pylint: disable=too-many-locals
def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute ops_connector resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS connector plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsConnectorTypes",
            "entity": "ConnectorType",
            "table_name": "ops_connector_type",
            "description": (
                "Global connector type registry containing adapter-kind and "
                "capability contracts."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=ConnectorTypeCreateValidation,
                update_schema=(
                    "Key",
                    "DisplayName",
                    "AdapterKind",
                    "CapabilitiesJson",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsConnectorInstances",
            "entity": "ConnectorInstance",
            "table_name": "ops_connector_instance",
            "description": (
                "Tenant-scoped connector instance runtime configuration and "
                "failure escalation settings."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=ConnectorInstanceCreateValidation,
                update_schema=(
                    "ConnectorTypeId",
                    "DisplayName",
                    "ConfigJson",
                    "SecretRef",
                    "Status",
                    "EscalationPolicyKey",
                    "RetryPolicyJson",
                    "Attributes",
                ),
            ),
            "actions": {
                "test_connection": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ConnectorInstanceTestConnectionValidation,
                    "confirm": "Run connector test-connection probe?",
                    "required_capabilities": [
                        "connector:invoke",
                        "net:outbound",
                        "secrets:read",
                    ],
                },
                "invoke": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ConnectorInstanceInvokeValidation,
                    "confirm": "Invoke connector capability now?",
                    "required_capabilities": [
                        "connector:invoke",
                        "net:outbound",
                        "secrets:read",
                    ],
                },
            },
        },
        {
            "set": "OpsConnectorCallLogs",
            "entity": "ConnectorCallLog",
            "table_name": "ops_connector_call_log",
            "description": (
                "Tenant-scoped immutable connector invocation provenance ledger "
                "with redacted request/response digests."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
    )

    connector_objects: list[PermissionObjectDef] = []
    for resource in resources:
        obj_name = title_to_snake(resource["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        connector_objects.append(obj)
        registry.register_permission_object(obj)

    connector_obj_keys = [obj.key for obj in connector_objects]
    admin_verb_keys = [
        admin_ns.verb(verb) for verb in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in connector_obj_keys
        for ptyp in admin_verb_keys
    )

    for resource in resources:
        entity_set = resource["set"]
        entity = resource["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"OPSCONNECTOR.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(resource.get("table_name", f"ops_connector_{obj_name}"))

        registry.register_resource(
            AdminResource(
                namespace=plugin_ns.ns,
                entity_set=entity_set,
                edm_type_name=edm_type_name,
                perm_obj=pobj.key,
                service_key=service_key,
                permissions=AdminPermissions(
                    permission_object=pobj.key,
                    read=admin_ns.verb("read"),
                    create=admin_ns.verb("create"),
                    update=admin_ns.verb("update"),
                    delete=admin_ns.verb("delete"),
                    manage=admin_ns.verb("manage"),
                ),
                capabilities=AdminCapabilities(
                    allow_read=bool(resource.get("allow_read", True)),
                    allow_create=bool(resource.get("allow_create", False)),
                    allow_update=bool(resource.get("allow_update", False)),
                    allow_delete=bool(resource.get("allow_delete", False)),
                    allow_manage=bool(resource.get("allow_manage", False)),
                    actions=dict(resource.get("actions", {})),
                ),
                behavior=AdminBehavior(
                    rgql_enabled=True,
                ),
                crud=resource.get("crud", CrudPolicy()),
                title=_humanize(entity_set),
                description=resource["description"],
            )
        )

        registry.register_table_spec(
            TableSpec(
                table_name=table_name,
                table_provider=(
                    f"mugen.core.plugin.ops_connector.model.{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_connector.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_connector.service.{obj_name}:"
                    f"{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
