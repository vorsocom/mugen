"""Channel orchestration plugin contribution entrypoint."""

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
from mugen.core.plugin.channel_orchestration.api.validation import (
    ApplyThrottleValidation,
    BlockSenderActionValidation,
    EscalateConversationValidation,
    EvaluateIntakeValidation,
    IngressBindingCreateValidation,
    RouteConversationValidation,
    SetFallbackValidation,
    UnblockSenderActionValidation,
    WorkItemCreateFromChannelValidation,
    WorkItemLinkToCaseValidation,
    WorkItemReplayValidation,
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
    """Contribute channel_orchestration resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Channel orchestration plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "ChannelProfiles",
            "entity": "ChannelProfile",
            "description": (
                "Channel-level profile registry used by generic orchestration rules"
                " and policies."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "ChannelKey",
                    "ProfileKey",
                    "ClientProfileId",
                ),
                update_schema=(
                    "ClientProfileId",
                    "DisplayName",
                    "RouteDefaultKey",
                    "PolicyId",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "IngressBindings",
            "entity": "IngressBinding",
            "description": (
                "Tenant-scoped inbound identifier bindings used to resolve"
                " ingress traffic into tenant/channel profile context."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=IngressBindingCreateValidation,
                update_schema=(
                    "ChannelProfileId",
                    "ChannelKey",
                    "IdentifierType",
                    "IdentifierValue",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "IntakeRules",
            "entity": "IntakeRule",
            "description": (
                "Keyword/menu/intent intake matching rules with explicit"
                " precedence metadata."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "Name",
                    "MatchKind",
                    "MatchValue",
                ),
                update_schema=(
                    "ChannelProfileId",
                    "Name",
                    "MatchKind",
                    "MatchValue",
                    "RouteKey",
                    "Priority",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "RoutingRules",
            "entity": "RoutingRule",
            "description": (
                "Generic route metadata for queue/user/service ownership"
                " composition."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "RouteKey",
                ),
                update_schema=(
                    "ChannelProfileId",
                    "RouteKey",
                    "TargetQueueName",
                    "OwnerUserId",
                    "TargetServiceKey",
                    "TargetNamespace",
                    "Priority",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "OrchestrationPolicies",
            "entity": "OrchestrationPolicy",
            "description": (
                "Shared hours/escalation/fallback policy defaults for"
                " channel-agnostic orchestration."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "Code",
                    "Name",
                ),
                update_schema=(
                    "Code",
                    "Name",
                    "HoursMode",
                    "EscalationMode",
                    "FallbackPolicy",
                    "FallbackTarget",
                    "EscalationTarget",
                    "EscalationAfterSeconds",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "ConversationStates",
            "entity": "ConversationState",
            "description": (
                "Operational state snapshots for intake/routing/throttle/fallback"
                " decisions per sender conversation context."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "SenderKey",
                ),
                update_schema=(
                    "ChannelProfileId",
                    "PolicyId",
                    "SenderKey",
                    "ExternalConversationRef",
                    "Status",
                    "RouteKey",
                    "AssignedQueueName",
                    "AssignedOwnerUserId",
                    "AssignedServiceKey",
                    "FallbackMode",
                    "FallbackTarget",
                    "FallbackReason",
                    "IsFallbackActive",
                    "Attributes",
                ),
            ),
            "actions": {
                "evaluate_intake": {
                    "perm": admin_ns.verb("manage"),
                    "schema": EvaluateIntakeValidation,
                    "confirm": "Evaluate intake rules for this conversation?",
                },
                "route": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RouteConversationValidation,
                    "confirm": "Resolve routing for this conversation?",
                },
                "escalate": {
                    "perm": admin_ns.verb("manage"),
                    "schema": EscalateConversationValidation,
                    "confirm": "Escalate this conversation?",
                },
                "apply_throttle": {
                    "perm": admin_ns.verb("manage"),
                    "schema": ApplyThrottleValidation,
                    "confirm": "Apply throttle policy for this conversation?",
                },
                "set_fallback": {
                    "perm": admin_ns.verb("manage"),
                    "schema": SetFallbackValidation,
                    "confirm": "Set fallback mode/target for this conversation?",
                },
            },
        },
        {
            "set": "ThrottleRules",
            "entity": "ThrottleRule",
            "description": (
                "Tenant/channel throttling controls including window limits and"
                " optional auto-block behavior."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "Code",
                ),
                update_schema=(
                    "ChannelProfileId",
                    "Code",
                    "SenderScope",
                    "WindowSeconds",
                    "MaxMessages",
                    "BlockOnViolation",
                    "BlockDurationSeconds",
                    "Priority",
                    "IsActive",
                    "Attributes",
                ),
            ),
        },
        {
            "set": "BlocklistEntries",
            "entity": "BlocklistEntry",
            "description": (
                "Sender-level blocklist entries managed by orchestration and"
                " moderation actions."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "SenderKey",
                ),
                update_schema=(
                    "ChannelProfileId",
                    "SenderKey",
                    "Reason",
                    "ExpiresAt",
                    "IsActive",
                    "Attributes",
                ),
            ),
            "actions": {
                "block_sender": {
                    "perm": admin_ns.verb("manage"),
                    "schema": BlockSenderActionValidation,
                    "confirm": "Block this sender?",
                },
                "unblock_sender": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UnblockSenderActionValidation,
                    "confirm": "Unblock this sender?",
                },
            },
        },
        {
            "set": "OrchestrationEvents",
            "entity": "OrchestrationEvent",
            "description": (
                "Append-only orchestration decision timeline for intake, routing,"
                " throttle, escalation, and fallback outcomes."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "WorkItems",
            "entity": "WorkItem",
            "description": (
                "Canonical intake envelopes used to replay channel payloads into"
                " workflow and SLA execution paths."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=(
                    "TenantId",
                    "TraceId",
                    "Source",
                ),
                update_schema=(
                    "Source",
                    "Participants",
                    "Content",
                    "Attachments",
                    "Signals",
                    "Extractions",
                    "LinkedCaseId",
                    "LinkedWorkflowInstanceId",
                    "Attributes",
                ),
            ),
            "actions": {
                "create_from_channel": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkItemCreateFromChannelValidation,
                    "confirm": "Create a canonical work item from channel payload?",
                },
                "link_to_case": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkItemLinkToCaseValidation,
                    "confirm": "Link this work item to case/workflow records?",
                },
                "replay": {
                    "perm": admin_ns.verb("manage"),
                    "schema": WorkItemReplayValidation,
                    "confirm": "Replay the canonical work item envelope?",
                },
            },
        },
    )

    objects: list[PermissionObjectDef] = []
    for r in resources:
        obj_name = title_to_snake(r["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        objects.append(obj)
        registry.register_permission_object(obj)

    obj_keys = [o.key for o in objects]
    admin_verb_keys = [
        admin_ns.verb(v) for v in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in obj_keys
        for ptyp in admin_verb_keys
    )

    for r in resources:
        entity_set = r["set"]
        entity = r["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"CHANNELORCH.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(r.get("table_name", f"channel_orchestration_{obj_name}"))

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
                    "mugen.core.plugin.channel_orchestration.model."
                    f"{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=(
                    "mugen.core.plugin.channel_orchestration.edm:" f"{obj_name}_type"
                ),
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    "mugen.core.plugin.channel_orchestration.service."
                    f"{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )
