"""Provides the usage session EDM type definition."""

__all__ = ["usage_session_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

usage_session_type = EdmType(
    name="OPSMETERING.UsageSession",
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
        "MeterDefinitionId": EdmProperty(
            "MeterDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "MeterPolicyId": EdmProperty("MeterPolicyId", TypeRef("Edm.Guid")),
        "UsageRecordId": EdmProperty("UsageRecordId", TypeRef("Edm.Guid")),
        "TrackedNamespace": EdmProperty(
            "TrackedNamespace",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "TrackedId": EdmProperty("TrackedId", TypeRef("Edm.Guid")),
        "TrackedRef": EdmProperty("TrackedRef", TypeRef("Edm.String")),
        "AccountId": EdmProperty("AccountId", TypeRef("Edm.Guid")),
        "SubscriptionId": EdmProperty("SubscriptionId", TypeRef("Edm.Guid")),
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "StartedAt": EdmProperty("StartedAt", TypeRef("Edm.DateTimeOffset")),
        "LastStartedAt": EdmProperty(
            "LastStartedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "PausedAt": EdmProperty("PausedAt", TypeRef("Edm.DateTimeOffset")),
        "StoppedAt": EdmProperty("StoppedAt", TypeRef("Edm.DateTimeOffset")),
        "ElapsedSeconds": EdmProperty(
            "ElapsedSeconds",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "IdempotencyKey": EdmProperty("IdempotencyKey", TypeRef("Edm.String")),
        "LastActorUserId": EdmProperty("LastActorUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsUsageSessions",
)
