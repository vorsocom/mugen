"""Provides the export job EDM type definition."""

__all__ = ["export_job_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

export_job_type = EdmType(
    name="OPSREPORTING.ExportJob",
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
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "ExportType": EdmProperty("ExportType", TypeRef("Edm.String"), nullable=False),
        "SpecJson": EdmProperty(
            "SpecJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DefaultSign": EdmProperty(
            "DefaultSign",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "DefaultSignatureKeyId": EdmProperty(
            "DefaultSignatureKeyId",
            TypeRef("Edm.String"),
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "ManifestJson": EdmProperty(
            "ManifestJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ManifestHash": EdmProperty("ManifestHash", TypeRef("Edm.String")),
        "SignatureJson": EdmProperty(
            "SignatureJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ExportRef": EdmProperty("ExportRef", TypeRef("Edm.String")),
        "PolicyDecisionJson": EdmProperty(
            "PolicyDecisionJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ErrorMessage": EdmProperty("ErrorMessage", TypeRef("Edm.String")),
        "CreatedByUserId": EdmProperty("CreatedByUserId", TypeRef("Edm.Guid")),
        "CompletedAt": EdmProperty("CompletedAt", TypeRef("Edm.DateTimeOffset")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsReportingExportJobs",
)
