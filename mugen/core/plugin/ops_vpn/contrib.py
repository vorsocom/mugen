"""
OPS VPN plugin contribution entrypoint.

Contributes vendor registry and scorecard resources into ACP.
"""

import re
from typing import Any

from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
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
from mugen.core.plugin.ops_vpn.api.validation import (
    VendorPerformanceEventCreateValidation,
    VendorScorecardRollupValidation,
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
    Contribute ops_vpn resources into the ACP registry.

    `admin_namespace` owns permission verbs.
    `plugin_namespace` owns permission objects and system flags.
    """
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS VPN plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsVpnTaxonomyDomains",
            "entity": "TaxonomyDomain",
            "description": "Tenant-scoped taxonomy domains (DD level).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Code", "Name"),
                update_schema=("Code", "Name", "Description", "Attributes"),
            ),
        },
        {
            "set": "OpsVpnTaxonomyCategories",
            "entity": "TaxonomyCategory",
            "description": "Tenant-scoped taxonomy categories (DDCC level).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "TaxonomyDomainId", "Code", "Name"),
                update_schema=("Code", "Name", "Description", "Attributes"),
            ),
        },
        {
            "set": "OpsVpnTaxonomySubcategories",
            "entity": "TaxonomySubcategory",
            "description": "Tenant-scoped taxonomy subcategories (DDCCSS level).",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "TaxonomyCategoryId", "Code", "Name"),
                update_schema=("Code", "Name", "Description", "Attributes"),
            ),
        },
        {
            "set": "OpsVpnVendors",
            "entity": "Vendor",
            "description": (
                "Vendor registry with lifecycle and reverification metadata."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Code", "DisplayName"),
                update_schema=(
                    "Code",
                    "DisplayName",
                    "ReverificationCadenceDays",
                    "ExternalRef",
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
                "activate": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Activate this vendor?",
                },
                "suspend": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Suspend this vendor?",
                },
                "delist": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Delist this vendor?",
                },
                "reverify": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "confirm": "Record reverification for this vendor?",
                },
            },
        },
        {
            "set": "OpsVpnVendorCategories",
            "entity": "VendorCategory",
            "description": "Vendor category assignments.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "VendorId", "CategoryCode"),
                update_schema=("DisplayName", "Attributes"),
            ),
        },
        {
            "set": "OpsVpnVendorCapabilities",
            "entity": "VendorCapability",
            "description": "Vendor capabilities and supported service regions.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "VendorId",
                    "CapabilityCode",
                    "ServiceRegion",
                ),
                update_schema=("Attributes",),
            ),
        },
        {
            "set": "OpsVpnVendorVerifications",
            "entity": "VendorVerification",
            "description": "Onboarding and reverification checks.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=("TenantId", "VendorId", "VerificationType", "Status"),
                update_schema=(
                    "CheckedAt",
                    "DueAt",
                    "CheckedByUserId",
                    "Notes",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsVpnVerificationCriteria",
            "entity": "VerificationCriterion",
            "description": (
                "Tenant-scoped checklist criteria for onboarding/reverification."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Code", "Name"),
                update_schema=(
                    "Name",
                    "Description",
                    "VerificationType",
                    "IsRequired",
                    "SortOrder",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsVpnVendorVerificationChecks",
            "entity": "VendorVerificationCheck",
            "description": "Checklist check results attached to a verification event.",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "VendorVerificationId", "CriterionCode"),
                update_schema=(
                    "CriterionId",
                    "Status",
                    "IsRequired",
                    "CheckedAt",
                    "DueAt",
                    "CheckedByUserId",
                    "Notes",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsVpnVendorVerificationArtifacts",
            "entity": "VendorVerificationArtifact",
            "description": (
                "Evidence artifacts linked to verification and check records."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "VendorVerificationId", "ArtifactType"),
                update_schema=(
                    "VerificationCheckId",
                    "Uri",
                    "ContentHash",
                    "UploadedByUserId",
                    "UploadedAt",
                    "Notes",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsVpnVendorPerformanceEvents",
            "entity": "VendorPerformanceEvent",
            "description": (
                "Operational performance observations for vendor scorecards."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=VendorPerformanceEventCreateValidation,
            ),
        },
        {
            "set": "OpsVpnScorecardPolicies",
            "entity": "ScorecardPolicy",
            "description": (
                "Tenant-scoped defaults for scorecard rollup and routability."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "crud": CrudPolicy(
                create_schema=("TenantId", "Code"),
                update_schema=(
                    "DisplayName",
                    "TimeToQuoteWeight",
                    "CompletionRateWeight",
                    "ComplaintRateWeight",
                    "ResponseSlaWeight",
                    "MinSampleSize",
                    "MinimumOverallScore",
                    "RequireAllMetrics",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OpsVpnVendorScorecards",
            "entity": "VendorScorecard",
            "description": "Period snapshots of normalized vendor performance.",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "actions": {
                "rollup": {
                    "perm": admin_ns.verb("manage"),
                    "schema": VendorScorecardRollupValidation,
                    "confirm": "Roll up scorecard for this vendor and period?",
                }
            },
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

        edm_type_name = f"OPSVPN.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(r.get("table_name", f"ops_vpn_{obj_name}"))

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
                table_provider=f"mugen.core.plugin.ops_vpn.model.{obj_name}:{entity}",
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_vpn.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    f"mugen.core.plugin.ops_vpn.service.{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
