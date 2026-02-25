"""Provides the audit correlation-link EDM type definition."""

__all__ = ["audit_correlation_link_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

audit_correlation_link_type = EdmType(
    name="AUDIT.AuditCorrelationLink",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String"), nullable=False),
        "CorrelationId": EdmProperty("CorrelationId", TypeRef("Edm.String")),
        "RequestId": EdmProperty("RequestId", TypeRef("Edm.String")),
        "SourcePlugin": EdmProperty(
            "SourcePlugin",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "EntitySet": EdmProperty("EntitySet", TypeRef("Edm.String"), nullable=False),
        "EntityId": EdmProperty("EntityId", TypeRef("Edm.Guid")),
        "Operation": EdmProperty("Operation", TypeRef("Edm.String"), nullable=False),
        "ActionName": EdmProperty("ActionName", TypeRef("Edm.String")),
        "ParentEntitySet": EdmProperty("ParentEntitySet", TypeRef("Edm.String")),
        "ParentEntityId": EdmProperty("ParentEntityId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
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
    entity_set_name="AuditCorrelationLinks",
)
