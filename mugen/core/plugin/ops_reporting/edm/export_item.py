"""Provides the export item EDM type definition."""

__all__ = ["export_item_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

export_item_type = EdmType(
    name="OPSREPORTING.ExportItem",
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
        "ExportJobId": EdmProperty("ExportJobId", TypeRef("Edm.Guid"), nullable=False),
        "ItemIndex": EdmProperty("ItemIndex", TypeRef("Edm.Int64"), nullable=False),
        "ResourceType": EdmProperty(
            "ResourceType", TypeRef("Edm.String"), nullable=False
        ),
        "ResourceId": EdmProperty("ResourceId", TypeRef("Edm.Guid"), nullable=False),
        "ContentHash": EdmProperty(
            "ContentHash", TypeRef("Edm.String"), nullable=False
        ),
        "ContentJson": EdmProperty(
            "ContentJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "MetaJson": EdmProperty(
            "MetaJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsReportingExportItems",
)
