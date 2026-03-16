"""Provides the vendor category EDM type definition."""

__all__ = ["vendor_category_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_category_type = EdmType(
    name="OPSVPN.VendorCategory",
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
        "VendorId": EdmProperty("VendorId", TypeRef("Edm.Guid"), nullable=False),
        "CategoryCode": EdmProperty(
            "CategoryCode", TypeRef("Edm.String"), nullable=False
        ),
        "DisplayName": EdmProperty("DisplayName", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "Vendor": EdmNavigationProperty(
            "Vendor",
            target_type=TypeRef("OPSVPN.Vendor"),
            source_fk="VendorId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVendorCategories",
)
