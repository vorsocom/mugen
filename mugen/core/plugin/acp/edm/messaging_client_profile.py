"""Provides an EdmType for the MessagingClientProfile declarative model."""

__all__ = ["messaging_client_profile_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

messaging_client_profile_type = EdmType(
    name="ACP.MessagingClientProfile",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "PlatformKey": EdmProperty(
            "PlatformKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "ProfileKey": EdmProperty(
            "ProfileKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "DisplayName": EdmProperty("DisplayName", TypeRef("Edm.String")),
        "IsActive": EdmProperty(
            "IsActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "Settings": EdmProperty(
            "Settings",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "SecretRefs": EdmProperty(
            "SecretRefs",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "PathToken": EdmProperty("PathToken", TypeRef("Edm.String")),
        "RecipientUserId": EdmProperty(
            "RecipientUserId",
            TypeRef("Edm.String"),
        ),
        "AccountNumber": EdmProperty("AccountNumber", TypeRef("Edm.String")),
        "PhoneNumberId": EdmProperty("PhoneNumberId", TypeRef("Edm.String")),
        "Provider": EdmProperty("Provider", TypeRef("Edm.String")),
    },
    key_properties=("Id",),
    entity_set_name="MessagingClientProfiles",
)
