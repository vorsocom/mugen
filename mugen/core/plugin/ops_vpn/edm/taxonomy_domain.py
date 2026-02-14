"""Provides the taxonomy domain EDM type definition."""

__all__ = ["taxonomy_domain_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

taxonomy_domain_type = EdmType(
    name="OPSVPN.TaxonomyDomain",
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
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "TaxonomyCategories": EdmNavigationProperty(
            "TaxonomyCategories",
            target_type=TypeRef("OPSVPN.TaxonomyCategory", is_collection=True),
            target_fk="TaxonomyDomainId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnTaxonomyDomains",
)
