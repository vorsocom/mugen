"""Provides the EvidenceBlob EDM type definition."""

__all__ = ["evidence_blob_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

evidence_blob_type = EdmType(
    name="AUDIT.EvidenceBlob",
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
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "SourcePlugin": EdmProperty("SourcePlugin", TypeRef("Edm.String")),
        "SubjectNamespace": EdmProperty("SubjectNamespace", TypeRef("Edm.String")),
        "SubjectId": EdmProperty("SubjectId", TypeRef("Edm.Guid")),
        "StorageUri": EdmProperty("StorageUri", TypeRef("Edm.String"), nullable=False),
        "ContentHash": EdmProperty(
            "ContentHash", TypeRef("Edm.String"), nullable=False
        ),
        "HashAlg": EdmProperty("HashAlg", TypeRef("Edm.String"), nullable=False),
        "ContentLength": EdmProperty("ContentLength", TypeRef("Edm.Int64")),
        "Immutability": EdmProperty(
            "Immutability",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "VerificationStatus": EdmProperty(
            "VerificationStatus",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "VerifiedAt": EdmProperty("VerifiedAt", TypeRef("Edm.DateTimeOffset")),
        "VerifiedByUserId": EdmProperty("VerifiedByUserId", TypeRef("Edm.Guid")),
        "RetentionUntil": EdmProperty("RetentionUntil", TypeRef("Edm.DateTimeOffset")),
        "RedactionDueAt": EdmProperty("RedactionDueAt", TypeRef("Edm.DateTimeOffset")),
        "RedactedAt": EdmProperty("RedactedAt", TypeRef("Edm.DateTimeOffset")),
        "RedactionReason": EdmProperty("RedactionReason", TypeRef("Edm.String")),
        "LegalHoldAt": EdmProperty("LegalHoldAt", TypeRef("Edm.DateTimeOffset")),
        "LegalHoldUntil": EdmProperty("LegalHoldUntil", TypeRef("Edm.DateTimeOffset")),
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
        "PurgedAt": EdmProperty("PurgedAt", TypeRef("Edm.DateTimeOffset")),
        "PurgedByUserId": EdmProperty("PurgedByUserId", TypeRef("Edm.Guid")),
        "PurgeReason": EdmProperty("PurgeReason", TypeRef("Edm.String")),
        "Meta": EdmProperty(
            "Meta",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="EvidenceBlobs",
)
