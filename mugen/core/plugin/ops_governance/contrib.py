"""OPS governance plugin contribution entrypoint.

Contributes generic governance resources into ACP.
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
from mugen.core.plugin.ops_governance.api.validation import (
    ActivatePolicyVersionActionValidation,
    ApplyRetentionActionValidation,
    ConsentRecordCreateValidation,
    DataHandlingRecordCreateValidation,
    DataHandlingRecordUpdateValidation,
    DelegationGrantCreateValidation,
    EvaluatePolicyActionValidation,
    GrantDelegationActionValidation,
    LegalHoldCreateValidation,
    LegalHoldPlaceHoldActionValidation,
    LegalHoldReleaseHoldActionValidation,
    PolicyDefinitionCreateValidation,
    PolicyDefinitionUpdateValidation,
    RecordConsentActionValidation,
    RetentionClassCreateValidation,
    RetentionClassUpdateValidation,
    RetentionPolicyCreateValidation,
    RetentionPolicyUpdateValidation,
    RetentionPolicyRunLifecycleValidation,
    RevokeDelegationActionValidation,
    WithdrawConsentActionValidation,
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
    """Contribute ops_governance resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="OPS governance plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "OpsConsentRecords",
            "entity": "ConsentRecord",
            "description": (
                "Append-only consent grant and withdrawal records for governance"
                " traceability."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(create_schema=ConsentRecordCreateValidation),
            "actions": {
                "record_consent": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RecordConsentActionValidation,
                    "confirm": "Record a new consent event?",
                },
                "withdraw_consent": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WithdrawConsentActionValidation,
                    "confirm": "Withdraw consent for this record?",
                },
            },
        },
        {
            "set": "OpsDelegationGrants",
            "entity": "DelegationGrant",
            "description": (
                "Append-only delegation grant and revocation records for"
                " act-on-behalf controls."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(create_schema=DelegationGrantCreateValidation),
            "actions": {
                "grant_delegation": {
                    "perm": admin_ns.verb("manage"),
                    "schema": GrantDelegationActionValidation,
                    "confirm": "Grant delegation?",
                },
                "revoke_delegation": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RevokeDelegationActionValidation,
                    "confirm": "Revoke this delegation?",
                },
            },
        },
        {
            "set": "OpsPolicyDefinitions",
            "entity": "PolicyDefinition",
            "description": (
                "Policy metadata used by downstream governance and enforcement"
                " workflows."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=PolicyDefinitionCreateValidation,
                update_schema=PolicyDefinitionUpdateValidation,
            ),
            "actions": {
                "evaluate_policy": {
                    "perm": admin_ns.verb("manage"),
                    "schema": EvaluatePolicyActionValidation,
                    "confirm": "Evaluate this policy definition?",
                },
                "activate_version": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ActivatePolicyVersionActionValidation,
                    "confirm": "Activate this policy definition version?",
                },
            },
        },
        {
            "set": "OpsPolicyDecisionLogs",
            "entity": "PolicyDecisionLog",
            "description": (
                "Append-only policy decision outcomes emitted by explicit"
                " evaluations."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "OpsRetentionPolicies",
            "entity": "RetentionPolicy",
            "description": (
                "Generic retention/redaction policy metadata. Downstream plugins"
                " execute enforcement jobs."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=RetentionPolicyCreateValidation,
                update_schema=RetentionPolicyUpdateValidation,
            ),
            "actions": {
                "apply_retention_action": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ApplyRetentionActionValidation,
                    "confirm": "Apply a retention action metadata signal?",
                },
                "run_lifecycle": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RetentionPolicyRunLifecycleValidation,
                    "confirm": "Run lifecycle orchestration for this policy now?",
                },
            },
        },
        {
            "set": "OpsRetentionClasses",
            "entity": "RetentionClass",
            "description": (
                "Retention class profiles used by lifecycle orchestration for"
                " AuditEvent and EvidenceBlob resources."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=RetentionClassCreateValidation,
                update_schema=RetentionClassUpdateValidation,
            ),
        },
        {
            "set": "OpsLegalHolds",
            "entity": "LegalHold",
            "description": (
                "Legal hold declarations synchronized to governed AuditEvent and"
                " EvidenceBlob targets."
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(create_schema=LegalHoldCreateValidation),
            "actions": {
                "place_hold": {
                    "perm": admin_ns.verb("manage"),
                    "schema": LegalHoldPlaceHoldActionValidation,
                    "confirm": "Place legal hold on the target resource?",
                },
                "release_hold": {
                    "perm": admin_ns.verb("manage"),
                    "schema": LegalHoldReleaseHoldActionValidation,
                    "confirm": "Release legal hold on this target resource?",
                },
            },
        },
        {
            "set": "OpsLifecycleActionLogs",
            "entity": "LifecycleActionLog",
            "description": (
                "Append-only lifecycle operation logs emitted by retention and"
                " legal-hold orchestration."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "OpsDataHandlingRecords",
            "entity": "DataHandlingRecord",
            "description": (
                "Data handling metadata for redaction/erasure/access/retention"
                " request tracking."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=DataHandlingRecordCreateValidation,
                update_schema=DataHandlingRecordUpdateValidation,
            ),
        },
    )

    governance_objects: list[PermissionObjectDef] = []
    for resource in resources:
        obj_name = title_to_snake(resource["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        governance_objects.append(obj)
        registry.register_permission_object(obj)

    governance_obj_keys = [obj.key for obj in governance_objects]
    admin_verb_keys = [
        admin_ns.verb(verb) for verb in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in governance_obj_keys
        for ptyp in admin_verb_keys
    )

    for resource in resources:
        entity_set = resource["set"]
        entity = resource["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"OPSGOVERNANCE.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(resource.get("table_name", f"ops_governance_{obj_name}"))

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
                    f"mugen.core.plugin.ops_governance.model.{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.ops_governance.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    "mugen.core.plugin.ops_governance.service."
                    f"{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
