"""OPS reporting plugin contribution entrypoint.

Contributes generic operational KPI resources into ACP.
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
from mugen.core.plugin.ops_reporting.api.validation import (
    AggregationJobCreateValidation,
    AggregationJobUpdateValidation,
    ExportJobBuildValidation,
    ExportJobCreateValidation,
    ExportJobVerifyValidation,
    KpiThresholdCreateValidation,
    KpiThresholdUpdateValidation,
    MetricDefinitionCreateValidation,
    MetricDefinitionUpdateValidation,
    MetricRecomputeWindowValidation,
    MetricRunAggregationValidation,
    ReportDefinitionCreateValidation,
    ReportDefinitionUpdateValidation,
    ReportSnapshotArchiveValidation,
    ReportSnapshotCreateValidation,
    ReportSnapshotGenerateValidation,
    ReportSnapshotPublishValidation,
    ReportSnapshotUpdateValidation,
    ReportSnapshotVerifyValidation,
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
    """Contribute ops_reporting resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS reporting plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsReportingMetricDefinitions",
            "entity": "MetricDefinition",
            "description": (
                "Metric definitions describing reusable aggregation formulas and"
                " source bindings into existing plugin stores."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=MetricDefinitionCreateValidation,
                update_schema=MetricDefinitionUpdateValidation,
            ),
            "actions": {
                "run_aggregation": {
                    "perm": admin_ns.verb("manage"),
                    "schema": MetricRunAggregationValidation,
                    "confirm": "Run aggregation for this metric definition?",
                },
                "recompute_window": {
                    "perm": admin_ns.verb("manage"),
                    "schema": MetricRecomputeWindowValidation,
                    "confirm": (
                        "Recompute this metric window and replace series values?"
                    ),
                },
            },
        },
        {
            "set": "OpsReportingMetricSeries",
            "entity": "MetricSeries",
            "description": (
                "Time-bucketed metric aggregates materialized deterministically"
                " per metric/window/scope."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "OpsReportingAggregationJobs",
            "entity": "AggregationJob",
            "description": (
                "Aggregation run metadata and idempotency ledger entries for metric"
                " windows."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=AggregationJobCreateValidation,
                update_schema=AggregationJobUpdateValidation,
            ),
        },
        {
            "set": "OpsReportingReportDefinitions",
            "entity": "ReportDefinition",
            "description": (
                "Generic report definitions mapping metric sets, filters, and grouping"
                " metadata without dashboard-specific semantics."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=ReportDefinitionCreateValidation,
                update_schema=ReportDefinitionUpdateValidation,
            ),
        },
        {
            "set": "OpsReportingReportSnapshots",
            "entity": "ReportSnapshot",
            "description": (
                "Point-in-time snapshot records generated from report definitions and"
                " metric series."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=ReportSnapshotCreateValidation,
                update_schema=ReportSnapshotUpdateValidation,
            ),
            "actions": {
                "generate_snapshot": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ReportSnapshotGenerateValidation,
                    "confirm": "Generate this report snapshot payload?",
                },
                "publish_snapshot": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ReportSnapshotPublishValidation,
                    "confirm": "Publish this generated report snapshot?",
                },
                "archive_snapshot": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ReportSnapshotArchiveValidation,
                    "confirm": "Archive this report snapshot?",
                },
                "verify_snapshot": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ReportSnapshotVerifyValidation,
                    "confirm": "Verify this report snapshot integrity metadata?",
                },
            },
        },
        {
            "set": "OpsReportingExportJobs",
            "entity": "ExportJob",
            "description": (
                "Deterministic export bundle jobs that create signed manifests and"
                " item-ledger proof data."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(),
            "actions": {
                "create_export": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ExportJobCreateValidation,
                    "confirm": "Create a queued export job?",
                },
                "build_export": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ExportJobBuildValidation,
                    "confirm": "Build this export job and finalize its manifest?",
                },
                "verify_export": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ExportJobVerifyValidation,
                    "confirm": "Verify this export manifest and item hashes?",
                },
            },
        },
        {
            "set": "OpsReportingExportItems",
            "entity": "ExportItem",
            "description": (
                "Read-only export item ledger rows containing canonicalized payload"
                " hashes."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "OpsReportingKpiThresholds",
            "entity": "KpiThreshold",
            "description": (
                "KPI threshold bands and target boundaries for generic alerting"
                " policies across scoped metrics."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=KpiThresholdCreateValidation,
                update_schema=KpiThresholdUpdateValidation,
            ),
            "soft_delete": SoftDeletePolicy(),
        },
    )

    ops_objects: list[PermissionObjectDef] = []
    for resource in resources:
        obj_name = title_to_snake(resource["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        ops_objects.append(obj)
        registry.register_permission_object(obj)

    ops_obj_keys = [obj.key for obj in ops_objects]
    admin_verb_keys = [
        admin_ns.verb(verb) for verb in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in ops_obj_keys
        for ptyp in admin_verb_keys
    )

    for resource in resources:
        entity_set = resource["set"]
        entity = resource["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"OPSREPORTING.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(resource.get("table_name", f"ops_reporting_{obj_name}"))

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
                    f"mugen.core.plugin.ops_reporting.model.{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_reporting.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_reporting.service.{obj_name}:"
                    f"{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
