"""OPS SLA plugin contribution entrypoint.

Contributes SLA policy, calendar, target, clock, and breach-event resources into ACP.
"""

import re
from typing import Any

from mugen.core.plugin.acp.contract.sdk.binding import (
    TableSpec,
    EdmTypeSpec,
    RelationalServiceSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    PermissionObjectDef,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminCapabilities,
    AdminBehavior,
    AdminPermissions,
    AdminResource,
    CrudPolicy,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockCreateValidation,
    SlaClockMarkBreachedValidation,
    SlaClockPauseValidation,
    SlaClockResumeValidation,
    SlaClockStartValidation,
    SlaClockStopValidation,
    SlaTargetCreateValidation,
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
    """Contribute ops_sla resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS SLA plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsSlaPolicies",
            "entity": "SlaPolicy",
            "table_name": "ops_sla_policy",
            "description": (
                "Tenant-scoped SLA policy metadata used to group target definitions"
                " and default calendars."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Code", "Name"),
                update_schema=(
                    "Code",
                    "Name",
                    "Description",
                    "CalendarId",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsSlaCalendars",
            "entity": "SlaCalendar",
            "table_name": "ops_sla_calendar",
            "description": (
                "Business-hours calendars (timezone, business windows, holiday"
                " references) used for SLA deadline calculations."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Code", "Name", "Timezone"),
                update_schema=(
                    "Code",
                    "Name",
                    "Timezone",
                    "BusinessStartTime",
                    "BusinessEndTime",
                    "BusinessDays",
                    "HolidayRefs",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsSlaTargets",
            "entity": "SlaTarget",
            "table_name": "ops_sla_target",
            "description": (
                "Policy targets for response/resolution metrics by priority/severity"
                " buckets."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=SlaTargetCreateValidation,
                update_schema=(
                    "Metric",
                    "Priority",
                    "Severity",
                    "TargetMinutes",
                    "WarnBeforeMinutes",
                    "AutoBreach",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsSlaClocks",
            "entity": "SlaClock",
            "table_name": "ops_sla_clock",
            "description": (
                "Elapsed tracking state per monitored object, including running/"
                "paused/stopped transitions and computed deadlines."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=SlaClockCreateValidation,
                update_schema=(
                    "PolicyId",
                    "CalendarId",
                    "TargetId",
                    "TrackedNamespace",
                    "TrackedId",
                    "TrackedRef",
                    "Metric",
                    "Priority",
                    "Severity",
                    "Attributes",
                ),
            ),
            "actions": {
                "start_clock": {
                    "perm": admin_ns.verb("manage"),
                    "schema": SlaClockStartValidation,
                    "confirm": "Start this SLA clock?",
                },
                "pause_clock": {
                    "perm": admin_ns.verb("manage"),
                    "schema": SlaClockPauseValidation,
                    "confirm": "Pause this SLA clock?",
                },
                "resume_clock": {
                    "perm": admin_ns.verb("manage"),
                    "schema": SlaClockResumeValidation,
                    "confirm": "Resume this SLA clock?",
                },
                "stop_clock": {
                    "perm": admin_ns.verb("manage"),
                    "schema": SlaClockStopValidation,
                    "confirm": "Stop this SLA clock?",
                },
                "mark_breached": {
                    "perm": admin_ns.verb("manage"),
                    "schema": SlaClockMarkBreachedValidation,
                    "confirm": "Mark this SLA clock as breached?",
                },
            },
        },
        {
            "set": "OpsSlaBreachEvents",
            "entity": "SlaBreachEvent",
            "table_name": "ops_sla_breach_event",
            "description": (
                "Append-only breach/escalation markers generated by SLA actions."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
    )

    ops_objects: list[PermissionObjectDef] = []
    for r in resources:
        obj_name = title_to_snake(r["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        ops_objects.append(obj)
        registry.register_permission_object(obj)

    ops_obj_keys = [o.key for o in ops_objects]
    admin_verb_keys = [
        admin_ns.verb(v) for v in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in ops_obj_keys
        for ptyp in admin_verb_keys
    )

    for r in resources:
        entity_set = r["set"]
        entity = r["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"OPSSLA.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(r.get("table_name", f"ops_sla_{obj_name}"))

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
                    allow_read=bool(r.get("allow_read", True)),
                    allow_create=bool(r.get("allow_create", False)),
                    allow_update=bool(r.get("allow_update", False)),
                    allow_delete=bool(r.get("allow_delete", False)),
                    allow_manage=bool(r.get("allow_manage", False)),
                    actions=dict(r.get("actions", {})),
                ),
                behavior=AdminBehavior(
                    soft_delete=r.get("soft_delete", SoftDeletePolicy()),
                    rgql_enabled=True,
                ),
                crud=r.get("crud", CrudPolicy()),
                title=_humanize(entity_set),
                description=r["description"],
            )
        )

        registry.register_table_spec(
            TableSpec(
                table_name=table_name,
                table_provider=f"mugen.core.plugin.ops_sla.model.{obj_name}:{entity}",
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_sla.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_sla.service.{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
