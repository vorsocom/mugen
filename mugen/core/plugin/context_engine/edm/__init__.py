"""EDM types for ACP-managed context_engine resources."""

__all__ = [
    "context_contributor_binding_type",
    "context_policy_type",
    "context_profile_type",
    "context_source_binding_type",
    "context_trace_policy_type",
]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


def _base_properties() -> dict[str, EdmProperty]:
    return {
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
    }


context_profile_type = EdmType(
    name="CTXENG.ContextProfile",
    kind="entity",
    properties={
        **_base_properties(),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "Platform": EdmProperty("Platform", TypeRef("Edm.String")),
        "ChannelKey": EdmProperty("ChannelKey", TypeRef("Edm.String")),
        "ClientProfileKey": EdmProperty("ClientProfileKey", TypeRef("Edm.String")),
        "PolicyId": EdmProperty("PolicyId", TypeRef("Edm.Guid")),
        "Persona": EdmProperty("Persona", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "IsDefault": EdmProperty("IsDefault", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ContextProfiles",
)

context_policy_type = EdmType(
    name="CTXENG.ContextPolicy",
    kind="entity",
    properties={
        **_base_properties(),
        "PolicyKey": EdmProperty("PolicyKey", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "BudgetJson": EdmProperty("BudgetJson", TypeRef("Edm.String")),
        "RedactionJson": EdmProperty("RedactionJson", TypeRef("Edm.String")),
        "RetentionJson": EdmProperty("RetentionJson", TypeRef("Edm.String")),
        "ContributorAllow": EdmProperty("ContributorAllow", TypeRef("Edm.String")),
        "ContributorDeny": EdmProperty("ContributorDeny", TypeRef("Edm.String")),
        "SourceAllow": EdmProperty("SourceAllow", TypeRef("Edm.String")),
        "SourceDeny": EdmProperty("SourceDeny", TypeRef("Edm.String")),
        "TraceEnabled": EdmProperty(
            "TraceEnabled",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "CacheEnabled": EdmProperty(
            "CacheEnabled",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "IsDefault": EdmProperty("IsDefault", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ContextPolicies",
)

context_contributor_binding_type = EdmType(
    name="CTXENG.ContextContributorBinding",
    kind="entity",
    properties={
        **_base_properties(),
        "BindingKey": EdmProperty("BindingKey", TypeRef("Edm.String"), nullable=False),
        "ContributorKey": EdmProperty(
            "ContributorKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Platform": EdmProperty("Platform", TypeRef("Edm.String")),
        "ChannelKey": EdmProperty("ChannelKey", TypeRef("Edm.String")),
        "Priority": EdmProperty("Priority", TypeRef("Edm.Int64"), nullable=False),
        "IsEnabled": EdmProperty("IsEnabled", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ContextContributorBindings",
)

context_source_binding_type = EdmType(
    name="CTXENG.ContextSourceBinding",
    kind="entity",
    properties={
        **_base_properties(),
        "SourceKind": EdmProperty("SourceKind", TypeRef("Edm.String"), nullable=False),
        "SourceKey": EdmProperty("SourceKey", TypeRef("Edm.String"), nullable=False),
        "Platform": EdmProperty("Platform", TypeRef("Edm.String")),
        "ChannelKey": EdmProperty("ChannelKey", TypeRef("Edm.String")),
        "Locale": EdmProperty("Locale", TypeRef("Edm.String")),
        "Category": EdmProperty("Category", TypeRef("Edm.String")),
        "IsEnabled": EdmProperty("IsEnabled", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ContextSourceBindings",
)

context_trace_policy_type = EdmType(
    name="CTXENG.ContextTracePolicy",
    kind="entity",
    properties={
        **_base_properties(),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "CapturePrepare": EdmProperty(
            "CapturePrepare",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "CaptureCommit": EdmProperty(
            "CaptureCommit",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "CaptureSelectedItems": EdmProperty(
            "CaptureSelectedItems",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "CaptureDroppedItems": EdmProperty(
            "CaptureDroppedItems",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ContextTracePolicies",
)
