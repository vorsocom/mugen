"""Provides the work-item EDM type definition."""

__all__ = ["work_item_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

work_item_type = EdmType(
    name="CHANNELORCH.WorkItem",
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
        "Source": EdmProperty("Source", TypeRef("Edm.String"), nullable=False),
        "Participants": EdmProperty(
            "Participants",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Content": EdmProperty(
            "Content",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Attachments": EdmProperty(
            "Attachments",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Signals": EdmProperty(
            "Signals",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Extractions": EdmProperty(
            "Extractions",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "LinkedCaseId": EdmProperty("LinkedCaseId", TypeRef("Edm.Guid")),
        "LinkedWorkflowInstanceId": EdmProperty(
            "LinkedWorkflowInstanceId",
            TypeRef("Edm.Guid"),
        ),
        "ReplayCount": EdmProperty("ReplayCount", TypeRef("Edm.Int64"), nullable=False),
        "LastReplayedAt": EdmProperty(
            "LastReplayedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LastActorUserId": EdmProperty("LastActorUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="WorkItems",
)
