"""Provides the retention class EDM type definition."""

__all__ = ["retention_class_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

retention_class_type = EdmType(
    name="OPSGOVERNANCE.RetentionClass",
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
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "ResourceType": EdmProperty(
            "ResourceType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "RetentionDays": EdmProperty(
            "RetentionDays",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "RedactionAfterDays": EdmProperty(
            "RedactionAfterDays",
            TypeRef("Edm.Int64"),
        ),
        "PurgeGraceDays": EdmProperty(
            "PurgeGraceDays",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "LegalHoldAllowed": EdmProperty(
            "LegalHoldAllowed",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsRetentionClasses",
)
