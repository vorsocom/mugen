"""Provides the entitlement-adjustment EDM type."""

__all__ = ["entitlement_adjustment_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

entitlement_adjustment_type = EdmType(
    name="BILLING.EntitlementAdjustment",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "BucketId": EdmProperty("BucketId", TypeRef("Edm.Guid"), nullable=False),
        "AccountId": EdmProperty("AccountId", TypeRef("Edm.Guid"), nullable=False),
        "SubscriptionId": EdmProperty("SubscriptionId", TypeRef("Edm.Guid")),
        "QuantityDelta": EdmProperty(
            "QuantityDelta", TypeRef("Edm.Int64"), nullable=False
        ),
        "AdjustmentBefore": EdmProperty(
            "AdjustmentBefore", TypeRef("Edm.Int64"), nullable=False
        ),
        "AdjustmentAfter": EdmProperty(
            "AdjustmentAfter", TypeRef("Edm.Int64"), nullable=False
        ),
        "CapacityAfter": EdmProperty(
            "CapacityAfter", TypeRef("Edm.Int64"), nullable=False
        ),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String"), nullable=False),
        "IdempotencyKey": EdmProperty(
            "IdempotencyKey", TypeRef("Edm.String"), nullable=False
        ),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "Bucket": EdmNavigationProperty(
            "Bucket",
            target_type=TypeRef("BILLING.EntitlementBucket"),
            source_fk="BucketId",
        ),
        "ActorUser": EdmNavigationProperty(
            "ActorUser",
            target_type=TypeRef("ACP.User"),
            source_fk="ActorUserId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingEntitlementAdjustments",
)
