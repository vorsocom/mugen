"""Provides an EdmType for the SchemaDefinition declarative model."""

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

schema_definition_type = EdmType(
    name="ACP.SchemaDefinition",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "Key": EdmProperty("Key", TypeRef("Edm.String"), nullable=False),
        "Version": EdmProperty("Version", TypeRef("Edm.Int32"), nullable=False),
        "Title": EdmProperty("Title", TypeRef("Edm.String")),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "SchemaKind": EdmProperty(
            "SchemaKind",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "SchemaJson": EdmProperty(
            "SchemaJson",
            TypeRef("Edm.String"),
            nullable=False,
            filterable=False,
            sortable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "ActivatedAt": EdmProperty("ActivatedAt", TypeRef("Edm.DateTimeOffset")),
        "ActivatedByUserId": EdmProperty("ActivatedByUserId", TypeRef("Edm.Guid")),
        "ChecksumSha256": EdmProperty(
            "ChecksumSha256",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="Schemas",
)
