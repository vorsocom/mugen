"""
OPS Case plugin contribution entrypoint.

Contributes case-management resources into ACP.
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
    SoftDeleteMode,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_case.api.validation import (
    CaseAssignValidation,
    CaseCancelValidation,
    CaseCloseValidation,
    CaseEscalateValidation,
    CaseLinkCreateValidation,
    CaseReopenValidation,
    CaseResolveValidation,
    CaseTriageValidation,
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
    """
    Contribute ops_case resources into the ACP registry.

    `admin_namespace` owns permission verbs.
    `plugin_namespace` owns permission objects and system flags.
    """
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS Case plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsCases",
            "entity": "Case",
            "description": (
                "Tenant-scoped operations case records with lifecycle, priorities,"
                " ownership, and SLA targets."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Title"),
                update_schema=(
                    "Title",
                    "Description",
                    "Priority",
                    "Severity",
                    "DueAt",
                    "SlaTargetAt",
                    "Attributes",
                ),
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "actions": {
                "triage": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseTriageValidation,
                    "confirm": "Triage this case?",
                },
                "assign": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseAssignValidation,
                    "confirm": "Update assignment for this case?",
                },
                "escalate": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseEscalateValidation,
                    "confirm": "Escalate this case?",
                },
                "resolve": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseResolveValidation,
                    "confirm": "Resolve this case?",
                },
                "close": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseCloseValidation,
                    "confirm": "Close this case?",
                },
                "reopen": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseReopenValidation,
                    "confirm": "Reopen this case?",
                },
                "cancel": {
                    "perm": admin_ns.verb("manage"),
                    "schema": CaseCancelValidation,
                    "confirm": "Cancel this case?",
                },
            },
        },
        {
            "set": "OpsCaseEvents",
            "entity": "CaseEvent",
            "description": (
                "Append-only timeline entries for status transitions and case actions."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "OpsCaseAssignments",
            "entity": "CaseAssignment",
            "description": "Assignment history snapshots for case owner/queue routing.",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "OpsCaseLinks",
            "entity": "CaseLink",
            "description": (
                "Generic references linking cases to related domain entities"
                " (tenant/customer/vendor/invoice/etc.)."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=CaseLinkCreateValidation,
                update_schema=(
                    "TargetNamespace",
                    "TargetId",
                    "TargetRef",
                    "TargetDisplay",
                    "RelationshipKind",
                    "Attributes",
                ),
            ),
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
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

        edm_type_name = f"OPSCASE.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(r.get("table_name", f"ops_case_{obj_name}"))

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
                table_provider=f"mugen.core.plugin.ops_case.model.{obj_name}:{entity}",
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_case.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_case.service.{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
