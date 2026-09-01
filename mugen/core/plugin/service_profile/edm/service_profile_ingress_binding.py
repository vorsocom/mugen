"""Provides the Service Profile ingress assignment EDM type definition."""

__all__ = ["service_profile_ingress_binding_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

service_profile_ingress_binding_type = EdmType(
    name="SERVICEPROFILE.ServiceProfileIngressBinding",
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
        "ServiceProfileId": EdmProperty(
            "ServiceProfileId", TypeRef("Edm.Guid"), nullable=False
        ),
        "IngressBindingId": EdmProperty(
            "IngressBindingId", TypeRef("Edm.Guid"), nullable=False
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
    entity_set_name="ServiceProfileIngressBindings",
)
