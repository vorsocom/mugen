"""Provides the ingress binding EDM type definition."""

__all__ = ["ingress_binding_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


ingress_binding_type = EdmType(
    name="CHANNELORCH.IngressBinding",
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
        "ChannelProfileId": EdmProperty("ChannelProfileId", TypeRef("Edm.Guid")),
        "ChannelKey": EdmProperty("ChannelKey", TypeRef("Edm.String"), nullable=False),
        "IdentifierType": EdmProperty(
            "IdentifierType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "IdentifierValue": EdmProperty(
            "IdentifierValue",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "ServiceRouteKey": EdmProperty("ServiceRouteKey", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="IngressBindings",
)
