"""Provides an EdmType for the User declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

user_type = EdmType(
    name="ACP.User",
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
        # PersonScopedMixin.
        "PersonId": EdmProperty(
            "PersonId",
            TypeRef("Edm.Guid"),
        ),
        # SoftDeleteMixin.
        "DeletedAt": EdmProperty(
            "DeletedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "DeletedByUserId": EdmProperty(
            "DeletedByUserId",
            TypeRef("Edm.Guid"),
        ),
        # User.
        "LockedAt": EdmProperty(
            "LockedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LockedByUserId": EdmProperty(
            "LockedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "PasswordHash": EdmProperty(
            "PasswordHash",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
            redact=True,
        ),
        "PasswordChangedAt": EdmProperty(
            "PasswordChangedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "PasswordChangedByUserId": EdmProperty(
            "PasswordChangedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "Username": EdmProperty(
            "Username",
            TypeRef("Edm.String"),
        ),
        "LoginEmail": EdmProperty(
            "LoginEmail",
            TypeRef("Edm.String"),
        ),
        "LastLoginAt": EdmProperty(
            "LastLoginAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "FailedLoginCount": EdmProperty(
            "FailedLoginCount",
            TypeRef("Edm.Int16"),
        ),
        "TokenVersion": EdmProperty(
            "TokenVersion",
            TypeRef("Edm.Int32"),
            filterable=False,
            sortable=False,
            redact=True,
        ),
    },
    nav_properties={
        "Person": EdmNavigationProperty(
            "Person",
            target_type=TypeRef(
                "ACP.Person",
                is_collection=False,
            ),
            source_fk="PersonId",
        ),
        "GlobalRoleMemberships": EdmNavigationProperty(
            "GlobalRoleMemberships",
            target_type=TypeRef(
                "ACP.GlobalRoleMembership",
                is_collection=True,
            ),
            target_fk="UserId",
        ),
        "RefreshTokens": EdmNavigationProperty(
            "RefreshTokens",
            target_type=TypeRef(
                "ACP.RefreshToken",
                is_collection=True,
            ),
            target_fk="UserId",
        ),
        "RoleMemberships": EdmNavigationProperty(
            "RoleMemberships",
            target_type=TypeRef(
                "ACP.RoleMembership",
                is_collection=True,
            ),
            target_fk="UserId",
        ),
        "TenantMemberships": EdmNavigationProperty(
            "TenantMemberships",
            target_type=TypeRef(
                "ACP.TenantMembership",
                is_collection=True,
            ),
            target_fk="UserId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="Users",
)
