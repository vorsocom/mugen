"""Provides the Service Profile EDM type definition."""

__all__ = ["service_profile_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

service_profile_type = EdmType(
    name="SERVICEPROFILE.ServiceProfile",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "Key": EdmProperty("Key", TypeRef("Edm.String"), nullable=False),
        "DisplayName": EdmProperty(
            "DisplayName", TypeRef("Edm.String"), nullable=False
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "ActivatedAt": EdmProperty("ActivatedAt", TypeRef("Edm.DateTimeOffset")),
        "DisabledAt": EdmProperty("DisabledAt", TypeRef("Edm.DateTimeOffset")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DeletedAt": EdmProperty("DeletedAt", TypeRef("Edm.DateTimeOffset")),
        "DeletedByUserId": EdmProperty("DeletedByUserId", TypeRef("Edm.Guid")),
    },
    key_properties=("Id",),
    entity_set_name="ServiceProfiles",
)
