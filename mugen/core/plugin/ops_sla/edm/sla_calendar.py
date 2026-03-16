"""Provides the sla calendar EDM type definition."""

__all__ = ["sla_calendar_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_calendar_type = EdmType(
    name="OPSSLA.SlaCalendar",
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
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Timezone": EdmProperty("Timezone", TypeRef("Edm.String"), nullable=False),
        "BusinessStartTime": EdmProperty(
            "BusinessStartTime", TypeRef("Edm.TimeOfDay"), nullable=False
        ),
        "BusinessEndTime": EdmProperty(
            "BusinessEndTime", TypeRef("Edm.TimeOfDay"), nullable=False
        ),
        "BusinessDays": EdmProperty(
            "BusinessDays",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "HolidayRefs": EdmProperty(
            "HolidayRefs",
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
    entity_set_name="OpsSlaCalendars",
)
