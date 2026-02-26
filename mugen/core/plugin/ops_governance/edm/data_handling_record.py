"""Provides the data handling record EDM type definition."""

__all__ = ["data_handling_record_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

data_handling_record_type = EdmType(
    name="OPSGOVERNANCE.DataHandlingRecord",
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
        "RetentionPolicyId": EdmProperty("RetentionPolicyId", TypeRef("Edm.Guid")),
        "SubjectNamespace": EdmProperty(
            "SubjectNamespace",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "SubjectId": EdmProperty("SubjectId", TypeRef("Edm.Guid")),
        "SubjectRef": EdmProperty("SubjectRef", TypeRef("Edm.String")),
        "RequestType": EdmProperty(
            "RequestType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "RequestStatus": EdmProperty(
            "RequestStatus",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "RequestedAt": EdmProperty(
            "RequestedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "DueAt": EdmProperty("DueAt", TypeRef("Edm.DateTimeOffset")),
        "CompletedAt": EdmProperty("CompletedAt", TypeRef("Edm.DateTimeOffset")),
        "ResolutionNote": EdmProperty("ResolutionNote", TypeRef("Edm.String")),
        "HandledByUserId": EdmProperty("HandledByUserId", TypeRef("Edm.Guid")),
        "EvidenceRef": EdmProperty("EvidenceRef", TypeRef("Edm.String")),
        "EvidenceBlobId": EdmProperty("EvidenceBlobId", TypeRef("Edm.Guid")),
        "Meta": EdmProperty(
            "Meta",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsDataHandlingRecords",
)
