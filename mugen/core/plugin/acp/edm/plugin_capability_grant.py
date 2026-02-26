"""Provides an EdmType for PluginCapabilityGrant declarative records."""

__all__ = ["plugin_capability_grant_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

plugin_capability_grant_type = EdmType(
    name="ACP.PluginCapabilityGrant",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "PluginKey": EdmProperty(
            "PluginKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Capabilities": EdmProperty(
            "Capabilities",
            TypeRef("Edm.String"),
            nullable=False,
            filterable=False,
            sortable=False,
        ),
        "GrantedAt": EdmProperty(
            "GrantedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "GrantedByUserId": EdmProperty("GrantedByUserId", TypeRef("Edm.Guid")),
        "ExpiresAt": EdmProperty("ExpiresAt", TypeRef("Edm.DateTimeOffset")),
        "RevokedAt": EdmProperty("RevokedAt", TypeRef("Edm.DateTimeOffset")),
        "RevokedByUserId": EdmProperty("RevokedByUserId", TypeRef("Edm.Guid")),
        "RevokeReason": EdmProperty("RevokeReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="PluginCapabilityGrants",
)
