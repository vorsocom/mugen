"""Provides the taxonomy category EDM type definition."""

__all__ = ["taxonomy_category_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

taxonomy_category_type = EdmType(
    name="OPSVPN.TaxonomyCategory",
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
        "TaxonomyDomainId": EdmProperty(
            "TaxonomyDomainId", TypeRef("Edm.Guid"), nullable=False
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
        "TaxonomyDomain": EdmNavigationProperty(
            "TaxonomyDomain",
            target_type=TypeRef("OPSVPN.TaxonomyDomain"),
            source_fk="TaxonomyDomainId",
        ),
        "TaxonomySubcategories": EdmNavigationProperty(
            "TaxonomySubcategories",
            target_type=TypeRef("OPSVPN.TaxonomySubcategory", is_collection=True),
            target_fk="TaxonomyCategoryId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnTaxonomyCategories",
)
