"""ACP contribution entrypoint for the context_engine plugin."""

from __future__ import annotations

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
from mugen.core.utility.string.case_conversion_helper import title_to_snake


def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute context_engine ACP resources."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Context engine plugin installed.",
            is_set=True,
        )
    )

    resources = (
        {
            "set": "ContextProfiles",
            "entity": "ContextProfile",
            "description": "Tenant-scoped context profiles for scope-based policy selection.",
            "create_schema": ("TenantId", "Name"),
            "update_schema": (
                "Description",
                "Platform",
                "ChannelKey",
                "PolicyId",
                "IsActive",
                "IsDefault",
                "Attributes",
            ),
            "edm_symbol": "context_profile_type",
            "service_cls": "ContextProfileService",
        },
        {
            "set": "ContextPolicies",
            "entity": "ContextPolicy",
            "description": "Context budget/redaction/retention policy rows.",
            "create_schema": ("TenantId", "PolicyKey"),
            "update_schema": (
                "Description",
                "BudgetJson",
                "RedactionJson",
                "RetentionJson",
                "ContributorAllow",
                "ContributorDeny",
                "SourceAllow",
                "SourceDeny",
                "TraceEnabled",
                "CacheEnabled",
                "IsActive",
                "IsDefault",
                "Attributes",
            ),
            "edm_symbol": "context_policy_type",
            "service_cls": "ContextPolicyService",
        },
        {
            "set": "ContextContributorBindings",
            "entity": "ContextContributorBinding",
            "description": "Contributor activation and priority bindings.",
            "create_schema": ("TenantId", "BindingKey", "ContributorKey"),
            "update_schema": (
                "Platform",
                "ChannelKey",
                "Priority",
                "IsEnabled",
                "Attributes",
            ),
            "edm_symbol": "context_contributor_binding_type",
            "service_cls": "ContextContributorBindingService",
        },
        {
            "set": "ContextSourceBindings",
            "entity": "ContextSourceBinding",
            "description": "Source selection overlays for contributor filtering.",
            "create_schema": ("TenantId", "SourceKind", "SourceKey"),
            "update_schema": (
                "Platform",
                "ChannelKey",
                "Locale",
                "Category",
                "IsEnabled",
                "Attributes",
            ),
            "edm_symbol": "context_source_binding_type",
            "service_cls": "ContextSourceBindingService",
        },
        {
            "set": "ContextTracePolicies",
            "entity": "ContextTracePolicy",
            "description": "Trace capture policies for prepare/commit provenance records.",
            "create_schema": ("TenantId", "Name"),
            "update_schema": (
                "CapturePrepare",
                "CaptureCommit",
                "CaptureSelectedItems",
                "CaptureDroppedItems",
                "IsActive",
                "Attributes",
            ),
            "edm_symbol": "context_trace_policy_type",
            "service_cls": "ContextTracePolicyService",
        },
    )

    admin_verb_keys = [
        admin_ns.verb(verb) for verb in ("read", "create", "update", "delete", "manage")
    ]

    for resource in resources:
        entity = str(resource["entity"])
        entity_set = str(resource["set"])
        obj_name = title_to_snake(entity)
        permission_object = PermissionObjectDef(plugin_ns.ns, obj_name)
        registry.register_permission_object(permission_object)
        registry.register_default_global_grants(
            DefaultGlobalGrant(admin_ns.key("administrator"), permission_object.key, ptyp, True)
            for ptyp in admin_verb_keys
        )

        edm_type_name = f"CTXENG.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = f"context_engine_{obj_name}"
        if obj_name == "context_contributor_binding":
            table_name = "context_engine_context_contributor_binding"
        if obj_name == "context_source_binding":
            table_name = "context_engine_context_source_binding"
        if obj_name == "context_trace_policy":
            table_name = "context_engine_context_trace_policy"

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
                    allow_manage=False,
                ),
                behavior=AdminBehavior(rgql_enabled=True),
                crud=CrudPolicy(
                    create_schema=resource["create_schema"],
                    update_schema=resource["update_schema"],
                ),
                title=entity_set,
                description=str(resource["description"]),
            )
        )
        registry.register_table_spec(
            TableSpec(
                table_name=table_name,
                table_provider=f"mugen.core.plugin.context_engine.model:{entity}",
            )
        )
        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=(
                    f"mugen.core.plugin.context_engine.edm:{resource['edm_symbol']}"
                ),
            )
        )
        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    "mugen.core.plugin.context_engine.service:"
                    f"{resource['service_cls']}"
                ),
                init_kwargs={"table": table_name},
            )
        )
