"""Provides the connector call log EDM definition."""

__all__ = ["connector_call_log_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

connector_call_log_type = EdmType(
    name="OPSCONNECTOR.ConnectorCallLog",
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
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String"), nullable=False),
        "ConnectorInstanceId": EdmProperty(
            "ConnectorInstanceId", TypeRef("Edm.Guid"), nullable=False
        ),
        "CapabilityName": EdmProperty(
            "CapabilityName", TypeRef("Edm.String"), nullable=False
        ),
        "ClientActionKey": EdmProperty("ClientActionKey", TypeRef("Edm.String")),
        "RequestJson": EdmProperty(
            "RequestJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "RequestHash": EdmProperty(
            "RequestHash", TypeRef("Edm.String"), nullable=False
        ),
        "ResponseJson": EdmProperty(
            "ResponseJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ResponseHash": EdmProperty("ResponseHash", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "HttpStatusCode": EdmProperty("HttpStatusCode", TypeRef("Edm.Int32")),
        "AttemptCount": EdmProperty(
            "AttemptCount", TypeRef("Edm.Int64"), nullable=False
        ),
        "DurationMs": EdmProperty("DurationMs", TypeRef("Edm.Int64")),
        "ErrorJson": EdmProperty(
            "ErrorJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "EscalationJson": EdmProperty(
            "EscalationJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "InvokedByUserId": EdmProperty("InvokedByUserId", TypeRef("Edm.Guid")),
        "InvokedAt": EdmProperty(
            "InvokedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsConnectorCallLogs",
)
