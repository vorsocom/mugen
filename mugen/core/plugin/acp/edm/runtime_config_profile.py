"""Provides an EdmType for the RuntimeConfigProfile declarative model."""

__all__ = ["runtime_config_profile_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

runtime_config_profile_type = EdmType(
    name="ACP.RuntimeConfigProfile",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "Category": EdmProperty("Category", TypeRef("Edm.String"), nullable=False),
        "ProfileKey": EdmProperty(
            "ProfileKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "DisplayName": EdmProperty("DisplayName", TypeRef("Edm.String")),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "SettingsJson": EdmProperty(
            "SettingsJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="RuntimeConfigProfiles",
)
