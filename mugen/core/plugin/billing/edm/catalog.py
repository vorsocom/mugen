"""Provides EDM types for global billing definitions."""

__all__ = [
    "currency_definition_type",
    "discount_definition_type",
    "invoice_template_type",
    "meter_definition_type",
    "payment_term_type",
    "price_entitlement_type",
    "run_definition_type",
    "tax_code_type",
    "tax_rate_type",
]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)


def _base_properties() -> dict[str, EdmProperty]:
    """Return common global-definition properties."""
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
        "RowVersion": EdmProperty(
            "RowVersion",
            TypeRef("Edm.Int64"),
            nullable=False,
            always_serialize=True,
        ),
    }


def _definition_properties() -> dict[str, EdmProperty]:
    """Return fields shared by named activatable definitions."""
    return {
        **_base_properties(),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "DisplayName": EdmProperty(
            "DisplayName",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    }


meter_definition_type = EdmType(
    name="BILLING.MeterDefinition",
    kind="entity",
    properties={
        **_base_properties(),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Unit": EdmProperty("Unit", TypeRef("Edm.String"), nullable=False),
        "AggregationMode": EdmProperty(
            "AggregationMode",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingMeterDefinitions",
)

price_entitlement_type = EdmType(
    name="BILLING.PriceEntitlement",
    kind="entity",
    properties={
        **_base_properties(),
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid"), nullable=False),
        "MeterDefinitionId": EdmProperty(
            "MeterDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "IncludedQuantity": EdmProperty(
            "IncludedQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "RolloverPolicy": EdmProperty(
            "RolloverPolicy",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DeletedAt": EdmProperty(
            "DeletedAt",
            TypeRef("Edm.DateTimeOffset"),
            always_serialize=True,
        ),
        "DeletedByUserId": EdmProperty("DeletedByUserId", TypeRef("Edm.Guid")),
        "IsArchived": EdmProperty(
            "IsArchived",
            TypeRef("Edm.Boolean"),
            nullable=False,
            computed=True,
            filterable=False,
            sortable=False,
            always_serialize=True,
        ),
    },
    nav_properties={
        "Price": EdmNavigationProperty(
            "Price",
            target_type=TypeRef("BILLING.Price"),
            source_fk="PriceId",
        ),
        "MeterDefinition": EdmNavigationProperty(
            "MeterDefinition",
            target_type=TypeRef("BILLING.MeterDefinition"),
            source_fk="MeterDefinitionId",
        ),
        "DeletedByUser": EdmNavigationProperty(
            "DeletedByUser",
            target_type=TypeRef("ACP.User"),
            source_fk="DeletedByUserId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingPriceEntitlements",
)

run_definition_type = EdmType(
    name="BILLING.RunDefinition",
    kind="entity",
    properties={
        **_definition_properties(),
        "Frequency": EdmProperty(
            "Frequency",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "IntervalCount": EdmProperty(
            "IntervalCount",
            TypeRef("Edm.Int32"),
            nullable=False,
        ),
        "Timezone": EdmProperty(
            "Timezone",
            TypeRef("Edm.String"),
            nullable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingRunDefinitions",
)

currency_definition_type = EdmType(
    name="BILLING.CurrencyDefinition",
    kind="entity",
    properties={
        **_base_properties(),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "NumericCode": EdmProperty(
            "NumericCode",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "DisplayName": EdmProperty(
            "DisplayName",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "MinorUnit": EdmProperty(
            "MinorUnit",
            TypeRef("Edm.Int32"),
        ),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingCurrencyDefinitions",
)

tax_code_type = EdmType(
    name="BILLING.TaxCode",
    kind="entity",
    properties=_definition_properties(),
    key_properties=("Id",),
    entity_set_name="BillingTaxCodes",
)

tax_rate_type = EdmType(
    name="BILLING.TaxRate",
    kind="entity",
    properties={
        **_base_properties(),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "TaxCodeId": EdmProperty(
            "TaxCodeId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "JurisdictionCode": EdmProperty(
            "JurisdictionCode",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "RateBasisPoints": EdmProperty(
            "RateBasisPoints",
            TypeRef("Edm.Int32"),
            nullable=False,
        ),
        "EffectiveFrom": EdmProperty(
            "EffectiveFrom",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "EffectiveTo": EdmProperty("EffectiveTo", TypeRef("Edm.DateTimeOffset")),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "TaxCode": EdmNavigationProperty(
            "TaxCode",
            target_type=TypeRef("BILLING.TaxCode"),
            source_fk="TaxCodeId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingTaxRates",
)

payment_term_type = EdmType(
    name="BILLING.PaymentTerm",
    kind="entity",
    properties={
        **_definition_properties(),
        "DueDays": EdmProperty("DueDays", TypeRef("Edm.Int32"), nullable=False),
    },
    key_properties=("Id",),
    entity_set_name="BillingPaymentTerms",
)

invoice_template_type = EdmType(
    name="BILLING.InvoiceTemplate",
    kind="entity",
    properties={
        **_definition_properties(),
        "Locale": EdmProperty("Locale", TypeRef("Edm.String"), nullable=False),
        "TemplateFormat": EdmProperty(
            "TemplateFormat",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "SubjectTemplate": EdmProperty(
            "SubjectTemplate",
            TypeRef("Edm.String"),
        ),
        "BodyTemplate": EdmProperty(
            "BodyTemplate",
            TypeRef("Edm.String"),
            nullable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingInvoiceTemplates",
)

discount_definition_type = EdmType(
    name="BILLING.DiscountDefinition",
    kind="entity",
    properties={
        **_definition_properties(),
        "Kind": EdmProperty("Kind", TypeRef("Edm.String"), nullable=False),
        "PercentageBasisPoints": EdmProperty(
            "PercentageBasisPoints",
            TypeRef("Edm.Int32"),
        ),
        "Amount": EdmProperty("Amount", TypeRef("Edm.Int64")),
        "CurrencyDefinitionId": EdmProperty(
            "CurrencyDefinitionId",
            TypeRef("Edm.Guid"),
        ),
        "CouponCode": EdmProperty("CouponCode", TypeRef("Edm.String")),
        "ValidFrom": EdmProperty("ValidFrom", TypeRef("Edm.DateTimeOffset")),
        "ValidUntil": EdmProperty("ValidUntil", TypeRef("Edm.DateTimeOffset")),
    },
    nav_properties={
        "CurrencyDefinition": EdmNavigationProperty(
            "CurrencyDefinition",
            target_type=TypeRef("BILLING.CurrencyDefinition"),
            source_fk="CurrencyDefinitionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingDiscountDefinitions",
)
