"""Provides the audit event EDM type definition."""

__all__ = ["audit_event_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


audit_event_type = EdmType(
    name="AUDIT.AuditEvent",
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
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "ActorId": EdmProperty("ActorId", TypeRef("Edm.Guid")),
        "EntitySet": EdmProperty("EntitySet", TypeRef("Edm.String"), nullable=False),
        "Entity": EdmProperty("Entity", TypeRef("Edm.String"), nullable=False),
        "EntityId": EdmProperty("EntityId", TypeRef("Edm.Guid")),
        "Operation": EdmProperty("Operation", TypeRef("Edm.String"), nullable=False),
        "ActionName": EdmProperty("ActionName", TypeRef("Edm.String")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Outcome": EdmProperty("Outcome", TypeRef("Edm.String"), nullable=False),
        "RequestId": EdmProperty("RequestId", TypeRef("Edm.String")),
        "CorrelationId": EdmProperty("CorrelationId", TypeRef("Edm.String")),
        "SourcePlugin": EdmProperty(
            "SourcePlugin",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "ChangedFields": EdmProperty(
            "ChangedFields",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "BeforeSnapshot": EdmProperty(
            "BeforeSnapshot",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "AfterSnapshot": EdmProperty(
            "AfterSnapshot",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Meta": EdmProperty(
            "Meta",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "RetentionUntil": EdmProperty("RetentionUntil", TypeRef("Edm.DateTimeOffset")),
        "RedactionDueAt": EdmProperty("RedactionDueAt", TypeRef("Edm.DateTimeOffset")),
        "RedactedAt": EdmProperty("RedactedAt", TypeRef("Edm.DateTimeOffset")),
        "RedactionReason": EdmProperty("RedactionReason", TypeRef("Edm.String")),
    },
    key_properties=("Id",),
    entity_set_name="AuditEvents",
)
