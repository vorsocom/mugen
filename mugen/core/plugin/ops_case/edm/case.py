"""Provides the case EDM type definition."""

__all__ = ["case_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

case_type = EdmType(
    name="OPSCASE.Case",
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
        "CaseNumber": EdmProperty("CaseNumber", TypeRef("Edm.String"), nullable=False),
        "Title": EdmProperty("Title", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "Priority": EdmProperty("Priority", TypeRef("Edm.String"), nullable=False),
        "Severity": EdmProperty("Severity", TypeRef("Edm.String"), nullable=False),
        "DueAt": EdmProperty("DueAt", TypeRef("Edm.DateTimeOffset")),
        "SlaTargetAt": EdmProperty("SlaTargetAt", TypeRef("Edm.DateTimeOffset")),
        "TriagedAt": EdmProperty("TriagedAt", TypeRef("Edm.DateTimeOffset")),
        "EscalatedAt": EdmProperty("EscalatedAt", TypeRef("Edm.DateTimeOffset")),
        "ResolvedAt": EdmProperty("ResolvedAt", TypeRef("Edm.DateTimeOffset")),
        "ClosedAt": EdmProperty("ClosedAt", TypeRef("Edm.DateTimeOffset")),
        "CancelledAt": EdmProperty("CancelledAt", TypeRef("Edm.DateTimeOffset")),
        "OwnerUserId": EdmProperty("OwnerUserId", TypeRef("Edm.Guid")),
        "QueueName": EdmProperty("QueueName", TypeRef("Edm.String")),
        "EscalationLevel": EdmProperty(
            "EscalationLevel",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "IsEscalated": EdmProperty("IsEscalated", TypeRef("Edm.Boolean")),
        "EscalatedByUserId": EdmProperty("EscalatedByUserId", TypeRef("Edm.Guid")),
        "CreatedByUserId": EdmProperty("CreatedByUserId", TypeRef("Edm.Guid")),
        "LastActorUserId": EdmProperty("LastActorUserId", TypeRef("Edm.Guid")),
        "ResolutionSummary": EdmProperty("ResolutionSummary", TypeRef("Edm.String")),
        "CancellationReason": EdmProperty("CancellationReason", TypeRef("Edm.String")),
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
        "CaseEvents": EdmNavigationProperty(
            "CaseEvents",
            target_type=TypeRef("OPSCASE.CaseEvent", is_collection=True),
            target_fk="CaseId",
        ),
        "CaseAssignments": EdmNavigationProperty(
            "CaseAssignments",
            target_type=TypeRef("OPSCASE.CaseAssignment", is_collection=True),
            target_fk="CaseId",
        ),
        "CaseLinks": EdmNavigationProperty(
            "CaseLinks",
            target_type=TypeRef("OPSCASE.CaseLink", is_collection=True),
            target_fk="CaseId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsCases",
)
