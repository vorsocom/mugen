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
        "ScopeKey": EdmProperty("ScopeKey", TypeRef("Edm.String"), nullable=False),
        "ScopeSeq": EdmProperty("ScopeSeq", TypeRef("Edm.Int64")),
        "PrevEntryHash": EdmProperty("PrevEntryHash", TypeRef("Edm.String")),
        "EntryHash": EdmProperty("EntryHash", TypeRef("Edm.String")),
        "HashAlg": EdmProperty("HashAlg", TypeRef("Edm.String"), nullable=False),
        "HashKeyId": EdmProperty("HashKeyId", TypeRef("Edm.String")),
        "BeforeSnapshotHash": EdmProperty(
            "BeforeSnapshotHash",
            TypeRef("Edm.String"),
        ),
        "AfterSnapshotHash": EdmProperty(
            "AfterSnapshotHash",
            TypeRef("Edm.String"),
        ),
        "SealedAt": EdmProperty("SealedAt", TypeRef("Edm.DateTimeOffset")),
        "RetentionUntil": EdmProperty("RetentionUntil", TypeRef("Edm.DateTimeOffset")),
        "RedactionDueAt": EdmProperty("RedactionDueAt", TypeRef("Edm.DateTimeOffset")),
        "RedactedAt": EdmProperty("RedactedAt", TypeRef("Edm.DateTimeOffset")),
        "RedactionReason": EdmProperty("RedactionReason", TypeRef("Edm.String")),
        "LegalHoldAt": EdmProperty("LegalHoldAt", TypeRef("Edm.DateTimeOffset")),
        "LegalHoldUntil": EdmProperty(
            "LegalHoldUntil",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LegalHoldByUserId": EdmProperty("LegalHoldByUserId", TypeRef("Edm.Guid")),
        "LegalHoldReason": EdmProperty("LegalHoldReason", TypeRef("Edm.String")),
        "LegalHoldReleasedAt": EdmProperty(
            "LegalHoldReleasedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LegalHoldReleasedByUserId": EdmProperty(
            "LegalHoldReleasedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "LegalHoldReleaseReason": EdmProperty(
            "LegalHoldReleaseReason",
            TypeRef("Edm.String"),
        ),
        "TombstonedAt": EdmProperty("TombstonedAt", TypeRef("Edm.DateTimeOffset")),
        "TombstonedByUserId": EdmProperty("TombstonedByUserId", TypeRef("Edm.Guid")),
        "TombstoneReason": EdmProperty("TombstoneReason", TypeRef("Edm.String")),
        "PurgeDueAt": EdmProperty("PurgeDueAt", TypeRef("Edm.DateTimeOffset")),
    },
    key_properties=("Id",),
    entity_set_name="AuditEvents",
)
