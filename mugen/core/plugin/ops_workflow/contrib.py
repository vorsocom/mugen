"""OPS Workflow plugin contribution entrypoint.

Contributes bounded workflow resources into ACP using declarative metadata only.
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
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowApproveValidation,
    WorkflowAssignTaskValidation,
    WorkflowCancelInstanceValidation,
    WorkflowCompleteTaskValidation,
    WorkflowRejectValidation,
    WorkflowStartInstanceValidation,
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
    """Contribute ops_workflow resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS Workflow plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsWorkflowDefinitions",
            "entity": "WorkflowDefinition",
            "description": (
                "Tenant-scoped workflow definitions that own versioned state machines."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Key", "Name"),
                update_schema=(
                    "Key",
                    "Name",
                    "Description",
                    "IsActive",
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
        {
            "set": "OpsWorkflowVersions",
            "entity": "WorkflowVersion",
            "description": (
                "Immutable-ish workflow definition versions used to scope states and"
                " transitions."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "WorkflowDefinitionId",
                    "VersionNumber",
                ),
                update_schema=(
                    "Status",
                    "PublishedAt",
                    "PublishedByUserId",
                    "IsDefault",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsWorkflowStates",
            "entity": "WorkflowState",
            "description": "Named states for a workflow version.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=("TenantId", "WorkflowVersionId", "Key", "Name"),
                update_schema=(
                    "Key",
                    "Name",
                    "IsInitial",
                    "IsTerminal",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsWorkflowTransitions",
            "entity": "WorkflowTransition",
            "description": "Deterministic transitions between workflow states.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "WorkflowVersionId",
                    "Key",
                    "FromStateId",
                    "ToStateId",
                ),
                update_schema=(
                    "Key",
                    "FromStateId",
                    "ToStateId",
                    "RequiresApproval",
                    "AutoAssignUserId",
                    "AutoAssignQueue",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsWorkflowInstances",
            "entity": "WorkflowInstance",
            "description": (
                "Runtime workflow instances with bounded lifecycle transitions and"
                " approval gates."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "WorkflowDefinitionId",
                    "WorkflowVersionId",
                    "Title",
                ),
                update_schema=(
                    "Title",
                    "ExternalRef",
                    "SubjectNamespace",
                    "SubjectId",
                    "SubjectRef",
                    "Attributes",
                ),
            ),
            "actions": {
                "start_instance": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowStartInstanceValidation,
                    "confirm": "Start this workflow instance?",
                },
                "advance": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowAdvanceValidation,
                    "confirm": "Advance this workflow instance?",
                },
                "approve": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowApproveValidation,
                    "confirm": "Approve this pending workflow transition?",
                },
                "reject": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowRejectValidation,
                    "confirm": "Reject this pending workflow transition?",
                },
                "cancel_instance": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowCancelInstanceValidation,
                    "confirm": "Cancel this workflow instance?",
                },
            },
        },
        {
            "set": "OpsWorkflowTasks",
            "entity": "WorkflowTask",
            "description": (
                "Workflow task records for approvals, ownership handoffs,"
                " and completion tracking."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "WorkflowInstanceId",
                    "TaskKind",
                    "Title",
                ),
            ),
            "actions": {
                "assign_task": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowAssignTaskValidation,
                    "confirm": "Assign or hand off this workflow task?",
                },
                "complete_task": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkflowCompleteTaskValidation,
                    "confirm": "Complete this workflow task?",
                },
            },
        },
        {
            "set": "OpsWorkflowEvents",
            "entity": "WorkflowEvent",
            "description": "Append-only workflow event timeline.",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
    )

    workflow_objects: list[PermissionObjectDef] = []
    for r in resources:
        obj_name = title_to_snake(r["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        workflow_objects.append(obj)
        registry.register_permission_object(obj)

    workflow_obj_keys = [o.key for o in workflow_objects]
    admin_verb_keys = [
        admin_ns.verb(v) for v in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in workflow_obj_keys
        for ptyp in admin_verb_keys
    )

    for r in resources:
        entity_set = r["set"]
        entity = r["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"OPSWORKFLOW.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(r.get("table_name", f"ops_workflow_{obj_name}"))

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
                table_provider=(
                    f"mugen.core.plugin.ops_workflow.model.{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_workflow.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_workflow.service.{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
