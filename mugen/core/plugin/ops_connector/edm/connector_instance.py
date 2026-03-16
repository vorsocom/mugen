"""Provides the connector instance EDM definition."""

__all__ = ["connector_instance_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

connector_instance_type = EdmType(
    name="OPSCONNECTOR.ConnectorInstance",
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
        "ConnectorTypeId": EdmProperty(
            "ConnectorTypeId", TypeRef("Edm.Guid"), nullable=False
        ),
        "DisplayName": EdmProperty(
            "DisplayName", TypeRef("Edm.String"), nullable=False
        ),
        "ConfigJson": EdmProperty(
            "ConfigJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "SecretRef": EdmProperty("SecretRef", TypeRef("Edm.String"), nullable=False),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "EscalationPolicyKey": EdmProperty(
            "EscalationPolicyKey", TypeRef("Edm.String")
        ),
        "RetryPolicyJson": EdmProperty(
            "RetryPolicyJson",
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
    entity_set_name="OpsConnectorInstances",
)
