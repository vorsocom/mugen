"""Provides an EdmType for the TenantDomain declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

tenant_domain_type = EdmType(
    name="ACP.TenantDomain",
    kind="entity",
    properties={
        # ModelBase.
        "Id": EdmProperty(
            "Id",
            TypeRef("Edm.Guid"),
        ),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "RowVersion": EdmProperty(
            "RowVersion",
            TypeRef("Edm.Int64"),
        ),
        # TenantScopedMixin.
        "TenantId": EdmProperty(
            "TenantId",
            TypeRef("Edm.Guid"),
        ),
        # TenantDomain.
        "Domain": EdmProperty(
            "Domain",
            TypeRef("Edm.String"),
        ),
        "VerifiedAt": EdmProperty(
            "VerifiedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "IsPrimary": EdmProperty(
            "IsPrimary",
            TypeRef("Edm.Boolean"),
        ),
    },
    nav_properties={
        "Tenant": EdmNavigationProperty(
            "Tenant",
            target_type=TypeRef(
                "ACP.Tenant",
                is_collection=False,
            ),
            source_fk="TenantId",
        ),
    },
    key_properties=("TenantId", "Id"),
    entity_set_name="TenantDomains",
)
