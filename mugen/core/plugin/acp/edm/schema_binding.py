"""Provides an EdmType for the SchemaBinding declarative model."""

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

schema_binding_type = EdmType(
    name="ACP.SchemaBinding",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "SchemaDefinitionId": EdmProperty(
            "SchemaDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "TargetNamespace": EdmProperty(
            "TargetNamespace",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "TargetEntitySet": EdmProperty(
            "TargetEntitySet",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "TargetAction": EdmProperty("TargetAction", TypeRef("Edm.String")),
        "BindingKind": EdmProperty(
            "BindingKind",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "IsRequired": EdmProperty(
            "IsRequired",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
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
    entity_set_name="SchemaBindings",
)
