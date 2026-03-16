"""Provides the product EDM type definition."""

__all__ = ["product_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

product_type = EdmType(
    name="BILLING.Product",
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
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty(
            "Description",
            TypeRef("Edm.String"),
            sortable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DeletedAt": EdmProperty("DeletedAt", TypeRef("Edm.DateTimeOffset")),
        "DeletedByUserId": EdmProperty("DeletedByUserId", TypeRef("Edm.Guid")),
    },
    nav_properties={
        "Tenant": EdmNavigationProperty(
            "Tenant",
            target_type=TypeRef("ACP.Tenant"),
            source_fk="TenantId",
        ),
        "DeletedByUser": EdmNavigationProperty(
            "DeletedByUser",
            target_type=TypeRef("ACP.User"),
            source_fk="DeletedByUserId",
        ),
        "Prices": EdmNavigationProperty(
            "Prices",
            target_type=TypeRef("BILLING.Price", is_collection=True),
            target_fk="ProductId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingProducts",
)
