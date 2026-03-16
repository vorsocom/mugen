"""Provides the connector type EDM definition."""

__all__ = ["connector_type_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

connector_type_type = EdmType(
    name="OPSCONNECTOR.ConnectorType",
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
        "Key": EdmProperty("Key", TypeRef("Edm.String"), nullable=False),
        "DisplayName": EdmProperty(
            "DisplayName", TypeRef("Edm.String"), nullable=False
        ),
        "AdapterKind": EdmProperty(
            "AdapterKind", TypeRef("Edm.String"), nullable=False
        ),
        "CapabilitiesJson": EdmProperty(
            "CapabilitiesJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsConnectorTypes",
)
