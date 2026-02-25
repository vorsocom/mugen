"""Provides an EdmType for the DedupRecord declarative model."""

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

dedup_record_type = EdmType(
    name="ACP.DedupRecord",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "Scope": EdmProperty("Scope", TypeRef("Edm.String"), nullable=False),
        "IdempotencyKey": EdmProperty(
            "IdempotencyKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "RequestHash": EdmProperty("RequestHash", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "ResultRef": EdmProperty("ResultRef", TypeRef("Edm.String")),
        "ResponseCode": EdmProperty("ResponseCode", TypeRef("Edm.Int32")),
        "ResponsePayload": EdmProperty(
            "ResponsePayload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ErrorCode": EdmProperty("ErrorCode", TypeRef("Edm.String")),
        "ErrorMessage": EdmProperty("ErrorMessage", TypeRef("Edm.String")),
        "OwnerInstance": EdmProperty("OwnerInstance", TypeRef("Edm.String")),
        "LeaseExpiresAt": EdmProperty(
            "LeaseExpiresAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "ExpiresAt": EdmProperty(
            "ExpiresAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="DedupRecords",
)
