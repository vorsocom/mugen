"""Provides the taxonomy subcategory EDM type definition."""

__all__ = ["taxonomy_subcategory_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

taxonomy_subcategory_type = EdmType(
    name="OPSVPN.TaxonomySubcategory",
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
        "TaxonomyCategoryId": EdmProperty(
            "TaxonomyCategoryId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "TaxonomyCategory": EdmNavigationProperty(
            "TaxonomyCategory",
            target_type=TypeRef("OPSVPN.TaxonomyCategory"),
            source_fk="TaxonomyCategoryId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnTaxonomySubcategories",
)
