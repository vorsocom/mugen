"""OPS metering plugin contribution entrypoint.

Contributes generic operational metering resources into ACP.
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
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_metering.api.validation import (
    MeterDefinitionCreateValidation,
    MeterDefinitionUpdateValidation,
    MeterPolicyCreateValidation,
    MeterPolicyUpdateValidation,
    UsageRecordCreateValidation,
    UsageRecordRateValidation,
    UsageRecordVoidValidation,
    UsageSessionCreateValidation,
    UsageSessionPauseValidation,
    UsageSessionResumeValidation,
    UsageSessionStartValidation,
    UsageSessionStopValidation,
    UsageSessionUpdateValidation,
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
    """Contribute ops_metering resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS metering plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsMeterDefinitions",
            "entity": "MeterDefinition",
            "description": (
                "Tenant-scoped meter definitions (code, unit, aggregation mode)"
                " used for generic usage normalization."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=MeterDefinitionCreateValidation,
                update_schema=MeterDefinitionUpdateValidation,
            ),
        },
        {
            "set": "OpsMeterPolicies",
            "entity": "MeterPolicy",
            "description": (
                "Tenant-scoped generic metering policy definitions for caps,"
                " multipliers, rounding, and billable windows."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=MeterPolicyCreateValidation,
                update_schema=MeterPolicyUpdateValidation,
            ),
        },
        {
            "set": "OpsUsageSessions",
            "entity": "UsageSession",
            "description": (
                "Sessionized duration tracking with start/pause/resume/stop"
                " lifecycle actions."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=UsageSessionCreateValidation,
                update_schema=UsageSessionUpdateValidation,
            ),
            "actions": {
                "start_session": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsageSessionStartValidation,
                    "confirm": "Start this usage session?",
                },
                "pause_session": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsageSessionPauseValidation,
                    "confirm": "Pause this usage session?",
                },
                "resume_session": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsageSessionResumeValidation,
                    "confirm": "Resume this usage session?",
                },
                "stop_session": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsageSessionStopValidation,
                    "confirm": "Stop this usage session?",
                },
            },
        },
        {
            "set": "OpsUsageRecords",
            "entity": "UsageRecord",
            "description": (
                "Immutable measured usage entries, including idempotent ingestion,"
                " rating, and void actions."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=UsageRecordCreateValidation,
            ),
            "actions": {
                "rate_record": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsageRecordRateValidation,
                    "confirm": "Rate this usage record?",
                },
                "void_record": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsageRecordVoidValidation,
                    "confirm": "Void this usage record?",
                },
            },
        },
        {
            "set": "OpsRatedUsages",
            "entity": "RatedUsage",
            "description": (
                "Normalized rated outcomes prior to billing usage handoff."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
    )

    metering_objects: list[PermissionObjectDef] = []
    for resource in resources:
        obj_name = title_to_snake(resource["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        metering_objects.append(obj)
        registry.register_permission_object(obj)

    metering_obj_keys = [obj.key for obj in metering_objects]
    admin_verb_keys = [
        admin_ns.verb(verb) for verb in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in metering_obj_keys
        for ptyp in admin_verb_keys
    )

    for resource in resources:
        entity_set = resource["set"]
        entity = resource["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"OPSMETERING.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(resource.get("table_name", f"ops_metering_{obj_name}"))

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
                    soft_delete=resource.get("soft_delete", SoftDeletePolicy()),
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
                    f"mugen.core.plugin.ops_metering.model.{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_metering.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_metering.service.{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
