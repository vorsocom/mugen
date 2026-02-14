"""Provides the case assignment EDM type definition."""

__all__ = ["case_assignment_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

case_assignment_type = EdmType(
    name="OPSCASE.CaseAssignment",
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
        "OwnerUserId": EdmProperty("OwnerUserId", TypeRef("Edm.Guid")),
        "QueueName": EdmProperty("QueueName", TypeRef("Edm.String")),
        "AssignedByUserId": EdmProperty("AssignedByUserId", TypeRef("Edm.Guid")),
        "AssignedAt": EdmProperty(
            "AssignedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "UnassignedAt": EdmProperty("UnassignedAt", TypeRef("Edm.DateTimeOffset")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "Case": EdmNavigationProperty(
            "Case",
            target_type=TypeRef("OPSCASE.Case"),
            source_fk="CaseId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsCaseAssignments",
)

