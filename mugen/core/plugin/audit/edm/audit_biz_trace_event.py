"""Provides the audit business-trace-event EDM type definition."""

__all__ = ["audit_biz_trace_event_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

audit_biz_trace_event_type = EdmType(
    name="AUDIT.AuditBizTraceEvent",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String"), nullable=False),
        "SpanId": EdmProperty("SpanId", TypeRef("Edm.String")),
        "ParentSpanId": EdmProperty("ParentSpanId", TypeRef("Edm.String")),
        "CorrelationId": EdmProperty("CorrelationId", TypeRef("Edm.String")),
        "RequestId": EdmProperty("RequestId", TypeRef("Edm.String")),
        "SourcePlugin": EdmProperty(
            "SourcePlugin",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "EntitySet": EdmProperty("EntitySet", TypeRef("Edm.String")),
        "ActionName": EdmProperty("ActionName", TypeRef("Edm.String")),
        "Stage": EdmProperty("Stage", TypeRef("Edm.String"), nullable=False),
        "StatusCode": EdmProperty("StatusCode", TypeRef("Edm.Int32")),
        "DurationMs": EdmProperty("DurationMs", TypeRef("Edm.Int64")),
        "DetailsJson": EdmProperty(
            "DetailsJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="AuditBizTraceEvents",
)
