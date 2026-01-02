"""Provides an EdmType for the RefreshToken declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

refresh_token_type = EdmType(
    name="ACP.RefreshToken",
    kind="entity",
    properties={
        # ModelBase.
        "Id": EdmProperty(
            "Id",
            TypeRef("Edm.Guid"),
        ),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "RowVersion": EdmProperty(
            "RowVersion",
            TypeRef("Edm.Int64"),
        ),
        # UserScopedMixin.
        "UserId": EdmProperty(
            "UserId",
            TypeRef("Edm.Guid"),
        ),
        # RefreshToken.
        "TokenHash": EdmProperty(
            "TokenHash",
            TypeRef("Edm.String"),
            redact=True,
        ),
        "TokenJti": EdmProperty(
            "TokenJti",
            TypeRef("Edm.Guid"),
        ),
        "ExpiresAt": EdmProperty(
            "ExpiresAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
    },
    nav_properties={
        "User": EdmNavigationProperty(
            "User",
            target_type=TypeRef(
                "ACP.User",
                is_collection=False,
            ),
            source_fk="UserId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="RefreshTokens",
)
