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
        "RowVersion": EdmProperty(
            "RowVersion",
            TypeRef("Edm.Int64"),
            nullable=False,
            always_serialize=True,
        ),
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
            filterable=False,
            sortable=False,
            computed=True,
            always_serialize=True,
        ),
    },
    nav_properties={
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
