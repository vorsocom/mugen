"""Provides the lifecycle action log EDM type definition."""

__all__ = ["lifecycle_action_log_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

lifecycle_action_log_type = EdmType(
    name="OPSGOVERNANCE.LifecycleActionLog",
    kind="entity",
    properties={
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
        "ResourceType": EdmProperty(
            "ResourceType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "ResourceId": EdmProperty("ResourceId", TypeRef("Edm.Guid"), nullable=False),
        "ActionType": EdmProperty("ActionType", TypeRef("Edm.String"), nullable=False),
        "Outcome": EdmProperty("Outcome", TypeRef("Edm.String"), nullable=False),
        "DryRun": EdmProperty("DryRun", TypeRef("Edm.Boolean"), nullable=False),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "CorrelationId": EdmProperty("CorrelationId", TypeRef("Edm.String")),
        "Details": EdmProperty(
            "Details",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsLifecycleActionLogs",
)
