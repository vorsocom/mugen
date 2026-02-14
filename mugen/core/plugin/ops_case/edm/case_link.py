"""Provides the case link EDM type definition."""

__all__ = ["case_link_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

case_link_type = EdmType(
    name="OPSCASE.CaseLink",
    kind="entity",
    properties={
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
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "CaseId": EdmProperty("CaseId", TypeRef("Edm.Guid"), nullable=False),
        "LinkType": EdmProperty("LinkType", TypeRef("Edm.String"), nullable=False),
        "TargetNamespace": EdmProperty("TargetNamespace", TypeRef("Edm.String")),
        "TargetType": EdmProperty("TargetType", TypeRef("Edm.String"), nullable=False),
        "TargetId": EdmProperty("TargetId", TypeRef("Edm.Guid")),
        "TargetRef": EdmProperty("TargetRef", TypeRef("Edm.String")),
        "TargetDisplay": EdmProperty("TargetDisplay", TypeRef("Edm.String")),
        "RelationshipKind": EdmProperty(
            "RelationshipKind",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "CreatedByUserId": EdmProperty("CreatedByUserId", TypeRef("Edm.Guid")),
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
        "Case": EdmNavigationProperty(
            "Case",
            target_type=TypeRef("OPSCASE.Case"),
            source_fk="CaseId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsCaseLinks",
)

