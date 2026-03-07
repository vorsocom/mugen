"""Provides the channel profile EDM type definition."""

__all__ = ["channel_profile_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


channel_profile_type = EdmType(
    name="CHANNELORCH.ChannelProfile",
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
        "ChannelKey": EdmProperty("ChannelKey", TypeRef("Edm.String"), nullable=False),
        "ProfileKey": EdmProperty("ProfileKey", TypeRef("Edm.String"), nullable=False),
        "RuntimeProfileKey": EdmProperty(
            "RuntimeProfileKey",
            TypeRef("Edm.String"),
        ),
        "DisplayName": EdmProperty("DisplayName", TypeRef("Edm.String")),
        "RouteDefaultKey": EdmProperty("RouteDefaultKey", TypeRef("Edm.String")),
        "PolicyId": EdmProperty("PolicyId", TypeRef("Edm.Guid")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ChannelProfiles",
)
