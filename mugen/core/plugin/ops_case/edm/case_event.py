"""Provides the case event EDM type definition."""

__all__ = ["case_event_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

case_event_type = EdmType(
    name="OPSCASE.CaseEvent",
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
        "CaseId": EdmProperty("CaseId", TypeRef("Edm.Guid"), nullable=False),
        "EventType": EdmProperty("EventType", TypeRef("Edm.String"), nullable=False),
        "StatusFrom": EdmProperty("StatusFrom", TypeRef("Edm.String")),
        "StatusTo": EdmProperty("StatusTo", TypeRef("Edm.String")),
        "Note": EdmProperty("Note", TypeRef("Edm.String")),
        "Payload": EdmProperty(
            "Payload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
    },
    nav_properties={
        "Case": EdmNavigationProperty(
            "Case",
            target_type=TypeRef("OPSCASE.Case"),
            source_fk="CaseId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsCaseEvents",
)
