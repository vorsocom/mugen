"""Validation schemas used by context_engine ACP CRUD resources."""

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation,
    build_update_validation,
)

__all__ = [
    "ContextContributorBindingCreateValidation",
    "ContextContributorBindingUpdateValidation",
    "ContextPolicyCreateValidation",
    "ContextPolicyUpdateValidation",
    "ContextProfileCreateValidation",
    "ContextProfileUpdateValidation",
    "ContextSourceBindingCreateValidation",
    "ContextSourceBindingUpdateValidation",
    "ContextTracePolicyCreateValidation",
    "ContextTracePolicyUpdateValidation",
]


ContextProfileCreateValidation = build_create_validation(
    "ContextProfileCreateValidation",
    module=__name__,
    doc="Validate create payloads for ContextProfile.",
    required_uuid=("tenant_id",),
    required_text=("name",),
    optional_text=(
        "description",
        "platform",
        "channel_key",
        "service_route_key",
        "client_profile_key",
        "persona",
    ),
    optional_uuid=("policy_id",),
    optional_bool=("is_active", "is_default"),
    optional_any=("attributes",),
)

ContextProfileUpdateValidation = build_update_validation(
    "ContextProfileUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ContextProfile.",
    optional_text=(
        "description",
        "platform",
        "channel_key",
        "service_route_key",
        "client_profile_key",
        "persona",
    ),
    optional_uuid=("policy_id",),
    optional_bool=("is_active", "is_default"),
    optional_any=("attributes",),
)

ContextPolicyCreateValidation = build_create_validation(
    "ContextPolicyCreateValidation",
    module=__name__,
    doc="Validate create payloads for ContextPolicy.",
    required_uuid=("tenant_id",),
    required_text=("policy_key",),
)

ContextPolicyUpdateValidation = build_update_validation(
    "ContextPolicyUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ContextPolicy.",
    optional_text=("description",),
    optional_bool=("trace_enabled", "cache_enabled", "is_active", "is_default"),
    optional_any=(
        "budget_json",
        "redaction_json",
        "retention_json",
        "contributor_allow",
        "contributor_deny",
        "source_allow",
        "source_deny",
        "attributes",
    ),
)

ContextContributorBindingCreateValidation = build_create_validation(
    "ContextContributorBindingCreateValidation",
    module=__name__,
    doc="Validate create payloads for ContextContributorBinding.",
    required_uuid=("tenant_id",),
    required_text=("binding_key", "contributor_key"),
    optional_text=("platform", "channel_key", "service_route_key"),
    optional_bool=("is_enabled",),
    optional_any=("priority", "attributes"),
)

ContextContributorBindingUpdateValidation = build_update_validation(
    "ContextContributorBindingUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ContextContributorBinding.",
    optional_text=("platform", "channel_key", "service_route_key"),
    optional_bool=("is_enabled",),
    optional_any=("priority", "attributes"),
)

ContextSourceBindingCreateValidation = build_create_validation(
    "ContextSourceBindingCreateValidation",
    module=__name__,
    doc="Validate create payloads for ContextSourceBinding.",
    required_uuid=("tenant_id",),
    required_text=("source_kind", "source_key"),
    optional_text=(
        "platform",
        "channel_key",
        "service_route_key",
        "locale",
        "category",
    ),
    optional_bool=("is_enabled",),
    optional_any=("attributes",),
)

ContextSourceBindingUpdateValidation = build_update_validation(
    "ContextSourceBindingUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ContextSourceBinding.",
    optional_text=(
        "platform",
        "channel_key",
        "service_route_key",
        "locale",
        "category",
    ),
    optional_bool=("is_enabled",),
    optional_any=("attributes",),
)

ContextTracePolicyCreateValidation = build_create_validation(
    "ContextTracePolicyCreateValidation",
    module=__name__,
    doc="Validate create payloads for ContextTracePolicy.",
    required_uuid=("tenant_id",),
    required_text=("name",),
)

ContextTracePolicyUpdateValidation = build_update_validation(
    "ContextTracePolicyUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ContextTracePolicy.",
    optional_bool=(
        "capture_prepare",
        "capture_commit",
        "capture_selected_items",
        "capture_dropped_items",
        "is_active",
    ),
    optional_any=("attributes",),
)
