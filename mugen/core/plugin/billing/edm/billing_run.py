"""Provides the billing run EDM type definition."""

__all__ = ["billing_run_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

billing_run_type = EdmType(
    name="BILLING.BillingRun",
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
        "AccountId": EdmProperty("AccountId", TypeRef("Edm.Guid")),
        "SubscriptionId": EdmProperty("SubscriptionId", TypeRef("Edm.Guid")),
        "DefinitionId": EdmProperty(
            "DefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "RetryOfRunId": EdmProperty("RetryOfRunId", TypeRef("Edm.Guid")),
        "AttemptNumber": EdmProperty(
            "AttemptNumber",
            TypeRef("Edm.Int32"),
            nullable=False,
        ),
        "PeriodStart": EdmProperty(
            "PeriodStart",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "PeriodEnd": EdmProperty(
            "PeriodEnd",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "IdempotencyKey": EdmProperty(
            "IdempotencyKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "StartedAt": EdmProperty("StartedAt", TypeRef("Edm.DateTimeOffset")),
        "CompletedAt": EdmProperty("CompletedAt", TypeRef("Edm.DateTimeOffset")),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "FailureCode": EdmProperty("FailureCode", TypeRef("Edm.String")),
        "FailureDetail": EdmProperty("FailureDetail", TypeRef("Edm.String")),
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
        "Account": EdmNavigationProperty(
            "Account",
            target_type=TypeRef("BILLING.Account"),
            source_fk="AccountId",
        ),
        "Subscription": EdmNavigationProperty(
            "Subscription",
            target_type=TypeRef("BILLING.Subscription"),
            source_fk="SubscriptionId",
        ),
        "Definition": EdmNavigationProperty(
            "Definition",
            target_type=TypeRef("BILLING.RunDefinition"),
            source_fk="DefinitionId",
        ),
        "RetryOfRun": EdmNavigationProperty(
            "RetryOfRun",
            target_type=TypeRef("BILLING.BillingRun"),
            source_fk="RetryOfRunId",
        ),
        "Invoices": EdmNavigationProperty(
            "Invoices",
            target_type=TypeRef("BILLING.Invoice", is_collection=True),
            target_fk="BillingRunId",
        ),
        "EntitlementBuckets": EdmNavigationProperty(
            "EntitlementBuckets",
            target_type=TypeRef("BILLING.EntitlementBucket", is_collection=True),
            target_fk="BillingRunId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingRuns",
)
