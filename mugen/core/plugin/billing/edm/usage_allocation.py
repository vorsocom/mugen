"""Provides the usage allocation EDM type definition."""

__all__ = ["usage_allocation_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

usage_allocation_type = EdmType(
    name="BILLING.UsageAllocation",
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
        "UsageEventId": EdmProperty(
            "UsageEventId", TypeRef("Edm.Guid"), nullable=False
        ),
        "EntitlementBucketId": EdmProperty(
            "EntitlementBucketId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "AllocatedQuantity": EdmProperty(
            "AllocatedQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "Tenant": EdmNavigationProperty(
            "Tenant",
            target_type=TypeRef("ACP.Tenant"),
            source_fk="TenantId",
        ),
        "UsageEvent": EdmNavigationProperty(
            "UsageEvent",
            target_type=TypeRef("BILLING.UsageEvent"),
            source_fk="UsageEventId",
        ),
        "EntitlementBucket": EdmNavigationProperty(
            "EntitlementBucket",
            target_type=TypeRef("BILLING.EntitlementBucket"),
            source_fk="EntitlementBucketId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingUsageAllocations",
)
